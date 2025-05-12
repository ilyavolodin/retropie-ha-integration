#!/bin/bash
# Report quit to MQTT with quick timeout for shutdown

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PYTHON_SCRIPT="$HOME/.config/retropie-ha/mqtt_client.py"

# Check if Python script exists
if [ -f "$PYTHON_SCRIPT" ]; then
  # Quick check if network is available - we don't want to hang on shutdown
  if ping -c 1 -W 1 "$(grep mqtt_host "$HOME/.config/retropie-ha/config.json" | cut -d'"' -f4)" &>/dev/null; then
    # Use timeout to ensure the script doesn't hang
    timeout 3 python3 "$PYTHON_SCRIPT" --event quit --shutdown-mode "$@"
  else
    echo "Network appears to be down, skipping MQTT quit notification" >> "$HOME/.config/retropie-ha/retropie-ha.log"
  fi
fi

exit 0

