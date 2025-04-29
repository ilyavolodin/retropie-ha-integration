#!/usr/bin/env python3
import time
import subprocess
import os
import json
import signal
import sys
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.expanduser('~/.config/retropie-ha/retropie-ha.log'))
        # Removed StreamHandler to prevent console output
    ]
)
logger = logging.getLogger('retropie-ha-status')

CONFIG_DIR = os.path.expanduser('~/.config/retropie-ha')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')
PID_FILE = os.path.join(CONFIG_DIR, 'reporter.pid')
MQTT_CLIENT = os.path.join(CONFIG_DIR, 'mqtt_client.py')

def get_config():
    """Load configuration from file"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        return {}

def write_pid():
    """Write PID to file"""
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

def remove_pid():
    """Remove PID file"""
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)

def signal_handler(sig, frame):
    """Handle signals to clean up"""
    logger.info("Received signal to terminate")
    # Send system shutdown event when shutting down
    subprocess.run(['python3', MQTT_CLIENT, '--event', 'quit'])
    remove_pid()
    sys.exit(0)

def main():
    """Main function to report status and listen for commands"""
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Write PID file
    write_pid()
    
    # Get configuration
    config = get_config()
    
    # Send system start event
    logger.info("Service starting, sending system-start event")
    subprocess.run(['python3', MQTT_CLIENT, '--event', 'system-start'])
    
    # Register with Home Assistant
    logger.info("Registering with Home Assistant")
    subprocess.run(['python3', MQTT_CLIENT, '--register'])
    
    # Start the MQTT listener in a separate process
    logger.info("Starting MQTT listener")
    listener_process = subprocess.Popen(['python3', MQTT_CLIENT, '--listen'], 
                                        stdout=subprocess.PIPE, 
                                        stderr=subprocess.PIPE)
    
    logger.info(f"Status reporter started with PID {os.getpid()}")
    
    try:
        # Wait for the listener to exit
        while listener_process.poll() is None:
            time.sleep(5)
        
        # If we get here, the listener has exited
        logger.error(f"MQTT listener exited with code {listener_process.returncode}")
        return_code = listener_process.returncode
        stdout, stderr = listener_process.communicate()
        logger.error(f"MQTT listener output: {stdout.decode()}")
        logger.error(f"MQTT listener errors: {stderr.decode()}")
    except Exception as e:
        logger.error(f"Error in status reporter: {e}")
    finally:
        # Try to clean up
        if listener_process.poll() is None:
            logger.info("Terminating MQTT listener")
            listener_process.terminate()
            try:
                listener_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Timeout waiting for listener to terminate, forcing kill")
                listener_process.kill()
        
        # Send system quit event
        logger.info("Service shutting down, sending quit event")
        subprocess.run(['python3', MQTT_CLIENT, '--event', 'quit'])
        
        # Remove PID file
        remove_pid()

if __name__ == '__main__':
    main()