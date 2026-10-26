"""Tests for the pilot-wire (fil-pilote) discriminator in HaClimate.__init__."""

import asyncio
import enum
import importlib.util
import sys
import types
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, Mock, call, patch

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
class _HomeAssistantError(Exception):
    def __init__(self, *args, **kwargs):
        self.translation_key = kwargs.get("translation_key")
        super().__init__(*args)


_ha_exceptions = _module(
    "homeassistant.exceptions", HomeAssistantError=_HomeAssistantError
)

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
    SensorDeviceClass=MagicMock(
        TEMPERATURE="temperature", BATTERY="battery", HUMIDITY="humidity"
    ),
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
    TextEntityDescription=MagicMock(),
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
    "custom_components.deltadore_tydom.entity_names",
    set_entity_name=MagicMock(),
)

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

_load("custom_components.deltadore_tydom.climate_commands", "climate_commands.py")

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


def _rf6600fp(*, authorization="HEATING", thermic_level="ECO"):
    """Create the RF6600FP capability profile."""
    entity, client = _thermostat(
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
            "overrideThermicLevel": {
                "type": "string",
                "permission": "rw",
                "enum_values": ["ECO", "COMFORT", "STOP", "ANTI_FROST"],
            },
            "localMode": {
                "type": "string",
                "permission": "rw",
                "enum_values": ["NORMAL", "STOP", "ANTI_FROST", "ABSENCE"],
            },
            "useMode": {
                "type": "string",
                "permission": "rw",
                "enum_values": ["SCHED", "OVERRIDE", "MANUAL"],
            },
        },
        data={
            "authorization": authorization,
            "thermicLevel": thermic_level,
            "localMode": "NORMAL",
            "useMode": "SCHED",
        },
    )
    client.general_climate = types.SimpleNamespace(mode="HEATING", lock_reason=None)
    return entity, client


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

    def test_live_setpoint_bounds_without_current_value_are_not_pilot_wire(
        self,
    ) -> None:
        """Advertised live limits keep an idle Tybox climate temperature-capable."""
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
                "authorization": "STOP",
                "thermicLevel": "STOP",
                "setpoint": None,
                "heatSetpoint": None,
                "minHeatSetpoint": 10.0,
                "maxHeatSetpoint": 30.0,
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


class TyboxThermostatModeTests(IsolatedAsyncioTestCase):
    """Keep an idle, bounded Tybox as a regular heat/off thermostat."""

    async def test_switching_from_stop_to_heat_writes_heating_command(self) -> None:
        """A live bounds-only Tybox still sends its HEATING register."""
        entity, client = _thermostat(
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
                    "enum_values": ["STOP", "COMFORT", "ECO"],
                },
            },
            data={
                "authorization": "STOP",
                "thermicLevel": "STOP",
                "setpoint": None,
                "heatSetpoint": None,
                "minHeatSetpoint": 10.0,
                "maxHeatSetpoint": 30.0,
            },
        )
        self.addCleanup(entity._get_command_tracker().close)

        self.assertFalse(entity._is_filpilote)
        await entity.async_set_hvac_mode(HVACMode.HEAT)

        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "comfortMode", "HEATING"
        )


class ClimateSensorMetadataTests(TestCase):
    """Ensure ancillary climate sensors expose correct Home Assistant metadata."""

    def test_hygro_in_is_a_humidity_measurement(self) -> None:
        """Indoor relative humidity uses HA's humidity class and percentage unit."""
        self.assertEqual(
            HaClimate.sensor_classes["hygroIn"],
            entities_module.SensorDeviceClass.HUMIDITY,
        )
        self.assertEqual(
            HaClimate.state_classes["hygroIn"],
            entities_module.SensorStateClass.MEASUREMENT,
        )
        self.assertEqual(HaClimate.units["hygroIn"], "%")


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


class RequestedClimateTargetTests(IsolatedAsyncioTestCase):
    """Apply the same pending-target display rule to every climate profile."""

    def climate(self, *, data=None, device_type="boiler", area=False):
        """Create a climate with real tracking and mocked protocol transport."""
        entity, client = _thermostat(
            metadata={
                "setpoint": {
                    "type": "numeric",
                    "permission": "rw",
                    "min": 5,
                    "max": 30,
                },
                "hvacMode": {
                    "permission": "rw",
                    "enum_values": ["STOP", "NORMAL", "COOLING"],
                },
            },
            data=data or {"hvacMode": "NORMAL", "setpoint": 21},
            device_type=device_type,
        )
        if area:
            entity._device.area_id = "7"
        client.put_area_data = AsyncMock()
        client.put_area_data_attributes = AsyncMock()
        entity.async_write_ha_state = MagicMock()
        entity._command_listening = True
        self.addCleanup(entity._get_command_tracker().close)
        return entity, client

    async def test_all_climate_profiles_display_request_without_self_confirmation(self):
        """Heat, cool, Naviclim, Tywell and TRV targets share one behaviour."""
        profiles = [
            ("boiler", {"hvacMode": "NORMAL", "setpoint": 21}, False, "setpoint"),
            (
                "boiler",
                {"authorization": "COOLING", "coolSetpoint": 21},
                False,
                "coolSetpoint",
            ),
            ("naviclim", {"hvacMode": "COOLING", "setpoint": 21}, False, "setpoint"),
            (
                "re2020Controller",
                {"authorization": "HEATING", "localMode": "NORMAL", "setpoint": 21},
                True,
                "setpoint",
            ),
            ("sh_hvac", {"currentSetpoint": 21}, True, "currentSetpoint"),
        ]
        for device_type, data, area, register in profiles:
            with self.subTest(device_type=device_type, data=data):
                entity, _ = self.climate(data=data, device_type=device_type, area=area)
                await entity.async_set_temperature(temperature=22)
                self.assertEqual(entity.target_temperature, 22)
                self.assertEqual(entity.reported_target_temperature, 21)
                self.assertEqual(
                    entity.extra_state_attributes["reported_temperature"], 21
                )
                self.assertTrue(entity.extra_state_attributes["command_pending"])
                # A stale/irrelevant push must neither reset the dial nor confirm it.
                entity._handle_climate_update()
                self.assertEqual(entity.target_temperature, 22)
                self.assertTrue(entity.extra_state_attributes["command_pending"])
                setattr(entity._device, register, 22)
                entity._handle_climate_update()
                self.assertEqual(entity.target_temperature, 22)
                self.assertFalse(entity.extra_state_attributes["command_pending"])
                self.assertEqual(
                    entity.extra_state_attributes["command_status"], "confirmed"
                )

    async def test_expiry_returns_to_latest_report_without_resending(self):
        """An unconfirmed target expires even while another command is pending."""
        entity, client = self.climate()
        await entity.async_set_temperature(temperature=22)
        entity._device.setpoint = 20
        tracker = entity._get_command_tracker()
        tracker.begin("hvac_mode", HVACMode.OFF)
        command = tracker._pending["temperature"]
        command.timeout.cancel()
        tracker._mark_unconfirmed("temperature", command)
        self.assertTrue(tracker.pending)
        self.assertEqual(entity.target_temperature, 20)
        client.put_devices_data.assert_awaited_once()
        # Late matching physical feedback is still a real confirmation.
        entity._device.setpoint = 22
        entity._handle_climate_update()
        self.assertNotIn("requested_temperature", tracker.attributes)

    async def test_failed_send_returns_to_reported_target(self):
        """A transport failure immediately removes the requested display value."""
        entity, client = self.climate()
        client.put_devices_data.side_effect = RuntimeError("send failed")
        with self.assertRaisesRegex(RuntimeError, "send failed"):
            await entity.async_set_temperature(temperature=22)
        self.assertEqual(entity.target_temperature, 21)
        self.assertEqual(entity.extra_state_attributes["command_status"], "failed")
        self.assertFalse(entity.extra_state_attributes["command_pending"])

    async def test_newest_request_survives_old_feedback_and_old_failure(self):
        """Rapid clicks keep the latest target until its own matching feedback."""
        entity, client = self.climate()
        await entity.async_set_temperature(temperature=22)
        tracker = entity._get_command_tracker()
        old = tracker._pending["temperature"]
        await entity.async_set_temperature(temperature=23)
        entity._device.setpoint = 22
        entity._handle_climate_update()
        tracker.fail("temperature", old)
        self.assertEqual(entity.target_temperature, 23)
        self.assertTrue(tracker.pending)
        entity._device.setpoint = 23
        entity._handle_climate_update()
        self.assertFalse(tracker.pending)
        self.assertEqual(client.put_devices_data.await_count, 2)

    async def test_general_lock_overrides_pending_target_and_restores_capabilities(
        self,
    ):
        """A general Off/Away takes priority over the optimistic temperature dial."""
        entity, client = self.climate()
        home = types.SimpleNamespace(mode="HEATING", lock_reason=None)
        client.general_climate = home
        await entity.async_set_temperature(temperature=22)
        self.assertEqual(entity.target_temperature, 22)
        self.assertTrue(
            entity.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE
        )
        home.mode = "STOP"
        home.lock_reason = "off"
        entity._handle_climate_update()
        self.assertEqual(entity.hvac_mode, HVACMode.OFF)
        self.assertEqual(entity.hvac_action, entities_module.HVACAction.OFF)
        self.assertEqual(entity.hvac_modes, [HVACMode.OFF])
        self.assertIsNone(entity.target_temperature)
        self.assertFalse(
            entity.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE
        )
        home.mode = "HEATING"
        home.lock_reason = "absence"
        self.assertEqual(entity.preset_mode, entities_module.PRESET_AWAY)
        self.assertEqual(entity.target_temperature, 21)
        with (
            patch.dict(sys.modules, {"homeassistant.exceptions": _ha_exceptions}),
            self.assertRaises(_HomeAssistantError) as error,
        ):
            await entity.async_set_temperature(temperature=23)
        self.assertEqual(error.exception.translation_key, "general_hvac_absence")
        client.put_devices_data.assert_awaited_once()
        home.lock_reason = None
        self.assertTrue(
            entity.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE
        )
        self.assertEqual(entity.target_temperature, 22)

    async def test_hvac_action_uses_reported_target(self):
        """An optimistic dial must not pretend heat/cool delivery has changed."""
        for mode, requested in [("HEATING", 18), ("COOLING", 24)]:
            with self.subTest(mode=mode):
                entity, _ = self.climate(
                    data={
                        "authorization": mode,
                        "setpoint": 21,
                        "temperature": 20,
                    }
                )
                action = entity.hvac_action
                await entity.async_set_temperature(temperature=requested)
                self.assertEqual(entity.target_temperature, requested)
                self.assertEqual(entity.hvac_action, action)


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


class TywellAreaModeTests(IsolatedAsyncioTestCase):
    """Match the zone-level STOP/NORMAL sequence captured from the official app."""

    @staticmethod
    def _zone(*, local_mode="NORMAL", authorization="HEATING"):
        entity, client = _thermostat(
            device_type="re2020ControlBoiler",
            metadata={
                "authorization": {"enum_values": ["STOP", "HEATING", "COOLING"]},
                "heatSetpoint": {"permission": "r", "min": 10, "max": 30},
            },
            data={
                "area_id": "7",
                "authorization": authorization,
                "localMode": local_mode,
                "thermicLevel": "ANTI_FROST" if local_mode == "STOP" else None,
                "heatSetpoint": None if local_mode == "STOP" else 23.5,
            },
        )
        client.put_area_data = AsyncMock()
        return entity, client

    async def test_off_heat_commands_use_the_area_local_mode(self) -> None:
        """Zone switching does not write the endpoint or seasonal authorization."""
        entity, client = self._zone()
        self.addCleanup(entity._get_command_tracker().close)
        await entity.async_set_hvac_mode(HVACMode.OFF)
        await entity.async_set_hvac_mode(HVACMode.HEAT)
        self.assertEqual(
            client.put_area_data.await_args_list,
            [
                call("7", "localMode", "STOP"),
                call("7", "localMode", "NORMAL"),
            ],
        )
        client.put_devices_data.assert_not_awaited()

    def test_zone_off_feedback_wins_over_heating_authorization(self) -> None:
        """A stopped zone is off while the installation's season stays heating."""
        entity, _ = self._zone(local_mode="STOP")
        self.assertFalse(entity._is_filpilote)
        self.assertEqual(entity.hvac_mode, HVACMode.OFF)
        self.assertEqual(entity.hvac_action, entities_module.HVACAction.OFF)
        self.assertEqual(entity.preset_mode, entities_module.PRESET_NONE)

    def test_zone_cooling_and_absence_are_preserved(self) -> None:
        """Local zone control retains cooling and the actual absence preset."""
        entity, _ = self._zone(authorization="COOLING")
        self.assertIn(HVACMode.COOL, entity.hvac_modes)
        self.assertEqual(entity.hvac_mode, HVACMode.COOL)
        entity._device.localMode = "ABSENCE"
        self.assertEqual(entity.preset_mode, entities_module.PRESET_AWAY)

    def test_off_has_no_active_target_and_normal_restores_it(self) -> None:
        """Do not present the gateway's frost-protection value as a heating target."""
        entity, _ = self._zone(local_mode="STOP")
        entity._device.heatSetpoint = 30.0
        entity._device.setpoint = 30.0
        self.assertIsNone(entity.target_temperature)
        entity._device.localMode = "NORMAL"
        entity._device.thermicLevel = None
        entity._device.heatSetpoint = 20.0
        entity._device.setpoint = 20.0
        self.assertEqual(entity.target_temperature, 20.0)

    def test_manual_target_uses_override_feedback(self) -> None:
        """A manual target must not bounce back to an unrelated scheduled value."""
        entity, _ = self._zone()
        entity._device.useMode = "MANUAL"
        entity._device.heatSetpoint = 30.0
        entity._device.overrideSetpoint = 22.5
        self.assertEqual(entity.target_temperature, 22.5)

    async def test_general_off_blocks_heat_without_changing_any_zone(self) -> None:
        """A local Heat request must not switch the whole installation on."""
        entity, client = self._zone(authorization="STOP")
        client.put_home_hvac_mode = AsyncMock()
        self.addCleanup(entity._get_command_tracker().close)
        self.assertEqual(entity.hvac_mode, HVACMode.OFF)
        with (
            patch.dict(sys.modules, {"homeassistant.exceptions": _ha_exceptions}),
            self.assertRaises(_HomeAssistantError) as error,
        ):
            await entity.async_set_hvac_mode(HVACMode.HEAT)
        self.assertEqual(error.exception.translation_key, "general_hvac_stopped")
        client.put_home_hvac_mode.assert_not_awaited()
        client.put_area_data.assert_not_awaited()
        client.put_devices_data.assert_not_awaited()
        self.assertFalse(entity.extra_state_attributes["command_pending"])

    async def test_clearing_absence_cannot_bypass_general_off(self) -> None:
        """Changing a zone preset must also respect the general Off lock."""
        entity, client = self._zone(local_mode="ABSENCE", authorization="STOP")
        client.put_home_hvac_mode = AsyncMock()
        self.addCleanup(entity._get_command_tracker().close)
        with (
            patch.dict(sys.modules, {"homeassistant.exceptions": _ha_exceptions}),
            self.assertRaises(_HomeAssistantError),
        ):
            await entity.async_set_preset_mode(entities_module.PRESET_NONE)
        client.put_home_hvac_mode.assert_not_awaited()
        client.put_area_data.assert_not_awaited()

    def test_frost_level_keeps_zone_enabled_without_exposing_30c_target(self) -> None:
        """An enabled zone can hold frost protection without a valid heat target."""
        entity, _ = self._zone()
        entity._device.thermicLevel = "ANTI_FROST"
        entity._device.heatSetpoint = 30
        entity._device.setpoint = 30
        self.assertEqual(entity.hvac_mode, HVACMode.HEAT)
        self.assertEqual(entity.hvac_action, entities_module.HVACAction.IDLE)
        self.assertIsNone(entity.target_temperature)
        entity._device.thermicLevel = None
        entity._device.heatSetpoint = 18.5
        self.assertEqual(entity.hvac_mode, HVACMode.HEAT)
        self.assertEqual(entity.target_temperature, 18.5)

    async def test_general_off_rejects_setpoint_before_sending(self) -> None:
        """The disabled app control must not be bypassed by HA set_temperature."""
        entity, client = self._zone(authorization="STOP")
        self.addCleanup(entity._get_command_tracker().close)
        with (
            patch.dict(sys.modules, {"homeassistant.exceptions": _ha_exceptions}),
            self.assertRaises(_HomeAssistantError),
        ):
            await entity.async_set_temperature(temperature=22)
        self.assertFalse(entity.extra_state_attributes["command_pending"])
        client.put_area_data.assert_not_awaited()
        client.put_devices_data.assert_not_awaited()

    async def test_pending_off_clears_on_local_mode_feedback(self) -> None:
        """STOP feedback confirms Off even if authorization remains HEATING."""
        entity, _ = self._zone()
        entity.async_write_ha_state = MagicMock()
        self.addCleanup(entity._get_command_tracker().close)
        await entity.async_set_hvac_mode(HVACMode.OFF)
        self.assertTrue(entity.extra_state_attributes["command_pending"])
        entity._device.localMode = "STOP"
        entity._handle_climate_update()
        self.assertFalse(entity.extra_state_attributes["command_pending"])


class LocalModeZoneTests(IsolatedAsyncioTestCase):
    """X3D heating zones that carry their state in `localMode`.

    Metadata captured from a TYDOM HOME gateway.  `authorization` is read-only
    and `comfortMode` write-only, both limited to the installation-wide season
    [STOP, HEATING]; the zone's own order lives in the read/write `localMode`
    register. Schedule-driven zones use ANTI_FROST for Off; profiles with a
    writable generic setpoint use STOP when their metadata advertises it.
    """

    @staticmethod
    def _zone(*, local_mode="ANTI_FROST", generic_setpoint=False):
        metadata = {
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
                "enum_values": ["STOP", "ANTI_FROST"],
            },
            "localMode": {
                "type": "string",
                "permission": "rw",
                "enum_values": ["NORMAL", "STOP", "ANTI_FROST", "ABSENCE"],
            },
            "heatSetpoint": {
                "type": "numeric",
                "permission": "rw",
                "min": 1.0,
                "max": 50.0,
            },
        }
        if generic_setpoint:
            metadata["setpoint"] = {
                "type": "numeric",
                "permission": "rw",
                "min": 10,
                "max": 30,
            }
        return _thermostat(
            metadata=metadata,
            data={
                "authorization": "HEATING",
                "thermicLevel": "ANTI_FROST" if local_mode == "ANTI_FROST" else None,
                "localMode": local_mode,
                "heatSetpoint": None,
                "ambientTemperature": 22.41,
            },
        )

    @staticmethod
    def _calybox_230(*, local_mode="NORMAL", thermic_level="AUTO"):
        """Create the mixed localMode/thermicLevel profile from issue #543."""
        return _thermostat(
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
                    "enum_values": ["ECO", "COMFORT", "STOP", "ANTI_FROST", "AUTO"],
                },
                "localMode": {
                    "type": "string",
                    "permission": "rw",
                    "enum_values": ["NORMAL", "STOP", "ANTI_FROST", "ABSENCE"],
                },
            },
            data={
                "authorization": "HEATING",
                "thermicLevel": thermic_level,
                "localMode": local_mode,
            },
        )

    def test_detected_and_offers_only_off_and_heat(self) -> None:
        """A localMode zone is not pilot-wire and has no AUTO mode."""
        entity, _client = self._zone()

        self.assertTrue(entity._uses_local_mode)
        self.assertFalse(entity._is_filpilote)
        self.assertEqual(entity._attr_hvac_modes, [HVACMode.OFF, HVACMode.HEAT])

    def test_area_device_keeps_its_area_derived_modes(self) -> None:
        """`localMode` is not unique to these zones.

        Area attributes use the same register name with LOCAL_SETPOINT for
        temporary overrides.  An area-derived entity builds its mode list from
        area_hvac_modes(), which can include COOL, so this branch must not
        reduce it to [off, heat].
        """
        entity, _client = self._zone()
        setattr(entity._device, "area_id", 1234)
        rebuilt = HaClimate(entity._device, hass=MagicMock())

        self.assertFalse(rebuilt._uses_local_mode)

    def test_register_without_anti_frost_is_not_treated_as_a_heating_zone(
        self,
    ) -> None:
        """Requires the heating-zone shape, not merely the word NORMAL."""
        entity, _client = _thermostat(
            metadata={
                "localMode": {
                    "type": "string",
                    "permission": "rw",
                    "enum_values": ["NORMAL", "LOCAL_SETPOINT"],
                },
                "setpoint": {
                    "type": "numeric",
                    "permission": "rw",
                    "min": 10,
                    "max": 30,
                },
            },
            data={"localMode": "NORMAL", "setpoint": 20.0},
        )

        self.assertFalse(entity._uses_local_mode)

    def test_reversible_zone_keeps_cooling_and_the_away_preset(self) -> None:
        """A cool+heat zone must not be collapsed to [off, heat].

        Frost protection is a preset on reversible zones, not an off state
        (#453 / #455).  Were this branch to claim them it would drop cooling.
        """
        entity, _client = _thermostat(
            metadata={
                "authorization": {
                    "type": "string",
                    "permission": "r",
                    "enum_values": ["STOP", "HEATING", "COOLING"],
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
                "localMode": {
                    "type": "string",
                    "permission": "rw",
                    "enum_values": ["NORMAL", "STOP", "ANTI_FROST", "ABSENCE"],
                },
                "setpoint": {
                    "type": "numeric",
                    "permission": "rw",
                    "min": 10,
                    "max": 30,
                },
            },
            data={
                "authorization": "COOLING",
                "thermicLevel": "ANTI_FROST",
                "localMode": "ANTI_FROST",
                "setpoint": None,
            },
        )

        self.assertFalse(entity._uses_local_mode)
        self.assertIn(HVACMode.COOL, entity._attr_hvac_modes)
        self.assertEqual(entity.preset_mode, entities_module.PRESET_AWAY)

    def test_zone_without_setpoint_metadata_is_not_pilot_wire(self) -> None:
        """A localMode zone must never also take the fil-pilote path.

        Without setpoint metadata or a live setpoint such a zone satisfies the
        pilot-wire test too, and most properties check _is_filpilote first —
        they would read and write thermicLevel, bypassing localMode entirely.
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
                    "enum_values": ["STOP", "ANTI_FROST"],
                },
                "localMode": {
                    "type": "string",
                    "permission": "rw",
                    "enum_values": ["NORMAL", "STOP", "ANTI_FROST", "ABSENCE"],
                },
            },
            data={
                "authorization": "HEATING",
                "thermicLevel": "ANTI_FROST",
                "localMode": "ANTI_FROST",
                "ambientTemperature": 22.41,
            },
        )

        self.assertTrue(entity._uses_local_mode)
        self.assertFalse(entity._is_filpilote)
        self.assertEqual(entity._attr_hvac_modes, [HVACMode.OFF, HVACMode.HEAT])
        self.assertEqual(
            entity._attr_preset_modes,
            [entities_module.PRESET_NONE, entities_module.PRESET_AWAY],
        )
        self.assertEqual(entity.hvac_mode, HVACMode.OFF)
        self.assertEqual(entity.hvac_action, entities_module.HVACAction.OFF)
        self.assertEqual(entity.preset_mode, entities_module.PRESET_NONE)

    async def test_zone_without_setpoint_metadata_writes_local_mode(self) -> None:
        """The same zone must drive localMode, not the pilot-wire register."""
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
                    "enum_values": ["STOP", "ANTI_FROST"],
                },
                "localMode": {
                    "type": "string",
                    "permission": "rw",
                    "enum_values": ["NORMAL", "STOP", "ANTI_FROST", "ABSENCE"],
                },
            },
            data={
                "authorization": "HEATING",
                "thermicLevel": "ANTI_FROST",
                "localMode": "ANTI_FROST",
            },
        )

        await entity.async_set_hvac_mode(HVACMode.HEAT)

        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "localMode", "NORMAL"
        )

    def test_write_only_local_mode_is_not_used(self) -> None:
        """The register is read to report state, so write-only will not do."""
        entity, _client = _thermostat(
            metadata={
                "localMode": {
                    "type": "string",
                    "permission": "w",
                    "enum_values": ["NORMAL", "STOP", "ANTI_FROST", "ABSENCE"],
                },
                "heatSetpoint": {
                    "type": "numeric",
                    "permission": "rw",
                    "min": 1.0,
                    "max": 50.0,
                },
            },
            data={"localMode": "ANTI_FROST", "heatSetpoint": None},
        )

        self.assertFalse(entity._uses_local_mode)

    def test_anti_frost_reads_as_off(self) -> None:
        """Frost protection is what the app calls off."""
        entity, _client = self._zone(local_mode="ANTI_FROST")

        self.assertEqual(entity.hvac_mode, HVACMode.OFF)
        self.assertEqual(entity.hvac_action, entities_module.HVACAction.OFF)

    def test_stop_reads_as_off(self) -> None:
        """A fully stopped zone is off too."""
        entity, _client = self._zone(local_mode="STOP")

        self.assertEqual(entity.hvac_mode, HVACMode.OFF)
        self.assertEqual(entity.hvac_action, entities_module.HVACAction.OFF)

    def test_normal_reads_as_heat(self) -> None:
        """A running zone reads as heat even though no setpoint is readable."""
        entity, _client = self._zone(local_mode="NORMAL")

        self.assertEqual(entity.hvac_mode, HVACMode.HEAT)

    async def test_unlinked_zone_cannot_bypass_general_off(self) -> None:
        """General Off also locks an endpoint-controlled zone."""
        entity, client = self._zone(local_mode="NORMAL")
        entity._device.authorization = "STOP"
        client.put_home_hvac_mode = AsyncMock()
        self.addCleanup(entity._get_command_tracker().close)
        with (
            patch.dict(sys.modules, {"homeassistant.exceptions": _ha_exceptions}),
            self.assertRaises(_HomeAssistantError),
        ):
            await entity.async_set_hvac_mode(HVACMode.HEAT)
        client.put_home_hvac_mode.assert_not_awaited()
        client.put_devices_data.assert_not_awaited()

    def test_stopped_season_keeps_a_normal_zone_off(self) -> None:
        """A local NORMAL order cannot override the installation's seasonal Stop."""
        entity, _ = self._zone(local_mode="NORMAL")
        entity._device.authorization = "STOP"
        self.assertEqual(entity.hvac_mode, HVACMode.OFF)

    def test_season_register_does_not_decide_the_mode(self) -> None:
        """The season register stays HEATING while the zone is off; it must not win."""
        entity, _client = self._zone(local_mode="ANTI_FROST")

        self.assertEqual(getattr(entity._device, "authorization"), "HEATING")
        self.assertEqual(entity.hvac_mode, HVACMode.OFF)

    def test_presets_are_the_ones_the_zone_actually_has(self) -> None:
        """The hardcoded NORMAL/ECO/COMFORT fallback is not implemented here."""
        entity, _client = self._zone()

        self.assertEqual(
            entity._attr_preset_modes,
            [entities_module.PRESET_NONE, entities_module.PRESET_AWAY],
        )

    def test_absence_reads_as_away(self) -> None:
        """ABSENCE is the zone's away order."""
        entity, _client = self._zone(local_mode="ABSENCE")

        self.assertEqual(entity.preset_mode, entities_module.PRESET_AWAY)
        self.assertEqual(entity.hvac_mode, HVACMode.HEAT)

    def test_running_zone_has_no_preset(self) -> None:
        """A NORMAL zone reports none rather than a phantom preset."""
        entity, _client = self._zone(local_mode="NORMAL")

        self.assertEqual(entity.preset_mode, entities_module.PRESET_NONE)

    def test_calybox_230_keeps_local_mode_and_exposes_real_thermic_presets(
        self,
    ) -> None:
        """Issue #543 exposes real Eco/Comfort levels alongside localMode."""
        entity, _client = self._calybox_230()

        self.assertTrue(entity._uses_local_mode)
        self.assertFalse(entity._is_filpilote)
        self.assertEqual(entity._attr_hvac_modes, [HVACMode.OFF, HVACMode.HEAT])
        self.assertEqual(
            entity.preset_modes,
            [
                entities_module.PRESET_ECO,
                entities_module.PRESET_COMFORT,
                entities_module.PRESET_NONE,
                entities_module.PRESET_AWAY,
            ],
        )
        self.assertEqual(entity.preset_mode, entities_module.PRESET_NONE)

        entity._device.thermicLevel = "ECO"
        self.assertEqual(entity.preset_mode, entities_module.PRESET_ECO)
        entity._device.thermicLevel = "COMFORT"
        self.assertEqual(entity.preset_mode, entities_module.PRESET_COMFORT)
        entity._device.localMode = "ABSENCE"
        entity._device.thermicLevel = "ANTI_FROST"
        self.assertEqual(entity.preset_mode, entities_module.PRESET_AWAY)

    def test_local_mode_without_auto_keeps_its_existing_preset_profile(self) -> None:
        """Do not infer the Calybox mixed profile from Eco/Comfort alone."""
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
                "localMode": {
                    "type": "string",
                    "permission": "rw",
                    "enum_values": ["NORMAL", "STOP", "ANTI_FROST", "ABSENCE"],
                },
            },
            data={
                "authorization": "HEATING",
                "thermicLevel": "ECO",
                "localMode": "NORMAL",
            },
        )

        self.assertTrue(entity._uses_local_mode)
        self.assertFalse(entity._uses_local_mode_thermic_presets)
        self.assertEqual(
            entity._attr_preset_modes,
            [entities_module.PRESET_NONE, entities_module.PRESET_AWAY],
        )

    def test_area_local_mode_does_not_take_calybox_thermic_presets(self) -> None:
        """An area climate keeps its own presets despite matching registers."""
        original, _client = self._calybox_230()
        entity, _client = _thermostat(
            metadata=original._device._metadata,
            data={
                "area_id": "7",
                "authorization": "HEATING",
                "localMode": "NORMAL",
                "thermicLevel": "AUTO",
            },
            device_type="re2020Controller",
        )

        self.assertTrue(entity._is_area_controlled)
        self.assertFalse(entity._uses_local_mode_thermic_presets)

    async def test_away_writes_absence(self) -> None:
        """Selecting away drives localMode ABSENCE."""
        entity, client = self._zone(local_mode="NORMAL")

        await entity.async_set_preset_mode(entities_module.PRESET_AWAY)

        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "localMode", "ABSENCE"
        )

    async def test_calybox_eco_and_comfort_write_thermic_level(self) -> None:
        """Eco and Comfort use the advertised register, not localMode."""
        entity, client = self._calybox_230()

        await entity.async_set_preset_mode(entities_module.PRESET_ECO)
        await entity.async_set_preset_mode(entities_module.PRESET_COMFORT)
        await entity.async_set_preset_mode(entities_module.PRESET_AWAY)

        client.put_devices_data.assert_has_awaits(
            [
                call("20", "10", "thermicLevel", "ECO"),
                call("20", "10", "thermicLevel", "COMFORT"),
                call("20", "10", "localMode", "ABSENCE"),
            ]
        )

    async def test_calybox_none_returns_to_auto(self) -> None:
        """None is the advertised Auto level, including when leaving Away."""
        entity, client = self._calybox_230(
            local_mode="ABSENCE", thermic_level="ANTI_FROST"
        )

        await entity.async_set_preset_mode(entities_module.PRESET_NONE)

        client.put_devices_data.assert_has_awaits(
            [
                call("20", "10", "thermicLevel", "AUTO"),
                call("20", "10", "localMode", "NORMAL"),
            ]
        )

    async def test_clearing_the_preset_does_not_switch_an_off_zone_on(self) -> None:
        """Clearing a preset on an off zone must leave it off.

        ANTI_FROST and STOP both read as off, so writing NORMAL there would
        turn heating on as a side effect of clearing a preset.
        """
        for off_mode in ("ANTI_FROST", "STOP"):
            with self.subTest(local_mode=off_mode):
                entity, client = self._zone(local_mode=off_mode)

                await entity.async_set_preset_mode(entities_module.PRESET_NONE)

                client.put_devices_data.assert_not_awaited()
                self.assertEqual(entity.hvac_mode, HVACMode.OFF)

    async def test_clearing_the_preset_on_a_running_zone_writes_nothing(self) -> None:
        """A NORMAL zone has no preset to clear, so there is nothing to write."""
        entity, client = self._zone(local_mode="NORMAL")

        await entity.async_set_preset_mode(entities_module.PRESET_NONE)

        client.put_devices_data.assert_not_awaited()

    async def test_preset_none_returns_the_zone_to_normal(self) -> None:
        """Clearing the preset lifts ABSENCE rather than doing nothing."""
        entity, client = self._zone(local_mode="ABSENCE")

        await entity.async_set_preset_mode(entities_module.PRESET_NONE)

        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "localMode", "NORMAL"
        )

    async def test_turning_off_writes_anti_frost_to_local_mode(self) -> None:
        """Schedule-driven zones mirror the app's ANTI_FROST off order."""
        entity, client = self._zone(local_mode="NORMAL")

        await entity.async_set_hvac_mode(HVACMode.OFF)

        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "localMode", "ANTI_FROST"
        )

    async def test_turning_off_setpoint_thermostat_writes_stop_to_local_mode(
        self,
    ) -> None:
        """A writable generic setpoint profile uses STOP for OFF."""
        entity, client = self._zone(local_mode="NORMAL", generic_setpoint=True)

        await entity.async_set_hvac_mode(HVACMode.OFF)

        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "localMode", "STOP"
        )

    async def test_turning_on_writes_normal_to_local_mode(self) -> None:
        """Heat restores the NORMAL order."""
        entity, client = self._zone(local_mode="ANTI_FROST")

        await entity.async_set_hvac_mode(HVACMode.HEAT)

        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "localMode", "NORMAL"
        )

    async def test_local_mode_commands_are_tracked_until_device_feedback(self) -> None:
        """Mode and preset writes wait for matching localMode feedback."""
        entity, client = self._zone(local_mode="ANTI_FROST")
        entity.async_write_ha_state = MagicMock()
        self.addCleanup(entity._get_command_tracker().close)

        await entity.async_set_hvac_mode(HVACMode.HEAT)
        self.assertTrue(entity.extra_state_attributes["command_pending"])
        entity._device.localMode = "NORMAL"
        entity._handle_climate_update()
        # The zone enable request is confirmed by NORMAL; a separate frost
        # switch can still hold the action Idle without keeping Heat pending.
        self.assertFalse(entity.extra_state_attributes["command_pending"])
        self.assertEqual(entity.hvac_action, entities_module.HVACAction.IDLE)
        entity._device.thermicLevel = None
        entity._handle_climate_update()
        self.assertFalse(entity.extra_state_attributes["command_pending"])

        await entity.async_set_preset_mode(entities_module.PRESET_AWAY)
        self.assertTrue(entity.extra_state_attributes["command_pending"])
        entity._device.localMode = "ABSENCE"
        entity._handle_climate_update()
        self.assertFalse(entity.extra_state_attributes["command_pending"])

        await entity.async_set_preset_mode(entities_module.PRESET_NONE)
        self.assertTrue(entity.extra_state_attributes["command_pending"])
        entity._device.localMode = "NORMAL"
        entity._handle_climate_update()
        self.assertFalse(entity.extra_state_attributes["command_pending"])

        await entity.async_set_hvac_mode(HVACMode.OFF)
        self.assertTrue(entity.extra_state_attributes["command_pending"])
        entity._device.localMode = "ANTI_FROST"
        entity._handle_climate_update()
        self.assertFalse(entity.extra_state_attributes["command_pending"])

        client.put_devices_data.assert_has_awaits(
            [
                call("20", "10", "localMode", "NORMAL"),
                call("20", "10", "localMode", "ABSENCE"),
                call("20", "10", "localMode", "NORMAL"),
                call("20", "10", "localMode", "ANTI_FROST"),
            ]
        )


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


class FrostResumeTests(IsolatedAsyncioTestCase):
    """Reproduce general Heating with local NORMAL but effective frost protection."""

    def zone(self, *, area=False):
        """Use the writable setpoint/local-mode capabilities captured on Site 2."""
        entity, client = _thermostat(
            device_type="re2020Controller" if area else "boiler",
            metadata={
                "authorization": {
                    "permission": "r",
                    "enum_values": ["STOP", "HEATING", "COOLING"],
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
                "localMode": {
                    "permission": "rw",
                    "enum_values": ["NORMAL", "STOP", "ANTI_FROST", "ABSENCE"],
                },
                "thermicLevel": {
                    "permission": "rw",
                    "enum_values": ["STOP", "ANTI_FROST"],
                },
            },
            data={
                "authorization": "HEATING",
                "localMode": "NORMAL",
                "thermicLevel": None,
                "heatSetpoint": 19.5,
                "setpoint": 19.5,
                "useMode": "SCHED",
            },
        )
        if area:
            entity._device.area_id = "7"
        client.put_area_data = AsyncMock()
        client.put_home_hvac_mode = AsyncMock()
        entity.async_write_ha_state = Mock()
        self.addCleanup(entity._get_command_tracker().close)
        return entity, client

    @staticmethod
    def freeze(entity):
        """Match the real post-general-stop feedback, including the false 30 target."""
        entity._device.thermicLevel = "ANTI_FROST"
        entity._device.localMode = "NORMAL"
        entity._device.heatSetpoint = 30
        entity._device.setpoint = 30
        entity._handle_climate_update()

    async def test_heat_resumes_confirmed_target_on_endpoint_and_area(self):
        """NORMAL alone cannot release this state; request the last real target."""
        for area in (False, True):
            with self.subTest(area=area):
                entity, client = self.zone(area=area)
                entity._handle_climate_update()
                self.freeze(entity)
                self.assertIsNone(entity.reported_target_temperature)
                await entity.async_set_hvac_mode(HVACMode.HEAT)
                if area:
                    client.put_area_data.assert_awaited_once_with(
                        "7", "setpoint", "19.5"
                    )
                    client.put_devices_data.assert_not_awaited()
                else:
                    client.put_devices_data.assert_awaited_once_with(
                        "20", "10", "heatSetpoint", "19.5"
                    )
                    client.put_area_data.assert_not_awaited()
                client.put_home_hvac_mode.assert_not_awaited()
                self.assertEqual(entity.target_temperature, 19.5)
                self.assertEqual(entity.hvac_mode, HVACMode.HEAT)
                self.assertTrue(entity.extra_state_attributes["command_pending"])
                # Heat is already enabled: only actual target feedback can
                # confirm resumption, not another unchanged NORMAL/frost push.
                entity._handle_climate_update()
                self.assertTrue(entity.extra_state_attributes["command_pending"])
                self.assertIsNone(entity.reported_target_temperature)
                self.assertEqual(entity.hvac_action, entities_module.HVACAction.IDLE)
                entity._device.thermicLevel = None
                entity._device.heatSetpoint = 19.5
                entity._device.setpoint = 19.5
                entity._handle_climate_update()
                self.assertEqual(entity.hvac_mode, HVACMode.HEAT)
                self.assertFalse(entity.extra_state_attributes["command_pending"])

    async def test_pending_target_is_never_used_as_a_confirmed_resume_target(self):
        """A requested but unconfirmed temperature cannot replace the real target."""
        entity, client = self.zone()
        entity._handle_climate_update()
        await entity.async_set_temperature(temperature=24)
        entity._handle_climate_update()
        client.put_devices_data.reset_mock()
        self.freeze(entity)
        await entity.async_set_hvac_mode(HVACMode.HEAT)
        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "heatSetpoint", "19.5"
        )

    async def test_no_known_target_raises_without_inventing_one(self):
        """A startup in frost requires an explicit target, never a default value."""
        entity, client = self.zone()
        self.freeze(entity)
        with self.assertRaises(_HomeAssistantError) as caught:
            await entity.async_set_hvac_mode(HVACMode.HEAT)
        self.assertEqual(caught.exception.translation_key, "resume_target_unknown")
        client.put_devices_data.assert_not_awaited()
        client.put_area_data.assert_not_awaited()
        self.assertFalse(entity.extra_state_attributes["command_pending"])
        # The standard HA action can release the zone even without a dial target.
        await entity.async_set_temperature(temperature=21)
        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "heatSetpoint", "21"
        )

    async def test_cooling_target_is_not_reused_for_heating(self):
        """A reversible controller must not substitute its cooling setpoint."""
        entity, client = self.zone()
        entity._last_confirmed_targets[HVACMode.COOL] = 25
        self.freeze(entity)
        with self.assertRaises(_HomeAssistantError):
            await entity.async_set_hvac_mode(HVACMode.HEAT)
        client.put_devices_data.assert_not_awaited()

    async def test_failed_resume_does_not_claim_heat_or_confirm_temperature(self):
        """A failed write leaves frost protection active and clears pending display."""
        entity, client = self.zone()
        entity._handle_climate_update()
        self.freeze(entity)
        client.put_devices_data.side_effect = RuntimeError("send failed")
        with self.assertRaisesRegex(RuntimeError, "send failed"):
            await entity.async_set_hvac_mode(HVACMode.HEAT)
        self.assertEqual(entity.hvac_mode, HVACMode.HEAT)
        self.assertIsNone(entity.target_temperature)
        self.assertFalse(entity.extra_state_attributes["command_pending"])

    async def test_general_off_still_blocks_resume(self):
        """Remembering a target never authorises restarting general heating."""
        entity, client = self.zone()
        entity._handle_climate_update()
        self.freeze(entity)
        client.general_climate = types.SimpleNamespace(mode="STOP", lock_reason="off")
        with (
            patch.dict(sys.modules, {"homeassistant.exceptions": _ha_exceptions}),
            self.assertRaises(_HomeAssistantError),
        ):
            await entity.async_set_hvac_mode(HVACMode.HEAT)
        client.put_devices_data.assert_not_awaited()
        client.put_home_hvac_mode.assert_not_awaited()

    async def test_normal_local_off_heat_keeps_its_original_command(self):
        """A locally stopped zone still resumes through NORMAL without extra writes."""
        entity, client = self.zone()
        entity._handle_climate_update()
        entity._device.localMode = "STOP"
        entity._device.thermicLevel = "STOP"
        await entity.async_set_hvac_mode(HVACMode.HEAT)
        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "localMode", "NORMAL"
        )

    async def test_outdated_target_is_revalidated_against_current_limits(self):
        """A confirmed target outside new device limits must not be resent."""
        entity, client = self.zone()
        entity._handle_climate_update()
        self.freeze(entity)
        entity._device.maxHeatSetpoint = 18
        with (
            patch.dict(sys.modules, {"homeassistant.exceptions": _ha_exceptions}),
            self.assertRaises(_HomeAssistantError),
        ):
            await entity.async_set_hvac_mode(HVACMode.HEAT)
        client.put_devices_data.assert_not_awaited()
        self.assertFalse(entity.extra_state_attributes["command_pending"])

    def test_away_and_frost_feedback_do_not_replace_confirmed_target(self):
        """Absence/frost temperatures are not user heating targets."""
        entity, _ = self.zone()
        entity._handle_climate_update()
        entity._device.localMode = "ABSENCE"
        entity._device.heatSetpoint = 10
        entity._handle_climate_update()
        self.assertEqual(entity._last_confirmed_targets[HVACMode.HEAT], 19.5)
        self.freeze(entity)
        self.assertEqual(entity._last_confirmed_targets[HVACMode.HEAT], 19.5)


class FrostProtectionActionTests(IsolatedAsyncioTestCase):
    """Preserve the five hardware-derived frost-switch scenarios from PR #540."""

    def test_general_stop_still_wins_over_enabled_zone_frost_protection(self):
        """The general mode must not be inferred from the zone frost switch."""
        entity, client = self._zone(local_mode="NORMAL", thermic_level="ANTI_FROST")
        home = types.SimpleNamespace(mode="STOP", lock_reason="off")
        client.general_climate = home
        self.assertEqual(entity.hvac_mode, HVACMode.OFF)
        self.assertEqual(entity.hvac_action, entities_module.HVACAction.OFF)
        self.assertEqual(entity.hvac_modes, [HVACMode.OFF])
        home.mode = "HEATING"
        home.lock_reason = None
        self.assertEqual(entity.hvac_mode, HVACMode.HEAT)
        self.assertEqual(entity.hvac_action, entities_module.HVACAction.IDLE)
        self.assertIn(HVACMode.HEAT, entity.hvac_modes)

    @staticmethod
    def _zone(
        *,
        local_mode="ANTI_FROST",
        thermic_level="derived",
        setpoint=None,
        ambient=22.41,
    ):
        if thermic_level == "derived":
            thermic_level = "ANTI_FROST" if local_mode == "ANTI_FROST" else None
        return _thermostat(
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
                    "enum_values": ["STOP", "ANTI_FROST"],
                },
                "localMode": {
                    "type": "string",
                    "permission": "rw",
                    "enum_values": ["NORMAL", "STOP", "ANTI_FROST", "ABSENCE"],
                },
                "heatSetpoint": {
                    "type": "numeric",
                    "permission": "rw",
                    "min": 1.0,
                    "max": 50.0,
                },
            },
            data={
                "authorization": "HEATING",
                "thermicLevel": thermic_level,
                "localMode": local_mode,
                "heatSetpoint": setpoint,
                "setpoint": setpoint,
                "ambientTemperature": ambient,
            },
        )

    def test_frost_protection_switch_on_reports_idle_not_heating(self) -> None:
        """Frost protection withholds every setpoint; the zone is not heating.

        Captured on a running zone (localMode NORMAL, useMode SCHED) with the
        app's frost protection switch on: thermicLevel ANTI_FROST, heatSetpoint
        and setpoint null.  Without a target the setpoint comparison cannot run
        and the entity used to report HEATING for as long as the switch stayed
        on, while the mode is, correctly, still heat.
        """
        entity, _client = self._zone(
            local_mode="NORMAL", thermic_level="ANTI_FROST", ambient=19.8
        )

        self.assertIsNone(entity.target_temperature)
        self.assertEqual(entity.hvac_mode, HVACMode.HEAT)
        self.assertEqual(entity.hvac_action, entities_module.HVACAction.IDLE)

    def test_frost_protection_switch_off_compares_against_the_setpoint(self) -> None:
        """With the switch off the gateway reports a setpoint again.

        Captured immediately after switching it off: thermicLevel cleared,
        heatSetpoint and setpoint 19.0.  The comparison then separates idle
        from heating.
        """
        warm, _ = self._zone(
            local_mode="NORMAL", thermic_level=None, setpoint=19.0, ambient=19.8
        )
        cold, _ = self._zone(
            local_mode="NORMAL", thermic_level=None, setpoint=19.0, ambient=17.1
        )

        self.assertEqual(warm.hvac_action, entities_module.HVACAction.IDLE)
        self.assertEqual(cold.hvac_action, entities_module.HVACAction.HEATING)

    def test_frost_protection_in_manual_use_mode_reports_idle(self) -> None:
        """The same holds for a zone that was set manually.

        Captured with useMode MANUAL: thermicLevel and overrideThermicLevel both
        ANTI_FROST, every setpoint cleared.
        """
        entity, _client = self._zone(
            local_mode="NORMAL", thermic_level="ANTI_FROST", ambient=19.8
        )
        setattr(entity._device, "useMode", "MANUAL")
        setattr(entity._device, "overrideThermicLevel", "ANTI_FROST")

        self.assertEqual(entity.hvac_action, entities_module.HVACAction.IDLE)

    def test_frost_protection_switch_does_not_change_the_off_states(self) -> None:
        """Power off still reads off, whatever the frost switch says."""
        for local_mode in ("ANTI_FROST", "STOP"):
            with self.subTest(local_mode=local_mode):
                entity, _client = self._zone(
                    local_mode=local_mode, thermic_level="ANTI_FROST"
                )

                self.assertEqual(entity.hvac_mode, HVACMode.OFF)
                self.assertEqual(entity.hvac_action, entities_module.HVACAction.OFF)

    def test_absence_with_frost_protection_reports_idle(self) -> None:
        """ABSENCE keeps reporting its own setpoint; the action stays idle."""
        entity, _client = self._zone(
            local_mode="ABSENCE", thermic_level="ANTI_FROST", setpoint=8.0, ambient=19.8
        )

        self.assertEqual(entity.hvac_mode, HVACMode.HEAT)
        self.assertEqual(entity.hvac_action, entities_module.HVACAction.IDLE)


class CommandNotificationTests(IsolatedAsyncioTestCase):
    """Keep mode/preset tracking silent while rendering real target changes."""

    climate = RequestedClimateTargetTests.climate

    async def test_mode_request_does_not_republish_the_old_mode(self):
        """Issue #539: pending alone must not reset the dashboard mode selector."""
        entity, _ = self.climate()
        diagnostic = Mock()
        entity._command_listeners.add(diagnostic)
        await entity.async_set_hvac_mode(HVACMode.OFF)
        entity.async_write_ha_state.assert_not_called()
        diagnostic.assert_called_once()
        self.assertEqual(entity.hvac_mode, HVACMode.HEAT)
        self.assertTrue(entity.extra_state_attributes["command_pending"])
        entity._device.hvacMode = "STOP"
        entity._handle_climate_update()
        entity.async_write_ha_state.assert_called_once()
        self.assertEqual(entity.hvac_mode, HVACMode.OFF)
        self.assertFalse(entity.extra_state_attributes["command_pending"])

    async def test_preset_request_does_not_republish_the_old_preset(self):
        """Away requests use the diagnostic until real localMode feedback."""
        entity, _ = LocalModeZoneTests._zone(local_mode="NORMAL")
        entity.async_write_ha_state = Mock()
        entity._command_listening = True
        diagnostic = Mock()
        entity._get_command_tracker()
        entity._command_listeners.add(diagnostic)
        self.addCleanup(entity._get_command_tracker().close)
        await entity.async_set_preset_mode(entities_module.PRESET_AWAY)
        entity.async_write_ha_state.assert_not_called()
        diagnostic.assert_called_once()
        self.assertEqual(entity.preset_mode, entities_module.PRESET_NONE)
        entity._device.localMode = "ABSENCE"
        entity._handle_climate_update()
        entity.async_write_ha_state.assert_called_once()
        self.assertEqual(entity.preset_mode, entities_module.PRESET_AWAY)
        self.assertFalse(entity.extra_state_attributes["command_pending"])

    async def test_target_changes_still_publish_immediately(self):
        """Mode tracking cannot disable the requested target display from #553."""
        entity, _ = self.climate()
        await entity.async_set_temperature(temperature=22)
        entity.async_write_ha_state.assert_called_once()
        self.assertEqual(entity.target_temperature, 22)
        entity.async_write_ha_state.reset_mock()
        await entity.async_set_hvac_mode(HVACMode.OFF)
        entity.async_write_ha_state.assert_not_called()
        self.assertEqual(entity.target_temperature, 22)
        self.assertEqual(entity.reported_target_temperature, 21)

    async def test_mode_failure_and_cancellation_restore_actual_state(self):
        """A failed mode send restores the card once no other request is pending."""
        for failure in (RuntimeError("send failed"), asyncio.CancelledError()):
            with self.subTest(failure=type(failure).__name__):
                entity, client = self.climate()
                client.put_devices_data.side_effect = failure
                with self.assertRaises(type(failure)):
                    await entity.async_set_hvac_mode(HVACMode.OFF)
                entity.async_write_ha_state.assert_called_once()
                self.assertFalse(entity.extra_state_attributes["command_pending"])
                self.assertEqual(entity.hvac_mode, HVACMode.HEAT)

    async def test_old_mode_failure_cannot_republish_over_a_newer_request(self):
        """The guarded fail result from #541 prevents stale rollback callbacks."""
        entity, _ = self.climate()
        started, release = asyncio.Event(), asyncio.Event()

        async def fail_later():
            started.set()
            await release.wait()
            raise RuntimeError("old failure")

        old = asyncio.create_task(
            entity._async_track_command("hvac_mode", HVACMode.OFF, fail_later())
        )
        await started.wait()
        await entity.async_set_hvac_mode(HVACMode.HEAT)
        release.set()
        with self.assertRaisesRegex(RuntimeError, "old failure"):
            await old
        entity.async_write_ha_state.assert_not_called()
        self.assertEqual(
            entity.extra_state_attributes["requested_hvac_mode"], HVACMode.HEAT
        )
        self.assertTrue(entity.extra_state_attributes["command_pending"])

    async def test_failed_mode_does_not_reset_a_pending_target(self):
        """An unrelated failure must keep the newest requested temperature."""
        entity, client = self.climate()
        await entity.async_set_temperature(temperature=22)
        entity.async_write_ha_state.reset_mock()
        client.put_devices_data.side_effect = RuntimeError("mode failed")
        with self.assertRaisesRegex(RuntimeError, "mode failed"):
            await entity.async_set_hvac_mode(HVACMode.OFF)
        entity.async_write_ha_state.assert_not_called()
        self.assertEqual(entity.target_temperature, 22)
        self.assertTrue(entity.extra_state_attributes["command_pending"])

    async def test_failed_target_restores_the_dial_even_with_a_pending_mode(self):
        """Temperature failure is rendered independently from a slow mode request."""
        entity, client = self.climate()
        await entity.async_set_hvac_mode(HVACMode.OFF)
        entity.async_write_ha_state.reset_mock()
        client.put_devices_data.side_effect = RuntimeError("target failed")
        with self.assertRaisesRegex(RuntimeError, "target failed"):
            await entity.async_set_temperature(temperature=22)
        self.assertEqual(entity.async_write_ha_state.call_count, 2)
        self.assertEqual(entity.target_temperature, 21)
        self.assertTrue(entity.extra_state_attributes["command_pending"])

    async def test_mode_timeout_stays_on_diagnostic_and_target_timeout_resets_dial(
        self,
    ):
        """Expiration must neither resend nor reintroduce old mode-only writes."""
        entity, client = self.climate()
        await entity.async_set_hvac_mode(HVACMode.OFF)
        tracker = entity._get_command_tracker()
        command = tracker._pending["hvac_mode"]
        command.timeout.cancel()
        tracker._mark_unconfirmed("hvac_mode", command)
        entity.async_write_ha_state.assert_not_called()
        self.assertEqual(entity.extra_state_attributes["command_status"], "unconfirmed")
        await entity.async_set_temperature(temperature=22)
        sent_before_expiry = client.put_devices_data.await_count
        entity.async_write_ha_state.reset_mock()
        command = tracker._pending["temperature"]
        command.timeout.cancel()
        tracker._mark_unconfirmed("temperature", command)
        entity.async_write_ha_state.assert_called_once()
        self.assertEqual(entity.target_temperature, 21)
        self.assertEqual(client.put_devices_data.await_count, sent_before_expiry)


class Rf6600FilPiloteDetectionTests(TestCase):
    """Keep the RF6600FP capability signature separate from other climates."""

    def test_rf6600fp_local_mode_metadata_keeps_pilot_wire_presets(self) -> None:
        """RF6600FP keeps pilot-wire presets despite localMode metadata."""
        entity, _client = _rf6600fp()
        self.assertFalse(entity._uses_local_mode)
        self.assertTrue(entity._uses_comfort_mode_pilot_wire)
        self.assertTrue(entity._is_filpilote)
        self.assertEqual(
            entity.preset_modes,
            [
                entities_module.PRESET_COMFORT,
                entities_module.PRESET_ECO,
                entities_module.PRESET_AWAY,
                entities_module.PRESET_NONE,
            ],
        )

    def test_calybox_auto_capability_keeps_local_mode(self) -> None:
        """AUTO capability keeps this device on the localMode path."""
        for level in ("AUTO", "ECO", "COMFORT", "ANTI_FROST", "STOP", None):
            with self.subTest(level=level):
                original, _ = _rf6600fp(thermic_level=level)
                original._device._metadata["thermicLevel"]["enum_values"].append("AUTO")
                entity = HaClimate(original._device, MagicMock())
                self.assertTrue(entity._uses_local_mode)
                self.assertFalse(entity._uses_comfort_mode_pilot_wire)
                self.assertFalse(entity._is_filpilote)

    def test_setpoint_thermostats_keep_setpoint_profile(self) -> None:
        """Real target registers prevent RF6600 classification."""
        for register in ("setpoint", "heatSetpoint", "coolSetpoint"):
            for target in (None, 19.5):
                with self.subTest(register=register, target=target):
                    original, _ = _rf6600fp()
                    original._device._metadata[register] = {
                        "type": "numeric",
                        "permission": "rw",
                        "min": 10,
                        "max": 30,
                    }
                    setattr(original._device, register, target)
                    entity = HaClimate(original._device, MagicMock())
                    self.assertFalse(entity._uses_comfort_mode_pilot_wire)
                    self.assertFalse(entity._is_filpilote)
                    self.assertTrue(
                        entity.supported_features
                        & ClimateEntityFeature.TARGET_TEMPERATURE
                    )

    def test_tywell_area_profiles_are_not_reclassified(self) -> None:
        """Area-linked Tywell controllers retain their area profile."""
        for device_type in (
            "re2020Controller",
            "re2020ControlPassive",
            "re2020ControlBoiler",
        ):
            with self.subTest(device_type=device_type):
                original, _ = _rf6600fp()
                device = original._device
                entity, _ = _thermostat(
                    metadata=device._metadata,
                    data={
                        "area_id": "7",
                        "authorization": "HEATING",
                        "localMode": "NORMAL",
                        "useMode": "SCHED",
                        "setpoint": None,
                    },
                    device_type=device_type,
                )
                self.assertFalse(entity._uses_comfort_mode_pilot_wire)

    def test_area_detection_falls_back_for_v034_devices(self) -> None:
        """Support older Tydom objects that only expose area_id."""
        entity, _client = _rf6600fp()
        entity._device = types.SimpleNamespace()
        self.assertFalse(entity._is_area_controlled)
        entity._device = types.SimpleNamespace(area_id="area-1")
        self.assertTrue(entity._is_area_controlled)

    def test_rf6600fp_authorization_reports_hvac_state(self) -> None:
        """Writable comfortMode reports the RF6600FP HVAC state."""
        entity, _client = _rf6600fp(authorization="STOP", thermic_level="COMFORT")
        self.assertEqual(entity.hvac_mode, HVACMode.OFF)
        entity._device.authorization = "HEATING"
        self.assertEqual(entity.hvac_mode, HVACMode.HEAT)

    def test_tybox_home_profile_is_not_reclassified(self) -> None:
        """Tybox Home RF 210 remains on the localMode climate path."""
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
                    "enum_values": ["STOP", "NO_REGUL", "ANTI_FROST"],
                },
                "localMode": {
                    "type": "string",
                    "permission": "rw",
                    "enum_values": ["NORMAL", "STOP", "ANTI_FROST", "ABSENCE"],
                },
                "useMode": {
                    "type": "string",
                    "permission": "rw",
                    "enum_values": ["SCHED", "OVERRIDE", "MANUAL"],
                },
            },
            data={
                "authorization": "HEATING",
                "thermicLevel": "ANTI_FROST",
                "localMode": "ANTI_FROST",
                "useMode": "SCHED",
            },
        )
        self.assertTrue(entity._uses_local_mode)
        self.assertFalse(entity._uses_comfort_mode_pilot_wire)
        self.assertFalse(entity._is_filpilote)


class Rf6600FilPiloteCommandTests(IsolatedAsyncioTestCase):
    """The RF6600FP uses comfortMode for authorization and thermicLevel for orders."""

    async def test_turning_off_writes_comfort_mode_stop(self) -> None:
        """Turn the RF6600FP off through its authorization register."""
        entity, client = _rf6600fp()
        await entity.async_set_hvac_mode(HVACMode.OFF)
        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "comfortMode", "STOP"
        )

    async def test_turning_on_enables_heating_before_comfort_order(self) -> None:
        """Enable the season before sending the first pilot-wire order."""
        entity, client = _rf6600fp(authorization="STOP", thermic_level="STOP")
        await entity.async_set_hvac_mode(HVACMode.HEAT)
        self.assertEqual(
            client.put_devices_data.await_args_list,
            [
                call("20", "10", "comfortMode", "HEATING"),
                call("20", "10", "thermicLevel", "COMFORT"),
            ],
        )

    async def test_turning_on_preserves_existing_pilot_order(self) -> None:
        """Keep the current pilot-wire level when heat is already enabled."""
        entity, client = _rf6600fp(thermic_level="ECO")
        await entity.async_set_hvac_mode(HVACMode.HEAT)
        client.put_devices_data.assert_not_awaited()

    async def test_preset_still_writes_pilot_wire_level(self) -> None:
        """Continue to send the selected preset through thermicLevel."""
        entity, client = _rf6600fp()
        await entity.async_set_preset_mode(entities_module.PRESET_ECO)
        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "thermicLevel", "ECO"
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
