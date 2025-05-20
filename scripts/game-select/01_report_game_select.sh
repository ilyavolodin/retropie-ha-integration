#!/bin/bash
# Report game selection to MQTT

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Determine the correct path based on system type
if [ -d "/userdata/system" ]; then
  # Batocera system
  PYTHON_SCRIPT="/userdata/system/retropie-ha/mqtt_client.py"
else
  # RetroPie system
  PYTHON_SCRIPT="$HOME/.config/retropie-ha/mqtt_client.py"
fi

# Check if Python script exists
if [ -f "$PYTHON_SCRIPT" ]; then
  echo "[$(date)] Running game-select event with: $PYTHON_SCRIPT --event game-select $@" >> /tmp/ha_events.log
  python3 "$PYTHON_SCRIPT" --event game-select "$@" >/dev/null 2>&1
else
  echo "[$(date)] Error: Python script not found at $PYTHON_SCRIPT" >> /tmp/ha_events.log
fi

exit 0

