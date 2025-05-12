# RetroPie Home Assistant Integration

This project provides integration between RetroPie and Home Assistant, allowing you to:

- Monitor your RetroPie system status (CPU temperature, memory usage, CPU usage)
- Track game sessions (which games are being played and for how long)
- View game metadata (descriptions, ratings, developers, publishers)
- See game thumbnails in Home Assistant
- Monitor system events (startup, shutdown, game selection)
- Track machine status (idle, playing, shutdown)
- Use text-to-speech to make announcements through your RetroPie
- Control RetroArch via network commands
- Display messages directly on the RetroArch screen
- Get RetroArch status information in real-time
- Change EmulationStation UI mode (Full, Kid, Kiosk)
- Track game collection statistics (total games, favorites, kid-friendly)
- Display real-time information in Home Assistant
- Trigger automations based on game events

## Features

- MQTT communication between RetroPie and Home Assistant
- EmulationStation event scripts that report system status
- RunCommand hooks for reliable game start/end detection
- System status events (when service starts and stops)
- Machine status tracking (idle, playing, shutdown)
- Game start time and play duration tracking
- Text-to-speech service that can be triggered from Home Assistant
- RetroArch Network Control Interface integration for:
  - Sending any RetroArch command
  - Displaying on-screen messages
  - Retrieving RetroArch status information
  - Automatic configuration of RetroArch network commands
- EmulationStation UI Mode control:
  - Change between Full, Kid, and Kiosk modes
  - Automatic restart of EmulationStation when mode changes
- Game collection scanning:
  - Total games count
  - Favorite games count
  - Kid-friendly games identification
  - Automatic rescanning when gamelist.xml files change
- Proper availability reporting for all entities
- CPU and temperature monitoring
- Memory and CPU usage reporting
- Game session tracking with rich metadata
- Game images and descriptions in the MQTT messages
- Easy installation and configuration
- Automatic EmulationStation audio issue fix

## Installation

1. Clone this repository on your RetroPie system:
   ```
   git clone https://github.com/yourusername/retropie-ha-integration.git
   cd retropie-ha-integration
   ```

2. Run the installation script:
   ```
   ./install.sh
   ```

3. Follow the prompts to configure your MQTT server settings.

4. The installation will:
   - Install required packages (paho-mqtt, pico2wave, alsa-utils)
   - Set up the MQTT client and status reporter
   - Test the text-to-speech functionality
   - Configure the service to start automatically

5. Restart EmulationStation:
   ```
   touch /tmp/es-restart && killall emulationstation
   ```

## Configuration

During installation, you'll be prompted to set:

- MQTT server address and credentials
- Device name for Home Assistant
- Topic prefix for MQTT messages
- Update interval for system metrics

These settings are stored in `~/.config/retropie-ha/config.json` and can be modified after installation.

## How It Works

This integration uses:

1. **System metrics reporting** - A background service reports CPU temperature, memory usage, and CPU load
2. **EmulationStation hooks** - Scripts triggered when games are selected, started, and ended
3. **RunCommand hooks** - Scripts triggered when games are launched and exited by RetroArch
4. **Game metadata extraction** - Information about games is pulled from EmulationStation's gamelist.xml files
5. **Game image embedding** - Thumbnail images are encoded and included in MQTT messages
6. **System status tracking** - Events are generated when the service starts and stops
7. **Machine status management** - The system keeps track of whether the console is idle, playing, or shut down
8. **Play duration tracking** - Game start times are recorded to calculate play duration
9. **Text-to-speech service** - Converts text from MQTT commands to speech using pico2wave and aplay
10. **RetroArch Network Control** - Direct integration with RetroArch's Network Control Interface for commands and status
11. **EmulationStation UI Mode Control** - Ability to change between Full, Kid, and Kiosk modes
12. **Game Collection Scanning** - Asynchronous scanning of all game systems for statistics

## Home Assistant Integration

The integration creates the following entities in Home Assistant:

- **Game Status** - Shows the currently running game with rich attributes including:
  - Game description
  - Game genre, developer, and publisher
  - Release date and rating
  - System and emulator being used
  - Game start time and play duration
- **Machine Status** - Shows whether the system is idle, playing a game, or shut down
- **System Status** - Shows whether the integration service is running or not
- **Total Games** - Shows the total number of games in your collection
- **Favorite Games** - Shows the number of games marked as favorites
- **Kid-Friendly Games** - Shows the number of games suitable for children
- **CPU Temperature** - Shows the current CPU temperature
- **CPU Frequency** - Shows the current CPU frequency in MHz
- **GPU Frequency** - Shows the current GPU frequency in MHz
- **Memory Usage** - Shows the current memory usage as a percentage
- **CPU Load** - Shows the current CPU load

The integration also creates the following services in Home Assistant:

- **Text-to-Speech (TTS)** - Send text to be spoken through the RetroPie speakers
- **RetroArch Message** - Display a message on the RetroArch screen
- **RetroArch Command** - Send any command to RetroArch
- **RetroArch Status** - Get current status information from RetroArch
- **UI Mode** - Change EmulationStation's UI mode (Full, Kid, Kiosk)
- **Scan Games** - Start a background scan of your game collection

## Using Text-to-Speech

You can use the text-to-speech service from Home Assistant to make announcements through your RetroPie speakers. This can be done through:

1. **Home Assistant Service Call**:
   - Service: `mqtt.publish`
   - Data:
     ```yaml
     topic: retropie/command/tts
     payload: '{"text": "Your announcement text here"}'
     ```

2. **Example Automation**:
   ```yaml
   automation:
     - alias: "Announce Game Start"
       trigger:
         - platform: state
           entity_id: sensor.retropie_game_status
           from: "idle"
       action:
         - service: mqtt.publish
           data:
             topic: retropie/command/tts
             payload_template: '{"text": "Now playing {{ states.sensor.retropie_game_status.attributes.name }}"}'
   ```

## Using RetroArch Network Control

The integration provides direct access to RetroArch's Network Control Interface from Home Assistant. This allows you to control RetroArch directly through MQTT commands.

The installation process automatically:
1. Detects the RetroArch configuration file
2. Enables network commands (`network_cmd_enable = "true"`)
3. Sets the network command port (`network_cmd_port = "55355"`)
4. Tests the connection to RetroArch during installation

Additionally, when a game is launched through RetroArch, the integration verifies the network commands are enabled and configures them if needed.

### Displaying Messages on RetroArch Screen

1. **Home Assistant Service Call**:
   - Service: `mqtt.publish`
   - Data:
     ```yaml
     topic: retropie/command/retroarch/message
     payload: '{"message": "Your message to display on RetroArch"}'
     ```

2. **Example Automation**:
   ```yaml
   automation:
     - alias: "Display Achievement on RetroArch"
       trigger:
         - platform: state
           entity_id: sensor.retropie_play_duration
           above: 3600  # 1 hour of play
       action:
         - service: mqtt.publish
           data:
             topic: retropie/command/retroarch/message
             payload: '{"message": "Achievement Unlocked: Dedicated Gamer!"}'
   ```

### Getting RetroArch Status

1. **Home Assistant Service Call**:
   - Service: `mqtt.publish`
   - Data:
     ```yaml
     topic: retropie/command/retroarch/status
     payload: '{}'
     ```

   - Response will be published to: `retropie/command/retroarch/status/response`

### Sending RetroArch Commands

1. **Home Assistant Service Call**:
   - Service: `mqtt.publish`
   - Data:
     ```yaml
     topic: retropie/command/retroarch
     payload: '{"command": "COMMAND_NAME"}'  # Replace COMMAND_NAME with any command from the RetroArch Network Control Interface
     ```

2. **Example Commands**:
   - `PAUSE_TOGGLE` - Pause or unpause the current game
   - `RESET` - Reset the current game
   - `SCREENSHOT` - Take a screenshot
   - `VOLUME_UP` / `VOLUME_DOWN` - Adjust volume
   - `SAVE_STATE` / `LOAD_STATE` - Save or load state
   - See the RetroArch documentation for a complete list of available commands

## Using EmulationStation UI Mode Control

You can change EmulationStation's user interface mode between Full, Kid, and Kiosk modes:

1. **Home Assistant Service Call**:
   - Service: `mqtt.publish`
   - Data:
     ```yaml
     topic: retropie/command/ui_mode
     payload: '{"mode": "Kid"}'  # Valid values: "Full", "Kid", "Kiosk"
     ```

2. **Example Automation**:
   ```yaml
   automation:
     - alias: "Switch to Kid Mode When Idle"
       trigger:
         - platform: state
           entity_id: sensor.retropie_machine_status
           to: "idle"
           for: "00:30:00"  # After 30 minutes of idle time
       action:
         - service: mqtt.publish
           data:
             topic: retropie/command/ui_mode
             payload: '{"mode": "Kid"}'
   ```

   This automation will switch to Kid mode after 30 minutes of idle time.

## Game Collection Statistics

The integration automatically scans your game collection and provides statistics as sensors:

1. **Available Sensors**:
   - `sensor.retropie_total_games`: Total number of games in your collection
   - `sensor.retropie_favorites`: Number of games marked as favorites
   - `sensor.retropie_kid_friendly`: Number of games suitable for children

2. **Automatic Updates**:
   - The integration automatically monitors all gamelist.xml files
   - When you add, remove, or mark games as favorites, stats are updated
   - There's a 5-second debounce to avoid frequent updates during bulk changes

3. **Manual Scan Trigger**:
   - Service: `mqtt.publish`
   - Data:
     ```yaml
     topic: retropie/command/scan_games
     payload: '{}'
     ```

## Troubleshooting

- Check service status: `sudo systemctl status retropie-ha.service`
- View logs: `sudo journalctl -u retropie-ha.service`
- Check integration logs: `cat ~/.config/retropie-ha/retropie-ha.log`
- Check EmulationStation logs: `tail ~/.emulationstation/es_log.txt`
- Check RunCommand event logs: `cat /tmp/retropie_events.log`

## License

MIT