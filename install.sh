#!/bin/bash
# Installation script for RetroPie Home Assistant Integration

set -e

# Configuration
CONFIG_DIR="$HOME/.config/retropie-ha"
ES_SCRIPTS_DIR="$HOME/.emulationstation/scripts"
RC_SCRIPTS_DIR="/opt/retropie/configs/all"

# Display banner
echo "============================================="
echo "  RetroPie Home Assistant Integration Setup  "
echo "============================================="
echo ""

# Ask for MQTT server information
read -p "MQTT Server Host [192.168.1.100]: " MQTT_HOST
MQTT_HOST=${MQTT_HOST:-192.168.1.100}

read -p "MQTT Server Port [1883]: " MQTT_PORT
MQTT_PORT=${MQTT_PORT:-1883}

read -p "MQTT Username (leave empty for none): " MQTT_USERNAME

if [ -n "$MQTT_USERNAME" ]; then
    read -s -p "MQTT Password: " MQTT_PASSWORD
    echo ""
fi

read -p "MQTT Topic Prefix [retropie/arcade]: " MQTT_TOPIC_PREFIX
MQTT_TOPIC_PREFIX=${MQTT_TOPIC_PREFIX:-retropie/arcade}

read -p "Device Name [arcade]: " DEVICE_NAME
DEVICE_NAME=${DEVICE_NAME:-arcade}

read -p "Status Update Interval (seconds) [30]: " UPDATE_INTERVAL
UPDATE_INTERVAL=${UPDATE_INTERVAL:-30}

# Update config.json
mkdir -p "$CONFIG_DIR"
cat > "$CONFIG_DIR/config.json" << EOL
{
  "mqtt_host": "$MQTT_HOST",
  "mqtt_port": $MQTT_PORT,
  "mqtt_username": "$MQTT_USERNAME",
  "mqtt_password": "$MQTT_PASSWORD",
  "mqtt_topic_prefix": "$MQTT_TOPIC_PREFIX",
  "device_name": "$DEVICE_NAME",
  "update_interval": $UPDATE_INTERVAL
}
EOL

echo "Configuration updated."
echo "Installing integration..."

# Check for existing installation and remove it if found
echo "Checking for existing installation..."
if systemctl is-active --quiet retropie-ha.service 2>/dev/null; then 
    echo "Stopping existing service..."
    sudo systemctl stop retropie-ha.service
    sudo systemctl disable retropie-ha.service
    echo "Service stopped and disabled."
fi

if [ -f /etc/systemd/system/retropie-ha.service ]; then
    echo "Removing existing service file..."
    sudo rm -f /etc/systemd/system/retropie-ha.service
    sudo systemctl daemon-reload
    echo "Service file removed."
fi

# Clean up any existing PID file
if [ -f "$CONFIG_DIR/reporter.pid" ]; then
    echo "Cleaning up old PID file..."
    # Check if the process is still running and kill it
    OLD_PID=$(cat "$CONFIG_DIR/reporter.pid")
    if kill -0 $OLD_PID 2>/dev/null; then
        echo "Terminating old process (PID: $OLD_PID)..."
        kill $OLD_PID
    fi
    rm -f "$CONFIG_DIR/reporter.pid"
fi

# Create directories
echo "Creating directories..."
mkdir -p "$CONFIG_DIR" 
mkdir -p "$ES_SCRIPTS_DIR/game-start" "$ES_SCRIPTS_DIR/game-end" "$ES_SCRIPTS_DIR/game-select" "$ES_SCRIPTS_DIR/system-select" "$ES_SCRIPTS_DIR/quit"
sudo mkdir -p "$RC_SCRIPTS_DIR/runcommand-onstart" "$RC_SCRIPTS_DIR/runcommand-onend"

# Install dependencies
echo "Installing dependencies..."
sudo apt-get update && sudo apt-get install -y python3-paho-mqtt mosquitto-clients libttspico-utils alsa-utils python3-pip

# Install Python dependencies
echo "Installing Python packages..."
# Try to install python3-watchdog via apt first (preferred method)
if sudo apt-get install -y python3-watchdog; then
    echo "Successfully installed watchdog via apt"
else
    echo "Could not install watchdog via apt, trying pip..."
    # Try pip with --break-system-packages flag (for newer Debian/Ubuntu systems)
    if pip3 install watchdog --break-system-packages; then
        echo "Successfully installed watchdog via pip with --break-system-packages"
    else
        echo "Could not install watchdog via pip with --break-system-packages, trying without the flag..."
        # Try standard pip install as a last resort
        if pip3 install watchdog; then
            echo "Successfully installed watchdog via pip"
        else
            echo "WARNING: Failed to install watchdog. File monitoring will be disabled."
            echo "To enable file monitoring, you can manually install watchdog using one of these methods:"
            echo "  - sudo apt-get install python3-watchdog"
            echo "  - pip3 install watchdog --break-system-packages"
            echo "  - Create a virtual environment and install there"
        fi
    fi
fi

# Copy Python scripts
echo "Copying Python scripts..."
cp -f "$(dirname "$0")/src/mqtt_client.py" "$CONFIG_DIR/mqtt_client.py"
cp -f "$(dirname "$0")/src/status_reporter.py" "$CONFIG_DIR/status_reporter.py"
chmod +x "$CONFIG_DIR/mqtt_client.py" "$CONFIG_DIR/status_reporter.py"

# Copy EmulationStation scripts
echo "Installing EmulationStation scripts..."
cp -f "$(dirname "$0")/scripts/game-start/"* "$ES_SCRIPTS_DIR/game-start/"
cp -f "$(dirname "$0")/scripts/game-end/"* "$ES_SCRIPTS_DIR/game-end/"
cp -f "$(dirname "$0")/scripts/game-select/"* "$ES_SCRIPTS_DIR/game-select/"
cp -f "$(dirname "$0")/scripts/system-select/"* "$ES_SCRIPTS_DIR/system-select/"
cp -f "$(dirname "$0")/scripts/quit/"* "$ES_SCRIPTS_DIR/quit/"
chmod +x "$ES_SCRIPTS_DIR"/*/*.sh

# Copy RunCommand scripts
echo "Installing RunCommand scripts..."
cp -f "$(dirname "$0")/scripts/game-start/"* "$RC_SCRIPTS_DIR/runcommand-onstart/"
cp -f "$(dirname "$0")/scripts/game-end/"* "$RC_SCRIPTS_DIR/runcommand-onend/"
chmod +x "$RC_SCRIPTS_DIR/runcommand-onstart/"* "$RC_SCRIPTS_DIR/runcommand-onend/"*

# Create RunCommand hooks
echo "Creating RunCommand hooks..."
cat > "$RC_SCRIPTS_DIR/runcommand-onstart.sh" << 'EOF'
#!/bin/bash
# Log the event
echo "[$(date)] RunCommand OnStart: $@" >> /tmp/retropie_events.log
# Call the report script
/opt/retropie/configs/all/runcommand-onstart/01_report_game_start.sh "$@"
EOF

cat > "$RC_SCRIPTS_DIR/runcommand-onend.sh" << 'EOF'
#!/bin/bash
# Log the event
echo "[$(date)] RunCommand OnEnd: $@" >> /tmp/retropie_events.log
# Call the report script
/opt/retropie/configs/all/runcommand-onend/01_report_game_end.sh "$@"
EOF

# Set permissions for RunCommand hooks
chmod +x "$RC_SCRIPTS_DIR/runcommand-onstart.sh" "$RC_SCRIPTS_DIR/runcommand-onend.sh"

# Fix EmulationStation audio mixer issue
echo "Fixing EmulationStation audio mixer issue..."
ES_SETTINGS="$HOME/.emulationstation/es_settings.cfg"
if [ -f "$ES_SETTINGS" ]; then
    # Create backup
    cp -f "$ES_SETTINGS" "$ES_SETTINGS.bak"
    # Remove existing VolumeControl entries and add our own
    cat "$ES_SETTINGS" | grep -v "VolumeControl" > "$ES_SETTINGS.new"
    echo '<bool name="VolumeControl" value="false" />' >> "$ES_SETTINGS.new"
    mv "$ES_SETTINGS.new" "$ES_SETTINGS"
    echo "EmulationStation audio mixer settings updated."
fi

# Create and install systemd service
echo "Creating systemd service..."
CURRENT_USER=$(whoami)
HOME_DIR=$(eval echo ~$CURRENT_USER)

# Create service file with correct paths
cat > /tmp/retropie-ha.service << EOF
[Unit]
Description=RetroPie Home Assistant Integration
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$HOME_DIR
ExecStart=/usr/bin/python3 $CONFIG_DIR/status_reporter.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Install service
echo "Installing systemd service..."
sudo mv /tmp/retropie-ha.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable retropie-ha.service

# Delete any existing configurations in Home Assistant
echo "Cleaning up old Home Assistant configurations..."
# Safely remove old discovery configurations to avoid duplicates
if [ -n "$MQTT_USERNAME" ]; then
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/cpu_temp/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/gpu_temp/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/game_status/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/memory_usage/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/cpu_load/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/machine_status/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/play_duration/config" -n -r -d
    # Clear old device automation entities
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/device_automation/retropie_${DEVICE_NAME// /_}/tts/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/device_automation/retropie_${DEVICE_NAME// /_}/retroarch_message/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/device_automation/retropie_${DEVICE_NAME// /_}/retroarch_command/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/device_automation/retropie_${DEVICE_NAME// /_}/retroarch_status/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/device_automation/retropie_${DEVICE_NAME// /_}/ui_mode/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/device_automation/retropie_${DEVICE_NAME// /_}/scan_games/config" -n -r -d
    
    # Clear new entities
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/text/retropie_${DEVICE_NAME// /_}/tts_text/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/button/retropie_${DEVICE_NAME// /_}/tts_speak/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/text/retropie_${DEVICE_NAME// /_}/retroarch_message_text/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/button/retropie_${DEVICE_NAME// /_}/retroarch_display_message/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/text/retropie_${DEVICE_NAME// /_}/retroarch_command_text/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/button/retropie_${DEVICE_NAME// /_}/retroarch_execute_command/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/button/retropie_${DEVICE_NAME// /_}/retroarch_get_status/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/select/retropie_${DEVICE_NAME// /_}/ui_mode/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/button/retropie_${DEVICE_NAME// /_}/scan_games/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/total_games/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/favorites/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/kid_friendly/config" -n -r -d
else
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/cpu_temp/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/gpu_temp/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/game_status/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/memory_usage/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/cpu_load/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/machine_status/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/play_duration/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/device_automation/retropie_${DEVICE_NAME// /_}/tts/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/device_automation/retropie_${DEVICE_NAME// /_}/retroarch_message/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/device_automation/retropie_${DEVICE_NAME// /_}/retroarch_command/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/device_automation/retropie_${DEVICE_NAME// /_}/retroarch_status/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/device_automation/retropie_${DEVICE_NAME// /_}/ui_mode/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/device_automation/retropie_${DEVICE_NAME// /_}/scan_games/config" -n -r -d
    
    # Clear new entities
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/text/retropie_${DEVICE_NAME// /_}/tts_text/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/button/retropie_${DEVICE_NAME// /_}/tts_speak/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/text/retropie_${DEVICE_NAME// /_}/retroarch_message_text/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/button/retropie_${DEVICE_NAME// /_}/retroarch_display_message/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/text/retropie_${DEVICE_NAME// /_}/retroarch_command_text/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/button/retropie_${DEVICE_NAME// /_}/retroarch_execute_command/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/button/retropie_${DEVICE_NAME// /_}/retroarch_get_status/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/select/retropie_${DEVICE_NAME// /_}/ui_mode/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/button/retropie_${DEVICE_NAME// /_}/scan_games/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/total_games/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/favorites/config" -n -r -d
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "homeassistant/sensor/retropie_${DEVICE_NAME// /_}/kid_friendly/config" -n -r -d
fi

# Test audio for text-to-speech
echo "Testing text-to-speech functionality..."
TTS_TEXT="RetroPie Home Assistant integration is now installed."
pico2wave -w /tmp/tts_test.wav "$TTS_TEXT" && aplay /tmp/tts_test.wav
rm -f /tmp/tts_test.wav

# Test RetroArch network connection
if [ "$RETROARCH_ENABLED" = true ]; then
  echo "Testing RetroArch network connection..."
  # Create a simple script to test the connection
  cat > /tmp/retroarch_test.sh << 'EOF'
#!/bin/bash
echo -n "VERSION" | nc -u -w1 127.0.0.1 55355
if [ $? -eq 0 ]; then
  echo "RetroArch network connection test was successful!"
else
  echo "Could not connect to RetroArch. Please make sure RetroArch is running with network commands enabled."
  echo "If RetroArch is currently closed, this is normal - the connection will be available when you launch RetroArch."
fi
EOF
  chmod +x /tmp/retroarch_test.sh
  # Run the test script
  /tmp/retroarch_test.sh
  rm -f /tmp/retroarch_test.sh
fi

# Start the service
sudo systemctl start retropie-ha.service

# Verify installation
echo "Verifying installation..."
sleep 2
if systemctl is-active --quiet retropie-ha.service; then
    echo "Service is running correctly."
else
    echo "Service failed to start. Check logs with: sudo journalctl -u retropie-ha.service"
fi

echo ""
echo "Installation completed successfully!"
echo "The RetroPie Home Assistant Integration is now running."
echo ""
echo "To check status: sudo systemctl status retropie-ha.service"
echo "To view logs: sudo journalctl -u retropie-ha.service"
echo "To view integration logs: cat $CONFIG_DIR/retropie-ha.log"
echo ""
echo "Your RetroPie will now report events and status to Home Assistant via MQTT."
echo "Home Assistant should auto-discover the sensors if MQTT integration is configured."
echo ""
echo "New features:"
echo "1. Machine status reporting (idle, playing, shutdown)"
echo "2. Play duration tracking"
echo "3. Text-to-speech functionality"
echo "4. System availability tracking"
echo "5. RetroArch Network Control Interface integration"
echo "   - Display messages on RetroArch screen"
echo "   - Send commands to RetroArch"
echo "   - Get RetroArch status information"
echo "6. EmulationStation UI Mode control"
echo "   - Switch between Full, Kid, and Kiosk modes"
echo "   - Create automations to switch modes based on conditions"
echo "7. Game Collection Statistics"
echo "   - Track total number of games in your collection"
echo "   - Count favorite games"
echo "   - Identify kid-friendly games based on ratings"
echo ""
echo "You can send text-to-speech commands from Home Assistant by publishing to:"
echo "  Topic: $MQTT_TOPIC_PREFIX/command/tts"
echo "  Payload: \"Hello from Home Assistant\""
echo "  or JSON: {\"text\": \"Hello from Home Assistant\"}"
echo ""
echo "RetroArch Network Control Interface commands can be sent via:"
echo "  Message Display: $MQTT_TOPIC_PREFIX/command/retroarch/message"
echo "  Status Request: $MQTT_TOPIC_PREFIX/command/retroarch/status"
echo "  Any Command: $MQTT_TOPIC_PREFIX/command/retroarch"
echo ""
echo "EmulationStation UI Mode can be controlled via:"
echo "  $MQTT_TOPIC_PREFIX/command/ui_mode"
echo "  Payload: {\"mode\": \"Full\"} or {\"mode\": \"Kid\"} or {\"mode\": \"Kiosk\"}"
echo ""
echo "Game collection statistics can be updated via:"
echo "  $MQTT_TOPIC_PREFIX/command/scan_games"
echo "  (This happens automatically at startup, but can be triggered manually)"
echo ""
# Try to automatically enable RetroArch network commands
echo "Setting up RetroArch Network Commands..."
RETROARCH_CFG_PATHS=(
  "$HOME/.config/retroarch/retroarch.cfg"
  "/opt/retropie/configs/all/retroarch.cfg"
  "/etc/retroarch.cfg"
)

RETROARCH_ENABLED=false
for CFG_PATH in "${RETROARCH_CFG_PATHS[@]}"; do
  if [ -f "$CFG_PATH" ]; then
    echo "Found RetroArch config at: $CFG_PATH"
    
    # Check if network_cmd_enable is already set
    if grep -q "network_cmd_enable" "$CFG_PATH"; then
      # Update existing setting
      sed -i 's/network_cmd_enable = "false"/network_cmd_enable = "true"/g' "$CFG_PATH"
      echo "Updated network_cmd_enable setting to true in $CFG_PATH"
    else
      # Add the setting if it doesn't exist
      echo 'network_cmd_enable = "true"' >> "$CFG_PATH"
      echo "Added network_cmd_enable = true to $CFG_PATH"
    fi
    
    # Optionally set the network command port if you want to use a specific port
    if ! grep -q "network_cmd_port" "$CFG_PATH"; then
      echo 'network_cmd_port = "55355"' >> "$CFG_PATH"
      echo "Added default network_cmd_port = 55355 to $CFG_PATH"
    fi
    
    RETROARCH_ENABLED=true
    break
  fi
done

if [ "$RETROARCH_ENABLED" = false ]; then
  echo "WARNING: Could not find RetroArch configuration file."
  echo "To enable RetroArch Network Commands manually, set:"
  echo "network_cmd_enable = \"true\" in retroarch.cfg"
fi
echo ""
echo "NOTE: A restart of EmulationStation is recommended:"
echo "touch /tmp/es-restart && killall emulationstation"