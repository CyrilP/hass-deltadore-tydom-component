# Delta Dore Tydom

[![License][license-shield]](LICENSE)

[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

This is a *custom component* for [Home Assistant](https://www.home-assistant.io/).

The `Delta Dore Tydom` integration allows you to observe and control a [Delta Dore Tydom smart home gateway](https://www.deltadore.fr/).

This integration can work in local or cloud mode, depending on its configuration.
The Delta Dore gateway can be detected using DHCP discovery.

![GitHub release](https://img.shields.io/github/release/CyrilP/hass-deltadore-tydom-component)
[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)

**This integration sets up the following platforms.**

Platform | Description
-- | --
`alarm_control_panel` | Controls a TYXAL alarm.
`binary_sensor` | Reports binary states and diagnostics.
`button` | Exposes stateless controls such as gate, garage and alarm actions.
`climate` | Controls heating, cooling and ventilation.
`cover` | Controls shutters, blinds and awnings.
`event` | Reports physical remote-control and wall-switch button presses.
`light` | Controls lights and dimmers.
`lock` | Controls a lock.
`number` | Controls writable numeric settings exposed by a device.
`scene` | Activates TYDOM scenes.
`select` | Controls writable enumerated settings exposed by a device.
`sensor` | Reports measurements and device information.
`switch` | Controls binary outputs, plugs and TYDOM moments.
`update` | Installs supported TYDOM firmware updates.
`weather` | Reports weather information.

### Tested hardware

The integration is capability-driven: compatible devices are discovered from
the usages and metadata advertised by TYDOM rather than from a fixed model
allowlist. The following hardware and configurations have been tested by
contributors; this is not an exhaustive compatibility list.

Category | Confirmed hardware or configuration | Home Assistant support
-- | -- | --
Alarm and safety | TYXAL+, CS8000, CSX40 and DFR smoke detectors | Alarm control, zone modes, diagnostics, event history, acknowledgement and supported remote product/zone management.
Climate and heating | Tybox 5101 with Typass ATL, Tywell Control, TYXIA 1137, Calybox and RF 6600 FP | Area-backed climate control, temperatures, setpoints, operating modes, humidity, battery and capability-driven heating commands where advertised.
Energy monitoring | TYWATT 1000, TYWATT 2000 and TYWATT 5400 with EMIC | Power, current and energy measurements, including heating and domestic-hot-water channels where advertised.
Gates and garage doors | TYXIA 4620 dry-contact receivers | Stateless toggle buttons matching the receiver's open/stop/close pulse sequence, without claiming unavailable position feedback.
Lighting and switching | TYXIA 4910 configured under TYDOM's `Others` usage, TYXIA 6610 and compatible X3D lights, dimmers and plugs | Lights, brightness, switches and plugs according to the capabilities reported by the endpoint.
Openings and covers | TYMOOV roller shutters, BSO installations, K-Line DVI windows and doors, and compatible X3D shutters and awnings | Up, down and stop cover control; opening/contact state where the hardware provides feedback.
Physical controls | TYXIA 2600 wall switches, TYXIA 1410 remote controls, TL 2000 remote controls and TYXAL+ remote controls | Native Home Assistant button events for automations, with battery diagnostics where supplied.
Solar sensors | TySense Sun | Solar irradiance in W/m² and associated diagnostics.
Ventilation | Naviclim Atlantic 875311 | Climate control, operating modes and supported fan speeds.

Devices not listed above may still work fully or expose a useful subset of
their attributes. Please include sanitised debug data when reporting an
untested device so support can be extended without hard-coding one installation.

## Installation

The preferred way to install the Delta Dore Tydom integration is through HACS.

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
The hostname or IP address can be:

* The hostname or IP address of your TYDOM (local mode only). Cloud access is still used to retrieve the gateway credentials.
* `mediation.tydom.com` to use the integration through the cloud.

The MAC address is the MAC address of your TYDOM gateway.

The email address and password are your Delta Dore account credentials.

The alarm PIN is optional and is used to set the alarm mode.

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

- `deltadore_tydom.get_events` returns alarm history filtered as all,
  alarm events, activation/deactivation events or unacknowledged events;
- `deltadore_tydom.acknowledge_events` acknowledges pending alarm events;
- `deltadore_tydom.get_alarm_products` lists configured products and zones;
- `deltadore_tydom.enter_alarm_maintenance` opens a locked remote
  configuration session and puts a disarmed CS8000 into maintenance mode;
- `deltadore_tydom.get_alarm_product_configuration` reads a product's active
  state and zone assignment;
- `deltadore_tydom.configure_alarm_product` enables or disables a product and
  can assign it to another zone;
- `deltadore_tydom.rename_alarm_zone` changes a zone's custom name, or clears
  its label when supplied with an empty name;
- `deltadore_tydom.exit_alarm_maintenance` returns the CS8000 to its normal
  disarmed state and unlocks the remote configuration session.

Use the first service to obtain the product and zone IDs required by the other
services. Product configuration requires the CS8000 to be disarmed and the
TYXAL installer code supplied in each service call. Enter maintenance before
reading or changing product configuration, and always exit maintenance when
finished. The installer code is used only for the request and is redacted from
logs. Product deletion, access codes, telephone settings and siren
configuration are not exposed.

The TYXAL alarm device also provides an **Acknowledge events** button for the
same operation when an action call or automation is not required.

## Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)

***

[integration_blueprint]: https://github.com/CyrilP/hass-deltadore-tydom-component
[buymecoffee]: https://www.buymeacoffee.com/cyrilp
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[exampleimg]: example.png
[forum]: https://community.home-assistant.io/
[license-shield]: https://img.shields.io/github/license/CyrilP/hass-deltadore-tydom-component.svg?style=for-the-badge
