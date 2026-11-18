"""Exercise the reported Rothelec hvac profile without live radio commands."""

import sys
import types
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from test_climate_filpilote_detection import (
    HVACMode,
    _ha_exceptions,
    _HomeAssistantError,
    _thermostat,
    entities_module,
)


def _radiator(*, local_mode="NORMAL", authorization="HEATING", **overrides):
    metadata = {
        "heatSetpoint": {"permission": "rw", "min": 1, "max": 50, "step": 0.5},
        "setpoint": {"permission": "rw", "min": 1, "max": 50, "step": 0.5},
        "overrideSetpoint": {"permission": "rw", "min": 1, "max": 50, "step": 0.5},
        "localMode": {
            "permission": "rw",
            "enum_values": ["NORMAL", "STOP", "ANTI_FROST", "ABSENCE"],
        },
        "useMode": {"permission": "rw", "enum_values": ["SCHED", "OVERRIDE", "MANUAL"]},
        "thermicLevel": {"permission": "rw", "enum_values": ["STOP", "ANTI_FROST"]},
        "overrideThermicLevel": {
            "permission": "rw",
            "enum_values": ["STOP", "ANTI_FROST"],
        },
        "comfortMode": {"permission": "w", "enum_values": ["STOP", "HEATING"]},
        "authorization": {"permission": "r", "enum_values": ["STOP", "HEATING"]},
    }
    data = {
        "authorization": authorization,
        "heatSetpoint": 19.0,
        "setpoint": 19.0,
        "minHeatSetpoint": 10,
        "maxHeatSetpoint": 30,
        "temperature": 16.96,
        "thermicLevel": None,
        "localMode": local_mode,
        "useMode": "SCHED",
        "overrideRemainingTime": 0,
    }
    data.update(overrides)
    entity, client = _thermostat(metadata=metadata, data=data, device_type="hvac")
    client.general_climate = types.SimpleNamespace(mode="HEATING", lock_reason=None)
    return entity, client


class RothelecClimateTests(IsolatedAsyncioTestCase):
    """Prove the existing isolated local-mode path handles this signature."""

    def test_legacy_generic_sensor_keeps_its_id_and_primary_climate(self):
        """Keep existing generic entity identity while climate remains primary."""
        entity, _ = _radiator()
        legacy = entities_module.HASensor(entity._device, None, set_primary=False)
        self.assertEqual(legacy._attr_unique_id, "10_20_sensor")
        self.assertEqual(legacy.native_value, 16.96)
        self.assertIs(entity._device._ha_device, entity)

    async def test_normal_target_and_zone_commands_use_endpoint_only(self):
        """Keep the reported target and send only endpoint-level commands."""
        entity, client = _radiator()
        self.assertEqual(entity.current_temperature, 16.96)
        self.assertEqual(entity.target_temperature, 19.0)
        self.assertEqual((entity.min_temp, entity.max_temp), (10.0, 30.0))
        self.assertFalse(entity._is_filpilote)
        self.assertTrue(entity._uses_local_mode)
        await entity.async_set_temperature(temperature=20.5)
        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "heatSetpoint", "20.5"
        )
        client.put_devices_data.reset_mock()
        await entity.async_set_hvac_mode(HVACMode.OFF)
        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "localMode", "STOP"
        )
        client.put_home_hvac_mode.assert_not_called()

    async def test_absence_and_general_off_never_trigger_a_heating_write(self):
        """General absence and off block zone writes."""
        entity, client = _radiator(
            local_mode="ABSENCE",
            authorization="STOP",
            heatSetpoint=None,
            setpoint=None,
            thermicLevel="STOP",
        )
        client.general_climate.lock_reason = "absence"
        self.assertEqual(entity.preset_mode, entities_module.PRESET_AWAY)
        with (
            patch.dict(sys.modules, {"homeassistant.exceptions": _ha_exceptions}),
            self.assertRaises(_HomeAssistantError),
        ):
            await entity.async_set_temperature(temperature=20)
        client.put_devices_data.assert_not_awaited()
        client.general_climate.mode = "STOP"
        client.general_climate.lock_reason = "off"
        self.assertEqual(entity.hvac_mode, HVACMode.OFF)
        with (
            patch.dict(sys.modules, {"homeassistant.exceptions": _ha_exceptions}),
            self.assertRaises(_HomeAssistantError),
        ):
            await entity.async_set_hvac_mode(HVACMode.HEAT)
        client.put_devices_data.assert_not_awaited()
        client.put_home_hvac_mode.assert_not_called()

    async def test_local_frost_and_absence_do_not_automatically_start_heating(self):
        """Clearing a frost preset cannot silently switch a zone on."""
        entity, client = _radiator(local_mode="ANTI_FROST", thermicLevel="ANTI_FROST")
        self.assertEqual(entity.hvac_mode, HVACMode.OFF)
        await entity.async_set_preset_mode(entities_module.PRESET_NONE)
        client.put_devices_data.assert_not_awaited()
        entity._device.localMode = "ABSENCE"
        await entity.async_set_preset_mode(entities_module.PRESET_NONE)
        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "localMode", "NORMAL"
        )
