# RetroPie Home Assistant Integration

This project provides integration between RetroPie and Home Assistant, allowing you to:

- Monitor your RetroPie system status (CPU temperature, memory usage, CPU usage)
- Track game sessions (which games are being played and for how long)
- View game metadata (descriptions, ratings, developers, publishers)
- See game thumbnails in Home Assistant
- Monitor system events (startup, shutdown, game selection)
- Track machine status (idle, playing, shutdown)
- Use text-to-speech to make announcements through your RetroPie
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
- **CPU Temperature** - Shows the current CPU temperature
- **Memory Usage** - Shows the current memory usage as a percentage
- **CPU Load** - Shows the current CPU load

The integration also creates the following services in Home Assistant:

- **Text-to-Speech (TTS)** - Send text to be spoken through the RetroPie speakers

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

## Troubleshooting

- Check service status: `sudo systemctl status retropie-ha.service`
- View logs: `sudo journalctl -u retropie-ha.service`
- Check integration logs: `cat ~/.config/retropie-ha/retropie-ha.log`
- Check EmulationStation logs: `tail ~/.emulationstation/es_log.txt`
- Check RunCommand event logs: `cat /tmp/retropie_events.log`

## License

MIT