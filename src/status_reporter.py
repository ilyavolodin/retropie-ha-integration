#!/usr/bin/env python3
import time
import subprocess
import os
import json
import signal
import sys
import logging
import platform

# Detect system type
SYSTEM_TYPE = "unknown"
if os.path.exists("/opt/retropie"):
    SYSTEM_TYPE = "retropie"
    CONFIG_DIR = os.path.expanduser('~/.config/retropie-ha')
    SYSTEM_NAME = "retropie"
elif os.path.exists("/userdata/system"):
    SYSTEM_TYPE = "batocera"
    CONFIG_DIR = "/userdata/system/retropie-ha"
    SYSTEM_NAME = "batocera"
else:
    # Fallback to RetroPie defaults
    CONFIG_DIR = os.path.expanduser('~/.config/retropie-ha')
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
logger = logging.getLogger(f'{SYSTEM_NAME}-ha-status')

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
    # Send system shutdown event when shutting down with a short timeout
    try:
        # Set a very short timeout for shutdown operations (3 seconds)
        subprocess.run(['python3', MQTT_CLIENT, '--event', 'quit', '--shutdown-mode'], 
                      timeout=3, 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        logger.warning("MQTT shutdown command timed out - network may be unavailable")
    except Exception as e:
        logger.error(f"Error during shutdown notification: {e}")
    
    # Always clean up and exit, even if the MQTT notification fails
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
    
    # Add delay to ensure network is fully up
    logger.info("Waiting for network to be fully available...")
    # Sleep for a few seconds to let the network initialize
    time.sleep(10)
    
    # Initialize retry counters
    max_retries = 5
    current_retry = 0
    restart_delay = 30  # seconds
    listener_process = None
    
    # Try to start and register repeatedly until successful
    while current_retry < max_retries:
        try:
            # Send system start event with timeout
            logger.info("Service starting, sending system-start event")
            subprocess.run(['python3', MQTT_CLIENT, '--event', 'system-start'], 
                          check=True, timeout=30)
            
            # Register with Home Assistant with timeout
            logger.info("Registering with Home Assistant")
            subprocess.run(['python3', MQTT_CLIENT, '--register'], 
                          check=True, timeout=30)
            
            # Start the MQTT listener in a separate process with proper error handling
            logger.info("Starting MQTT listener")
            try:
                listener_process = subprocess.Popen(['python3', MQTT_CLIENT, '--listen'], 
                                                  stdout=subprocess.PIPE, 
                                                  stderr=subprocess.PIPE)
                # Give it a moment to start and check if it immediately fails
                time.sleep(2)
                if listener_process.poll() is not None:
                    # Process exited immediately
                    stdout, stderr = listener_process.communicate()
                    logger.error(f"MQTT listener failed to start: {stderr.decode()}")
                    raise Exception("MQTT listener failed to start")
            except Exception as e:
                logger.error(f"Failed to start MQTT listener: {e}")
                raise
            
            logger.info(f"Status reporter started with PID {os.getpid()}")
            
            # Reset retry counter if we got here successfully
            current_retry = 0
            break
            
        except subprocess.CalledProcessError as e:
            current_retry += 1
            wait_time = min(2 ** current_retry, 60)  # Exponential backoff, max 60 seconds
            logger.warning(f"Failed to start services (attempt {current_retry}/{max_retries}). Retrying in {wait_time} seconds...")
            time.sleep(wait_time)
    
    # If we couldn't start after all retries, exit with error
    if current_retry >= max_retries and listener_process is None:
        logger.error(f"Failed to start services after {max_retries} attempts. Check network connectivity.")
        remove_pid()
        sys.exit(1)
    
    # Main monitoring loop with restart capability
    while True:
        try:
            # Check if listener is still running
            if listener_process.poll() is not None:
                # Listener exited unexpectedly
                return_code = listener_process.returncode
                stdout, stderr = listener_process.communicate()
                logger.error(f"MQTT listener exited with code {return_code}")
                logger.error(f"MQTT listener output: {stdout.decode()}")
                logger.error(f"MQTT listener errors: {stderr.decode()}")
                
                # Restart the listener after a delay
                logger.info(f"Restarting MQTT listener in {restart_delay} seconds...")
                time.sleep(restart_delay)
                logger.info("Restarting MQTT listener")
                try:
                    listener_process = subprocess.Popen(['python3', MQTT_CLIENT, '--listen'], 
                                                      stdout=subprocess.PIPE, 
                                                      stderr=subprocess.PIPE)
                    # Give it a moment to start and check if it immediately fails
                    time.sleep(2)
                    if listener_process.poll() is not None:
                        # Process exited immediately
                        stdout, stderr = listener_process.communicate()
                        logger.error(f"MQTT listener failed to restart: {stderr.decode()}")
                        # We'll try again in the next loop iteration
                    else:
                        logger.info("MQTT listener restarted successfully")
                except Exception as e:
                    logger.error(f"Failed to restart MQTT listener: {e}")
                    # We'll try again in the next loop iteration
            
            # Sleep before checking again
            time.sleep(5)
                
        except Exception as e:
            logger.error(f"Error in status reporter: {e}")
            time.sleep(restart_delay)
        except KeyboardInterrupt:
            break
    
    # Clean up before exiting
    try:
        # Try to clean up
        if listener_process and listener_process.poll() is None:
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
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
    finally:
        # Always remove PID file
        remove_pid()

if __name__ == '__main__':
    main()