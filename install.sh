#!/bin/bash
# Main installation script for RetroPie/Batocera Home Assistant Integration
# This script handles configuration and calls the system-specific installation script

set -e

# Display banner
echo "============================================="
echo "  Home Assistant Integration Setup Launcher  "
echo "============================================="
echo ""

# Detect system type: RetroPie or Batocera
SYSTEM_TYPE="unknown"
if [ -d "/opt/retropie" ]; then
    SYSTEM_TYPE="retropie"
    echo "Detected system: RetroPie"
    CONFIG_DIR="$HOME/.config/retropie-ha"
    SYSTEM_NAME="retropie"
    DEFAULT_TOPIC_PREFIX="retropie/arcade"
elif [ -d "/userdata/system" ]; then
    SYSTEM_TYPE="batocera"
    echo "Detected system: Batocera"
    CONFIG_DIR="/userdata/system/retropie-ha"
    SYSTEM_NAME="batocera"
    DEFAULT_TOPIC_PREFIX="batocera/arcade"
else
    echo "Unknown system type. This script requires either RetroPie or Batocera."
    echo "Please install on a compatible system."
    exit 1
fi

echo "Setting up configuration..."
echo ""

# Check if we have an existing config file
EXISTING_CONFIG="$CONFIG_DIR/config.json"
if [ -f "$EXISTING_CONFIG" ]; then
    echo "Found existing configuration. Using values from previous installation."
    
    # Extract values from the existing config file
    if command -v jq >/dev/null 2>&1; then
        # Use jq if available (more reliable)
        MQTT_HOST=$(jq -r '.mqtt_host' "$EXISTING_CONFIG")
        MQTT_PORT=$(jq -r '.mqtt_port' "$EXISTING_CONFIG")
        MQTT_USERNAME=$(jq -r '.mqtt_username' "$EXISTING_CONFIG")
        MQTT_PASSWORD=$(jq -r '.mqtt_password' "$EXISTING_CONFIG")
        MQTT_TOPIC_PREFIX=$(jq -r '.mqtt_topic_prefix' "$EXISTING_CONFIG")
        DEVICE_NAME=$(jq -r '.device_name' "$EXISTING_CONFIG")
        UPDATE_INTERVAL=$(jq -r '.update_interval' "$EXISTING_CONFIG")
    else
        # Fallback to grep/sed if jq is not available
        MQTT_HOST=$(grep -o '"mqtt_host": "[^"]*' "$EXISTING_CONFIG" | sed 's/"mqtt_host": "//')
        MQTT_PORT=$(grep -o '"mqtt_port": [0-9]*' "$EXISTING_CONFIG" | sed 's/"mqtt_port": //')
        MQTT_USERNAME=$(grep -o '"mqtt_username": "[^"]*' "$EXISTING_CONFIG" | sed 's/"mqtt_username": "//')
        MQTT_PASSWORD=$(grep -o '"mqtt_password": "[^"]*' "$EXISTING_CONFIG" | sed 's/"mqtt_password": "//')
        MQTT_TOPIC_PREFIX=$(grep -o '"mqtt_topic_prefix": "[^"]*' "$EXISTING_CONFIG" | sed 's/"mqtt_topic_prefix": "//')
        DEVICE_NAME=$(grep -o '"device_name": "[^"]*' "$EXISTING_CONFIG" | sed 's/"device_name": "//')
        UPDATE_INTERVAL=$(grep -o '"update_interval": [0-9]*' "$EXISTING_CONFIG" | sed 's/"update_interval": //')
    fi
    
    echo "Using MQTT Host: $MQTT_HOST"
    echo "Using MQTT Port: $MQTT_PORT"
    echo "Using MQTT Username: ${MQTT_USERNAME:-None}"
    echo "Using MQTT Topic Prefix: $MQTT_TOPIC_PREFIX"
    echo "Using Device Name: $DEVICE_NAME"
    echo "Using Update Interval: $UPDATE_INTERVAL seconds"
    
    # Ask user if they want to change any values
    read -p "Do you want to change any of these values? (y/N): " CHANGE_CONFIG
    if [[ "$CHANGE_CONFIG" =~ ^[Yy]$ ]]; then
        echo "Please enter new values (or press Enter to keep the current value):"
        # Ask for new values with current values as defaults
        read -p "MQTT Server Host [$MQTT_HOST]: " NEW_MQTT_HOST
        MQTT_HOST=${NEW_MQTT_HOST:-$MQTT_HOST}
        
        read -p "MQTT Server Port [$MQTT_PORT]: " NEW_MQTT_PORT
        MQTT_PORT=${NEW_MQTT_PORT:-$MQTT_PORT}
        
        read -p "MQTT Username (leave empty for none) [$MQTT_USERNAME]: " NEW_MQTT_USERNAME
        MQTT_USERNAME=${NEW_MQTT_USERNAME:-$MQTT_USERNAME}
        
        if [ -n "$MQTT_USERNAME" ]; then
            read -s -p "MQTT Password: " NEW_MQTT_PASSWORD
            echo ""
            MQTT_PASSWORD=${NEW_MQTT_PASSWORD:-$MQTT_PASSWORD}
        fi
        
        read -p "MQTT Topic Prefix [$MQTT_TOPIC_PREFIX]: " NEW_MQTT_TOPIC_PREFIX
        MQTT_TOPIC_PREFIX=${NEW_MQTT_TOPIC_PREFIX:-$MQTT_TOPIC_PREFIX}
        
        read -p "Device Name [$DEVICE_NAME]: " NEW_DEVICE_NAME
        DEVICE_NAME=${NEW_DEVICE_NAME:-$DEVICE_NAME}
        
        read -p "Status Update Interval (seconds) [$UPDATE_INTERVAL]: " NEW_UPDATE_INTERVAL
        UPDATE_INTERVAL=${NEW_UPDATE_INTERVAL:-$UPDATE_INTERVAL}
    fi
else
    # No existing config - ask for all values
    echo "No existing configuration found. Please enter the following information:"
    
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
    
    read -p "MQTT Topic Prefix [$DEFAULT_TOPIC_PREFIX]: " MQTT_TOPIC_PREFIX
    MQTT_TOPIC_PREFIX=${MQTT_TOPIC_PREFIX:-$DEFAULT_TOPIC_PREFIX}
    
    read -p "Device Name [arcade]: " DEVICE_NAME
    DEVICE_NAME=${DEVICE_NAME:-arcade}
    
    read -p "Status Update Interval (seconds) [30]: " UPDATE_INTERVAL
    UPDATE_INTERVAL=${UPDATE_INTERVAL:-30}
fi

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

# Check Python prerequisites and install dependencies if needed
echo "Checking Python prerequisites..."

# Check if Python is available
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: Python 3 is not installed. This is required for the integration."
    echo "Please ensure Python 3 is properly installed on your system."
    exit 1
fi

echo "Python 3 is available."

# Function to install pip if needed
install_pip() {
    if ! command -v pip3 >/dev/null 2>&1; then
        echo "Installing pip..."
        # Use get-pip.py method (most reliable cross-platform)
        curl -s -o /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py
        python3 /tmp/get-pip.py --user
        # Add pip to PATH if installed to user directory
        export PATH="$HOME/.local/bin:$PATH"
        rm -f /tmp/get-pip.py
    fi
}

# Create a Python package directory if it doesn't exist (for Batocera)
if [ "$SYSTEM_TYPE" = "batocera" ]; then
    PYTHON_PACKAGE_DIR="/userdata/system/python"
    mkdir -p "$PYTHON_PACKAGE_DIR"
fi

# Check for paho-mqtt and install if missing
echo "Checking for paho-mqtt module..."
if python3 -c "import paho.mqtt.client" 2>/dev/null; then
    echo "paho-mqtt module is available."
else
    echo "paho-mqtt module is missing. Attempting to install..."
    
    if [ "$SYSTEM_TYPE" = "retropie" ]; then
        # For RetroPie, use apt-get
        echo "Installing paho-mqtt via apt-get..."
        sudo apt-get update && sudo apt-get install -y python3-paho-mqtt
    else
        # For Batocera or other systems
        # First check if we can use the package manager
        if command -v opkg >/dev/null 2>&1; then
            echo "Trying to install paho-mqtt via opkg..."
            opkg update && opkg install python3-paho-mqtt
        else
            # Try to install pip first
            install_pip
            
            if command -v pip3 >/dev/null 2>&1; then
                echo "Installing paho-mqtt via pip..."
                
                if [ "$SYSTEM_TYPE" = "batocera" ]; then
                    # Try to install to a writeable directory for Batocera
                    pip3 install --target="$PYTHON_PACKAGE_DIR" paho-mqtt
                    
                    # Add the package directory to Python path
                    export PYTHONPATH="$PYTHON_PACKAGE_DIR:$PYTHONPATH"
                    echo "PYTHONPATH set to: $PYTHONPATH"
                else
                    # For other systems, standard pip install
                    pip3 install paho-mqtt
                fi
                
                # Verify installation
                if python3 -c "import paho.mqtt.client" 2>/dev/null; then
                    echo "Successfully installed paho-mqtt."
                else
                    echo "ERROR: Failed to install paho-mqtt. Integration may not work correctly."
                    echo "Please manually install the paho-mqtt Python package."
                fi
            else
                echo "ERROR: Could not install pip. Cannot install required dependencies."
                echo "Please manually install paho-mqtt Python package."
            fi
        fi
    fi
fi

# Check for watchdog module (optional)
echo "Checking for watchdog module (optional)..."
if python3 -c "import watchdog" 2>/dev/null; then
    echo "watchdog module is available."
else
    echo "watchdog module is not available (optional feature)."
    
    if [ "$SYSTEM_TYPE" = "retropie" ]; then
        echo "Attempting to install watchdog for RetroPie..."
        if sudo apt-get install -y python3-watchdog; then
            echo "Successfully installed watchdog via apt"
        else
            echo "Could not install watchdog via apt, trying pip..."
            pip3 install watchdog || echo "Watchdog installation failed but it's optional."
        fi
    elif [ "$SYSTEM_TYPE" = "batocera" ]; then
        echo "Attempting to install watchdog for Batocera..."
        pip3 install --target="$PYTHON_PACKAGE_DIR" watchdog || echo "Watchdog installation failed but it's optional."
    fi
    
    echo "Some file monitoring features will be disabled."
fi

# If we're on Batocera, create a PYTHONPATH setup script
if [ "$SYSTEM_TYPE" = "batocera" ]; then
    echo "# Add custom Python packages to PYTHONPATH" > "$CONFIG_DIR/pythonpath.sh"
    echo "export PYTHONPATH=\"$PYTHON_PACKAGE_DIR:\$PYTHONPATH\"" >> "$CONFIG_DIR/pythonpath.sh"
    chmod +x "$CONFIG_DIR/pythonpath.sh"
fi

# Find the system-specific installation scripts
SCRIPT_DIR="$(dirname "$0")"

# Export variables for use in the system-specific installation scripts
export MQTT_HOST MQTT_PORT MQTT_USERNAME MQTT_PASSWORD MQTT_TOPIC_PREFIX DEVICE_NAME UPDATE_INTERVAL CONFIG_DIR SYSTEM_NAME
# Export a special flag to indicate the script is being called from the main installer
export CALLED_FROM_INSTALLER=true
export PYTHON_PACKAGE_DIR

# Call the appropriate installation script based on the detected system type
if [ "$SYSTEM_TYPE" = "retropie" ]; then
    echo "Launching RetroPie-specific installation script..."
    bash "$SCRIPT_DIR/retropie_install"
elif [ "$SYSTEM_TYPE" = "batocera" ]; then
    echo "Launching Batocera-specific installation script..."
    bash "$SCRIPT_DIR/batocera_install"
else
    echo "Error: Unknown system type despite earlier detection. This shouldn't happen."
    exit 1
fi

echo ""
echo "Installation completed successfully!"
echo "Thank you for installing the Home Assistant Integration for your ${SYSTEM_TYPE^} system!"
echo ""
echo "Your $SYSTEM_NAME will now report events and status to Home Assistant via MQTT at: $MQTT_TOPIC_PREFIX"
echo "Home Assistant should auto-discover the sensors if MQTT integration is configured."
echo ""
echo "Note: Remember to always use ./install.sh for future updates or reinstallation."
echo "      The system-specific scripts ($(basename $SCRIPT_DIR)/retropie_install or"
echo "      $(basename $SCRIPT_DIR)/batocera_install) cannot be run directly."