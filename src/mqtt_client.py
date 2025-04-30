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
import threading
import atexit
# Try to import watchdog, but don't crash if it's not available
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    from watchdog.events import PatternMatchingEventHandler
    watchdog_available = True
except ImportError:
    watchdog_available = False
    # Don't log here, since logger isn't initialized yet
    # We'll log this later

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.expanduser('~/.config/retropie-ha/retropie-ha.log'))
        # Removed StreamHandler to prevent console output
    ]
)
logger = logging.getLogger('retropie-ha')

# Constants
CONFIG_DIR = os.path.expanduser('~/.config/retropie-ha')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')
ROMS_DIR = os.path.expanduser('~/RetroPie/roms')
STATE_FILE = os.path.join(CONFIG_DIR, 'state.json')
RETROARCH_PORT = 55355  # Default RetroArch Network Control Interface port

# Global state
current_state = {
    'machine_status': 'idle',  # idle, playing, shutdown
    'current_game': None,
    'game_start_time': None,
    'last_update': int(time.time()),
    'game_collection': {
        'total_games': 0,
        'favorites': 0,
        'kid_friendly': 0,
        'last_scan': 0,
        'systems': {}
    }
}

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

def save_state():
    """Save current state to file"""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(current_state, f)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")

def load_state():
    """Load state from file"""
    global current_state
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                current_state.update(json.load(f))
    except Exception as e:
        logger.error(f"Failed to load state: {e}")

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
        'memory': mem_info,
        'machine_status': current_state.get('machine_status', 'idle'),
        'current_game': current_state.get('current_game'),
        'game_start_time': current_state.get('game_start_time')
    }
    
    # Add play duration if a game is running
    if info['machine_status'] == 'playing' and info['game_start_time']:
        info['play_duration_seconds'] = int(time.time()) - info['game_start_time']
    
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
    global current_state
    
    config = get_config()
    topic_prefix = config.get('mqtt_topic_prefix', 'retropie')
    device_name = config.get('device_name', socket.gethostname())
    
    payload = {
        'event': event_type,
        'timestamp': int(time.time()),
        'device': device_name,
        'system_info': get_system_info(),
    }
    
    # Update machine status based on event
    if event_type == 'system-start':
        current_state['machine_status'] = 'idle'
        current_state['current_game'] = None
        current_state['game_start_time'] = None
        current_state['last_update'] = int(time.time())
        save_state()
        
        # Also publish availability status
        publish_state_message(f"{topic_prefix}/availability", "online", retain=True)
        
    elif event_type == 'game-start' and args and len(args) >= 3:
        system = args[0]
        rom_path = args[2]
        emulator = args[1]
        game_name = os.path.basename(rom_path)
        
        # Verify RetroArch network commands are enabled for this game session
        # This runs in a separate thread to avoid blocking the game launch
        if 'retroarch' in emulator.lower():
            threading.Thread(target=verify_retroarch_network_commands, daemon=True).start()
        
        # Get additional game metadata
        metadata = get_game_metadata(system, rom_path)
        display_name = metadata.get('name', game_name)
        
        # Update state
        current_state['machine_status'] = 'playing'
        current_state['current_game'] = display_name
        current_state['game_start_time'] = int(time.time())
        current_state['last_update'] = int(time.time())
        save_state()
        
        # Build payload with metadata
        game_data = {
            'system': system,
            'emulator': emulator,
            'rom_path': rom_path,
            'rom_name': game_name,
            'game_name': display_name,
            'start_time': current_state['game_start_time']
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
        
        # Also update machine status
        publish_machine_status()
        
    elif event_type == 'game-end':
        # Reset current game info but keep system running
        current_state['machine_status'] = 'idle'
        
        # Add game session duration to payload if we have start time
        if current_state['game_start_time']:
            payload['game_name'] = current_state['current_game']
            payload['start_time'] = current_state['game_start_time']
            payload['duration_seconds'] = int(time.time()) - current_state['game_start_time']
            payload['end_time'] = int(time.time())
        
        # Reset game info
        current_state['current_game'] = None
        current_state['game_start_time'] = None
        current_state['last_update'] = int(time.time())
        save_state()
        
        # Also update machine status
        publish_machine_status()
        
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
        # System is shutting down
        current_state['machine_status'] = 'shutdown'
        current_state['last_update'] = int(time.time())
        save_state()
        
        if args and len(args) >= 1:
            payload.update({'quit_mode': args[0]})
        
        # Also publish availability status
        publish_state_message(f"{topic_prefix}/availability", "offline", retain=True)
        
        # Update machine status
        publish_machine_status()
    
    topic = f"{topic_prefix}/event/{event_type}"
    # Events should NOT be retained - they should expire when received
    return publish_mqtt_message(topic, json.dumps(payload), retain=False)

def publish_state_message(state_topic, state_value, retain=True):
    """Publish a simple state message to MQTT"""
    return publish_mqtt_message(state_topic, state_value, retain=retain)

def publish_machine_status():
    """Publish machine status to MQTT"""
    config = get_config()
    topic_prefix = config.get('mqtt_topic_prefix', 'retropie')
    
    # Create the status payload
    payload = {
        'timestamp': int(time.time()),
        'status': current_state['machine_status'],
        'current_game': current_state['current_game'],
        'game_start_time': current_state['game_start_time']
    }
    
    # Add play duration if a game is running
    if current_state['machine_status'] == 'playing' and current_state['game_start_time']:
        payload['play_duration_seconds'] = int(time.time()) - current_state['game_start_time']
    
    # Publish to the machine_status topic
    topic = f"{topic_prefix}/machine_status"
    return publish_mqtt_message(topic, json.dumps(payload), retain=True)

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
    
    # Update last update time
    current_state['last_update'] = int(time.time())
    save_state()
    
    topic = f"{topic_prefix}/status"
    # Status updates should be retained so they're available immediately
    return publish_mqtt_message(topic, json.dumps(payload), retain=True)

def on_connect(client, userdata, flags, rc):
    """Callback when connected to MQTT broker"""
    logger.info(f"Connected to MQTT broker with result code {rc}")
    
    # Get topic prefix from config
    topic_prefix = get_config().get('mqtt_topic_prefix', 'retropie')
    
    # Subscribe to all command topics
    command_topics = [
        # TTS
        f"{topic_prefix}/command/tts",
        f"{topic_prefix}/tts_text/set",
        
        # RetroArch
        f"{topic_prefix}/command/retroarch/status", 
        f"{topic_prefix}/command/retroarch/message",
        f"{topic_prefix}/command/retroarch",
        f"{topic_prefix}/retroarch_message_text/set",
        f"{topic_prefix}/retroarch_command_text/set",
        
        # UI Mode
        f"{topic_prefix}/command/ui_mode",
        
        # Scan Games
        f"{topic_prefix}/command/scan_games"
    ]
    
    for topic in command_topics:
        client.subscribe(topic)
        logger.info(f"Subscribed to command topic: {topic}")

def on_message(client, userdata, msg):
    """Callback when a message is received"""
    try:
        logger.info(f"Received message on topic {msg.topic}: {msg.payload.decode()}")
        
        # Check the message topic to determine the action
        config = get_config()
        topic_prefix = config.get('mqtt_topic_prefix', 'retropie')
        
        # Handle TTS related
        if msg.topic == f"{topic_prefix}/command/tts":
            handle_tts_command(msg, topic_prefix)
        elif msg.topic == f"{topic_prefix}/tts_text/set":
            handle_tts_command(msg, topic_prefix)
        
        # Handle RetroArch related
        elif msg.topic == f"{topic_prefix}/command/retroarch/status":
            handle_retroarch_status_command(msg, topic_prefix)
        elif msg.topic == f"{topic_prefix}/command/retroarch/message":
            handle_retroarch_message_command(msg, topic_prefix)
        elif msg.topic == f"{topic_prefix}/retroarch_message_text/set":
            # Store the message text for later use
            text = msg.payload.decode().strip()
            if hasattr(handle_retroarch_message_command, 'current_text'):
                handle_retroarch_message_command.current_text = text
            # Update the state topic
            publish_mqtt_message(f"{topic_prefix}/retroarch_message_text/state", text, retain=True)
        elif msg.topic == f"{topic_prefix}/command/retroarch":
            handle_retroarch_command_message(msg, topic_prefix)
        elif msg.topic == f"{topic_prefix}/retroarch_command_text/set":
            # Store the command text for later use
            text = msg.payload.decode().strip()
            if hasattr(handle_retroarch_command_message, 'current_text'):
                handle_retroarch_command_message.current_text = text
            # Update the state topic
            publish_mqtt_message(f"{topic_prefix}/retroarch_command_text/state", text, retain=True)
            
        # Handle UI mode change
        elif msg.topic == f"{topic_prefix}/command/ui_mode":
            handle_ui_mode_command(msg, topic_prefix)
            
        # Handle game collection scan
        elif msg.topic == f"{topic_prefix}/command/scan_games":
            handle_scan_games_command(msg, topic_prefix)
    
    except Exception as e:
        logger.error(f"Error processing message: {e}")

def handle_tts_command(msg, topic_prefix):
    """Handle TTS command message"""
    try:
        # Check if this is a button press or text input
        payload = msg.payload.decode().strip()
        
        if payload == "SPEAK":
            # This is a button press, use the stored text
            if hasattr(handle_tts_command, 'current_text') and handle_tts_command.current_text:
                text = handle_tts_command.current_text
                logger.info(f"Button pressed. Executing TTS for text: {text}")
                threading.Thread(target=execute_tts, args=(text,)).start()
                
                # Send acknowledgment
                ack_topic = f"{topic_prefix}/command/tts/response"
                ack_payload = {
                    'timestamp': int(time.time()),
                    'status': 'success',
                    'text': text
                }
                publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
            else:
                logger.error("No text available for TTS")
                
                # Send error response
                ack_topic = f"{topic_prefix}/command/tts/response"
                ack_payload = {
                    'timestamp': int(time.time()),
                    'status': 'error',
                    'message': 'No text provided'
                }
                publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
        else:
            # This is text input or a direct TTS command with text
            try:
                # Try to parse as JSON
                command = json.loads(payload)
                text = command.get('text', '')
            except json.JSONDecodeError:
                # Use the payload as direct text
                text = payload
            
            if text:
                # Store the text for button presses
                handle_tts_command.current_text = text
                
                # Update the text input state
                publish_mqtt_message(f"{topic_prefix}/tts_text/state", text, retain=True)
                
                # If this was a direct command with text (not just setting the input),
                # execute TTS immediately
                if msg.topic == f"{topic_prefix}/command/tts" and text != "SPEAK":
                    logger.info(f"Direct command. Executing TTS for text: {text}")
                    threading.Thread(target=execute_tts, args=(text,)).start()
                    
                    # Send acknowledgment
                    ack_topic = f"{topic_prefix}/command/tts/response"
                    ack_payload = {
                        'timestamp': int(time.time()),
                        'status': 'success',
                        'text': text
                    }
                    publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
            else:
                logger.error("Received empty text")
                
                # Send error response
                ack_topic = f"{topic_prefix}/command/tts/response"
                ack_payload = {
                    'timestamp': int(time.time()),
                    'status': 'error',
                    'message': 'Empty text provided'
                }
                publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
    
    except Exception as e:
        logger.error(f"Error handling TTS command: {e}")
        # Send error response
        ack_topic = f"{topic_prefix}/command/tts/response"
        ack_payload = {
            'timestamp': int(time.time()),
            'status': 'error',
            'message': f'Error: {str(e)}'
        }
        publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)

def handle_retroarch_status_command(msg, topic_prefix):
    """Handle RetroArch status command message"""
    try:
        # For button press or direct command, get the status
        payload = msg.payload.decode().strip()
        
        if payload == "GET_STATUS" or payload == "" or payload == "{}":
            # Get RetroArch status
            status_info = get_retroarch_status()
            
            # Prepare response
            ack_topic = f"{topic_prefix}/command/retroarch/status/response"
            if status_info:
                ack_payload = {
                    'timestamp': int(time.time()),
                    'status': 'success',
                    'data': status_info
                }
                
                # Also publish to a status topic for sensors
                publish_mqtt_message(f"{topic_prefix}/retroarch/status", json.dumps(status_info), retain=True)
            else:
                ack_payload = {
                    'timestamp': int(time.time()),
                    'status': 'error',
                    'message': 'Failed to get RetroArch status, check if RetroArch is running with Network Commands enabled'
                }
            publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
        else:
            logger.error(f"Unexpected payload for status command: {payload}")
            
            # Send error response
            ack_topic = f"{topic_prefix}/command/retroarch/status/response"
            ack_payload = {
                'timestamp': int(time.time()),
                'status': 'error',
                'message': f'Unexpected payload: {payload}'
            }
            publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
    
    except Exception as e:
        logger.error(f"Error handling RetroArch status command: {e}")
        # Send error response
        ack_topic = f"{topic_prefix}/command/retroarch/status/response"
        ack_payload = {
            'timestamp': int(time.time()),
            'status': 'error',
            'message': f'Error: {str(e)}'
        }
        publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)

def handle_retroarch_message_command(msg, topic_prefix):
    """Handle RetroArch message display command"""
    try:
        payload = msg.payload.decode().strip()
        
        if payload == "DISPLAY":
            # This is a button press, use the stored message
            if hasattr(handle_retroarch_message_command, 'current_text') and handle_retroarch_message_command.current_text:
                message = handle_retroarch_message_command.current_text
                logger.info(f"Button pressed. Displaying message on RetroArch: {message}")
                success = display_retroarch_message(message)
                
                # Send acknowledgment
                ack_topic = f"{topic_prefix}/command/retroarch/message/response"
                if success:
                    ack_payload = {
                        'timestamp': int(time.time()),
                        'status': 'success',
                        'message': message
                    }
                else:
                    ack_payload = {
                        'timestamp': int(time.time()),
                        'status': 'error',
                        'message': 'Failed to display message, check if RetroArch is running with Network Commands enabled'
                    }
                publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
            else:
                logger.error("No message available to display")
                
                # Send error response
                ack_topic = f"{topic_prefix}/command/retroarch/message/response"
                ack_payload = {
                    'timestamp': int(time.time()),
                    'status': 'error',
                    'message': 'No message provided'
                }
                publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
        else:
            # This is a direct message or JSON command
            try:
                # Try to parse as JSON
                command = json.loads(payload)
                message = command.get('message', '')
            except json.JSONDecodeError:
                # Use the payload as direct text
                message = payload
            
            if message:
                # Store the message for button presses
                handle_retroarch_message_command.current_text = message
                
                # Update the text input state
                publish_mqtt_message(f"{topic_prefix}/retroarch_message_text/state", message, retain=True)
                
                # If this is a direct command (not from the text input), display message
                if msg.topic == f"{topic_prefix}/command/retroarch/message" and message != "DISPLAY":
                    logger.info(f"Direct command. Displaying message on RetroArch: {message}")
                    success = display_retroarch_message(message)
                    
                    # Send acknowledgment
                    ack_topic = f"{topic_prefix}/command/retroarch/message/response"
                    if success:
                        ack_payload = {
                            'timestamp': int(time.time()),
                            'status': 'success',
                            'message': message
                        }
                    else:
                        ack_payload = {
                            'timestamp': int(time.time()),
                            'status': 'error',
                            'message': 'Failed to display message, check if RetroArch is running with Network Commands enabled'
                        }
                    publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
            else:
                logger.error("Received empty message")
                
                # Send error response
                ack_topic = f"{topic_prefix}/command/retroarch/message/response"
                ack_payload = {
                    'timestamp': int(time.time()),
                    'status': 'error',
                    'message': 'No message provided'
                }
                publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
    
    except Exception as e:
        logger.error(f"Error handling RetroArch message command: {e}")
        # Send error response
        ack_topic = f"{topic_prefix}/command/retroarch/message/response"
        ack_payload = {
            'timestamp': int(time.time()),
            'status': 'error',
            'message': f'Error: {str(e)}'
        }
        publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)

def handle_retroarch_command_message(msg, topic_prefix):
    """Handle generic RetroArch command"""
    try:
        payload = msg.payload.decode().strip()
        
        if payload == "EXECUTE":
            # This is a button press, use the stored command
            if hasattr(handle_retroarch_command_message, 'current_text') and handle_retroarch_command_message.current_text:
                command = handle_retroarch_command_message.current_text
                logger.info(f"Button pressed. Sending command to RetroArch: {command}")
                result = send_retroarch_command(command)
                
                # Send acknowledgment
                ack_topic = f"{topic_prefix}/command/retroarch/response"
                if result is not None:
                    ack_payload = {
                        'timestamp': int(time.time()),
                        'status': 'success',
                        'command': command,
                        'response': result if isinstance(result, str) else ''
                    }
                else:
                    ack_payload = {
                        'timestamp': int(time.time()),
                        'status': 'error',
                        'command': command,
                        'message': 'Failed to send command, check if RetroArch is running with Network Commands enabled'
                    }
                publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
            else:
                logger.error("No command available to execute")
                
                # Send error response
                ack_topic = f"{topic_prefix}/command/retroarch/response"
                ack_payload = {
                    'timestamp': int(time.time()),
                    'status': 'error',
                    'message': 'No command provided'
                }
                publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
        else:
            # This is a direct command or JSON command
            try:
                # Try to parse as JSON
                command_obj = json.loads(payload)
                command = command_obj.get('command', '')
            except json.JSONDecodeError:
                # Use the payload as direct command
                command = payload
            
            if command:
                # Store the command for button presses
                handle_retroarch_command_message.current_text = command
                
                # Update the text input state
                publish_mqtt_message(f"{topic_prefix}/retroarch_command_text/state", command, retain=True)
                
                # If this is a direct command (not from the text input), execute it
                if msg.topic == f"{topic_prefix}/command/retroarch" and command != "EXECUTE":
                    logger.info(f"Direct command. Sending command to RetroArch: {command}")
                    result = send_retroarch_command(command)
                    
                    # Send acknowledgment
                    ack_topic = f"{topic_prefix}/command/retroarch/response"
                    if result is not None:
                        ack_payload = {
                            'timestamp': int(time.time()),
                            'status': 'success',
                            'command': command,
                            'response': result if isinstance(result, str) else ''
                        }
                    else:
                        ack_payload = {
                            'timestamp': int(time.time()),
                            'status': 'error',
                            'command': command,
                            'message': 'Failed to send command, check if RetroArch is running with Network Commands enabled'
                        }
                    publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
            else:
                logger.error("Received empty command")
                
                # Send error response
                ack_topic = f"{topic_prefix}/command/retroarch/response"
                ack_payload = {
                    'timestamp': int(time.time()),
                    'status': 'error',
                    'message': 'No command provided'
                }
                publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
    
    except Exception as e:
        logger.error(f"Error handling RetroArch command: {e}")
        # Send error response
        ack_topic = f"{topic_prefix}/command/retroarch/response"
        ack_payload = {
            'timestamp': int(time.time()),
            'status': 'error',
            'message': f'Error: {str(e)}'
        }
        publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)

def handle_ui_mode_command(msg, topic_prefix):
    """Handle EmulationStation UI mode change command"""
    try:
        # For select entity, the payload is just the mode
        mode = msg.payload.decode().strip()
        
        # Check if the message is in JSON format
        try:
            command_obj = json.loads(mode)
            if isinstance(command_obj, dict) and 'mode' in command_obj:
                mode = command_obj.get('mode', '')
        except json.JSONDecodeError:
            # Already have mode as plain text
            pass
        
        if mode and mode in ['Full', 'Kid', 'Kiosk']:
            # Change the UI mode
            logger.info(f"Changing EmulationStation UI mode to: {mode}")
            success = change_es_ui_mode(mode)
            
            # Update the mode state
            publish_mqtt_message(f"{topic_prefix}/ui_mode/state", mode, retain=True)
            
            # Send acknowledgment
            ack_topic = f"{topic_prefix}/command/ui_mode/response"
            if success:
                ack_payload = {
                    'timestamp': int(time.time()),
                    'status': 'success',
                    'mode': mode,
                    'message': f'UI mode changed to {mode}. EmulationStation will restart.'
                }
            else:
                ack_payload = {
                    'timestamp': int(time.time()),
                    'status': 'error',
                    'mode': mode,
                    'message': f'Failed to change UI mode to {mode}. Check logs for details.'
                }
            publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
        else:
            logger.error(f"Invalid UI mode: {mode}. Must be one of: Full, Kid, Kiosk")
            
            # Send error response
            ack_topic = f"{topic_prefix}/command/ui_mode/response"
            ack_payload = {
                'timestamp': int(time.time()),
                'status': 'error',
                'message': f'Invalid UI mode: {mode}. Must be one of: Full, Kid, Kiosk'
            }
            publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
    except Exception as e:
        logger.error(f"Error handling UI mode command: {e}")
        # Send error response
        ack_topic = f"{topic_prefix}/command/ui_mode/response"
        ack_payload = {
            'timestamp': int(time.time()),
            'status': 'error',
            'message': f'Error: {str(e)}'
        }
        publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)

def handle_scan_games_command(msg, topic_prefix):
    """Handle game collection scan command"""
    try:
        # Button press or direct command
        payload = msg.payload.decode().strip()
        
        if payload == "SCAN" or payload == "" or payload == "{}":
            # Start the scan
            logger.info("Received command to scan game collection")
            success = scan_game_collection()
            
            # Send acknowledgment
            ack_topic = f"{topic_prefix}/command/scan_games/response"
            if success:
                ack_payload = {
                    'timestamp': int(time.time()),
                    'status': 'success',
                    'message': 'Game collection scan started in the background'
                }
            else:
                ack_payload = {
                    'timestamp': int(time.time()),
                    'status': 'error',
                    'message': 'Failed to start game collection scan. Check logs for details.'
                }
            publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
        else:
            logger.error(f"Unexpected payload for scan command: {payload}")
            
            # Send error response
            ack_topic = f"{topic_prefix}/command/scan_games/response"
            ack_payload = {
                'timestamp': int(time.time()),
                'status': 'error',
                'message': f'Unexpected payload: {payload}'
            }
            publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)
    
    except Exception as e:
        logger.error(f"Error handling scan games command: {e}")
        # Send error response
        ack_topic = f"{topic_prefix}/command/scan_games/response"
        ack_payload = {
            'timestamp': int(time.time()),
            'status': 'error',
            'message': f'Error: {str(e)}'
        }
        publish_mqtt_message(ack_topic, json.dumps(ack_payload), retain=False)

def execute_tts(text):
    """Execute text-to-speech using system speakers"""
    try:
        # Use pico2wave for TTS (install with: sudo apt-get install libttspico-utils)
        wav_file = "/tmp/tts_output.wav"
        subprocess.run(["pico2wave", "-w", wav_file, text], check=True)
        
        # Play the generated audio file
        subprocess.run(["aplay", wav_file], check=True)
        
        # Clean up
        if os.path.exists(wav_file):
            os.remove(wav_file)
            
        logger.info("TTS executed successfully")
        return True
    except Exception as e:
        logger.error(f"Error executing TTS: {e}")
        return False

def scan_game_collection():
    """Scan all gamelist.xml files to collect game statistics"""
    try:
        # Scan in a separate thread to avoid blocking
        threading.Thread(target=_scan_game_collection_thread, daemon=True).start()
        return True
    except Exception as e:
        logger.error(f"Error starting game collection scan: {e}")
        return False

# Global observer for file monitoring
file_observer = None
scan_debounce_timer = None
DEBOUNCE_SECONDS = 5  # Debounce file changes to prevent multiple rapid scans

class GamelistChangeHandler(PatternMatchingEventHandler):
    """Event handler for gamelist.xml file changes"""
    
    def __init__(self):
        super(GamelistChangeHandler, self).__init__(
            patterns=["*gamelist.xml"],
            ignore_directories=True,
            case_sensitive=False
        )
    
    def on_modified(self, event):
        """Called when a file is modified"""
        self._handle_gamelist_change(event)
    
    def on_created(self, event):
        """Called when a file is created"""
        self._handle_gamelist_change(event)
    
    def _handle_gamelist_change(self, event):
        """Handle game list file changes with debounce"""
        global scan_debounce_timer
        
        # Log the event
        logger.info(f"Detected change in gamelist: {event.src_path}")
        
        # Cancel existing timer if it's running
        if scan_debounce_timer is not None:
            scan_debounce_timer.cancel()
        
        # Set a new timer to trigger scan after delay
        scan_debounce_timer = threading.Timer(DEBOUNCE_SECONDS, self._trigger_scan)
        scan_debounce_timer.daemon = True
        scan_debounce_timer.start()
    
    def _trigger_scan(self):
        """Trigger a game collection scan after debounce period"""
        logger.info("Triggering game collection scan due to gamelist.xml changes")
        scan_game_collection()

def start_file_monitoring():
    """Start monitoring gamelist.xml files for changes"""
    global file_observer
    
    if not watchdog_available:
        logger.warning("Watchdog library not available. File monitoring disabled.")
        logger.warning("To enable file monitoring, install watchdog using:")
        logger.warning("  sudo apt-get install python3-watchdog")
        logger.warning("  or pip3 install watchdog")
        return False
    
    try:
        # Create event handler and observer
        event_handler = GamelistChangeHandler()
        file_observer = Observer()
        file_observer.daemon = True  # Make sure observer thread exits when main thread exits
        
        # Schedule monitoring for each system directory
        if os.path.exists(ROMS_DIR):
            # Schedule the main ROMS_DIR
            file_observer.schedule(event_handler, ROMS_DIR, recursive=False)
            
            # Schedule each system directory
            for system_dir in os.listdir(ROMS_DIR):
                system_path = os.path.join(ROMS_DIR, system_dir)
                if os.path.isdir(system_path):
                    file_observer.schedule(event_handler, system_path, recursive=False)
        
        # Start the observer
        file_observer.start()
        logger.info(f"Started file monitoring for gamelist.xml files in {ROMS_DIR}")
        
        # Register a cleanup function to stop the observer
        atexit.register(stop_file_monitoring)
        
        return True
    except Exception as e:
        logger.error(f"Error starting file monitoring: {e}")
        return False

def stop_file_monitoring():
    """Stop monitoring gamelist.xml files"""
    global file_observer
    
    # If watchdog is not available, there's nothing to stop
    if not watchdog_available:
        return False
    
    if file_observer and file_observer.is_alive():
        logger.info("Stopping file monitoring")
        file_observer.stop()
        file_observer.join(timeout=3)  # Wait up to 3 seconds for the thread to finish
        file_observer = None
        return True
    return False

def _scan_game_collection_thread():
    """Background thread to scan game collection"""
    global current_state
    
    try:
        logger.info("Starting game collection scan...")
        start_time = time.time()
        
        # Stats to collect
        total_games = 0
        favorites = 0
        kid_friendly = 0
        systems_data = {}
        
        # Rating threshold for kid-friendly games (typically 0.0-1.0 scale)
        kid_rating_threshold = 0.5  # Consider games with rating <= 0.5 as kid-friendly
        
        # Scan each system directory in the ROMS_DIR
        for system_dir in os.listdir(ROMS_DIR):
            system_path = os.path.join(ROMS_DIR, system_dir)
            
            # Skip if not a directory
            if not os.path.isdir(system_path):
                continue
            
            # Look for gamelist.xml
            gamelist_path = os.path.join(system_path, 'gamelist.xml')
            if not os.path.exists(gamelist_path):
                continue
            
            # Parse the gamelist.xml
            try:
                tree = ET.parse(gamelist_path)
                root = tree.getroot()
                
                # Initialize system stats
                system_games = 0
                system_favorites = 0
                system_kid_friendly = 0
                
                # Process each game
                for game in root.findall('game'):
                    system_games += 1
                    
                    # Check if favorite
                    favorite_elem = game.find('favorite')
                    if favorite_elem is not None and favorite_elem.text == 'true':
                        system_favorites += 1
                        favorites += 1
                    
                    # Check rating for kid-friendly
                    rating_elem = game.find('rating')
                    if rating_elem is not None and rating_elem.text:
                        try:
                            rating = float(rating_elem.text)
                            if rating <= kid_rating_threshold:
                                system_kid_friendly += 1
                                kid_friendly += 1
                        except ValueError:
                            pass
                
                # Update total count
                total_games += system_games
                
                # Store system data
                systems_data[system_dir] = {
                    'games': system_games,
                    'favorites': system_favorites,
                    'kid_friendly': system_kid_friendly
                }
                
                logger.info(f"Scanned system '{system_dir}': {system_games} games, "
                           f"{system_favorites} favorites, {system_kid_friendly} kid-friendly")
            
            except Exception as e:
                logger.error(f"Error parsing gamelist for system '{system_dir}': {e}")
        
        # Update the global state
        current_state['game_collection'] = {
            'total_games': total_games,
            'favorites': favorites,
            'kid_friendly': kid_friendly,
            'last_scan': int(time.time()),
            'systems': systems_data
        }
        
        # Save state to file
        save_state()
        
        # Publish game collection stats
        publish_game_collection_stats()
        
        elapsed_time = time.time() - start_time
        logger.info(f"Game collection scan completed in {elapsed_time:.2f} seconds: "
                   f"{total_games} total games, {favorites} favorites, {kid_friendly} kid-friendly")
        
    except Exception as e:
        logger.error(f"Error in game collection scan thread: {e}")

def publish_game_collection_stats():
    """Publish game collection statistics to MQTT"""
    try:
        config = get_config()
        topic_prefix = config.get('mqtt_topic_prefix', 'retropie')
        
        # Prepare payload
        payload = {
            'timestamp': int(time.time()),
            'total_games': current_state['game_collection']['total_games'],
            'favorites': current_state['game_collection']['favorites'],
            'kid_friendly': current_state['game_collection']['kid_friendly'],
            'last_scan': current_state['game_collection']['last_scan'],
            'systems': len(current_state['game_collection']['systems'])
        }
        
        # Publish to the game_collection topic
        topic = f"{topic_prefix}/game_collection"
        publish_mqtt_message(topic, json.dumps(payload), retain=True)
        logger.info("Published game collection statistics")
        return True
    except Exception as e:
        logger.error(f"Error publishing game collection stats: {e}")
        return False

def change_es_ui_mode(mode):
    """Change EmulationStation's UI mode (Full, Kid, Kiosk)
    
    Args:
        mode (str): The UI mode to set. Must be one of: 'Full', 'Kid', 'Kiosk'
        
    Returns:
        bool: True if the mode was changed successfully, False otherwise
    """
    try:
        if mode not in ['Full', 'Kid', 'Kiosk']:
            logger.error(f"Invalid UI mode: {mode}. Must be one of: Full, Kid, Kiosk")
            return False
        
        # Path to EmulationStation settings file
        es_settings_paths = [
            os.path.expanduser('~/.emulationstation/es_settings.cfg'),
            '/opt/retropie/configs/all/emulationstation/es_settings.cfg'
        ]
        
        es_settings_path = None
        for path in es_settings_paths:
            if os.path.exists(path):
                es_settings_path = path
                break
        
        if not es_settings_path:
            logger.error("Could not find EmulationStation settings file")
            return False
        
        logger.info(f"Found EmulationStation settings at: {es_settings_path}")
        
        # Parse the XML settings file
        try:
            tree = ET.parse(es_settings_path)
            root = tree.getroot()
            
            # Check if UIMode setting exists
            ui_mode_elem = None
            for elem in root.findall('string'):
                if elem.get('name') == 'UIMode':
                    ui_mode_elem = elem
                    break
            
            if ui_mode_elem is not None:
                # Update existing setting
                current_mode = ui_mode_elem.get('value')
                if current_mode == mode:
                    logger.info(f"UI mode is already set to {mode}")
                    return True
                
                ui_mode_elem.set('value', mode)
                logger.info(f"Changed UI mode from {current_mode} to {mode}")
            else:
                # Create new UIMode setting
                ui_mode_elem = ET.SubElement(root, 'string')
                ui_mode_elem.set('name', 'UIMode')
                ui_mode_elem.set('value', mode)
                logger.info(f"Created new UI mode setting: {mode}")
            
            # Write the updated settings back to the file
            tree.write(es_settings_path)
            
            # Restart EmulationStation if it's running
            restart_emulationstation()
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating EmulationStation settings: {e}")
            return False
            
    except Exception as e:
        logger.error(f"Error changing EmulationStation UI mode: {e}")
        return False

def restart_emulationstation():
    """Restart EmulationStation by touching /tmp/es-restart and killing the process"""
    try:
        # Create the restart trigger file
        with open('/tmp/es-restart', 'w') as f:
            f.write('')
        
        # Kill EmulationStation to trigger restart
        try:
            subprocess.run(['killall', 'emulationstation'], check=False)
            logger.info("Sent restart signal to EmulationStation")
            return True
        except Exception as e:
            logger.error(f"Error killing EmulationStation: {e}")
            return False
            
    except Exception as e:
        logger.error(f"Error creating restart trigger: {e}")
        return False

def verify_retroarch_network_commands():
    """Verify that RetroArch has network commands enabled and set it if not"""
    try:
        # Common paths for RetroArch configuration
        retroarch_cfg_paths = [
            os.path.expanduser('~/.config/retroarch/retroarch.cfg'),
            '/opt/retropie/configs/all/retroarch.cfg',
            '/etc/retroarch.cfg'
        ]
        
        for cfg_path in retroarch_cfg_paths:
            if os.path.exists(cfg_path):
                logger.info(f"Found RetroArch config at: {cfg_path}")
                
                # Check if we need to modify the config
                modified = False
                
                # Read the current config
                with open(cfg_path, 'r') as f:
                    config_lines = f.readlines()
                
                # Check for network_cmd_enable setting
                has_network_enable = False
                for i, line in enumerate(config_lines):
                    if 'network_cmd_enable' in line:
                        has_network_enable = True
                        if 'false' in line.lower():
                            config_lines[i] = 'network_cmd_enable = "true"\n'
                            modified = True
                            logger.info("Updated network_cmd_enable to true")
                
                # Add network_cmd_enable if it doesn't exist
                if not has_network_enable:
                    config_lines.append('network_cmd_enable = "true"\n')
                    modified = True
                    logger.info("Added network_cmd_enable = true")
                
                # Check for network_cmd_port setting
                has_network_port = False
                for line in config_lines:
                    if 'network_cmd_port' in line:
                        has_network_port = True
                
                # Add network_cmd_port if it doesn't exist
                if not has_network_port:
                    config_lines.append(f'network_cmd_port = "{RETROARCH_PORT}"\n')
                    modified = True
                    logger.info(f"Added network_cmd_port = {RETROARCH_PORT}")
                
                # Write back the modified config if changes were made
                if modified:
                    try:
                        with open(cfg_path, 'w') as f:
                            f.writelines(config_lines)
                        logger.info(f"Updated RetroArch config at {cfg_path}")
                    except Exception as write_err:
                        logger.error(f"Error writing RetroArch config: {write_err}")
                
                # We found and processed a config file, so we're done
                return True
        
        logger.warning("Could not find RetroArch configuration file")
        return False
    except Exception as e:
        logger.error(f"Error verifying RetroArch network commands: {e}")
        return False

def send_retroarch_command(command):
    """Send a command to RetroArch via Network Control Interface"""
    try:
        # Create a UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.0)  # Set a 1-second timeout
        
        # Send the command
        sock.sendto(command.encode(), ('127.0.0.1', RETROARCH_PORT))
        
        # For commands that expect a response, wait for it
        if command in ["VERSION", "GET_STATUS", "GET_CONFIG_PARAM"]:
            try:
                response, addr = sock.recvfrom(1024)
                return response.decode().strip()
            except socket.timeout:
                logger.warning(f"Timeout waiting for response to command: {command}")
                return None
        
        return True
    except Exception as e:
        logger.error(f"Error sending RetroArch command: {e}")
        return None
    finally:
        sock.close()

def display_retroarch_message(message):
    """Display a message on the RetroArch screen"""
    try:
        # The SHOW_MESG command requires the message in a specific format
        command = f"SHOW_MESG {message}"
        result = send_retroarch_command(command)
        return result is not None
    except Exception as e:
        logger.error(f"Error displaying RetroArch message: {e}")
        return False

def get_retroarch_status():
    """Get the current status of RetroArch"""
    try:
        response = send_retroarch_command("GET_STATUS")
        if response:
            # Parse the response
            status_info = {}
            lines = response.split('\n')
            for line in lines:
                if ':' in line:
                    key, value = line.split(':', 1)
                    status_info[key.strip()] = value.strip()
            return status_info
        return None
    except Exception as e:
        logger.error(f"Error getting RetroArch status: {e}")
        return None

def start_mqtt_listener():
    """Start a background MQTT listener for commands"""
    config = get_config()
    
    if not config.get('mqtt_host'):
        logger.error("MQTT host not configured, cannot start listener")
        return False
    
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    
    if config.get('mqtt_username') and config.get('mqtt_password'):
        client.username_pw_set(config['mqtt_username'], config['mqtt_password'])
    
    try:
        client.connect(config['mqtt_host'], int(config.get('mqtt_port', 1883)), 60)
        client.loop_start()
        logger.info("MQTT listener started")
        return client
    except Exception as e:
        logger.error(f"Error starting MQTT listener: {e}")
        return None

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
    
    # Origin information
    origin_info = {
        "name": "RetroPie Home Assistant Integration",
        "sw": sw_version,
        "url": "https://github.com/yourusername/retropie-ha-integration"
    }
    
    # Availability definition (common for all sensors)
    availability = [
        {
            "topic": f"{topic_prefix}/availability",
            "value_template": "{{ value }}"
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
    
    # Register machine status sensor
    machine_status_config = {
        "device": device_info,
        "name": f"RetroPie {device_name} Machine Status",
        "unique_id": f"retropie_{safe_device_name}_machine_status",
        "object_id": f"retropie_{safe_device_name}_machine_status",
        "state_topic": f"{topic_prefix}/machine_status",
        "value_template": "{{ value_json.status }}",
        "icon": "mdi:nintendo-switch",
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
        "state_topic": f"{topic_prefix}/machine_status",
        "value_template": "{{ value_json.current_game if value_json.current_game else 'None' }}",
        "json_attributes_topic": f"{topic_prefix}/event/game-start",
        "json_attributes_template": "{{ {'description': value_json.description if 'description' in value_json else '', 'system': value_json.system if 'system' in value_json else '', 'emulator': value_json.emulator if 'emulator' in value_json else '', 'genre': value_json.genre if 'genre' in value_json else '', 'developer': value_json.developer if 'developer' in value_json else '', 'publisher': value_json.publisher if 'publisher' in value_json else '', 'rating': value_json.rating if 'rating' in value_json else '', 'releasedate': value_json.releasedate if 'releasedate' in value_json else '', 'start_time': value_json.start_time if 'start_time' in value_json else '' } | tojson }}",
        "icon": "mdi:gamepad-variant",
        "availability": availability,
        "availability_mode": "all",
        "enabled_by_default": True,
        "origin": origin_info
    }
    
    # Register play duration sensor
    play_duration_config = {
        "device": device_info,
        "name": f"RetroPie {device_name} Play Duration",
        "unique_id": f"retropie_{safe_device_name}_play_duration",
        "object_id": f"retropie_{safe_device_name}_play_duration",
        "state_topic": f"{topic_prefix}/machine_status",
        "value_template": "{{ value_json.play_duration_seconds if 'play_duration_seconds' in value_json else 0 }}",
        "unit_of_measurement": "s",
        "icon": "mdi:timer",
        "state_class": "measurement",
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
    
    # Register TTS input text entity
    tts_input_config = {
        "device": device_info,
        "name": f"RetroPie {device_name} TTS Text",
        "unique_id": f"retropie_{safe_device_name}_tts_text",
        "state_topic": f"{topic_prefix}/tts_text/state",
        "command_topic": f"{topic_prefix}/tts_text/set",
        "icon": "mdi:text-to-speech",
        "availability": availability,
        "availability_mode": "all",
        "retain": False,
        "enabled_by_default": True,
        "origin": origin_info
    }
    
    # Register TTS button entity
    tts_button_config = {
        "device": device_info,
        "name": f"RetroPie {device_name} TTS Speak",
        "unique_id": f"retropie_{safe_device_name}_tts_speak",
        "command_topic": f"{topic_prefix}/command/tts",
        "payload_press": "SPEAK",
        "icon": "mdi:text-to-speech",
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
            f"{topic_prefix}/availability",
            availability_payload,
            qos=1,
            retain=True
        )
        logger.info(f"Published availability status")
        
        # Publish initial machine status
        publish_machine_status()
        
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
            f"homeassistant/sensor/retropie_{safe_device_name}/machine_status/config",
            json.dumps(machine_status_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published machine status sensor config")
        
        client.publish(
            f"homeassistant/sensor/retropie_{safe_device_name}/game_status/config",
            json.dumps(game_status_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published game status sensor config")
        
        client.publish(
            f"homeassistant/sensor/retropie_{safe_device_name}/play_duration/config",
            json.dumps(play_duration_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published play duration sensor config")
        
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
        
        # Register total games sensor
        total_games_config = {
            "device": device_info,
            "name": f"RetroPie {device_name} Total Games",
            "unique_id": f"retropie_{safe_device_name}_total_games",
            "object_id": f"retropie_{safe_device_name}_total_games",
            "state_topic": f"{topic_prefix}/game_collection",
            "value_template": "{{ value_json.total_games }}",
            "icon": "mdi:gamepad-variant-outline",
            "state_class": "measurement",
            "availability": availability,
            "availability_mode": "all",
            "enabled_by_default": True,
            "origin": origin_info
        }
        
        client.publish(
            f"homeassistant/sensor/retropie_{safe_device_name}/total_games/config",
            json.dumps(total_games_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published total games sensor config")
        
        # Register favorites sensor
        favorites_config = {
            "device": device_info,
            "name": f"RetroPie {device_name} Favorite Games",
            "unique_id": f"retropie_{safe_device_name}_favorites",
            "object_id": f"retropie_{safe_device_name}_favorites",
            "state_topic": f"{topic_prefix}/game_collection",
            "value_template": "{{ value_json.favorites }}",
            "icon": "mdi:star",
            "state_class": "measurement",
            "availability": availability,
            "availability_mode": "all",
            "enabled_by_default": True,
            "origin": origin_info
        }
        
        client.publish(
            f"homeassistant/sensor/retropie_{safe_device_name}/favorites/config",
            json.dumps(favorites_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published favorites sensor config")
        
        # Register kid-friendly games sensor
        kid_friendly_config = {
            "device": device_info,
            "name": f"RetroPie {device_name} Kid-Friendly Games",
            "unique_id": f"retropie_{safe_device_name}_kid_friendly",
            "object_id": f"retropie_{safe_device_name}_kid_friendly",
            "state_topic": f"{topic_prefix}/game_collection",
            "value_template": "{{ value_json.kid_friendly }}",
            "icon": "mdi:human-male-child",
            "state_class": "measurement",
            "availability": availability,
            "availability_mode": "all",
            "enabled_by_default": True,
            "origin": origin_info
        }
        
        client.publish(
            f"homeassistant/sensor/retropie_{safe_device_name}/kid_friendly/config",
            json.dumps(kid_friendly_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published kid-friendly games sensor config")
        
        client.publish(
            f"homeassistant/text/retropie_{safe_device_name}/tts_text/config",
            json.dumps(tts_input_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published TTS text input config")
        
        client.publish(
            f"homeassistant/button/retropie_{safe_device_name}/tts_speak/config",
            json.dumps(tts_button_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published TTS button config")
        
        # Register RetroArch message input text
        retroarch_message_input_config = {
            "device": device_info,
            "name": f"RetroPie {device_name} RetroArch Message Text",
            "unique_id": f"retropie_{safe_device_name}_retroarch_message_text",
            "state_topic": f"{topic_prefix}/retroarch_message_text/state",
            "command_topic": f"{topic_prefix}/retroarch_message_text/set",
            "icon": "mdi:message-text",
            "availability": availability,
            "availability_mode": "all",
            "retain": False,
            "enabled_by_default": True,
            "origin": origin_info
        }
        
        client.publish(
            f"homeassistant/text/retropie_{safe_device_name}/retroarch_message_text/config",
            json.dumps(retroarch_message_input_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published RetroArch message text input config")
        
        # Register RetroArch message button
        retroarch_message_button_config = {
            "device": device_info,
            "name": f"RetroPie {device_name} Display Message",
            "unique_id": f"retropie_{safe_device_name}_retroarch_display_message",
            "command_topic": f"{topic_prefix}/command/retroarch/message",
            "payload_press": "DISPLAY",
            "icon": "mdi:message-text",
            "availability": availability,
            "availability_mode": "all",
            "enabled_by_default": True,
            "origin": origin_info
        }
        
        client.publish(
            f"homeassistant/button/retropie_{safe_device_name}/retroarch_display_message/config",
            json.dumps(retroarch_message_button_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published RetroArch message button config")
        
        # Register RetroArch command input text
        retroarch_command_input_config = {
            "device": device_info,
            "name": f"RetroPie {device_name} RetroArch Command Text",
            "unique_id": f"retropie_{safe_device_name}_retroarch_command_text",
            "state_topic": f"{topic_prefix}/retroarch_command_text/state",
            "command_topic": f"{topic_prefix}/retroarch_command_text/set",
            "icon": "mdi:gamepad-variant",
            "availability": availability,
            "availability_mode": "all",
            "retain": False,
            "enabled_by_default": True,
            "origin": origin_info
        }
        
        client.publish(
            f"homeassistant/text/retropie_{safe_device_name}/retroarch_command_text/config",
            json.dumps(retroarch_command_input_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published RetroArch command text input config")
        
        # Register RetroArch command button
        retroarch_command_button_config = {
            "device": device_info,
            "name": f"RetroPie {device_name} Execute Command",
            "unique_id": f"retropie_{safe_device_name}_retroarch_execute_command",
            "command_topic": f"{topic_prefix}/command/retroarch",
            "payload_press": "EXECUTE",
            "icon": "mdi:gamepad-variant",
            "availability": availability,
            "availability_mode": "all",
            "enabled_by_default": True,
            "origin": origin_info
        }
        
        client.publish(
            f"homeassistant/button/retropie_{safe_device_name}/retroarch_execute_command/config",
            json.dumps(retroarch_command_button_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published RetroArch command button config")
        
        # Register RetroArch status button
        retroarch_status_button_config = {
            "device": device_info,
            "name": f"RetroPie {device_name} Get Status",
            "unique_id": f"retropie_{safe_device_name}_retroarch_get_status",
            "command_topic": f"{topic_prefix}/command/retroarch/status",
            "payload_press": "GET_STATUS",
            "icon": "mdi:information-outline",
            "availability": availability,
            "availability_mode": "all",
            "enabled_by_default": True,
            "origin": origin_info
        }
        
        client.publish(
            f"homeassistant/button/retropie_{safe_device_name}/retroarch_get_status/config",
            json.dumps(retroarch_status_button_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published RetroArch status button config")
        
        # Register UI mode select entity
        ui_mode_select_config = {
            "device": device_info,
            "name": f"RetroPie {device_name} UI Mode",
            "unique_id": f"retropie_{safe_device_name}_ui_mode_select",
            "state_topic": f"{topic_prefix}/ui_mode/state",
            "command_topic": f"{topic_prefix}/command/ui_mode",
            "options": ["Full", "Kid", "Kiosk"],
            "icon": "mdi:view-dashboard",
            "availability": availability,
            "availability_mode": "all",
            "enabled_by_default": True,
            "origin": origin_info
        }
        
        client.publish(
            f"homeassistant/select/retropie_{safe_device_name}/ui_mode/config",
            json.dumps(ui_mode_select_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published UI mode select config")
        
        # Register scan games button
        scan_games_button_config = {
            "device": device_info,
            "name": f"RetroPie {device_name} Scan Games",
            "unique_id": f"retropie_{safe_device_name}_scan_games_button",
            "command_topic": f"{topic_prefix}/command/scan_games",
            "payload_press": "SCAN",
            "icon": "mdi:database-search",
            "availability": availability,
            "availability_mode": "all",
            "enabled_by_default": True,
            "origin": origin_info
        }
        
        client.publish(
            f"homeassistant/button/retropie_{safe_device_name}/scan_games/config",
            json.dumps(scan_games_button_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published scan games button config")
        
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
    
    # Load saved state if exists
    load_state()
    
    parser = argparse.ArgumentParser(description='RetroPie Home Assistant Integration')
    parser.add_argument('--event', help='Event type (game-start, game-end, etc.)')
    parser.add_argument('--status', action='store_true', help='Publish system status')
    parser.add_argument('--register', action='store_true', help='Register with Home Assistant')
    parser.add_argument('--tts', help='Text to speak')
    parser.add_argument('--listen', action='store_true', help='Start MQTT listener for commands')
    parser.add_argument('args', nargs='*', help='Event arguments')
    
    args = parser.parse_args()
    
    if args.register:
        logger.info("Registering with Home Assistant...")
        if register_with_ha():
            logger.info("Successfully registered with Home Assistant")
        else:
            logger.error("Failed to register with Home Assistant")
        sys.exit(0)
    
    if args.tts:
        logger.info(f"Executing TTS: {args.tts}")
        execute_tts(args.tts)
        sys.exit(0)
    
    if args.listen:
        logger.info("Starting MQTT listener...")
        # Send system-start event
        publish_game_event('system-start')
        
        # Start MQTT listener
        # Start a game collection scan in the background
        logger.info("Starting initial game collection scan...")
        scan_game_collection()
        
        # Start monitoring gamelist.xml files for changes
        start_file_monitoring()
        
        mqtt_client = start_mqtt_listener()
        if mqtt_client:
            try:
                # Keep the program running
                while True:
                    time.sleep(10)
                    # Publish status update periodically
                    publish_system_status()
            except KeyboardInterrupt:
                logger.info("Stopping MQTT listener...")
                mqtt_client.loop_stop()
                # Stop file monitoring
                stop_file_monitoring()
                
                # Send system-shutdown event before exiting
                publish_game_event('quit')
        sys.exit(0)
    
    if args.status:
        publish_system_status()
        sys.exit(0)
    
    if args.event:
        publish_game_event(args.event, args.args)
        sys.exit(0)
    
    # If no arguments provided, just publish status
    publish_system_status()