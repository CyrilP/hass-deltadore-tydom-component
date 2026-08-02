# Delta Dore Tydom

[![License][license-shield]](LICENSE)

[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

This a *custom component* for [Home Assistant](https://www.home-assistant.io/).

The `Delta Dore Tydom` integration allows you to observe and control [Delta Dore Tydom smart home gateway](https://www.deltadore.fr/).

This integration can work in local mode or cloud mode depending on how the integration is configured (see Configuration part)
The Delta Dore gateway can be detected using dhcp discovery.

![GitHub release](https://img.shields.io/github/release/CyrilP/hass-deltadore-tydom-component)
[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)

**This integration will set up the following platforms.**

Platform | Description
-- | --
`binary_sensor` | Show something `True` or `False`.
`sensor` | Show info.
`switch` | Switch something `True` or `False`.
`cover` | controls an opening or cover.
`climate` | controls temperature, humidity, or fans.
`light` | controls a light.
`lock` | controls a lock.
`alarm_control_panel` | controls an alarm.
`weather` | provides meteorological data
`update` | firmware update

**This integration has been tested with the following hardware.**

- Cover (Up/Down/Stop)
- Tywatt 5400, Tywatt 1000
- Tyxal+ DFR
- K-Line DVI (windows, door)
- Typass ATL (zones temperatures, target temperature, mode (Auto mode is used for antifrost), water/heat power usage) with Tybox 5101
- Calybox
- Tyxal+, Tyxal CSX40
- TYXIA 6610
- BSO
- Naviclim Atlantic 875311
- RF 6600 FP : partial issue #92

Some other functions may also work or only report attributes.

## Installation

The preferred way to install the Delta Dore Tydom integration is by addig it using HACS.

Add your device via the Integration menu

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=deltadore_tydom)

Manual method :

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
1. If you do not have a `custom_components` directory (folder) there, you need to create it.
1. In the `custom_components` directory (folder) create a new folder called `deltadore_tydom`.
1. Download _all_ the files from the `custom_components/deltadore_tydom/` directory (folder) in this repository.
1. Place the files you downloaded in the new directory (folder) you created.
1. Restart Home Assistant
1. In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "Delta Dore Tydom"

## Configuration is done in the UI

<!---->
The hostname/ip can be :
* The hostname/ip of your Tydom (local mode only). An access to the cloud is done to retrieve the Tydom credentials
* mediation.tydom.com. Using this configuration makes the integration work through the cloud

The Mac address is the Mac of you Tydom

Email/Password are you Dela Dore credentials

The alarm PIN is optional and used to set your alarm mode

## Capturing data for unsupported devices

The repository includes a read-only capture tool for documenting devices and
protocol behaviour that the integration does not yet support:

```bash
python3 tools/capture_tydom_data.py \
  --host 192.168.1.100 \
  --mac 001A2502419B \
  --password '<Tydom gateway password>' \
  --duration 120
```

The tool requests the current configuration, device, area, scenario, group and
moment resources, including `/devices/meta`, `/devices/cmeta`, `/devices/data`,
`/areas/meta`, `/areas/cmeta` and `/areas/data`. It then continues listening for
events while the equipment is operated physically or from the Tydom app.

Each run produces:

- `raw_messages.txt`, containing timestamped and replayable WebSocket frames;
- `parsed_messages.json`, containing normalised URIs, methods or response
  statuses, and decoded payloads.

Passwords, tokens, authorisation headers and email addresses are redacted before
the files are written. Device identifiers, names, topology and state values are
retained because they are needed for protocol analysis, so captures must still
be reviewed before being shared publicly.

For a useful device capture, perform one clearly identifiable action, wait about
ten seconds, perform the reverse action, and record both timestamps. The capture
sees responses and events published by the gateway; it cannot necessarily reveal
the exact outbound request sent by another client such as the official mobile
application.

See the [complete capture guide](tools/README_capture.md) for local and remote
connection examples, output analysis, parser validation and security guidance.
The separate [endpoint discovery guide](tools/README_discover_endpoints.md)
describes how to probe available API resources and HTTP methods.

## TYXAL+ remote management

The alarm control panel provides services for the TYXAL+ functions that are
useful in Home Assistant:

- `deltadore_tydom.get_alarm_products` lists configured products and zones;
- `deltadore_tydom.enter_alarm_maintenance` opens a locked remote
  configuration session and puts a disarmed CS8000 into maintenance mode;
- `deltadore_tydom.get_alarm_product_configuration` reads a product's active
  state and zone assignment;
- `deltadore_tydom.configure_alarm_product` enables or disables a product and
  can assign it to another zone;
- `deltadore_tydom.rename_alarm_zone` changes a zone's custom name;
- `deltadore_tydom.exit_alarm_maintenance` returns the CS8000 to its normal
  disarmed state and unlocks the remote configuration session.

Use the first service to obtain the product and zone IDs required by the other
services. Product configuration requires the CS8000 to be disarmed and the
TYXAL installer code supplied in each service call. Enter maintenance before
reading or changing product configuration, and always exit maintenance when
finished. The installer code is used only for the request and is redacted from
logs. Product deletion, access codes, telephone settings and siren
configuration are not exposed.

## Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)

***

[integration_blueprint]: https://github.com/CyrilP/hass-deltadore-tydom-component
[buymecoffee]: https://www.buymeacoffee.com/cyrilp
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[exampleimg]: example.png
[forum]: https://community.home-assistant.io/
[license-shield]: https://img.shields.io/github/license/CyrilP/hass-deltadore-tydom-component.svg?style=for-the-badge
