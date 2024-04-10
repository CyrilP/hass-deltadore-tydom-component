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
`update` | firmware update

**This integration has been tested with the following hardware.**

- Cover (Up/Down/Stop)
- Tywatt 5400, Tywatt 1000
- Tyxal+ DFR
- K-Line DVI (windows, door)
- Typass ATL (zones temperatures, target temperature, mode (Auto mode is used for antifrost), water/heat power usage) with Tybox 5101
- Calybox
- Tyxal+, Tyxal CSX40
- TYXIA 6610 (issue with status change)

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

## Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)

***

[integration_blueprint]: https://github.com/CyrilP/hass-deltadore-tydom-component
[buymecoffee]: https://www.buymeacoffee.com/cyrilp
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[exampleimg]: example.png
[forum]: https://community.home-assistant.io/
[license-shield]: https://img.shields.io/github/license/CyrilP/hass-deltadore-tydom-component.svg?style=for-the-badge
