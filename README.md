# RetroPie Home Assistant Integration

This project provides integration between RetroPie and Home Assistant, allowing you to:

- Monitor your RetroPie system status (CPU temperature, memory usage, CPU usage)
- Track game sessions (which games are being played and for how long)
- View game metadata (descriptions, ratings, developers, publishers)
- See game thumbnails in Home Assistant
- Monitor system events (startup, shutdown, game selection)
- Display real-time information in Home Assistant
- Trigger automations based on game events

## Features

- MQTT communication between RetroPie and Home Assistant
- EmulationStation event scripts that report system status
- RunCommand hooks for reliable game start/end detection
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

4. Restart EmulationStation:
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

## Home Assistant Integration

The integration creates the following entities in Home Assistant:

- **Game Status** - Shows the currently running game with rich attributes including:
  - Game description
  - Game genre, developer, and publisher
  - Release date and rating
  - System and emulator being used
- **CPU Temperature** - Shows the current CPU temperature
- **Memory Usage** - Shows the current memory usage as a percentage
- **CPU Load** - Shows the current CPU load

## Troubleshooting

- Check service status: `sudo systemctl status retropie-ha.service`
- View logs: `sudo journalctl -u retropie-ha.service`
- Check integration logs: `cat ~/.config/retropie-ha/retropie-ha.log`
- Check EmulationStation logs: `tail ~/.emulationstation/es_log.txt`
- Check RunCommand event logs: `cat /tmp/retropie_events.log`

## License

MIT