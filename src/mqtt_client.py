#!/usr/bin/env python3
import json
import paho.mqtt.client as mqtt
import argparse
import time
import os
import subprocess
import socket
import re
import sys
import logging
import xml.etree.ElementTree as ET
import base64
from pathlib import Path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.expanduser('~/.config/retropie-ha/retropie-ha.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('retropie-ha')

# Constants
CONFIG_DIR = os.path.expanduser('~/.config/retropie-ha')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')
ROMS_DIR = os.path.expanduser('~/RetroPie/roms')

def ensure_config_dir():
    """Ensure configuration directory exists"""
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)

def get_config():
    """Load configuration from file"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        return {}

def get_cpu_temperature():
    """Get CPU temperature using vcgencmd"""
    try:
        output = subprocess.check_output(['vcgencmd', 'measure_temp'], universal_newlines=True)
        temp = re.search(r'temp=(\d+\.\d+)', output)
        if temp:
            return float(temp.group(1))
    except Exception as e:
        logger.error(f"Failed to get CPU temperature: {e}")
    return None

def get_gpu_temperature():
    """Get GPU temperature (on Raspberry Pi, this is often the same as CPU)"""
    try:
        # On some systems, there might be a separate GPU temperature command
        # For Raspberry Pi, we typically use the same as CPU
        return get_cpu_temperature()
    except Exception as e:
        logger.error(f"Failed to get GPU temperature: {e}")
    return None

def get_system_info():
    """Get basic system information"""
    hostname = socket.gethostname()
    
    # Get system uptime
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])
    except Exception:
        uptime_seconds = 0
    
    # Get system load
    try:
        with open('/proc/loadavg', 'r') as f:
            load = f.readline().split()[:3]
    except Exception:
        load = [0, 0, 0]
    
    # Get memory info
    mem_info = {}
    try:
        output = subprocess.check_output(['free', '-m'], universal_newlines=True).split('\n')
        mem_line = output[1].split()
        mem_info = {
            'total': int(mem_line[1]),
            'used': int(mem_line[2]),
            'free': int(mem_line[3])
        }
    except Exception as e:
        logger.error(f"Failed to get memory info: {e}")
        mem_info = {'total': 0, 'used': 0, 'free': 0}
    
    info = {
        'hostname': hostname,
        'cpu_temp': get_cpu_temperature(),
        'gpu_temp': get_gpu_temperature(),
        'uptime_seconds': uptime_seconds,
        'load': load,
        'memory': mem_info
    }
    return info

def get_game_metadata(system, rom_path):
    """Get game metadata from EmulationStation gamelist.xml"""
    try:
        # Clean up input paths
        if rom_path.startswith('./'):
            rom_path = rom_path[2:]  # Remove ./ prefix
        
        # Find the gamelist.xml file
        gamelist_path = os.path.join(ROMS_DIR, system, 'gamelist.xml')
        if not os.path.exists(gamelist_path):
            logger.warning(f"gamelist.xml not found for system {system}")
            return {}
        
        # Parse the gamelist.xml
        tree = ET.parse(gamelist_path)
        root = tree.getroot()
        
        # Find the game entry
        for game in root.findall('game'):
            path_elem = game.find('path')
            if path_elem is not None:
                game_path = path_elem.text
                # Remove ./ prefix if it exists
                if game_path.startswith('./'):
                    game_path = game_path[2:]
                
                # Check if paths match
                if os.path.basename(game_path) == os.path.basename(rom_path):
                    metadata = {}
                    
                    # Get basic metadata
                    for elem in ['desc', 'rating', 'releasedate', 'developer', 'publisher', 'genre']:
                        if game.find(elem) is not None:
                            metadata[elem] = game.find(elem).text
                    
                    # Get game name (can be in different elements)
                    if game.find('name') is not None:
                        metadata['name'] = game.find('name').text
                    elif game.find('n') is not None:
                        metadata['name'] = game.find('n').text
                    
                    # Get image paths and convert to base64 if they exist
                    for img_type in ['image', 'thumbnail', 'marquee']:
                        img_elem = game.find(img_type)
                        if img_elem is not None and img_elem.text:
                            img_path = img_elem.text
                            if img_path.startswith('./'):
                                img_path = img_path[2:]
                            
                            full_img_path = os.path.join(ROMS_DIR, system, img_path)
                            if os.path.exists(full_img_path):
                                try:
                                    # Only include the thumbnail to keep the size reasonable
                                    if img_type == 'thumbnail':
                                        with open(full_img_path, 'rb') as img_file:
                                            img_data = img_file.read()
                                            metadata['image_data'] = base64.b64encode(img_data).decode('utf-8')
                                            metadata['image_path'] = full_img_path
                                except Exception as e:
                                    logger.error(f"Failed to read image file {full_img_path}: {e}")
                    
                    return metadata
        
        logger.warning(f"Game {rom_path} not found in gamelist.xml for system {system}")
        return {}
    except Exception as e:
        logger.error(f"Error getting game metadata: {e}")
        return {}

def publish_mqtt_message(topic, message, retain=False):
    """Publish a message to MQTT broker"""
    config = get_config()
    
    if not config.get('mqtt_host'):
        logger.error("MQTT host not configured")
        return False
    
    client = mqtt.Client()
    
    if config.get('mqtt_username') and config.get('mqtt_password'):
        client.username_pw_set(config['mqtt_username'], config['mqtt_password'])
    
    try:
        client.connect(config['mqtt_host'], int(config.get('mqtt_port', 1883)), 60)
        client.publish(topic, message, qos=1, retain=retain)
        client.disconnect()
        logger.info(f"Published to {topic}: {message[:100]}{'...' if len(message) > 100 else ''}")
        return True
    except Exception as e:
        logger.error(f"Error publishing to MQTT: {e}")
        return False

def publish_game_event(event_type, args=None):
    """Publish an EmulationStation game event to MQTT"""
    config = get_config()
    topic_prefix = config.get('mqtt_topic_prefix', 'retropie')
    device_name = config.get('device_name', socket.gethostname())
    
    payload = {
        'event': event_type,
        'timestamp': int(time.time()),
        'device': device_name,
        'system_info': get_system_info(),
    }
    
    # Add specific event data
    if event_type == 'game-start' and args and len(args) >= 3:
        system = args[0]
        rom_path = args[2]
        emulator = args[1]
        game_name = os.path.basename(rom_path)
        
        # Get additional game metadata
        metadata = get_game_metadata(system, rom_path)
        
        # Build payload with metadata
        game_data = {
            'system': system,
            'emulator': emulator,
            'rom_path': rom_path,
            'rom_name': game_name,
            'game_name': metadata.get('name', game_name)
        }
        
        # Add additional metadata if available
        if 'desc' in metadata:
            game_data['description'] = metadata['desc']
        if 'genre' in metadata:
            game_data['genre'] = metadata['genre']
        if 'developer' in metadata:
            game_data['developer'] = metadata['developer']
        if 'publisher' in metadata:
            game_data['publisher'] = metadata['publisher']
        if 'rating' in metadata:
            game_data['rating'] = metadata['rating']
        if 'releasedate' in metadata:
            game_data['releasedate'] = metadata['releasedate']
        if 'image_path' in metadata:
            game_data['image_path'] = metadata['image_path']
        if 'image_data' in metadata:
            game_data['image_data'] = metadata['image_data']
        
        payload.update(game_data)
    elif event_type == 'game-end':
        # No extra args for game-end
        pass
    elif event_type == 'system-select' and args and len(args) >= 2:
        payload.update({
            'system_name': args[0],
            'access_type': args[1]
        })
    elif event_type == 'game-select' and args and len(args) >= 4:
        system = args[0]
        rom_path = args[1]
        game_name = args[2]
        access_type = args[3]
        
        # Get additional game metadata
        metadata = get_game_metadata(system, rom_path)
        
        # Build payload with metadata
        game_data = {
            'system_name': system,
            'rom_path': rom_path,
            'game_name': metadata.get('name', game_name),
            'access_type': access_type
        }
        
        # Add additional metadata if available
        if 'desc' in metadata:
            game_data['description'] = metadata['desc']
        if 'genre' in metadata:
            game_data['genre'] = metadata['genre']
        if 'developer' in metadata:
            game_data['developer'] = metadata['developer']
        if 'publisher' in metadata:
            game_data['publisher'] = metadata['publisher']
        if 'rating' in metadata:
            game_data['rating'] = metadata['rating']
        if 'releasedate' in metadata:
            game_data['releasedate'] = metadata['releasedate']
        if 'image_path' in metadata:
            game_data['image_path'] = metadata['image_path']
        if 'image_data' in metadata:
            game_data['image_data'] = metadata['image_data']
        
        payload.update(game_data)
    elif event_type == 'quit':
        if args and len(args) >= 1:
            payload.update({'quit_mode': args[0]})
    
    topic = f"{topic_prefix}/event/{event_type}"
    # Events should NOT be retained - they should expire when received
    return publish_mqtt_message(topic, json.dumps(payload), retain=False)

def publish_state_message(state_topic, state_value, retain=True):
    """Publish a simple state message to MQTT"""
    return publish_mqtt_message(state_topic, state_value, retain=retain)

def publish_system_status():
    """Publish system status information to MQTT"""
    config = get_config()
    topic_prefix = config.get('mqtt_topic_prefix', 'retropie')
    device_name = config.get('device_name', socket.gethostname())
    
    payload = {
        'timestamp': int(time.time()),
        'device': device_name,
        'system_info': get_system_info()
    }
    
    topic = f"{topic_prefix}/status"
    # Status updates should be retained so they're available immediately
    return publish_mqtt_message(topic, json.dumps(payload), retain=True)

def on_connect(client, userdata, flags, rc):
    """Callback when connected to MQTT broker"""
    logger.info(f"Connected to MQTT broker with result code {rc}")

def register_with_ha():
    """Register device with Home Assistant via MQTT discovery"""
    config = get_config()
    topic_prefix = config.get('mqtt_topic_prefix', 'retropie')
    device_name = config.get('device_name', socket.gethostname())
    
    # Clean device_name to avoid issues with MQTT topics
    safe_device_name = re.sub(r'[^a-zA-Z0-9_]', '_', device_name)
    
    # Package version
    sw_version = "1.0.0"
    
    # Create device information
    device_info = {
        "identifiers": [
            f"retropie_{safe_device_name}"
        ],
        "name": f"RetroPie {device_name}",
        "model": "RetroPie Arcade",
        "manufacturer": "RetroPie",
        "sw_version": sw_version
    }
    
    # Origin information (like in the Zigbee example)
    origin_info = {
        "name": "RetroPie Home Assistant Integration",
        "sw": sw_version,
        "url": "https://github.com/yourusername/retropie-ha-integration"
    }
    
    # Availability definition (common for all sensors)
    availability = [
        {
            "topic": f"{topic_prefix}/status",
            "value_template": "{{ 'online' }}"
        }
    ]
    
    # Register CPU temperature sensor
    cpu_temp_config = {
        "device": device_info,
        "name": f"RetroPie {device_name} CPU Temperature",
        "unique_id": f"retropie_{safe_device_name}_cpu_temp",
        "object_id": f"retropie_{safe_device_name}_cpu_temp",
        "state_topic": f"{topic_prefix}/status",
        "value_template": "{{ value_json.system_info.cpu_temp }}",
        "unit_of_measurement": "°C",
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:chip",
        "availability": availability,
        "availability_mode": "all",
        "enabled_by_default": True,
        "origin": origin_info
    }
    
    # Register GPU temperature sensor
    gpu_temp_config = {
        "device": device_info,
        "name": f"RetroPie {device_name} GPU Temperature",
        "unique_id": f"retropie_{safe_device_name}_gpu_temp",
        "object_id": f"retropie_{safe_device_name}_gpu_temp",
        "state_topic": f"{topic_prefix}/status",
        "value_template": "{{ value_json.system_info.gpu_temp }}",
        "unit_of_measurement": "°C",
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:gpu",
        "availability": availability,
        "availability_mode": "all",
        "enabled_by_default": True,
        "origin": origin_info
    }
    
    # Register game status sensor with enhanced information
    game_status_config = {
        "device": device_info,
        "name": f"RetroPie {device_name} Game Status",
        "unique_id": f"retropie_{safe_device_name}_game_status",
        "object_id": f"retropie_{safe_device_name}_game_status",
        "state_topic": f"{topic_prefix}/event/game-start",
        "value_template": "{{ value_json.game_name if 'game_name' in value_json else 'None' }}",
        "json_attributes_topic": f"{topic_prefix}/event/game-start",
        "json_attributes_template": "{{ {'description': value_json.description if 'description' in value_json else '', 'system': value_json.system if 'system' in value_json else '', 'emulator': value_json.emulator if 'emulator' in value_json else '', 'genre': value_json.genre if 'genre' in value_json else '', 'developer': value_json.developer if 'developer' in value_json else '', 'publisher': value_json.publisher if 'publisher' in value_json else '', 'rating': value_json.rating if 'rating' in value_json else '', 'releasedate': value_json.releasedate if 'releasedate' in value_json else '' } | tojson }}",
        "icon": "mdi:gamepad-variant",
        "availability": availability,
        "availability_mode": "all",
        "enabled_by_default": True,
        "origin": origin_info
    }
    
    # Register memory usage sensor
    memory_usage_config = {
        "device": device_info,
        "name": f"RetroPie {device_name} Memory Usage",
        "unique_id": f"retropie_{safe_device_name}_memory_usage",
        "object_id": f"retropie_{safe_device_name}_memory_usage",
        "state_topic": f"{topic_prefix}/status",
        "value_template": "{{ value_json.system_info.memory.used / value_json.system_info.memory.total * 100 }}",
        "unit_of_measurement": "%",
        "icon": "mdi:memory",
        "state_class": "measurement",
        "availability": availability,
        "availability_mode": "all",
        "enabled_by_default": True,
        "origin": origin_info
    }
    
    # Register CPU load sensor
    cpu_load_config = {
        "device": device_info,
        "name": f"RetroPie {device_name} CPU Load",
        "unique_id": f"retropie_{safe_device_name}_cpu_load",
        "object_id": f"retropie_{safe_device_name}_cpu_load",
        "state_topic": f"{topic_prefix}/status",
        "value_template": "{{ value_json.system_info.load[0] }}",
        "icon": "mdi:chip",
        "state_class": "measurement",
        "availability": availability,
        "availability_mode": "all",
        "enabled_by_default": True,
        "origin": origin_info
    }
    
    # Create an active client to ensure connection before publishing
    client = mqtt.Client()
    client.on_connect = on_connect
    
    if config.get('mqtt_username') and config.get('mqtt_password'):
        client.username_pw_set(config['mqtt_username'], config['mqtt_password'])
    
    try:
        # Connect to broker and wait for on_connect callback
        client.connect(config['mqtt_host'], int(config.get('mqtt_port', 1883)), 60)
        client.loop_start()
        time.sleep(1)  # Give time for the connection to establish
        
        # Publish availability status topic first
        availability_payload = "online"
        client.publish(
            f"{topic_prefix}/status",
            availability_payload,
            qos=1,
            retain=True
        )
        logger.info(f"Published availability status")
        
        # Publish all discovery messages with retain flag set to True
        # This ensures they persist in the broker
        client.publish(
            f"homeassistant/sensor/retropie_{safe_device_name}/cpu_temp/config",
            json.dumps(cpu_temp_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published CPU temperature sensor config")
        
        client.publish(
            f"homeassistant/sensor/retropie_{safe_device_name}/gpu_temp/config",
            json.dumps(gpu_temp_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published GPU temperature sensor config")
        
        client.publish(
            f"homeassistant/sensor/retropie_{safe_device_name}/game_status/config",
            json.dumps(game_status_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published game status sensor config")
        
        client.publish(
            f"homeassistant/sensor/retropie_{safe_device_name}/memory_usage/config",
            json.dumps(memory_usage_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published memory usage sensor config")
        
        client.publish(
            f"homeassistant/sensor/retropie_{safe_device_name}/cpu_load/config",
            json.dumps(cpu_load_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published CPU load sensor config")
        
        # Also publish an initial status message to make the sensors available immediately
        status_payload = {
            'timestamp': int(time.time()),
            'device': device_name,
            'system_info': get_system_info()
        }
        client.publish(
            f"{topic_prefix}/status",
            json.dumps(status_payload),
            qos=1,
            retain=True
        )
        logger.info(f"Published initial status update")
        
        # Disconnect cleanly
        time.sleep(2)  # Give time for messages to be delivered
        client.loop_stop()
        client.disconnect()
        return True
    except Exception as e:
        logger.error(f"Error registering with Home Assistant: {e}")
        if client.is_connected():
            client.loop_stop()
            client.disconnect()
        return False

if __name__ == '__main__':
    # Ensure config directory exists
    ensure_config_dir()
    
    parser = argparse.ArgumentParser(description='RetroPie Home Assistant Integration')
    parser.add_argument('--event', help='Event type (game-start, game-end, etc.)')
    parser.add_argument('--status', action='store_true', help='Publish system status')
    parser.add_argument('--register', action='store_true', help='Register with Home Assistant')
    parser.add_argument('args', nargs='*', help='Event arguments')
    
    args = parser.parse_args()
    
    if args.register:
        logger.info("Registering with Home Assistant...")
        if register_with_ha():
            logger.info("Successfully registered with Home Assistant")
        else:
            logger.error("Failed to register with Home Assistant")
        sys.exit(0)
        
    if args.status:
        publish_system_status()
        sys.exit(0)
        
    if args.event:
        publish_game_event(args.event, args.args)
        sys.exit(0)
        
    # If no arguments provided, just publish status
    publish_system_status()