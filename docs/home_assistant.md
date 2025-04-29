# Home Assistant Configuration

This integration uses MQTT discovery to automatically register sensors in Home Assistant. As long as you have MQTT discovery enabled in your Home Assistant instance, the sensors should appear automatically.

## Prerequisites

1. Home Assistant with MQTT integration set up
2. MQTT discovery enabled (it's enabled by default)

## MQTT Configuration in Home Assistant

If you haven't configured MQTT yet in Home Assistant, here's how:

1. Go to **Settings** → **Devices & Services**
2. Click on **Add Integration**
3. Search for **MQTT** and select it
4. Enter your MQTT broker details:
   - Host: Your MQTT broker address
   - Port: Usually 1883
   - Username and Password (if required)

## Sensors

This integration creates the following sensors in Home Assistant:

1. **RetroPie CPU Temperature** - Shows the current CPU temperature
2. **RetroPie GPU Temperature** - Shows the current GPU temperature
3. **RetroPie Game Status** - Shows the currently active game

## Example Dashboard Card

You can add a nice card to your dashboard to display the RetroPie information:

```yaml
type: entities
title: RetroPie Arcade
entities:
  - entity: sensor.retropie_arcade_cpu_temperature
    name: CPU Temperature
  - entity: sensor.retropie_arcade_gpu_temperature
    name: GPU Temperature
  - entity: sensor.retropie_arcade_game_status
    name: Current Game
```

## Advanced Custom Dashboard Card

For a more advanced card with game information display:

```yaml
type: vertical-stack
cards:
  - type: gauge
    entity: sensor.retropie_arcade_cpu_temperature
    name: CPU Temperature
    min: 30
    max: 85
    severity:
      green: 30
      yellow: 65
      red: 75
  - type: conditional
    conditions:
      - entity: sensor.retropie_arcade_game_status
        state_not: ''
    card:
      type: markdown
      content: >
        ## Now Playing

        **{{ states('sensor.retropie_arcade_game_status') }}**
```

## Automation Example

Here's an example automation that triggers when a game starts:

```yaml
alias: "RetroPie Game Started Notification"
description: "Notify when a game is started on RetroPie"
trigger:
  - platform: mqtt
    topic: retropie/arcade/event/game-start
condition: []
action:
  - service: notify.mobile_app
    data:
      title: "RetroPie Game Started"
      message: "Now playing: {{ trigger.payload_json.game_name }}"
mode: single
```
