"""Regression coverage for the Tybox Home RF 210 preset selector profile."""

from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from test_climate_filpilote_detection import _thermostat, entities_module

PRESET_AWAY = entities_module.PRESET_AWAY
PRESET_NONE = entities_module.PRESET_NONE
HVACMode = entities_module.HVACMode
HVACAction = entities_module.HVACAction


def _rf210(*, local_mode="NORMAL", thermic_level="NO_REGUL"):
    """Return the narrow SCHED + NO_REGUL + localMode PAC capability profile."""
    return _thermostat(
        metadata={
            "authorization": {
                "permission": "r",
                "enum_values": ["STOP", "HEATING", "COOLING", "AUTO"],
            },
            "comfortMode": {
                "permission": "w",
                "enum_values": ["STOP", "HEATING", "COOLING"],
            },
            "thermicLevel": {
                "permission": "rw",
                "enum_values": ["STOP", "NO_REGUL", "ANTI_FROST"],
            },
            "heatSetpoint": {"permission": "rw", "min": 1.0, "max": 50.0},
            "setpoint": {"permission": "rw", "min": 1.0, "max": 50.0},
            "localMode": {
                "permission": "rw",
                "enum_values": ["NORMAL", "STOP", "ANTI_FROST", "ABSENCE"],
            },
            "useMode": {
                "permission": "rw",
                "enum_values": ["SCHED", "OVERRIDE", "MANUAL"],
            },
        },
        data={
            "authorization": "HEATING",
            "heatSetpoint": 19.0,
            "setpoint": 19.0,
            "thermicLevel": thermic_level,
            "localMode": local_mode,
            "useMode": "SCHED",
            "temperature": 18.0,
        },
    )


class NoRegulPresetTests(TestCase):
    """NO_REGUL is internal state and maps to the advertised no-preset value."""

    def test_no_regul_is_filtered_and_none_is_added_only_for_that_capability(self):
        """NO_REGUL maps to none, and the selector contains that value."""
        entity, _client = _thermostat(
            metadata={
                "authorization": {
                    "permission": "r",
                    "enum_values": ["STOP", "HEATING"],
                },
                "comfortMode": {
                    "permission": "r",
                    "enum_values": ["NO_REGUL", "COMFORT"],
                },
                "thermicLevel": {
                    "permission": "rw",
                    "enum_values": ["STOP", "NO_REGUL", "ANTI_FROST"],
                },
                "setpoint": {"permission": "rw", "min": 5.0, "max": 35.0},
            },
            data={"authorization": "HEATING", "thermicLevel": "NO_REGUL"},
        )

        self.assertNotIn("NO_REGUL", entity.preset_modes)
        self.assertIn(PRESET_NONE, entity.preset_modes)
        self.assertEqual(entity.preset_mode, PRESET_NONE)
        self.assertIn(entity.preset_mode, entity.preset_modes)

    def test_devices_without_no_regul_keep_the_existing_preset_list(self):
        """Unrelated climates do not gain an extra no-preset option."""
        entity, _client = _thermostat(
            metadata={
                "authorization": {
                    "permission": "r",
                    "enum_values": ["STOP", "HEATING"],
                },
                "thermicLevel": {
                    "permission": "rw",
                    "enum_values": ["STOP", "ANTI_FROST"],
                },
                "setpoint": {"permission": "rw", "min": 5.0, "max": 35.0},
            },
            data={"authorization": "HEATING", "thermicLevel": "ANTI_FROST"},
        )

        self.assertEqual(entity.preset_modes, [PRESET_AWAY])
        self.assertNotIn(PRESET_NONE, entity.preset_modes)

    def test_no_regul_comfort_mode_also_advertises_none(self):
        """The fallback is valid if NO_REGUL is reported by comfortMode."""
        entity, _client = _thermostat(
            metadata={
                "authorization": {
                    "permission": "r",
                    "enum_values": ["STOP", "HEATING"],
                },
                "comfortMode": {
                    "permission": "rw",
                    "enum_values": ["NO_REGUL", "COMFORT"],
                },
                "thermicLevel": {
                    "permission": "rw",
                    "enum_values": ["STOP", "ANTI_FROST"],
                },
                "setpoint": {"permission": "rw", "min": 5.0, "max": 35.0},
            },
            data={
                "authorization": "HEATING",
                "comfortMode": "NO_REGUL",
            },
        )

        self.assertNotIn("NO_REGUL", entity.preset_modes)
        self.assertEqual(entity.preset_mode, PRESET_NONE)
        self.assertIn(entity.preset_mode, entity.preset_modes)


class Rf210LocalModeTests(TestCase):
    """Only the complete SCHED/NO_REGUL/localMode profile gets this mapping."""

    def test_absence_and_anti_frost_are_not_collapsed_together(self):
        """Absence stays Away while Anti-frost is not mislabeled as Away."""
        absence, _client = _rf210(local_mode="ABSENCE")
        anti_frost, _client = _rf210(local_mode="ANTI_FROST")

        self.assertTrue(absence._uses_local_mode_presets)
        self.assertEqual(absence.preset_mode, PRESET_AWAY)
        self.assertEqual(anti_frost.preset_mode, PRESET_NONE)
        self.assertNotEqual(anti_frost.preset_mode, absence.preset_mode)
        self.assertNotIn("frost_protection", anti_frost.preset_modes)

    def test_local_mode_stop_reports_hvac_off_even_when_authorization_is_heating(self):
        """STOP wins over the season-level HEATING authorization."""
        entity, _client = _rf210(local_mode="STOP")

        self.assertEqual(entity.hvac_mode, HVACMode.OFF)
        self.assertEqual(entity.hvac_action, HVACAction.OFF)
        self.assertEqual(entity.preset_mode, PRESET_NONE)

    def test_typass_area_profile_without_no_regul_is_not_reclassified(self):
        """The Typass area capability path keeps its existing preset profile."""
        entity, _client = _thermostat(
            metadata={
                "authorization": {
                    "permission": "r",
                    "enum_values": ["STOP", "HEATING"],
                },
                "localMode": {
                    "permission": "rw",
                    "enum_values": ["NORMAL", "LOCAL_SETPOINT", "ABSENCE"],
                },
                "useMode": {
                    "permission": "rw",
                    "enum_values": ["SCHED", "OVERRIDE"],
                },
                "thermicLevel": {
                    "permission": "rw",
                    "enum_values": ["STOP", "ANTI_FROST"],
                },
                "setpoint": {"permission": "rw", "min": 10.0, "max": 30.0},
            },
            data={
                "authorization": "HEATING",
                "localMode": "NORMAL",
                "useMode": "SCHED",
                "thermicLevel": "ANTI_FROST",
                "setpoint": 19.0,
            },
        )
        entity._device.area_id = "area-7"

        self.assertFalse(entity._uses_local_mode_presets)
        self.assertEqual(entity.preset_modes, [PRESET_AWAY])


class Rf210LocalModeCommandTests(IsolatedAsyncioTestCase):
    """Guard localMode writes against unwanted heating changes."""

    async def test_none_does_not_restart_a_stopped_zone(self):
        """Clearing none while stopped must not write NORMAL."""
        entity, client = _rf210(local_mode="STOP")

        await entity.async_set_preset_mode(PRESET_NONE)

        client.put_devices_data.assert_not_awaited()

    async def test_none_does_not_overwrite_frost_state(self):
        """The unverified frost state is left untouched."""
        entity, client = _rf210(local_mode="ANTI_FROST")

        await entity.async_set_preset_mode(PRESET_NONE)

        client.put_devices_data.assert_not_awaited()

    async def test_none_clears_away_to_normal(self):
        """Only an active Away override is cleared to normal regulation."""
        entity, client = _rf210(local_mode="ABSENCE")

        await entity.async_set_preset_mode(PRESET_NONE)

        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "localMode", "NORMAL"
        )

    async def test_area_backed_rf210_uses_area_command(self):
        """Area-linked RF 210 devices keep using the area API."""
        entity, client = _rf210(local_mode="NORMAL")
        entity._device.area_id = "area-7"
        client.put_area_data = AsyncMock()

        await entity.async_set_preset_mode(PRESET_AWAY)

        client.put_area_data.assert_awaited_once_with("area-7", "localMode", "ABSENCE")
        client.put_devices_data.assert_not_awaited()
