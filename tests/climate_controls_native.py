"""Native HA regressions for thermostat limits and real-state command tracking."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock
import unittest

from homeassistant.components.climate import HVACMode, PRESET_AWAY, PRESET_NONE
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from custom_components.deltadore_tydom.climate_commands import ClimateCommandTracker
from custom_components.deltadore_tydom.ha_entities import (
    ClimateCommandPendingSensor,
    HaClimate,
)
from custom_components.deltadore_tydom.tydom.tydom_devices import TydomBoiler
from entity_names_native import attach_platform, LANGUAGES

ROOT = Path(__file__).parents[1]


def thermostat(*, data=None, metadata=None, area=False, trv=False):
    """Create the real climate and protocol entities with a mocked transport."""
    client = Mock()
    client.put_devices_data = AsyncMock()
    client.put_area_data = AsyncMock()
    client.put_area_data_attributes = AsyncMock()
    client.put_home_hvac_mode = AsyncMock()
    device = TydomBoiler(
        client,
        "10_20",
        "20",
        "Thermostat",
        "sh_hvac" if trv else "boiler",
        "10",
        metadata
        if metadata is not None
        else {
            "hvacMode": {"permission": "rw", "enum_values": ["STOP", "NORMAL"]},
            "setpoint": {"type": "numeric", "permission": "rw", "min": 5, "max": 30},
        },
        data if data is not None else {"hvacMode": "NORMAL", "setpoint": 21.0},
    )
    if area:
        device.area_id = "2"
    climate = HaClimate(device, None)
    climate.async_write_ha_state = Mock()
    return climate, device, client


class CommandTrackerTests(IsolatedAsyncioTestCase):
    """Check confirmation, replacement and timeout without any radio commands."""

    def tracker(self):
        """Create a tracker whose timers are always cleaned up."""
        tracker = ClimateCommandTracker(Mock())
        self.addCleanup(tracker.close)
        return tracker

    async def test_only_matching_values_confirm(self):
        """An unrelated update cannot acknowledge a requested setpoint."""
        tracker = self.tracker()
        tracker.begin("temperature", 22.0)
        tracker.confirm({"temperature": 21.0})
        self.assertTrue(tracker.pending)
        tracker.confirm({"temperature": "22.0"})
        self.assertFalse(tracker.pending)
        self.assertEqual(tracker.attributes["command_status"], "confirmed")

    async def test_multiple_requests_confirm_independently(self):
        """A mode confirmation must not hide an outstanding temperature."""
        tracker = self.tracker()
        tracker.begin("temperature", 22)
        tracker.begin("hvac_mode", HVACMode.COOL)
        tracker.confirm({"hvac_mode": HVACMode.COOL, "temperature": 21})
        self.assertTrue(tracker.pending)
        self.assertNotIn("requested_hvac_mode", tracker.attributes)
        self.assertEqual(tracker.attributes["requested_temperature"], 22)
        tracker.confirm({"temperature": 22})
        self.assertFalse(tracker.pending)

    async def test_older_failure_does_not_remove_newer_request(self):
        """Superseding a value must be safe against the earlier send failing."""
        tracker = self.tracker()
        old = tracker.begin("temperature", 22)
        new = tracker.begin("temperature", 23)
        self.assertTrue(old.timeout.cancelled())
        tracker.fail("temperature", old)
        self.assertEqual(tracker.attributes["requested_temperature"], 23)
        tracker.confirm({"temperature": 22})
        self.assertTrue(tracker.pending)
        tracker.fail("temperature", new)
        self.assertFalse(tracker.pending)
        self.assertEqual(tracker.attributes["command_status"], "failed")

    async def test_deadline_keeps_pending_until_actual_confirmation(self):
        """A timer expiring neither confirms nor resends a command."""
        tracker = self.tracker()
        command = tracker.begin("temperature", 22)
        command.timeout.cancel()
        tracker._mark_unconfirmed("temperature", command)
        self.assertTrue(tracker.pending)
        self.assertEqual(tracker.attributes["command_status"], "unconfirmed")
        tracker.confirm({"temperature": 22})
        self.assertFalse(tracker.pending)

    async def test_old_deadline_cannot_change_a_new_request(self):
        """An earlier timer must not mark the replacement request overdue."""
        tracker = self.tracker()
        old = tracker.begin("temperature", 22)
        tracker.begin("temperature", 23)
        tracker._mark_unconfirmed("temperature", old)
        self.assertEqual(tracker.attributes["command_status"], "pending")

    async def test_close_cancels_all_timers(self):
        """Unloading must release every pending deadline."""
        tracker = self.tracker()
        commands = [
            tracker.begin("temperature", 22),
            tracker.begin("hvac_mode", "cool"),
        ]
        tracker.close()
        self.assertFalse(tracker.pending)
        self.assertTrue(all(command.timeout.cancelled() for command in commands))

    async def test_invalid_reported_temperature_does_not_confirm(self):
        """Missing, invalid and non-finite feedback cannot confirm a number."""
        tracker = self.tracker()
        tracker.begin("temperature", 22)
        for value in (None, "invalid", float("nan"), float("inf")):
            tracker.confirm({"temperature": value})
            self.assertTrue(tracker.pending)


class ClimateControlTests(IsolatedAsyncioTestCase):
    """Exercise actual HA properties, command handlers and status lifecycle."""

    def climate(self, **kwargs):
        """Create a thermostat and release its command timers after each test."""
        climate, device, client = thermostat(**kwargs)
        self.addCleanup(climate._get_command_tracker().close)
        return climate, device, client

    async def test_endpoint_limits_follow_heating_cooling_and_updates(self):
        """Installer bounds apply without an area and change with live feedback."""
        climate, device, _ = self.climate(
            data={
                "authorization": "HEATING",
                "heatSetpoint": 21,
                "coolSetpoint": 25,
                "minHeatSetpoint": 14,
                "maxHeatSetpoint": 25,
                "minCoolSetpoint": 18,
                "maxCoolSetpoint": 29,
            }
        )
        self.assertFalse(hasattr(device, "area_id"))
        self.assertEqual((climate.min_temp, climate.max_temp), (14, 25))
        device.authorization = "COOLING"
        self.assertEqual((climate.min_temp, climate.max_temp), (18, 29))
        device.minCoolSetpoint = 19
        self.assertEqual(climate.min_temp, 19)

    async def test_metadata_limits_fill_missing_live_bounds(self):
        """Each bound falls back independently to the advertised register."""
        climate, _, _ = self.climate(
            data={"authorization": "HEATING", "minHeatSetpoint": 14},
            metadata={"heatSetpoint": {"type": "numeric", "min": 10, "max": 27}},
        )
        self.assertEqual((climate.min_temp, climate.max_temp), (14, 27))

    async def test_standard_hvac_mode_limits(self):
        """A NORMAL or COOLING thermostat also selects the matching bounds."""
        climate, device, _ = self.climate(
            data={
                "hvacMode": "NORMAL",
                "setpoint": 21,
                "minHeatSetpoint": 14,
                "maxHeatSetpoint": 25,
                "minCoolSetpoint": 18,
                "maxCoolSetpoint": 29,
            }
        )
        self.assertEqual((climate.min_temp, climate.max_temp), (14, 25))
        device.hvacMode = "COOLING"
        self.assertEqual((climate.min_temp, climate.max_temp), (18, 29))

    async def test_default_limits_when_device_has_none(self):
        """Keep Home Assistant defaults for devices without advertised limits."""
        climate, _, _ = self.climate(metadata={})
        self.assertEqual((climate.min_temp, climate.max_temp), (7, 35))

    async def test_out_of_range_rejected_before_transport(self):
        """Both the climate and direct protocol command respect live bounds."""
        climate, device, client = self.climate(
            data={
                "hvacMode": "NORMAL",
                "setpoint": 21,
                "minHeatSetpoint": 14,
                "maxHeatSetpoint": 25,
            }
        )
        for value in (13.5, 25.5):
            with self.assertRaises(HomeAssistantError):
                await climate.async_set_temperature(temperature=value)
            with self.assertRaises(HomeAssistantError):
                await device.set_temperature(value)
        self.assertFalse(climate.extra_state_attributes["command_pending"])
        client.put_devices_data.assert_not_awaited()

    async def test_invalid_temperature_rejected(self):
        """Reject NaN, infinity and non-numeric requests without changing status."""
        climate, device, client = self.climate()
        for value in (float("nan"), float("inf"), "-inf", "invalid", None):
            with self.assertRaises(HomeAssistantError):
                await device.set_temperature(value)
        client.put_devices_data.assert_not_awaited()

    async def test_pending_until_matching_device_update(self):
        """Sending preserves real state; an actual matching push clears pending."""
        climate, device, client = self.climate()
        sensor = ClimateCommandPendingSensor(climate)
        climate._command_listening = True
        device.register_callback(climate._handle_climate_update)
        await climate.async_set_temperature(temperature=22)
        self.assertEqual(climate.target_temperature, 21)
        self.assertTrue(sensor.is_on)
        self.assertEqual(climate.extra_state_attributes["requested_temperature"], 22)
        client.put_devices_data.assert_awaited_once_with("20", "10", "setpoint", "22")
        await device.publish_updates()
        self.assertTrue(sensor.is_on)
        device.setpoint = 22
        await device.publish_updates()
        self.assertFalse(sensor.is_on)
        self.assertEqual(climate.target_temperature, 22)
        self.assertEqual(sensor.extra_state_attributes["command_status"], "confirmed")
        self.assertGreaterEqual(climate.async_write_ha_state.call_count, 2)

    async def test_pending_visible_while_transport_is_waiting(self):
        """Show the request before the async transport finishes sending."""
        climate, _, client = self.climate()
        gate = asyncio.Event()

        async def send(*args):
            await gate.wait()

        client.put_devices_data.side_effect = send
        task = asyncio.create_task(climate.async_set_temperature(temperature=22))
        await asyncio.sleep(0)
        self.assertTrue(climate.extra_state_attributes["command_pending"])
        self.assertFalse(task.done())
        gate.set()
        await task
        self.assertTrue(climate.extra_state_attributes["command_pending"])

    async def test_failed_send_is_not_left_pending(self):
        """Propagate the transport exception and report failure."""
        climate, _, client = self.climate()
        client.put_devices_data.side_effect = RuntimeError("send failed")
        with self.assertRaisesRegex(RuntimeError, "send failed"):
            await climate.async_set_temperature(temperature=22)
        self.assertFalse(climate.extra_state_attributes["command_pending"])
        self.assertEqual(climate.extra_state_attributes["command_status"], "failed")

    async def test_cancelled_send_cleans_pending(self):
        """Cancellation is distinct from device confirmation."""
        climate, _, client = self.climate()
        client.put_devices_data.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await climate.async_set_temperature(temperature=22)
        self.assertEqual(climate.extra_state_attributes["command_status"], "cancelled")
        self.assertFalse(climate.extra_state_attributes["command_pending"])

    async def test_invalid_new_request_keeps_previous_request(self):
        """A refused value must not hide an earlier command still awaiting feedback."""
        climate, _, client = self.climate()
        await climate.async_set_temperature(temperature=22)
        with self.assertRaises(HomeAssistantError):
            await climate.async_set_temperature(temperature=31)
        self.assertEqual(climate.extra_state_attributes["requested_temperature"], 22)
        client.put_devices_data.assert_awaited_once()

    async def test_mode_and_away_are_confirmed_from_live_state(self):
        """Mode and absence requests follow the same real-state confirmation."""
        climate, device, client = self.climate(
            metadata={
                "hvacMode": {"permission": "rw", "enum_values": ["STOP", "NORMAL"]},
                "localMode": {"permission": "rw", "enum_values": ["NORMAL", "ABSENCE"]},
            }
        )
        climate._command_listening = True
        device.register_callback(climate._handle_climate_update)
        await climate.async_set_hvac_mode(HVACMode.OFF)
        self.assertEqual(climate.hvac_mode, HVACMode.HEAT)
        device.hvacMode = "STOP"
        await device.publish_updates()
        self.assertFalse(climate.extra_state_attributes["command_pending"])
        await climate.async_set_preset_mode(PRESET_AWAY)
        self.assertTrue(climate.extra_state_attributes["command_pending"])
        self.assertNotEqual(climate.preset_mode, PRESET_AWAY)
        device.localMode = "ABSENCE"
        await device.publish_updates()
        self.assertFalse(climate.extra_state_attributes["command_pending"])
        client.put_devices_data.assert_any_await("20", "10", "localMode", "ABSENCE")

    async def test_noop_preset_does_not_create_pending_request(self):
        """Existing no-op presets must not invent a command to wait for."""
        climate, _, client = self.climate()
        await climate.async_set_preset_mode(PRESET_NONE)
        self.assertFalse(climate.extra_state_attributes["command_pending"])
        client.put_devices_data.assert_not_awaited()

    async def test_trv_numeric_wire_value_and_matching_feedback(self):
        """Preserve TRV area commands and their actual current setpoint."""
        climate, device, client = self.climate(
            trv=True,
            area=True,
            metadata={"localSetpoint": {"type": "numeric", "min": 5, "max": 30}},
            data={"currentSetpoint": 21, "localMode": "FOLLOW_MASTER"},
        )
        await climate.async_set_temperature(temperature=22)
        client.put_area_data_attributes.assert_awaited_once_with(
            "2",
            {
                "localSetpoint": 22.0,
                "localSetpRemainingTimeStr": "UNTIL_SCHED",
                "localMode": "LOCAL_SETPOINT",
            },
        )
        self.assertEqual(climate.target_temperature, 21)
        device.currentSetpoint = 22
        climate._handle_climate_update()
        self.assertFalse(climate.extra_state_attributes["command_pending"])

    async def test_indicator_is_diagnostic_and_translated_in_eight_languages(self):
        """The new entity has its own identifier and native translated name."""
        climate, device, _ = self.climate()
        names = (
            "Command pending",
            "Commande en attente",
            "Befehl ausstehend",
            "Orden pendiente",
            "Comando in attesa",
            "Comando pendente",
            "Opdracht in behandeling",
            "Polecenie w toku",
        )
        for lang, name in zip(LANGUAGES, names, strict=True):
            sensor = attach_platform(
                ClimateCommandPendingSensor(climate), lang, "binary_sensor"
            )
            self.assertEqual(sensor.name, name)
            self.assertEqual(sensor.unique_id, "10_20_climate_command_pending")
            self.assertEqual(sensor.entity_category, EntityCategory.DIAGNOSTIC)
        self.assertEqual(climate.unique_id, "10_20_climate")
        self.assertNotIn("command_pending", device.__dict__)

    async def test_indicator_created_only_once(self):
        """Inventory refreshes must not duplicate the status entity."""
        climate, _, _ = self.climate()
        first = climate.get_sensors()
        second = climate.get_sensors()
        self.assertEqual(
            sum(isinstance(s, ClimateCommandPendingSensor) for s in first), 1
        )
        self.assertFalse(
            any(isinstance(s, ClimateCommandPendingSensor) for s in second)
        )

    async def test_sensor_lifecycle_preserves_primary_reference(self):
        """A diagnostic subscription must not replace the climate's device link."""
        climate, device, _ = self.climate()
        sensor = ClimateCommandPendingSensor(climate)
        sensor.async_write_ha_state = Mock()
        await sensor.async_added_to_hass()
        self.assertIs(device._ha_device, climate)
        await climate.async_set_temperature(temperature=22)
        sensor.async_write_ha_state.assert_called_once()
        await sensor.async_will_remove_from_hass()
        await climate.async_set_temperature(temperature=23)
        sensor.async_write_ha_state.assert_called_once()
        self.assertIs(device._ha_device, climate)

    async def test_area_proxy_status_does_not_duplicate_raw_sensors(self):
        """Give derived climates status while keeping physical sensor ownership."""
        climate, device, _ = self.climate(area=True)
        device._uid = "10_20_area_climate"
        device.temperature = 20
        sensors = climate.get_sensors()
        self.assertEqual(len(sensors), 1)
        self.assertIsInstance(sensors[0], ClimateCommandPendingSensor)
        self.assertEqual(
            sensors[0].device_info["identifiers"], climate.device_info["identifiers"]
        )

    async def test_indicator_updates_when_device_availability_changes(self):
        """Device updates refresh the indicator even without a pending request."""
        climate, device, _ = self.climate()
        sensor = ClimateCommandPendingSensor(climate)
        sensor.async_write_ha_state = Mock()
        await sensor.async_added_to_hass()
        await device.publish_updates()
        sensor.async_write_ha_state.assert_called_once()
        await sensor.async_will_remove_from_hass()
        self.assertNotIn(sensor.async_write_ha_state, device._callbacks)

    async def test_unloading_climate_clears_indicator(self):
        """An enabled diagnostic must not stay on after its climate is unloaded."""
        climate, _, _ = self.climate()
        sensor = ClimateCommandPendingSensor(climate)
        sensor.async_write_ha_state = Mock()
        await sensor.async_added_to_hass()
        await climate.async_set_temperature(temperature=22)
        climate._get_command_tracker().close()
        self.assertFalse(sensor.is_on)
        self.assertEqual(sensor.async_write_ha_state.call_count, 2)
        await sensor.async_will_remove_from_hass()

    async def test_climate_lifecycle_removes_callback_and_timers(self):
        """Unloading cleans both device subscription and confirmation timers."""
        climate, device, _ = self.climate()
        await climate.async_added_to_hass()
        self.assertIn(climate._handle_climate_update, device._callbacks)
        await climate.async_set_temperature(temperature=22)
        command = climate._command_tracker._pending["temperature"]
        await climate.async_will_remove_from_hass()
        self.assertNotIn(climate._handle_climate_update, device._callbacks)
        self.assertTrue(command.timeout.cancelled())
        self.assertFalse(climate.extra_state_attributes["command_pending"])

    async def test_exception_translations_have_matching_placeholders(self):
        """Every supported language can render the new service errors."""
        for lang in LANGUAGES:
            data = json.loads(
                (
                    ROOT / f"custom_components/deltadore_tydom/translations/{lang}.json"
                ).read_text(encoding="utf-8")
            )
            message = data["exceptions"]["target_temperature_out_of_range"]["message"]
            self.assertIn(
                "22", message.format(temperature="22", minimum="14", maximum="20")
            )
            self.assertTrue(data["exceptions"]["invalid_target_temperature"]["message"])


if __name__ == "__main__":
    unittest.main()
