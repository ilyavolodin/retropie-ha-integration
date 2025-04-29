#!/bin/bash
# Report quit to MQTT

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PYTHON_SCRIPT="$HOME/.config/retropie-ha/mqtt_client.py"

# Check if Python script exists
if [ -f "$PYTHON_SCRIPT" ]; then
  python3 "$PYTHON_SCRIPT" --event quit "$@" &
fi

exit 0

