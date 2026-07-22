# Add area-backed climate support for Tywell Control

## Summary

This completes and extends the area-based thermostat work originally proposed in #233. Newer Tywell installations carry thermostat state and commands through `/areas/data` rather than solely through `/devices/data`, and the logical device layout varies according to how the Tywell Control is associated.

The integration now supports both currently known layouts:

- An area-linked `re2020ControlBoiler` is exposed directly as a climate device.
- An area-linked `re2020ControlPassive` keeps its original sensor device and gains a separate area-backed climate device.

An unlinked passive controller remains sensor/shutter-only, and an unlinked thermal endpoint does not create a non-functional climate entity.

## Changes

- Fetch area state during the initial TYDOM connection.
- Parse both `/areas/data` and individual `/areas/{id}/data` responses.
- Associate device endpoints with their reported thermal area and route area updates to every linked climate device.
- Cache area state received before device discovery and retain valid state across partial or errored responses.
- Add properly encoded `PUT /areas/{id}/data` commands for HVAC mode and target temperature.
- Use the area `authorization` value to represent heating, cooling and off states.
- Expose only the HVAC modes advertised by the installation.
- Select `setpoint`, `heatSetpoint` or `coolSetpoint` according to the current mode and gateway metadata.
- Derive target-temperature limits and increments from live area values, with linked-controller metadata as a fallback. No installation-specific 10-30 degrees C range is hard-coded.
- Preserve the strongest controller metadata when later TYDOM messages contain only a partial set of linked endpoints.
- Reuse the passive Tywell's room temperature for the derived climate entity while avoiding duplicate temperature sensors.
- Keep high-frequency discovery and area-update diagnostics at debug level.

## Installation compatibility

The implementation follows TYDOM usage types, capabilities and area links; it does not check for a particular gateway, heat pump or receiver model.

It therefore covers:

- The direct `re2020ControlBoiler` layout reported in #233.
- The `re2020ControlPassive` plus linked thermal controller layout observed with a Tywell Pro, Tywell Control, Tybox 5101 and Typass ATL.
- Heating-only and reversible heating/cooling areas with installation-specific limits and setpoint registers.

An unknown layout using another usage type or no thermal area link will remain unchanged until a corresponding TYDOM capture is available.

## Verification

- 14 automated tests cover direct and passive discovery, unlinked-device gating, initial and pushed area state, out-of-order responses, errored responses, metadata retention, HVAC capabilities, mode and temperature writes, live limits, and reversible-system setpoints.
- All automated tests pass.
- Ruff formatting and lint checks pass.
- Tested successfully on a live Tywell Pro installation using a Tywell Control, two Tybox 5101 thermostats and a Typass ATL controlling an Atlantic heat pump. Area state updates and target-temperature commands were confirmed in Home Assistant and the TYDOM logs.

## Files changed

- `custom_components/deltadore_tydom/ha_entities.py`
- `custom_components/deltadore_tydom/tydom/MessageHandler.py`
- `custom_components/deltadore_tydom/tydom/tydom_client.py`
- `custom_components/deltadore_tydom/tydom/tydom_devices.py`
- `tests/test_area_thermostats.py`
