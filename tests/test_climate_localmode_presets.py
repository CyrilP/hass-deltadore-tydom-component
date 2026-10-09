"""Tests for localMode-driven presets on PAC / boiler zones.

Covers two things on a Tybox Home RF 210 (Sofath LIZEA IV heat pump) profile:

* the issue #505 fix: the preset selector must never go empty, i.e.
  ``preset_mode`` always stays a member of ``preset_modes`` (``PRESET_NONE`` is
  advertised, and the internal ``NO_REGUL`` thermicLevel value is not exposed);
* the follow-up: ANTI_FROST and ABSENCE are surfaced as *distinct* presets
  (``frost_protection`` vs ``away``) driven by the rw ``localMode`` register,
  instead of both collapsing onto ``away``.

The Home-Assistant-free bootstrap is reused from
``test_climate_filpilote_detection`` to avoid duplicating ~260 lines of stubs.
"""

from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from test_climate_filpilote_detection import _thermostat, entities_module

PRESET_AWAY = entities_module.PRESET_AWAY
PRESET_NONE = entities_module.PRESET_NONE
PRESET_FROST_PROTECTION = entities_module.PRESET_FROST_PROTECTION


def _pac_boiler(*, local_mode="NORMAL", use_mode="MANUAL"):
    """A Tybox Home RF 210 style boiler.

    localMode is the rw mode register [NORMAL, STOP, ANTI_FROST, ABSENCE]; a
    writable setpoint keeps it out of the fil-pilote path.
    """
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
            "localMode": local_mode,
            "useMode": use_mode,
        },
    )


class LocalModePresetModesTests(TestCase):
    """The advertised preset list is built from the localMode register."""

    def test_profile_is_detected(self) -> None:
        entity, _client = _pac_boiler()
        self.assertTrue(entity._uses_local_mode_presets)
        self.assertFalse(entity._is_filpilote)

    def test_preset_modes_are_away_frost_and_none(self) -> None:
        """ABSENCE -> away, ANTI_FROST -> frost_protection, plus PRESET_NONE."""
        entity, _client = _pac_boiler()
        self.assertEqual(
            entity.preset_modes,
            [PRESET_AWAY, PRESET_FROST_PROTECTION, PRESET_NONE],
        )

    def test_custom_preset_is_localised_without_renaming_the_entity(self) -> None:
        """The frost_protection preset is localised via a name-less key."""
        entity, _client = _pac_boiler()
        self.assertEqual(entity._attr_translation_key, "tydom_climate")


class LocalModePresetStateTests(TestCase):
    """preset_mode reflects the live localMode value and is always valid."""

    def test_normal_reports_none(self) -> None:
        """NORMAL regulation has no special preset (issue #505: not empty)."""
        entity, _client = _pac_boiler(local_mode="NORMAL")
        self.assertEqual(entity.preset_mode, PRESET_NONE)
        self.assertIn(entity.preset_mode, entity.preset_modes)

    def test_stop_reports_none(self) -> None:
        entity, _client = _pac_boiler(local_mode="STOP")
        self.assertEqual(entity.preset_mode, PRESET_NONE)
        self.assertIn(entity.preset_mode, entity.preset_modes)

    def test_anti_frost_reports_frost_protection(self) -> None:
        entity, _client = _pac_boiler(local_mode="ANTI_FROST")
        self.assertEqual(entity.preset_mode, PRESET_FROST_PROTECTION)
        self.assertIn(entity.preset_mode, entity.preset_modes)

    def test_absence_reports_away(self) -> None:
        entity, _client = _pac_boiler(local_mode="ABSENCE")
        self.assertEqual(entity.preset_mode, PRESET_AWAY)
        self.assertIn(entity.preset_mode, entity.preset_modes)


class LocalModeSetPresetTests(IsolatedAsyncioTestCase):
    """Selecting a preset writes the localMode register."""

    async def test_selecting_frost_protection_writes_anti_frost(self) -> None:
        entity, client = _pac_boiler(local_mode="NORMAL")
        await entity.async_set_preset_mode(PRESET_FROST_PROTECTION)
        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "localMode", "ANTI_FROST"
        )

    async def test_selecting_away_writes_absence(self) -> None:
        entity, client = _pac_boiler(local_mode="NORMAL")
        await entity.async_set_preset_mode(PRESET_AWAY)
        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "localMode", "ABSENCE"
        )

    async def test_selecting_none_writes_normal(self) -> None:
        entity, client = _pac_boiler(local_mode="ANTI_FROST")
        await entity.async_set_preset_mode(PRESET_NONE)
        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "localMode", "NORMAL"
        )


class NoRegulAndPresetNoneTests(TestCase):
    """issue #505 on a non-localMode zone: NO_REGUL hidden, PRESET_NONE valid."""

    def _zone(self, *, thermic_level):
        """A reversible zone exposing thermicLevel [STOP, NO_REGUL, ANTI_FROST].

        No absence-capable localMode, so it keeps the generic thermicLevel path.
        """
        return _thermostat(
            metadata={
                "authorization": {
                    "permission": "r",
                    "enum_values": ["STOP", "HEATING", "COOLING", "AUTO"],
                },
                "thermicLevel": {
                    "permission": "rw",
                    "enum_values": ["STOP", "NO_REGUL", "ANTI_FROST"],
                },
                "heatSetpoint": {"permission": "rw", "min": 1.0, "max": 50.0},
                "setpoint": {"permission": "rw", "min": 1.0, "max": 50.0},
            },
            data={
                "authorization": "HEATING",
                "heatSetpoint": 19.0,
                "setpoint": 19.0,
                "thermicLevel": thermic_level,
            },
        )

    def test_no_regul_is_not_exposed_as_a_preset(self) -> None:
        entity, _client = self._zone(thermic_level="ANTI_FROST")
        self.assertFalse(entity._uses_local_mode_presets)
        self.assertNotIn("NO_REGUL", entity.preset_modes)

    def test_preset_none_is_advertised(self) -> None:
        entity, _client = self._zone(thermic_level="ANTI_FROST")
        self.assertIn(PRESET_NONE, entity.preset_modes)

    def test_no_regul_state_reports_valid_none(self) -> None:
        """thermicLevel NO_REGUL must resolve to a member of preset_modes."""
        entity, _client = self._zone(thermic_level="NO_REGUL")
        self.assertEqual(entity.preset_mode, PRESET_NONE)
        self.assertIn(entity.preset_mode, entity.preset_modes)


if __name__ == "__main__":
    import unittest

    unittest.main()
