#!/bin/bash
# Report quit to MQTT with quick timeout for shutdown

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Determine the correct path based on system type
if [ -d "/userdata/system" ]; then
  # Batocera system
  PYTHON_SCRIPT="/userdata/system/retropie-ha/mqtt_client.py"
  CONFIG_DIR="/userdata/system/retropie-ha"
else
  # RetroPie system
  PYTHON_SCRIPT="$HOME/.config/retropie-ha/mqtt_client.py"
  CONFIG_DIR="$HOME/.config/retropie-ha"
fi

LOG_FILE="$CONFIG_DIR/batocera_ha.log"
CONFIG_FILE="$CONFIG_DIR/config.json"

# Check if Python script exists
if [ -f "$PYTHON_SCRIPT" ]; then
  echo "[$(date)] Running quit event" >> /tmp/ha_events.log
  
  # Quick check if network is available - we don't want to hang on shutdown
  if ping -c 1 -W 1 "$(grep mqtt_host "$CONFIG_FILE" | cut -d'"' -f4)" &>/dev/null; then
    # Use timeout to ensure the script doesn't hang
    echo "[$(date)] Running quit event with: $PYTHON_SCRIPT --event quit --shutdown-mode" >> /tmp/ha_events.log
    timeout 3 python3 "$PYTHON_SCRIPT" --event quit --shutdown-mode "$@" >/dev/null 2>&1
  else
    echo "[$(date)] Network appears to be down, skipping MQTT quit notification" >> /tmp/ha_events.log
    echo "Network appears to be down, skipping MQTT quit notification" >> "$LOG_FILE"
  fi
else
  echo "[$(date)] Error: Python script not found at $PYTHON_SCRIPT" >> /tmp/ha_events.log
fi

exit 0

