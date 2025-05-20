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

# Detect system type
SYSTEM_TYPE = "unknown"
if os.path.exists("/opt/retropie"):
    SYSTEM_TYPE = "retropie"
    CONFIG_DIR = os.path.expanduser('~/.config/retropie-ha')
    ROMS_DIR = os.path.expanduser('~/RetroPie/roms')
    SYSTEM_NAME = "retropie"
elif os.path.exists("/userdata/system"):
    SYSTEM_TYPE = "batocera"
    CONFIG_DIR = "/userdata/system/retropie-ha"
    ROMS_DIR = "/userdata/roms"
    SYSTEM_NAME = "batocera"
else:
    # Fallback to RetroPie defaults
    CONFIG_DIR = os.path.expanduser('~/.config/retropie-ha')
    ROMS_DIR = os.path.expanduser('~/RetroPie/roms')
    SYSTEM_NAME = "retropie"

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(CONFIG_DIR, 'retropie-ha.log'))
        # Removed StreamHandler to prevent console output
    ]
)
logger = logging.getLogger(f'{SYSTEM_NAME}-ha')

# Constants
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')
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

def get_cpu_frequency():
    """Get current CPU frequency in MHz using vcgencmd"""
    try:
        output = subprocess.check_output(['vcgencmd', 'measure_clock', 'arm'], universal_newlines=True)
        freq = re.search(r'frequency\(\d+\)=(\d+)', output)
        if freq:
            # Convert from Hz to MHz
            return int(int(freq.group(1)) / 1000000)
        
        # Alternative format parsing
        freq = re.search(r'=(\d+)', output)
        if freq:
            # Convert from Hz to MHz
            return int(int(freq.group(1)) / 1000000)
    except Exception as e:
        logger.error(f"Failed to get CPU frequency: {e}")
    return None

def get_gpu_frequency():
    """Get current GPU frequency in MHz using vcgencmd"""
    try:
        output = subprocess.check_output(['vcgencmd', 'measure_clock', 'core'], universal_newlines=True)
        freq = re.search(r'frequency\(\d+\)=(\d+)', output)
        if freq:
            # Convert from Hz to MHz
            return int(int(freq.group(1)) / 1000000)
            
        # Alternative format parsing
        freq = re.search(r'=(\d+)', output)
        if freq:
            # Convert from Hz to MHz
            return int(int(freq.group(1)) / 1000000)
    except Exception as e:
        logger.error(f"Failed to get GPU frequency: {e}")
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
        'cpu_freq': get_cpu_frequency(),
        'gpu_freq': get_gpu_frequency(),
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
        
        # Find the gamelist.xml file - check multiple possible locations based on system type
        gamelist_paths = []
        
        # First try system-specific ROM directory (primary location)
        gamelist_paths.append(os.path.join(ROMS_DIR, system, 'gamelist.xml'))
        
        # For Batocera, also check alternative locations
        if SYSTEM_TYPE == "batocera":
            # Batocera can have gamelist.xml files in multiple locations
            gamelist_paths.append(f"/userdata/system/configs/emulationstation/gamelists/{system}/gamelist.xml")
        
        # For RetroPie, check alternative location
        elif SYSTEM_TYPE == "retropie":
            gamelist_paths.append(os.path.expanduser(f"~/.emulationstation/gamelists/{system}/gamelist.xml"))
        
        # Try each path until we find an existing file
        gamelist_path = None
        for path in gamelist_paths:
            if os.path.exists(path):
                gamelist_path = path
                break
        
        if not gamelist_path:
            logger.warning(f"gamelist.xml not found for system {system} in any of the expected locations")
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

def publish_mqtt_message(topic, message, retain=False, max_retries=5, shutdown_mode=False):
    """Publish a message to MQTT broker with retry logic"""
    global args  # Access command line args to check for shutdown mode
    
    # Check if we're in shutdown mode from function parameter or command line args
    if not shutdown_mode and hasattr(args, 'shutdown_mode') and args.shutdown_mode:
        shutdown_mode = True
    
    config = get_config()
    
    if not config.get('mqtt_host'):
        logger.error("MQTT host not configured")
        return False
    
    # Quick network check before attempting MQTT connection (to avoid hanging)
    if shutdown_mode:
        try:
            # Use a very short socket timeout to test connectivity (0.5 seconds)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            result = s.connect_ex((config['mqtt_host'], int(config.get('mqtt_port', 1883))))
            s.close()
            if result != 0:
                logger.warning(f"Network check failed during shutdown - MQTT broker unreachable")
                return False
        except Exception as e:
            logger.warning(f"Network check failed during shutdown: {e}")
            return False
      # Use a unique client id to avoid connection conflicts
    client_id = f"{SYSTEM_NAME}-publisher-{int(time.time())}-{os.getpid()}"
    client = mqtt.Client(client_id=client_id)
    
    # Set up a connection callback to track successful connections
    connection_successful = False
    def on_connect_local(client, userdata, flags, rc):
        nonlocal connection_successful
        if rc == 0:
            connection_successful = True
        else:
            logger.warning(f"Connection failed with result code {rc}")
    
    client.on_connect = on_connect_local
    
    if config.get('mqtt_username') and config.get('mqtt_password'):
        client.username_pw_set(config['mqtt_username'], config['mqtt_password'])
    
    # Set appropriate timeouts and retry counts based on mode
    if shutdown_mode:
        # Use minimal retries and timeouts during shutdown
        actual_max_retries = 1
        connect_timeout = 2
        publish_wait = 1
        max_wait = 1
    else:
        # Normal operation values
        actual_max_retries = max_retries
        connect_timeout = 15
        publish_wait = 5
        max_wait = 60
    
    # Add retry logic with exponential backoff
    retries = 0
    while retries < actual_max_retries:
        try:
            # Set connection timeout based on mode
            client.connect_async(config['mqtt_host'], int(config.get('mqtt_port', 1883)))
            client.loop_start()
            
            # Wait for connection with timeout
            connect_start = time.time()
            while not connection_successful and time.time() - connect_start < connect_timeout:
                time.sleep(0.1)
                
            if not connection_successful:
                client.loop_stop()
                raise Exception(f"Connection timed out after {connect_timeout} seconds")
            
            # Set up for synchronous publishing with result checking
            msg_info = client.publish(topic, message, qos=1, retain=retain)
            
            # Wait for the message to be sent (with a timeout)
            publish_success = False
            start_time = time.time()
            
            # Set up a publish callback
            def on_publish(client, userdata, mid):
                nonlocal publish_success
                if mid == msg_info.mid:
                    publish_success = True
            
            client.on_publish = on_publish
            
            while not publish_success and time.time() - start_time < publish_wait:
                time.sleep(0.1)  # Check less frequently to reduce CPU usage
            
            # Cleanup
            client.loop_stop()
            client.disconnect()
            
            # Check if the publish succeeded
            if not publish_success:
                raise Exception("Message publish timed out")
                
            logger.info(f"Published to {topic}: {message[:100]}{'...' if len(message) > 100 else ''}")
            return True
        except Exception as e:
            retries += 1
            # Only log as error on final retry, otherwise log as warning
            if retries >= actual_max_retries:
                log_level = logging.WARNING if shutdown_mode else logging.ERROR
                logger.log(log_level, f"Error publishing to MQTT after {actual_max_retries} attempts: {e}")
                if isinstance(e, socket.error):
                    logger.log(log_level, f"Socket error details: {e.errno} - {e.strerror}")
                try:
                    client.loop_stop()
                    client.disconnect()
                except:
                    pass
                return False
            else:
                # Calculate wait time with exponential backoff (2^retry seconds)
                wait_time = min(2 ** retries, max_wait)
                logger.warning(f"Error publishing to MQTT (attempt {retries}/{actual_max_retries}): {e}. Retrying in {wait_time} seconds.")
                try:
                    client.loop_stop()
                    client.disconnect()
                except:
                    pass
                time.sleep(wait_time)
                
    # This should never be reached due to the return in the final retry
    return False

def publish_game_event(event_type, event_args=None):
    """Publish an EmulationStation game event to MQTT"""
    global current_state, args
    
    # Check if we're in shutdown mode for quit events
    shutdown_mode = False
    if event_type == 'quit' and hasattr(args, 'shutdown_mode') and args.shutdown_mode:
        shutdown_mode = True
        logger.info("Processing quit event in shutdown mode with reduced timeouts")
    
    config = get_config()
    topic_prefix = config.get('mqtt_topic_prefix', SYSTEM_NAME)
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
        
    elif event_type == 'game-start' and event_args and len(event_args) >= 3:
        system = event_args[0]
        rom_path = event_args[2]
        emulator = event_args[1]
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
        
        if event_args and len(event_args) >= 1:
            payload.update({'quit_mode': event_args[0]})
        
        # Also publish availability status with shutdown_mode flag
        publish_state_message(f"{topic_prefix}/availability", "offline", retain=True, shutdown_mode=shutdown_mode)
        
        # Skip machine status update during shutdown if in shutdown mode (to save time)
        if not shutdown_mode:
            publish_machine_status()
        else:
            logger.info("Skipping extra status updates during shutdown mode")
    
    topic = f"{topic_prefix}/event/{event_type}"
    # Events should NOT be retained - they should expire when received
    # Pass shutdown_mode flag for quit events
    if event_type == 'quit':
        return publish_mqtt_message(topic, json.dumps(payload), retain=False, shutdown_mode=shutdown_mode)
    else:
        return publish_mqtt_message(topic, json.dumps(payload), retain=False)

def publish_state_message(state_topic, state_value, retain=True, shutdown_mode=False):
    """Publish a simple state message to MQTT"""
    return publish_mqtt_message(state_topic, state_value, retain=retain, shutdown_mode=shutdown_mode)

def publish_machine_status():
    """Publish machine status to MQTT"""
    config = get_config()
    topic_prefix = config.get('mqtt_topic_prefix', SYSTEM_NAME)
    
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
    topic_prefix = config.get('mqtt_topic_prefix', SYSTEM_NAME)
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
    topic_prefix = get_config().get('mqtt_topic_prefix', SYSTEM_NAME)
    
    # Subscribe to all command topics
    command_topics = [
        # Debug topic for testing
        f"{topic_prefix}/debug",
        
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
        topic_prefix = config.get('mqtt_topic_prefix', SYSTEM_NAME)
        
        # Debug topic for testing connection
        if msg.topic == f"{topic_prefix}/debug":
            logger.info(f"DEBUG MESSAGE RECEIVED: {msg.payload.decode()}")
            publish_mqtt_message(f"{topic_prefix}/debug/response", 
                              f"Debug received: {msg.payload.decode()}", retain=False)
            return
        
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
            if not hasattr(handle_retroarch_message_command, 'current_text'):
                handle_retroarch_message_command.current_text = ""
            handle_retroarch_message_command.current_text = text
            # Update the state topic
            publish_mqtt_message(f"{topic_prefix}/retroarch_message_text/state", text, retain=True)
        elif msg.topic == f"{topic_prefix}/command/retroarch":
            handle_retroarch_command_message(msg, topic_prefix)
        elif msg.topic == f"{topic_prefix}/retroarch_command_text/set":
            # Store the command text for later use
            text = msg.payload.decode().strip()
            if not hasattr(handle_retroarch_command_message, 'current_text'):
                handle_retroarch_command_message.current_text = ""
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
        # More detailed error reporting
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

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
        
        # Play the generated audio file using the logged-in user's audio session
        try:
            # First, get the user who is currently logged in and has the active X session
            user_cmd = subprocess.run(["who"], capture_output=True, text=True)
            active_users = user_cmd.stdout.strip().split('\n')
            
            if active_users:
                # Use the first active user
                active_user = active_users[0].split()[0]
                logger.info(f"Found active user: {active_user}")
                
                # Run the command as the active user who has access to the audio system
                command = f"export XDG_RUNTIME_DIR=/run/user/$(id -u {active_user}) && aplay {wav_file}"
                play_cmd = subprocess.run(["sudo", "-u", active_user, "bash", "-c", command], check=True)
                logger.info("Audio played successfully through user session")
            else:
                # If no active user, try direct playback
                logger.info("No active user session found, trying direct playback")
                subprocess.run(["aplay", wav_file], check=True)
                
        except Exception as session_error:
            logger.error(f"Error playing through user session: {session_error}")
            
            # Try alternative methods in sequence
            methods = [
                # Try with default user
                ("Playing via pi user", ["sudo", "-u", "pi", "aplay", wav_file]),
                # Try with PULSE_SERVER
                ("Playing with PULSE_SERVER", ["env", "PULSE_SERVER=localhost", "aplay", wav_file]),
                # Try mpg123
                ("Trying mpg123", ["mpg123", wav_file]),
                # Try omxplayer 
                ("Trying omxplayer", ["omxplayer", "-o", "both", wav_file]),
                # Try mplayer
                ("Trying mplayer", ["mplayer", wav_file]),
                # Try specific ALSA device
                ("Trying HDMI output", ["aplay", "-D", "plughw:0,0", wav_file]),
                # Try HDMI 1
                ("Trying HDMI 1", ["aplay", "-D", "plughw:1,0", wav_file])
            ]
            
            success = False
            for desc, cmd in methods:
                try:
                    logger.info(desc)
                    subprocess.run(cmd, check=True)
                    success = True
                    logger.info(f"Success with {desc}")
                    break
                except Exception as e:
                    logger.error(f"Failed with {desc}: {e}")
            
            if not success:
                # As a last resort, save play command to a script for manual execution
                script_path = "/tmp/play_tts.sh"
                with open(script_path, 'w') as f:
                    f.write("#!/bin/bash\n")
                    f.write(f"aplay {wav_file}\n")
                os.chmod(script_path, 0o755)
                logger.error(f"Audio playback failed with all methods. Manual script saved to {script_path}")
                raise Exception("All audio playback methods failed")
        
        # Clean up only if requested
        cleanup = True  # Set to False for debugging
        if cleanup and os.path.exists(wav_file):
            os.remove(wav_file)
            
        logger.info("TTS executed successfully")
        return True
    except Exception as e:
        logger.error(f"Error executing TTS: {e}")
        # Don't fail the whole operation due to audio issues
        return True  # Still return success so other operations continue

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
        
        # Monitor locations based on system type
        paths_to_monitor = []
        
        # Always monitor the ROMs directory for all systems
        if os.path.exists(ROMS_DIR):
            paths_to_monitor.append(ROMS_DIR)
            
            # Add each system subdirectory
            for system_dir in os.listdir(ROMS_DIR):
                system_path = os.path.join(ROMS_DIR, system_dir)
                if os.path.isdir(system_path):
                    paths_to_monitor.append(system_path)
        
        # For Batocera, also monitor the ES configs directory
        if SYSTEM_TYPE == "batocera" and os.path.exists("/userdata/system/configs/emulationstation/gamelists"):
            paths_to_monitor.append("/userdata/system/configs/emulationstation/gamelists")
            
            # Add each system's gamelist directory
            es_gamelists = "/userdata/system/configs/emulationstation/gamelists"
            if os.path.exists(es_gamelists):
                for system_dir in os.listdir(es_gamelists):
                    system_path = os.path.join(es_gamelists, system_dir)
                    if os.path.isdir(system_path):
                        paths_to_monitor.append(system_path)
        
        # For RetroPie, monitor the ES gamelists directory
        elif SYSTEM_TYPE == "retropie":
            es_gamelists = os.path.expanduser("~/.emulationstation/gamelists")
            if os.path.exists(es_gamelists):
                paths_to_monitor.append(es_gamelists)
                
                # Add each system's gamelist directory
                for system_dir in os.listdir(es_gamelists):
                    system_path = os.path.join(es_gamelists, system_dir)
                    if os.path.isdir(system_path):
                        paths_to_monitor.append(system_path)
        
        # Schedule monitoring for all identified paths
        for path in paths_to_monitor:
            file_observer.schedule(event_handler, path, recursive=False)
        
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
            
            # Look for gamelist.xml - check multiple possible locations
            gamelist_paths = []
            
            # First try system-specific ROM directory (primary location)
            gamelist_paths.append(os.path.join(system_path, 'gamelist.xml'))
            
            # For Batocera, also check alternative locations
            if SYSTEM_TYPE == "batocera":
                # Batocera can have gamelist.xml files in multiple locations
                gamelist_paths.append(f"/userdata/system/configs/emulationstation/gamelists/{system_dir}/gamelist.xml")
            
            # For RetroPie, check alternative location
            elif SYSTEM_TYPE == "retropie":
                gamelist_paths.append(os.path.expanduser(f"~/.emulationstation/gamelists/{system_dir}/gamelist.xml"))
            
            # Try each path until we find an existing file
            gamelist_path = None
            for path in gamelist_paths:
                if os.path.exists(path):
                    gamelist_path = path
                    break
            
            if not gamelist_path:
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
        topic_prefix = config.get('mqtt_topic_prefix', SYSTEM_NAME)
        
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
        
        # First try the direct text manipulation approach which is more reliable
        try:
            # Read the current file content
            with open(es_settings_path, 'r') as f:
                content = f.read()
            
            # Check if UIMode is already in the file
            mode_pattern = re.compile(r'<(string|bool) name="UIMode" value="([^"]*)"')
            match = mode_pattern.search(content)
            
            if match:
                # Found existing setting, update it
                current_mode = match.group(2)
                tag_type = match.group(1)  # string or bool
                
                if current_mode == mode:
                    logger.info(f"UI mode is already set to {mode}")
                    return True
                
                # Replace the existing setting
                logger.info(f"Changing UI mode from {current_mode} to {mode}")
                content = re.sub(
                    f'<{tag_type} name="UIMode" value="[^"]*"',
                    f'<{tag_type} name="UIMode" value="{mode}"',
                    content
                )
            else:
                # No existing setting, add it after XML declaration or at the start
                logger.info(f"Adding new UI mode setting: {mode}")
                if '?>' in content:
                    # Add after XML declaration
                    xml_end = content.find('?>') + 2
                    content = content[:xml_end] + f'\n<string name="UIMode" value="{mode}" />' + content[xml_end:]
                else:
                    # Add to beginning of file
                    content = f'<string name="UIMode" value="{mode}" />\n' + content
            
            # Write the changes back
            with open(es_settings_path, 'w') as f:
                f.write(content)
                
            # Apply UI mode change (try without restart if possible)
            apply_ui_mode_change(mode)
            return True
            
        except Exception as direct_error:
            logger.error(f"Error using direct text manipulation: {direct_error}")
            
            # Try with XML parsing as fallback
            try:
                logger.info("Attempting XML parsing approach as fallback")
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
                
                # Apply UI mode change (try without restart if possible)
                apply_ui_mode_change(mode)
                
                return True
                
            except Exception as xml_error:
                logger.error(f"Error updating EmulationStation settings with XML: {xml_error}")
                
                # Last resort approach - use a direct echo command
                try:
                    logger.info("Attempting direct echo command as last resort")
                    # Use grep to check if setting already exists
                    check = subprocess.run(['grep', '-q', 'UIMode', es_settings_path], check=False)
                    
                    if check.returncode == 0:
                        # Setting exists, use sed to replace it
                        subprocess.run([
                            'sed', '-i', 
                            f's/<[^>]*name="UIMode" value="[^"]*"/<string name="UIMode" value="{mode}"/', 
                            es_settings_path
                        ], check=True)
                    else:
                        # Setting doesn't exist, append it to the file
                        with open(es_settings_path, 'a') as f:
                            f.write(f'\n<string name="UIMode" value="{mode}" />\n')
                    
                    restart_emulationstation()
                    return True
                    
                except Exception as echo_error:
                    logger.error(f"All methods failed. Last error: {echo_error}")
                    return False
            
    except Exception as e:
        logger.error(f"Error changing EmulationStation UI mode: {e}")
        return False

def apply_ui_mode_change(mode):
    """Apply UI mode change without restarting EmulationStation if possible"""
    try:
        # Since EmulationStation is likely started with a systemd service,
        # the best approach is to modify the config file and let EmulationStation
        # reload it on next launch rather than trying to change a running instance
        
        # Check if we can find the autostart.sh script that launches EmulationStation
        autostart_paths = [
            '/opt/retropie/configs/all/autostart.sh',
            '/home/pi/.bashrc',  # Sometimes ES is started from here
            '/etc/profile.d/10-emulationstation.sh'
        ]
        
        # Log information about the script we're searching for
        for path in autostart_paths:
            if os.path.exists(path):
                logger.info(f"Found autostart script at {path}, content:")
                with open(path, 'r') as f:
                    logger.info(f.read()[:500])  # Log first 500 chars
        
        # For now, just write the UI mode to the config file but don't try to
        # change the running instance, as it appears to be launched with force parameters
        logger.info(f"UI mode preference set to {mode} in config. Will take effect on next EmulationStation restart.")
        
        # Write a short message to inform the user
        try:
            # Use OSD command if EmulationStation has it
            osd_script = "/tmp/es_ui_mode_info.sh"
            with open(osd_script, 'w') as f:
                f.write('#!/bin/bash\n')
                f.write(f'echo "UI MODE: {mode}" > /dev/tty1\n')
                f.write(f'echo "Changes will take effect after EmulationStation restarts" > /dev/tty1\n')
                f.write(f'sleep 5\n')
            
            os.chmod(osd_script, 0o755)
            subprocess.Popen([osd_script], start_new_session=True)
        except Exception as e:
            logger.warning(f"Failed to display UI mode info: {e}")
            
        return True
            
    except Exception as e:
        logger.error(f"Error applying UI mode change: {e}")
        return False

def restart_emulationstation(mode=None):
    """Restart EmulationStation by touching /tmp/es-restart and killing the process"""
    try:
        # Create the restart trigger file
        with open('/tmp/es-restart', 'w') as f:
            f.write('')
        
        # Kill EmulationStation to trigger restart
        try:
            # Make sure all existing EmulationStation processes are killed
            subprocess.run(['pkill', '-9', 'emulationstation'], check=False)
            time.sleep(2)  # Give it time to fully terminate
            
            if mode == 'Kid':
                # Launch ES in Kid mode
                logger.info("Launching EmulationStation in Kid mode")
                subprocess.Popen([
                    '/opt/retropie/supplementary/emulationstation/emulationstation', 
                    '--force-kid'
                ], start_new_session=True)
            elif mode == 'Kiosk':
                # Launch ES in Kiosk mode
                logger.info("Launching EmulationStation in Kiosk mode")
                subprocess.Popen([
                    '/opt/retropie/supplementary/emulationstation/emulationstation', 
                    '--force-kiosk'
                ], start_new_session=True)
            elif mode == 'Full':
                # Launch ES in Full mode
                logger.info("Launching EmulationStation in Full mode")
                subprocess.Popen([
                    '/opt/retropie/supplementary/emulationstation/emulationstation'
                ], start_new_session=True)
            else:
                # Just kill it and let the system restart it with default settings
                logger.info("Killing EmulationStation, system will restart it")
            
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

def is_retroarch_running():
    """Check if RetroArch appears to be running"""
    try:
        # Check with ps command
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        if 'retroarch' in result.stdout.lower():
            return True
            
        # Check if the network port is in use (alternative method)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.2)
            sock.sendto(b"VERSION", ('127.0.0.1', RETROARCH_PORT))
            response, _ = sock.recvfrom(1024)
            if response:
                return True
        except:
            pass
            
        return False
    except Exception as e:
        logger.error(f"Error checking if RetroArch is running: {e}")
        return False

def send_retroarch_command(command):
    """Send a command to RetroArch via Network Control Interface"""
    try:
        # Check if RetroArch might be running first
        retroarch_status = is_retroarch_running()
        if not retroarch_status:
            logger.warning("RetroArch does not appear to be running. Command might not work.")
        
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
        # Include more descriptive error message
        if isinstance(e, socket.error) and e.errno == 111:
            logger.error("Connection refused. RetroArch might not be running or network commands are disabled.")
        return None
    finally:
        if 'sock' in locals() and sock:
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

def start_mqtt_listener(max_retries=10):
    """Start a background MQTT listener for commands with retry logic"""
    config = get_config()
    
    if not config.get('mqtt_host'):
        logger.error("MQTT host not configured, cannot start listener")
        return False
      # Create a more robust client with auto-reconnect
    client = mqtt.Client(client_id=f"{SYSTEM_NAME}-ha-{int(time.time())}", clean_session=True)
    client.on_connect = on_connect
    client.on_message = on_message
    
    # Set up auto-reconnect parameters - very important for stability
    client.reconnect_delay_set(min_delay=1, max_delay=60)
    
    # Add a disconnect callback to log disconnections
    def on_disconnect(client, userdata, rc):
        if rc != 0:
            logger.warning(f"Unexpected MQTT disconnection with code {rc}. Will auto-reconnect.")
        else:
            logger.info("MQTT client disconnected cleanly")
    
    client.on_disconnect = on_disconnect
    
    if config.get('mqtt_username') and config.get('mqtt_password'):
        client.username_pw_set(config['mqtt_username'], config['mqtt_password'])
    
    # Add retry logic with exponential backoff
    retries = 0
    max_wait = 60  # Maximum wait time in seconds
    while retries < max_retries:
        try:
            # Set a shorter connection timeout for quicker failure detection
            client.connect(config['mqtt_host'], int(config.get('mqtt_port', 1883)), 15)
            client.loop_start()
            logger.info("MQTT listener started successfully")
              # Add will message so Home Assistant knows when we're offline
            topic_prefix = config.get('mqtt_topic_prefix', SYSTEM_NAME)
            will_topic = f"{topic_prefix}/availability"
            client.will_set(will_topic, "offline", qos=1, retain=True)
            
            # Immediately publish online status
            client.publish(will_topic, "online", qos=1, retain=True)
            
            # Add a periodic ping to verify connection is still alive
            def maintain_connection():
                """Periodic function to maintain connection and verify it's working"""
                while True:
                    try:
                        time.sleep(60)  # Check connection every minute
                        if not client.is_connected():
                            logger.warning("MQTT connection lost, reconnecting...")
                            try:
                                client.reconnect()
                                logger.info("MQTT reconnection successful")
                            except Exception as reconnect_error:
                                logger.error(f"Failed to reconnect: {reconnect_error}")
                        else:
                            # Send a ping by publishing to a debug topic periodically
                            client.publish(f"{topic_prefix}/availability", "online", qos=1, retain=True)
                    except Exception as e:
                        logger.error(f"Error in connection maintenance thread: {e}")
            
            # Start connection maintenance in a background thread
            connection_thread = threading.Thread(target=maintain_connection, daemon=True)
            connection_thread.start()
            
            return client
        except Exception as e:
            retries += 1
            # Calculate wait time with exponential backoff (2^retry seconds)
            wait_time = min(2 ** retries, max_wait)
            
            if retries >= max_retries:
                logger.error(f"Failed to start MQTT listener after {max_retries} attempts: {e}")
                return None
            else:
                logger.warning(f"Error starting MQTT listener (attempt {retries}/{max_retries}): {e}. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
    
    # Should never reach here due to the return in the max retries case
    return None

def register_with_ha():
    """Register device with Home Assistant via MQTT discovery"""
    config = get_config()
    topic_prefix = config.get('mqtt_topic_prefix', SYSTEM_NAME)
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
    
    # Register CPU frequency sensor
    cpu_frequency_config = {
        "device": device_info,
        "name": f"RetroPie {device_name} CPU Frequency",
        "unique_id": f"retropie_{safe_device_name}_cpu_freq",
        "object_id": f"retropie_{safe_device_name}_cpu_freq",
        "state_topic": f"{topic_prefix}/status",
        "value_template": "{{ value_json.system_info.cpu_freq }}",
        "unit_of_measurement": "MHz",
        "icon": "mdi:sine-wave",
        "state_class": "measurement",
        "availability": availability,
        "availability_mode": "all",
        "enabled_by_default": True,
        "origin": origin_info
    }
    
    # Register GPU frequency sensor
    gpu_frequency_config = {
        "device": device_info,
        "name": f"RetroPie {device_name} GPU Frequency",
        "unique_id": f"retropie_{safe_device_name}_gpu_freq",
        "object_id": f"retropie_{safe_device_name}_gpu_freq",
        "state_topic": f"{topic_prefix}/status",
        "value_template": "{{ value_json.system_info.gpu_freq }}",
        "unit_of_measurement": "MHz",
        "icon": "mdi:video",
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
        
        # Publish CPU frequency sensor
        client.publish(
            f"homeassistant/sensor/retropie_{safe_device_name}/cpu_freq/config",
            json.dumps(cpu_frequency_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published CPU frequency sensor config")
        
        # Publish GPU frequency sensor
        client.publish(
            f"homeassistant/sensor/retropie_{safe_device_name}/gpu_freq/config",
            json.dumps(gpu_frequency_config),
            qos=1,
            retain=True
        )
        logger.info(f"Published GPU frequency sensor config")
        
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
    parser.add_argument('--shutdown-mode', action='store_true', help='Use reduced timeouts for shutdown operations')
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
        # For quit events, if shutdown_mode is specified, pass it to ensure lower timeouts
        if args.event == 'quit' and args.shutdown_mode:
            logger.info("Running quit event in shutdown mode")
        publish_game_event(args.event, args.args)
        sys.exit(0)
    
    # If no arguments provided, just publish status
    publish_system_status()