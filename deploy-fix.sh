#!/bin/bash
# Script to deploy changes to the RetroPie system

# Configuration
RETROPIE_SSH="pi@192.168.1.238"
RETROPIE_CONFIG="~/.config/retropie-ha"

# Display banner
echo "=============================================="
echo "  RetroPie HA Integration - Deploy Fixes     "
echo "=============================================="
echo ""

# 1. Copy the updated files
echo "Copying updated files to RetroPie..."
scp ./src/mqtt_client.py "$RETROPIE_SSH:$RETROPIE_CONFIG/"
scp ./src/status_reporter.py "$RETROPIE_SSH:$RETROPIE_CONFIG/"
scp ./scripts/quit/01_report_quit.sh "$RETROPIE_SSH:~/.emulationstation/scripts/quit/"

# Create documentation directory if it doesn't exist
ssh "$RETROPIE_SSH" "mkdir -p $RETROPIE_CONFIG/docs"
scp ./docs/home_assistant.md "$RETROPIE_SSH:$RETROPIE_CONFIG/docs/"
echo "Files copied successfully."

# 2. Restart the service
echo "Restarting the service on RetroPie..."
ssh "$RETROPIE_SSH" "sudo systemctl restart retropie-ha.service"
echo "Service restarted."

# 3. Check if the service started successfully
echo "Checking service status..."
ssh "$RETROPIE_SSH" "sudo systemctl status retropie-ha.service | head -n 10"

# 4. Test MQTT communication
echo ""
echo "Testing MQTT communication with debug message..."
ssh "$RETROPIE_SSH" "mosquitto_pub -h 192.168.1.150 -p 1883 -u mqttuser -P MQTT365Conant -t 'retropie/arcade/debug' -m 'Testing fixed MQTT client'"
echo "Debug message sent. Check logs for confirmation."

echo ""
echo "Fix deployment completed. Please test various commands from Home Assistant now."