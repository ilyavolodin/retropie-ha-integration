#!/usr/bin/env python3
import time
import subprocess
import os
import json
import signal
import sys

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
        print(f"Failed to load configuration: {e}")
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
    remove_pid()
    sys.exit(0)

def main():
    """Main function to report status periodically"""
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Write PID file
    write_pid()
    
    # Get configuration
    config = get_config()
    update_interval = int(config.get('update_interval', 30))
    
    # Register with Home Assistant
    subprocess.run(['python3', MQTT_CLIENT, '--register'])
    
    # Report status periodically
    try:
        while True:
            subprocess.run(['python3', MQTT_CLIENT, '--status'])
            time.sleep(update_interval)
    except Exception as e:
        print(f"Error in status reporter: {e}")
    finally:
        remove_pid()

if __name__ == '__main__':
    main()

