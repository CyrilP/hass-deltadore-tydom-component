"""Tests for the pilot-wire (fil-pilote) discriminator in HaClimate.__init__."""

import enum
import importlib.util
import sys
import types
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, call

_MISSING = object()
_original_modules: dict[str, object] = {}


def _module(name: str, **attributes) -> types.ModuleType:
    """Install a minimal module needed to load ha_entities.py in isolation."""
    _original_modules.setdefault(name, sys.modules.get(name, _MISSING))
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    sys.modules[name] = module
    return module


class _StubEntity:
    """Minimal stand-in for Home Assistant entity base classes."""

    def __init__(self, *args, **kwargs) -> None:
        pass


class _StubClimateEntity(_StubEntity):
    """Stub mirroring the handful of ClimateEntity default attrs HaClimate reads."""

    _attr_supported_features = 0
    _attr_min_temp = 7.0
    _attr_max_temp = 35.0
    _attr_target_temperature_step = None


class _IntFlagStub(enum.IntFlag):
    """Base for feature-flag stubs so `|` works like the real HA enums."""


def _feature_flag(name: str, members: list[str]) -> type:
    return _IntFlagStub(name, {m: 2**i for i, m in enumerate(members)})


ClimateEntityFeature = _feature_flag(
    "ClimateEntityFeature",
    ["TURN_OFF", "TURN_ON", "TARGET_TEMPERATURE", "PRESET_MODE", "FAN_MODE"],
)
CoverEntityFeature = _feature_flag(
    "CoverEntityFeature",
    ["OPEN", "CLOSE", "STOP", "SET_POSITION", "SET_TILT_POSITION"],
)
AlarmControlPanelEntityFeature = _feature_flag(
    "AlarmControlPanelEntityFeature",
    ["ARM_AWAY", "ARM_HOME", "ARM_NIGHT", "TRIGGER"],
)


class HVACMode(enum.StrEnum):
    """Stub mirroring the handful of HVACMode members HaClimate reads."""

    OFF = "off"
    HEAT = "heat"
    COOL = "cool"
    AUTO = "auto"
    FAN_ONLY = "fan_only"
    DRY = "dry"


# --- homeassistant.components.binary_sensor ---
_module(
    "homeassistant.components.binary_sensor",
    BinarySensorDeviceClass=MagicMock(),
    BinarySensorEntity=_StubEntity,
    BinarySensorEntityDescription=MagicMock(),
)

# --- homeassistant.components.climate ---
_module(
    "homeassistant.components.climate",
    ClimateEntity=_StubClimateEntity,
    ClimateEntityFeature=ClimateEntityFeature,
    FAN_AUTO="auto",
    HVACAction=MagicMock(),
    HVACMode=HVACMode,
    PRESET_AWAY="away",
    PRESET_COMFORT="comfort",
    PRESET_ECO="eco",
    PRESET_NONE="none",
)

# --- homeassistant.const ---
_module(
    "homeassistant.const",
    ATTR_TEMPERATURE="temperature",
    UnitOfTemperature=MagicMock(CELSIUS="°C"),
    UnitOfEnergy=MagicMock(),
    UnitOfPower=MagicMock(),
    UnitOfElectricCurrent=MagicMock(),
    EntityCategory=MagicMock(),
    PERCENTAGE="%",
)

# --- homeassistant.helpers.entity / homeassistant.helpers ---
_module("homeassistant.helpers.entity", DeviceInfo=dict)
_module("homeassistant.helpers", device_registry=types.ModuleType("device_registry"))
_module("homeassistant.helpers.device_registry")

# --- homeassistant.exceptions ---
_module("homeassistant.exceptions", HomeAssistantError=Exception)

# --- homeassistant.components.cover ---
_module(
    "homeassistant.components.cover",
    ATTR_POSITION="position",
    ATTR_TILT_POSITION="tilt_position",
    CoverEntity=_StubEntity,
    CoverDeviceClass=MagicMock(),
    CoverEntityFeature=CoverEntityFeature,
)

# --- homeassistant.components.sensor ---
_module(
    "homeassistant.components.sensor",
    SensorDeviceClass=MagicMock(TEMPERATURE="temperature", BATTERY="battery"),
    SensorStateClass=MagicMock(MEASUREMENT="measurement"),
    SensorEntity=_StubEntity,
    SensorEntityDescription=MagicMock(),
)

# --- homeassistant.components.light ---
_module(
    "homeassistant.components.light",
    LightEntity=_StubEntity,
    ColorMode=MagicMock(),
    ATTR_BRIGHTNESS="brightness",
)

# --- homeassistant.components.update ---
_module(
    "homeassistant.components.update",
    UpdateEntity=_StubEntity,
    UpdateEntityFeature=MagicMock(),
    UpdateDeviceClass=MagicMock(),
)

# --- homeassistant.components.alarm_control_panel ---
_module(
    "homeassistant.components.alarm_control_panel",
    AlarmControlPanelEntity=_StubEntity,
    CodeFormat=MagicMock(),
    AlarmControlPanelEntityFeature=AlarmControlPanelEntityFeature,
    AlarmControlPanelState=MagicMock(),
)

# --- homeassistant.util.percentage ---
_module(
    "homeassistant.util.percentage",
    percentage_to_ranged_value=MagicMock(),
    ranged_value_to_percentage=MagicMock(),
)
_module("homeassistant.util")

# --- homeassistant.components.weather ---
_module(
    "homeassistant.components.weather",
    WeatherEntity=_StubEntity,
    ATTR_CONDITION_CLEAR_NIGHT="clear-night",
    ATTR_CONDITION_CLOUDY="cloudy",
    ATTR_CONDITION_FOG="fog",
    ATTR_CONDITION_LIGHTNING="lightning",
    ATTR_CONDITION_POURING="pouring",
    ATTR_CONDITION_RAINY="rainy",
    ATTR_CONDITION_SNOWY="snowy",
    ATTR_CONDITION_SUNNY="sunny",
)

# --- remaining homeassistant.components.* single-entity modules ---
_module("homeassistant.components.scene", Scene=_StubEntity)
_module("homeassistant.components.switch", SwitchEntity=_StubEntity)
_module("homeassistant.components.button", ButtonEntity=_StubEntity)
_module("homeassistant.components.number", NumberEntity=_StubEntity)
_module("homeassistant.components.select", SelectEntity=_StubEntity)
_module(
    "homeassistant.components.text",
    TextEntity=_StubEntity,
    TextMode=MagicMock(),
)
_module(
    "homeassistant.components.event",
    EventDeviceClass=MagicMock(),
    EventEntity=_StubEntity,
)
_module("homeassistant.components")
_module("homeassistant")

# --- custom_components scaffolding, same pattern as test_climate_setpoint_preservation.py ---
for package_name in (
    "custom_components",
    "custom_components.deltadore_tydom",
    "custom_components.deltadore_tydom.tydom",
):
    package = _module(package_name)
    package.__path__ = []

_module(
    "custom_components.deltadore_tydom.const",
    DOMAIN="deltadore_tydom",
    LOGGER=MagicMock(),
    TYDOM_UNIT_TO_HA_UNIT={},
    get_naviclim_fan_mode=MagicMock(),
    get_naviclim_fan_modes=MagicMock(),
    validate_value_with_metadata=MagicMock(return_value=(True, None)),
)

_module(
    "custom_components.deltadore_tydom.tydom.MessageHandler",
    device_name={},
    groups_data={},
)
_module(
    "custom_components.deltadore_tydom.official_association_tutorials",
    get_association_illustration_data_url=MagicMock(return_value=None),
)


def _load(module_name: str, relative_path: str):
    module_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "deltadore_tydom"
        / relative_path
    )
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    _original_modules.setdefault(module_name, sys.modules.get(module_name, _MISSING))
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


devices_module = _load(
    "custom_components.deltadore_tydom.tydom.tydom_devices", "tydom/tydom_devices.py"
)
TydomBoiler = devices_module.TydomBoiler

entities_module = _load(
    "custom_components.deltadore_tydom.ha_entities", "ha_entities.py"
)
HaClimate = entities_module.HaClimate

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


def _thermostat(*, metadata, data, device_type="boiler"):
    """Create a TydomBoiler device and its HaClimate entity."""
    client = MagicMock()
    client.put_devices_data = AsyncMock()
    device = TydomBoiler(
        client,
        "10_20",
        "20",
        "Thermostat",
        device_type,
        "10",
        metadata,
        data,
    )
    entity = HaClimate(device, hass=MagicMock())
    return entity, client


def _reversible_zone(*, thermic_level="ANTI_FROST"):
    """Create a cool+heat zone exposing ANTI_FROST through thermicLevel."""
    return _thermostat(
        metadata={
            "authorization": {
                "type": "string",
                "permission": "r",
                "enum_values": ["STOP", "HEATING", "COOLING", "AUTO"],
            },
            "comfortMode": {
                "type": "string",
                "permission": "w",
                "enum_values": ["STOP", "HEATING", "COOLING"],
            },
            "thermicLevel": {
                "type": "string",
                "permission": "rw",
                "enum_values": ["STOP", "ANTI_FROST"],
            },
            "setpoint": {
                "type": "numeric",
                "permission": "rw",
                "min": 10,
                "max": 30,
            },
            "heatSetpoint": {
                "type": "numeric",
                "permission": "rw",
                "min": 10,
                "max": 30,
            },
            "coolSetpoint": {
                "type": "numeric",
                "permission": "rw",
                "min": 10,
                "max": 30,
            },
        },
        data={
            "authorization": "COOLING",
            "thermicLevel": thermic_level,
            "setpoint": None,
            "heatSetpoint": None,
            "coolSetpoint": None,
        },
    )


class FilPiloteDetectionTests(TestCase):
    """Ensure _is_filpilote correctly discriminates pilot-wire zones."""

    def test_authorization_only_rf6600_is_detected_as_pilot_wire(self) -> None:
        """An RF 6600 zone using `authorization` (no hvacMode) must be recognised as pilot-wire.

        This ensures it gets the [off, heat] + presets UI.
        """
        entity, _client = _thermostat(
            metadata={
                "authorization": {
                    "type": "string",
                    "permission": "r",
                    "enum_values": ["STOP", "HEATING"],
                },
                "comfortMode": {
                    "type": "string",
                    "permission": "w",
                    "enum_values": ["STOP", "HEATING"],
                },
                "thermicLevel": {
                    "type": "string",
                    "permission": "rw",
                    "enum_values": ["ECO", "COMFORT", "STOP", "ANTI_FROST"],
                },
            },
            data={
                "authorization": "HEATING",
                "thermicLevel": "ECO",
            },
        )
        self.assertTrue(entity._is_filpilote)
        self.assertEqual(entity._attr_hvac_modes, [HVACMode.OFF, HVACMode.HEAT])

    def test_authorization_with_heat_setpoint_is_not_pilot_wire(self) -> None:
        """A conventional authorisation-based thermostat must not be misclassified.

        It exposes `heatSetpoint` (not `setpoint`) and must NOT be treated as
        pilot-wire, or it would lose target-temperature support.
        """
        entity, _client = _thermostat(
            metadata={
                "authorization": {
                    "type": "string",
                    "permission": "r",
                    "enum_values": ["STOP", "HEATING"],
                },
                "thermicLevel": {
                    "type": "string",
                    "permission": "rw",
                    "enum_values": ["ECO", "COMFORT", "STOP", "ANTI_FROST"],
                },
                "heatSetpoint": {
                    "type": "numeric",
                    "permission": "rw",
                    "min": 5,
                    "max": 30,
                },
            },
            data={
                "authorization": "HEATING",
                "thermicLevel": "ECO",
                "heatSetpoint": 19.5,
            },
        )
        self.assertFalse(entity._is_filpilote)

    def test_live_setpoint_without_metadata_is_not_pilot_wire(self) -> None:
        """Keep a Tywell/Typass zone controllable before metadata is loaded.

        Some gateways publish /devices/data before /devices/meta.  A live
        writable setpoint is enough evidence that the zone is not an RF 6600
        pilot-wire heater, even when its min/max metadata is not available yet.
        """
        entity, _client = _thermostat(
            metadata={
                "authorization": {
                    "type": "string",
                    "permission": "r",
                    "enum_values": ["STOP", "HEATING"],
                },
                "thermicLevel": {
                    "type": "string",
                    "permission": "rw",
                    "enum_values": ["ECO", "COMFORT", "STOP", "ANTI_FROST"],
                },
            },
            data={
                "authorization": "HEATING",
                "thermicLevel": "COMFORT",
                "setpoint": 20.0,
                "minSetpoint": 5.0,
                "maxSetpoint": 30.0,
            },
        )

        self.assertFalse(entity._is_filpilote)
        self.assertTrue(
            entity.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE
        )

    def test_authorization_with_cool_setpoint_is_not_pilot_wire(self) -> None:
        """Same guard, using `coolSetpoint` instead of `heatSetpoint`."""
        entity, _client = _thermostat(
            metadata={
                "authorization": {
                    "type": "string",
                    "permission": "r",
                    "enum_values": ["STOP", "HEATING"],
                },
                "thermicLevel": {
                    "type": "string",
                    "permission": "rw",
                    "enum_values": ["ECO", "COMFORT", "STOP", "ANTI_FROST"],
                },
                "coolSetpoint": {
                    "type": "numeric",
                    "permission": "rw",
                    "min": 16,
                    "max": 28,
                },
            },
            data={
                "authorization": "HEATING",
                "thermicLevel": "ECO",
                "coolSetpoint": 24.0,
            },
        )
        self.assertFalse(entity._is_filpilote)


class AreaTrvClimateTests(IsolatedAsyncioTestCase):
    """Ensure a TRV adopts its area capabilities after late discovery."""

    async def test_area_link_exposes_target_temperature_and_writes_a_number(self):
        """A late area link must replace the generic heat/off UI with a setpoint."""
        entity, client = _thermostat(
            metadata={
                "regTemperature": {"permission": "r"},
                "waterFlowReq": {"permission": "r"},
            },
            data={"regTemperature": 23.5, "waterFlowReq": False},
            device_type="sh_hvac",
        )

        # /devices/data can be parsed before its linked /areas/data response.
        # The association must therefore be evaluated at state-write time, not
        # only while this entity is constructed.
        entity._device.area_id = "7"
        entity._device.currentSetpoint = 21.0

        self.assertEqual(entity.hvac_modes, [HVACMode.HEAT])
        self.assertEqual(entity.target_temperature, 21.0)
        self.assertEqual(
            entity.supported_features, ClimateEntityFeature.TARGET_TEMPERATURE
        )

        client.put_area_data_attributes = AsyncMock()
        await entity.async_set_temperature(temperature=20.5)

        client.put_area_data_attributes.assert_awaited_once_with(
            "7",
            {
                "localSetpoint": 20.5,
                "localSetpRemainingTimeStr": "UNTIL_SCHED",
                "localMode": "LOCAL_SETPOINT",
            },
        )


class ReversibleZoneAntiFrostPresetTests(IsolatedAsyncioTestCase):
    """Ensure reversible zones expose and write the frost-protection preset."""

    async def test_anti_frost_is_exposed_as_away(self) -> None:
        """A thermicLevel ANTI_FROST state must not fall back to `none`."""
        entity, _client = _reversible_zone()

        self.assertFalse(entity._is_filpilote)
        self.assertIn(entities_module.PRESET_AWAY, entity._attr_preset_modes)
        self.assertEqual(entity.preset_mode, entities_module.PRESET_AWAY)

    async def test_away_writes_anti_frost_to_thermic_level(self) -> None:
        """The standard HA away preset must target thermicLevel ANTI_FROST."""
        entity, client = _reversible_zone(thermic_level="STOP")

        await entity.async_set_preset_mode(entities_module.PRESET_AWAY)

        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "thermicLevel", "ANTI_FROST"
        )


class AbsencePresetTests(IsolatedAsyncioTestCase):
    """Expose TYDOM's ABSENCE local mode as Home Assistant's Away preset."""

    async def test_absence_local_mode_is_reflected_as_away(self) -> None:
        """An active TYDOM absence mode takes precedence over comfort mode."""
        entity, _client = _thermostat(
            metadata={
                "comfortMode": {
                    "permission": "rw",
                    "enum_values": ["NORMAL", "ECO", "COMFORT"],
                },
            },
            data={"comfortMode": "NORMAL", "localMode": "ABSENCE"},
        )

        self.assertIn(entities_module.PRESET_AWAY, entity.preset_modes)
        self.assertEqual(entity.preset_mode, entities_module.PRESET_AWAY)

    async def test_selecting_away_writes_area_absence_mode(self) -> None:
        """Use the linked thermal area register for an advertised absence mode."""
        entity, client = _thermostat(
            metadata={
                "comfortMode": {
                    "permission": "rw",
                    "enum_values": ["NORMAL", "ECO", "COMFORT"],
                },
                "localMode": {
                    "permission": "rw",
                    "enum_values": ["SCHED", "MANUAL", "ABSENCE"],
                },
            },
            data={"area_id": "1791094613", "localMode": "SCHED"},
        )
        client.put_area_data = AsyncMock()

        self.assertIn(entities_module.PRESET_AWAY, entity.preset_modes)
        await entity.async_set_preset_mode(entities_module.PRESET_AWAY)

        client.put_area_data.assert_awaited_once_with(
            "1791094613", "localMode", "ABSENCE"
        )

    async def test_absence_preset_does_not_fall_back_to_anti_frost(self) -> None:
        """Do not write another register when localMode is read-only."""
        entity, client = _thermostat(
            metadata={
                "comfortMode": {
                    "permission": "rw",
                    "enum_values": ["NORMAL", "ECO", "COMFORT"],
                },
                "localMode": {
                    "permission": "r",
                    "enum_values": ["SCHED", "MANUAL", "ABSENCE"],
                },
                "thermicLevel": {
                    "permission": "rw",
                    "enum_values": ["ANTI_FROST"],
                },
            },
            data={"localMode": "ABSENCE"},
        )

        await entity.async_set_preset_mode(entities_module.PRESET_AWAY)

        client.put_devices_data.assert_not_awaited()


class PresetNoneSendsAutoTests(IsolatedAsyncioTestCase):
    """Ensure selecting the `None` preset drives thermicLevel AUTO when supported.

    Also checks it is a safe no-op otherwise (refs #411).
    """

    async def test_preset_none_sends_thermic_level_auto_when_supported(self) -> None:
        """Send AUTO for a Calybox-230-like zone advertising it.

        A zone whose thermicLevel enum includes AUTO must send
        `thermicLevel: AUTO` when the None preset is selected.
        """
        entity, client = _thermostat(
            metadata={
                "authorization": {
                    "type": "string",
                    "permission": "r",
                    "enum_values": ["STOP", "HEATING"],
                },
                "thermicLevel": {
                    "type": "string",
                    "permission": "rw",
                    "enum_values": [
                        "ECO",
                        "COMFORT",
                        "STOP",
                        "ANTI_FROST",
                        "AUTO",
                    ],
                },
            },
            data={
                "authorization": "HEATING",
                "thermicLevel": "COMFORT",
            },
        )
        self.assertTrue(entity._is_filpilote)

        await entity.async_set_preset_mode("none")

        self.assertEqual(
            client.put_devices_data.await_args_list,
            [call("20", "10", "thermicLevel", "AUTO")],
        )

    async def test_preset_none_is_a_no_op_when_auto_not_advertised(self) -> None:
        """Do nothing for an RF 6600 zone that doesn't advertise AUTO.

        A zone whose thermicLevel enum has no AUTO value must not send
        anything for the None preset (previous, safe behaviour).
        """
        entity, client = _thermostat(
            metadata={
                "authorization": {
                    "type": "string",
                    "permission": "r",
                    "enum_values": ["STOP", "HEATING"],
                },
                "thermicLevel": {
                    "type": "string",
                    "permission": "rw",
                    "enum_values": ["ECO", "COMFORT", "STOP", "ANTI_FROST"],
                },
            },
            data={
                "authorization": "HEATING",
                "thermicLevel": "ECO",
            },
        )
        self.assertTrue(entity._is_filpilote)

        await entity.async_set_preset_mode("none")

        client.put_devices_data.assert_not_awaited()


if __name__ == "__main__":
    import unittest

    unittest.main()
