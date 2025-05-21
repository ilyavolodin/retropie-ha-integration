#!/bin/bash
# Report game start to MQTT

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
  # Log the event
  echo "[$(date)] Running game-start event with: $PYTHON_SCRIPT --event game-start $@" >> /tmp/ha_events.log
  
  # Make sure we have at least 3 arguments as required by the mqtt_client.py
  if [ $# -lt 3 ]; then
    # If running manually or with incomplete args, provide dummy values
    if [ $# -eq 1 ]; then
      # System name provided, use it with dummy values
      SYSTEM="$1"
      EMULATOR="unknown"
      ROM_PATH="unknown.rom"
    elif [ $# -eq 2 ]; then
      # System and game provided
      SYSTEM="$1"
      EMULATOR="unknown"
      ROM_PATH="$2"
    else
      # No args, use all dummy values
      SYSTEM="unknown"
      EMULATOR="unknown"
      ROM_PATH="unknown.rom"
    fi
    
    # Run with dummy values
    echo "[$(date)] Using fallback values for incomplete args: $SYSTEM $EMULATOR $ROM_PATH" >> /tmp/ha_events.log
    python3 "$PYTHON_SCRIPT" --event game-start "$SYSTEM" "$EMULATOR" "$ROM_PATH" >/dev/null 2>&1
  else
    # Normal operation with all required args
    # For Batocera, make sure we properly escape any special characters in the ROM path
    ROM_PATH="${@: -1}"  # Get the last argument (ROM path)
    SYSTEM="${1}"        # First argument is system name
    EMULATOR="${2}"      # Second argument is emulator name
    
    echo "[$(date)] Parsed arguments: SYSTEM=$SYSTEM EMULATOR=$EMULATOR ROM_PATH=$ROM_PATH" >> /tmp/ha_events.log
    python3 "$PYTHON_SCRIPT" --event game-start "$SYSTEM" "$EMULATOR" "$ROM_PATH" >/dev/null 2>&1
  fi
else
  echo "[$(date)] Error: Python script not found at $PYTHON_SCRIPT" >> /tmp/ha_events.log
fi

exit 0

