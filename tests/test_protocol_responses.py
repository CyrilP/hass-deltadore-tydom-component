"""Tests for Tydom protocol response handling."""

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, call


_MISSING = object()
_original_modules: dict[str, object] = {}


def _module(name: str, **attributes) -> types.ModuleType:
    """Install a minimal module needed to load the protocol code in isolation."""
    _original_modules.setdefault(name, sys.modules.get(name, _MISSING))
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    sys.modules[name] = module
    return module


for package_name in (
    "custom_components",
    "custom_components.deltadore_tydom",
    "custom_components.deltadore_tydom.tydom",
):
    package = _module(package_name)
    package.__path__ = []

logger = MagicMock()
_module(
    "custom_components.deltadore_tydom.const",
    LOGGER=logger,
    validate_value_with_metadata=MagicMock(return_value=(True, None)),
)

root = Path(__file__).parents[1]
tydom_path = root / "custom_components" / "deltadore_tydom" / "tydom"

devices_spec = importlib.util.spec_from_file_location(
    "custom_components.deltadore_tydom.tydom.tydom_devices",
    tydom_path / "tydom_devices.py",
)
assert devices_spec is not None and devices_spec.loader is not None
devices_module = importlib.util.module_from_spec(devices_spec)
_original_modules.setdefault(
    devices_spec.name, sys.modules.get(devices_spec.name, _MISSING)
)
sys.modules[devices_spec.name] = devices_module
devices_spec.loader.exec_module(devices_module)

handler_spec = importlib.util.spec_from_file_location(
    "custom_components.deltadore_tydom.tydom.MessageHandler",
    tydom_path / "MessageHandler.py",
)
assert handler_spec is not None and handler_spec.loader is not None
handler_module = importlib.util.module_from_spec(handler_spec)
_original_modules.setdefault(
    handler_spec.name, sys.modules.get(handler_spec.name, _MISSING)
)
sys.modules[handler_spec.name] = handler_module
handler_spec.loader.exec_module(handler_module)

MessageHandler = handler_module.MessageHandler
TydomLight = devices_module.TydomLight
TydomEnergy = devices_module.TydomEnergy
TydomAlarm = devices_module.TydomAlarm

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


def _alarm_with_command(
    command: str,
    values: list[str],
    *,
    away_zones: str = "1,3",
    legacy: bool = False,
) -> tuple[object, MagicMock]:
    """Return an alarm advertising one writable cdata command."""
    client = MagicMock()
    client._zone_away = away_zones
    client._zone_home = "1"
    client._zone_night = "2"
    client.put_alarm_cdata = AsyncMock()
    alarm = TydomAlarm(
        client,
        "10_20",
        "20",
        "Alarm",
        "alarm",
        "10",
        {},
        {"part1State": "OFF"} if legacy else {},
        command_metadata={
            command: {
                "permission": "w",
                "parameters": [{"name": "value", "enum_values": values}],
            }
        },
    )
    return alarm, client


class ProtocolResponseTests(IsolatedAsyncioTestCase):
    """Exercise response acknowledgements and light refresh polling."""

    def setUp(self) -> None:
        """Reset protocol state shared between tests."""
        handler_module.device_name.clear()
        handler_module.device_type.clear()
        handler_module.device_command_metadata.clear()

    async def test_alarm_command_metadata_is_retained_by_endpoint(self) -> None:
        """Command capabilities must remain available to alarm entities."""
        handler = MessageHandler(MagicMock(), b"")

        await handler.parse_cmeta_data(
            [
                {
                    "id": 20,
                    "endpoints": [
                        {
                            "id": 10,
                            "error": 0,
                            "cmetadata": [
                                {
                                    "name": "zoneCmd",
                                    "permission": "w",
                                    "parameters": [
                                        {
                                            "name": "value",
                                            "type": "string",
                                            "enum_values": ["ON", "OFF", "FORCED_ON"],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
            None,
        )

        self.assertIn(
            "FORCED_ON",
            handler_module.device_command_metadata["10_20"]["zoneCmd"]["parameters"][0][
                "enum_values"
            ],
        )

    async def test_transac_zero_alarm_result_resolves_command_waiter(self) -> None:
        """TYDOM alarm broadcasts must complete the matching pending command."""
        handler = MessageHandler(MagicMock(), b"")
        handler_module.device_name["10_20"] = "Alarm"
        handler_module.device_type["10_20"] = "alarm"
        waiter = handler.create_alarm_command_waiter("20", "10", "zoneCmd")

        await handler.parse_devices_cdata(
            [
                {
                    "id": 20,
                    "endpoints": [
                        {
                            "id": 10,
                            "error": 0,
                            "cdata": [
                                {
                                    "name": "zoneCmd",
                                    "values": {
                                        "result": "DENIED",
                                        "authent": "USER",
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
            "0",
        )

        self.assertEqual((await waiter)["values"]["result"], "DENIED")

    async def test_force_arm_uses_advertised_zone_command(self) -> None:
        """Modern alarms may force only a command advertised by cmetadata."""
        alarm, client = _alarm_with_command("zoneCmd", ["ON", "OFF", "FORCED_ON"])

        await alarm.force_arm("away", "123456")

        client.put_alarm_cdata.assert_awaited_once_with(
            "20", "10", "123456", "FORCED_ON", "1,3", False
        )

    async def test_force_arm_rejects_unadvertised_command(self) -> None:
        """Force arming must not guess support when FORCED_ON is absent."""
        alarm, client = _alarm_with_command("zoneCmd", ["ON", "OFF"])

        with self.assertRaisesRegex(ValueError, "does not advertise FORCED_ON"):
            await alarm.force_arm("away", "123456")

        client.put_alarm_cdata.assert_not_awaited()

    async def test_force_arm_uses_advertised_global_command(self) -> None:
        """An empty configured zone selection must use the global alarm command."""
        alarm, client = _alarm_with_command(
            "alarmCmd", ["ON", "OFF", "FORCED_ON"], away_zones=""
        )

        await alarm.force_arm("away", "123456")

        client.put_alarm_cdata.assert_awaited_once_with(
            "20", "10", "123456", "FORCED_ON", "", False
        )

    async def test_force_arm_uses_advertised_legacy_part_command(self) -> None:
        """Legacy alarms must retain their per-part command path."""
        alarm, client = _alarm_with_command(
            "partCmd", ["OFF", "ON", "FORCED_ON"], legacy=True
        )

        await alarm.force_arm("away", "123456")

        client.put_alarm_cdata.assert_awaited_once_with(
            "20", "10", "123456", "FORCED_ON", "1,3", True
        )

    async def test_spontaneous_alarm_event_is_forwarded_as_device_update(self) -> None:
        """A pushed eventAlarm must reach the stored alarm device."""
        handler = MessageHandler(MagicMock(), b"")
        handler_module.device_name["10_20"] = "Alarm"
        handler_module.device_type["10_20"] = "alarm"

        devices = await handler.parse_devices_cdata(
            [
                {
                    "id": 20,
                    "endpoints": [
                        {
                            "id": 10,
                            "error": 0,
                            "cdata": [
                                {
                                    "name": "eventAlarm",
                                    "parameters": {},
                                    "values": {
                                        "event": {
                                            "name": "marcheTotale",
                                            "product": {
                                                "nameCustom": "TL 2000 Sandra",
                                                "typeLong": "TL 2000",
                                            },
                                        }
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
            "0",
        )

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].eventAlarm["name"], "marcheTotale")

    async def test_alarm_actor_prefers_named_access_code(self) -> None:
        """A spontaneous named user code must take precedence over product data."""
        client = MagicMock()
        stored = TydomAlarm(client, "10_20", "20", "Alarm", "alarm", "10", {}, {})
        incoming = TydomAlarm(
            client,
            "10_20",
            "20",
            "Alarm",
            "alarm",
            "10",
            {},
            {
                "eventAlarm": {
                    "name": "arret",
                    "accessCode": {"nameCustom": "Sandra"},
                    "product": {"nameCustom": "TYDOM application"},
                }
            },
        )

        await stored.update_device(incoming)

        self.assertEqual(stored.latest_alarm_actor, "Sandra")
        self.assertEqual(stored.latest_alarm_actor_type, "access_code")
        self.assertEqual(stored.latest_alarm_event_target, "disarmed")
        self.assertEqual(stored.alarm_event_sequence, 1)

    async def test_alarm_actor_uses_named_remote(self) -> None:
        """A spontaneous named physical remote must populate the alarm actor."""
        client = MagicMock()
        stored = TydomAlarm(client, "10_20", "20", "Alarm", "alarm", "10", {}, {})
        incoming = TydomAlarm(
            client,
            "10_20",
            "20",
            "Alarm",
            "alarm",
            "10",
            {},
            {
                "eventAlarm": {
                    "name": "marcheTotale",
                    "product": {
                        "nameCustom": "TL 2000 Sandra",
                        "typeLong": "TL 2000",
                    },
                }
            },
        )

        await stored.update_device(incoming)

        self.assertEqual(stored.latest_alarm_actor, "TL 2000 Sandra")
        self.assertEqual(stored.latest_alarm_actor_type, "product")
        self.assertEqual(stored.latest_alarm_event_target, "armed")
        self.assertEqual(stored.alarm_event_sequence, 1)

    async def test_non_state_alarm_event_does_not_replace_actor(self) -> None:
        """Intrusion and diagnostic events must not become changed_by actors."""
        client = MagicMock()
        stored = TydomAlarm(client, "10_20", "20", "Alarm", "alarm", "10", {}, {})
        incoming = TydomAlarm(
            client,
            "10_20",
            "20",
            "Alarm",
            "alarm",
            "10",
            {},
            {
                "eventAlarm": {
                    "name": "intrusion",
                    "product": {"nameCustom": "Living room detector"},
                }
            },
        )

        await stored.update_device(incoming)

        self.assertIsNone(stored.latest_alarm_actor)
        self.assertIsNone(stored.latest_alarm_actor_type)
        self.assertIsNone(stored.latest_alarm_event_target)
        self.assertEqual(stored.alarm_event_sequence, 0)

    def test_light_brightness_requires_intermediate_levels(self) -> None:
        """Binary level metadata must not advertise variable brightness."""
        client = MagicMock()
        binary_light = TydomLight(
            client,
            "10_20",
            "20",
            "Binary light",
            "light",
            "10",
            {"level": {"min": 0, "max": 100, "step": 100}},
            {"level": 0},
        )
        dimmable_light = TydomLight(
            client,
            "11_21",
            "21",
            "Dimmable light",
            "light",
            "11",
            {"level": {"min": 0, "max": 100, "step": 1}},
            {"level": 0},
        )

        self.assertFalse(binary_light.supports_brightness)
        self.assertTrue(dimmable_light.supports_brightness)

    @staticmethod
    def _profile_alarm(data: dict[str, str]) -> tuple[object, MagicMock]:
        """Return an alarm with configurable profiles and live zone states."""
        client = MagicMock()
        client._zone_home = "3"
        client._zone_night = "1,3"
        client._zone_away = "1,2,3"
        client.put_alarm_cdata = AsyncMock()
        alarm = TydomAlarm(
            client, "10_20", "20", "Alarm", "alarm", "10", {}, data
        )
        return alarm, client

    async def test_alarm_profile_reduction_disables_only_surplus_zones(self) -> None:
        """Away to Night must remove zone 2 without a global disarm."""
        alarm, client = self._profile_alarm(
            {"zone1State": "ON", "zone2State": "ON", "zone3State": "ON"}
        )

        await alarm.alarm_arm_night("123456")

        client.put_alarm_cdata.assert_awaited_once_with(
            "20", "10", "123456", "OFF", "2", False
        )

    async def test_alarm_profile_additions_precede_removals(self) -> None:
        """A profile replacement must extend protection before reducing it."""
        alarm, client = self._profile_alarm(
            {"zone1State": "ON", "zone2State": "ON", "zone3State": "OFF"}
        )
        client._zone_home = "2,3"

        await alarm.alarm_arm_home("123456")

        self.assertEqual(
            client.put_alarm_cdata.await_args_list,
            [
                call("20", "10", "123456", "ON", "3", False),
                call("20", "10", "123456", "OFF", "1", False),
            ],
        )

    async def test_alarm_profile_from_disarmed_enables_target_zones(self) -> None:
        """Arming from OFF must enable the complete configured profile."""
        alarm, client = self._profile_alarm(
            {"zone1State": "OFF", "zone2State": "OFF", "zone3State": "OFF"}
        )

        await alarm.alarm_arm_home("123456")

        client.put_alarm_cdata.assert_awaited_once_with(
            "20", "10", "123456", "ON", "3", False
        )

    async def test_disarmed_mode_ignores_stale_zone_states(self) -> None:
        """Explicit OFF mode must override zone values left over from arming."""
        alarm, client = self._profile_alarm(
            {"alarmMode": "OFF", "zone1State": "ON", "zone3State": "ON"}
        )

        await alarm.alarm_arm_home("123456")

        client.put_alarm_cdata.assert_awaited_once_with(
            "20", "10", "123456", "ON", "3", False
        )

    async def test_empty_alarm_profile_retains_global_arm_command(self) -> None:
        """An unconfigured zone list must keep the established global command."""
        alarm, client = self._profile_alarm({"zone1State": "OFF"})
        client._zone_away = ""

        await alarm.alarm_arm_away("123456")

        client.put_alarm_cdata.assert_awaited_once_with(
            "20", "10", "123456", "ON", "", False
        )

    async def test_alarm_profile_uses_updated_integration_configuration(self) -> None:
        """Profile calculations must use current integration option values."""
        alarm, client = self._profile_alarm(
            {"zone1State": "ON", "zone2State": "OFF"}
        )
        client._zone_home = "2"

        await alarm.alarm_arm_home("123456")

        self.assertEqual(
            client.put_alarm_cdata.await_args_list,
            [
                call("20", "10", "123456", "ON", "2", False),
                call("20", "10", "123456", "OFF", "1", False),
            ],
        )

    async def test_legacy_alarm_profiles_use_part_commands(self) -> None:
        """Legacy alarm transitions must retain the part-command dispatcher."""
        alarm, client = self._profile_alarm(
            {"part1State": "ON", "part2State": "ON", "part3State": "OFF"}
        )
        client._zone_night = "2,3"

        await alarm.alarm_arm_night("123456")

        self.assertEqual(
            client.put_alarm_cdata.await_args_list,
            [
                call("20", "10", "123456", "ON", "3", True),
                call("20", "10", "123456", "OFF", "1", True),
            ],
        )

    @staticmethod
    def _legacy_alarm() -> tuple[TydomAlarm, MagicMock]:
        """Return a CSX-style alarm advertising regular global commands."""
        client = MagicMock()
        client.put_devices_data = AsyncMock()
        client.put_alarm_cdata = AsyncMock()
        client._zone_away = ""
        client._zone_home = "2"
        client._zone_night = "1"
        alarm = TydomAlarm(
            client,
            "10_20",
            "20",
            "Legacy alarm",
            "alarm",
            "10",
            {
                "alarmCmd": {
                    "permission": "w",
                    "enum_values": ["OFF", "ON", "FORCED_ON"],
                },
                "part1State": {"permission": "r"},
            },
            {"alarmMode": "OFF", "part1State": "OFF"},
        )
        return alarm, client

    async def test_legacy_global_disarm_uses_regular_data(self) -> None:
        """CSX-style alarmCmd must use its advertised regular data endpoint."""
        alarm, client = self._legacy_alarm()

        await alarm.alarm_disarm("unused-code")

        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "alarmCmd", "OFF"
        )
        client.put_alarm_cdata.assert_not_awaited()

    async def test_legacy_global_arm_uses_regular_data(self) -> None:
        """A global legacy arm must not be sent to unsupported cdata."""
        alarm, client = self._legacy_alarm()

        await alarm.alarm_arm_away("unused-code")

        client.put_devices_data.assert_awaited_once_with(
            "20", "10", "alarmCmd", "ON"
        )
        client.put_alarm_cdata.assert_not_awaited()

    async def test_legacy_partial_arm_retains_cdata_part_command(self) -> None:
        """Configured CSX parts must retain the existing cdata dispatcher."""
        alarm, client = self._legacy_alarm()

        await alarm.alarm_arm_home("unused-code")

        client.put_alarm_cdata.assert_awaited_once_with(
            "20", "10", "unused-code", "ON", "2", True
        )
        client.put_devices_data.assert_not_awaited()

    async def test_modern_alarm_retains_cdata_global_command(self) -> None:
        """Modern zone-based alarms must retain authenticated cdata writes."""
        client = MagicMock()
        client.put_devices_data = AsyncMock()
        client.put_alarm_cdata = AsyncMock()
        alarm = TydomAlarm(
            client,
            "10_20",
            "20",
            "Modern alarm",
            "alarm",
            "10",
            {"alarmCmd": {"permission": "w", "enum_values": ["OFF", "ON"]}},
            {"alarmMode": "ON", "zone1State": "ON"},
        )

        await alarm.alarm_disarm("123456")

        client.put_alarm_cdata.assert_awaited_once_with(
            "20", "10", "123456", "OFF", None, False
        )
        client.put_devices_data.assert_not_awaited()

    async def test_alarm_inventory_merges_labels_and_technical_data(self) -> None:
        """Inventory responses should be useful without exposing other labels."""
        client = MagicMock()
        client.get_alarm_products_cdata = AsyncMock(
            return_value={
                "productInfo": {
                    "values": {
                        "products": [
                            {"id": 4, "uuid": "product-uuid", "batteryLevel": 88}
                        ]
                    }
                },
                "label": {
                    "values": {
                        "products": [
                            {
                                "id": 4,
                                "nameCustom": "Garage detector",
                                "typeLong": "Movement detector",
                                "zone": 0,
                            }
                        ],
                        "zones": [{"id": 0, "nameCustom": "Ground floor"}],
                        "accessCodes": [{"id": 1, "nameCustom": "Private"}],
                    }
                },
            }
        )
        alarm = TydomAlarm(client, "10_20", "20", "Alarm", "alarm", "10", {}, {})

        result = await alarm.get_alarm_products()

        self.assertEqual(
            result,
            {
                "zones": [{"id": 0, "name_custom": "Ground floor"}],
                "products": [
                    {
                        "id": 4,
                        "name_custom": "Garage detector",
                        "type_long": "Movement detector",
                        "zone": 0,
                        "uuid": "product-uuid",
                        "battery_level": 88,
                    }
                ],
            },
        )
        self.assertNotIn("accessCodes", result)

    async def test_alarm_product_configuration_filters_sensitive_sections(self) -> None:
        """Only common product settings should reach a service response."""
        client = MagicMock()
        client.get_alarm_product_configuration_cdata = AsyncMock(
            return_value={
                "values": {
                    "id": 4,
                    "common": {
                        "inactive": False,
                        "zone": 0,
                        "autoProtectActive": True,
                    },
                    "transmitter": {"codePin": "secret"},
                }
            }
        )
        alarm = TydomAlarm(client, "10_20", "20", "Alarm", "alarm", "10", {}, {})

        result = await alarm.get_alarm_product_configuration("123456", 4)

        self.assertEqual(
            result,
            {"id": 4, "active": True, "zone": 0, "auto_protect_active": True},
        )
        self.assertNotIn("transmitter", result)

    async def test_unacknowledged_alarm_events_are_sanitised_and_cached(self) -> None:
        """Pending history should provide a bounded dashboard-safe event list."""
        client = MagicMock()
        client.get_historic_cdata = AsyncMock(
            return_value=[
                {
                    "values": {
                        "event": {
                            "name": "INTRUSION",
                            "date": "2026-08-02T19:00:00",
                            "zones": [2],
                            "product": {
                                "nameCustom": "Garage detector",
                                "typeLong": "DMB",
                                "privateRadioIdentifier": "hidden",
                            },
                            "accessCode": {"nameCustom": "Owner", "id": 12},
                            "privateField": "hidden",
                        }
                    }
                }
            ]
        )
        alarm = TydomAlarm(client, "10_20", "20", "Alarm", "alarm", "10", {}, {})
        callback = MagicMock()
        alarm.register_callback(callback)

        result = await alarm.get_events(
            "UNACKED_EVENTS", timeout=10.0, log_timeout=False
        )

        self.assertEqual(
            result,
            [
                {
                    "name": "INTRUSION",
                    "date": "2026-08-02T19:00:00",
                    "zones": [2],
                    "product": {
                        "nameCustom": "Garage detector",
                        "typeLong": "DMB",
                    },
                    "accessCode": {"nameCustom": "Owner"},
                }
            ],
        )
        self.assertEqual(alarm.pending_events, result)
        client.get_historic_cdata.assert_awaited_once_with(
            "20",
            "10",
            "UNACKED_EVENTS",
            log_timeout=False,
            timeout=10.0,
        )
        callback.assert_called_once_with()

    async def test_acknowledgement_does_not_block_on_gateway_history(self) -> None:
        """Acknowledgement must not issue an unsupported 60-second history read."""
        client = MagicMock()
        client.put_ackevents_cdata = AsyncMock()
        alarm = TydomAlarm(client, "10_20", "20", "Alarm", "alarm", "10", {}, {})
        alarm._pending_events = [{"name": "INTRUSION"}]
        callback = MagicMock()
        alarm.register_callback(callback)

        await alarm.acknowledge_events()

        client.put_ackevents_cdata.assert_awaited_once_with("20", "10", None)
        client.get_historic_cdata.assert_not_called()
        self.assertEqual(alarm.pending_events, [{"name": "INTRUSION"}])
        callback.assert_not_called()

    async def test_ignored_acknowledgement_keeps_pending_alarm_events(self) -> None:
        """A transport acknowledgement must not hide an uncleared gateway event."""
        client = MagicMock()
        client.put_ackevents_cdata = AsyncMock()
        client.get_historic_cdata = AsyncMock(
            return_value=[
                {
                    "values": {
                        "event": {
                            "name": "alarmIntrusion",
                            "date": "2026-08-05T09:59:00",
                        }
                    }
                }
            ]
        )
        alarm = TydomAlarm(client, "10_20", "20", "Alarm", "alarm", "10", {}, {})
        alarm._pending_events = [{"name": "alarmIntrusion"}]

        await alarm.acknowledge_events()

        self.assertEqual(alarm.pending_events, [{"name": "alarmIntrusion"}])
        client.get_historic_cdata.assert_not_called()

    async def test_empty_success_response_is_treated_as_acknowledgement(self) -> None:
        """An empty successful response must not be reported as an unknown message."""
        logger.reset_mock()
        handler = MessageHandler(MagicMock(), b"")

        devices = await handler.route_response(
            b"HTTP/1.1 200 OK\r\n"
            b"Uri-Origin: /devices/20/endpoints/10/data\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 0\r\n"
            b"Transac-Id: 0\r\n\r\n"
        )

        self.assertIsNone(devices)
        logger.warning.assert_not_called()

    async def test_empty_devices_response_is_a_valid_inventory(self) -> None:
        """An empty TYDOM inventory must not be reported as an unknown message."""
        logger.reset_mock()
        handler = MessageHandler(MagicMock(), b"")
        handler.parse_devices_data = AsyncMock(return_value=[])

        devices = await handler.route_response(
            b"HTTP/1.1 200 OK\r\n"
            b"Uri-Origin: /devices/data\r\n"
            b"Content-Type: application/json\r\n\r\n[]"
        )

        self.assertEqual(devices, [])
        handler.parse_devices_data.assert_awaited_once_with([], None)
        logger.warning.assert_not_called()

    async def test_unsupported_optional_endpoint_is_remembered(self) -> None:
        """A legacy gateway's missing scenarios endpoint is not a warning."""
        logger.reset_mock()
        client = MagicMock()
        handler = MessageHandler(client, b"")

        await handler.route_response(
            b"HTTP/1.1 404 Not Found\r\n"
            b"Uri-Origin: /scenarios/file\r\n"
            b"Content-Type: text/html\r\n\r\nnot found"
        )

        client.mark_optional_path_unsupported.assert_called_once_with("/scenarios/file")
        logger.warning.assert_not_called()

    async def test_single_alarm_configuration_cdata_completes_reply(self) -> None:
        """Non-history cdata must complete without a streamed EOR sentinel."""
        client = MagicMock()
        handler = MessageHandler(client, b"")
        handler.get_type_from_id = MagicMock(return_value="alarm")
        handler.get_name_from_id = MagicMock(return_value="Alarm")
        reply_event = asyncio.Event()
        handler._end_reply_events["request-1"] = reply_event

        await handler.parse_devices_cdata(
            [
                {
                    "id": 20,
                    "endpoints": [
                        {
                            "id": 10,
                            "error": 0,
                            "cdata": [
                                {
                                    "name": "productConf",
                                    "values": {"id": 4, "common": {"zone": 2}},
                                }
                            ],
                        }
                    ],
                }
            ],
            "request-1",
        )

        self.assertTrue(reply_event.is_set())
        self.assertEqual(
            handler.get_reply("request-1")["events"][0]["name"], "productConf"
        )

    async def test_alarm_data_after_early_eor_is_not_lost(self) -> None:
        """A TYXAL cdata object arriving just after EOR must win the race."""
        handler = MessageHandler(MagicMock(), b"")
        handler.get_type_from_id = MagicMock(return_value="alarm")
        handler.get_name_from_id = MagicMock(return_value="Alarm")
        reply_event = asyncio.Event()
        handler._end_reply_events["request-1"] = reply_event
        envelope = {"id": 20, "endpoints": [{"id": 10, "error": 0, "cdata": []}]}

        envelope["endpoints"][0]["cdata"] = [{"EOR": True}]
        await handler.parse_devices_cdata([envelope], "request-1")
        self.assertFalse(reply_event.is_set())

        envelope["endpoints"][0]["cdata"] = [
            {
                "name": "productConf",
                "values": {"id": 2, "common": {"inactive": False}},
            }
        ]
        await handler.parse_devices_cdata([envelope], "request-1")

        self.assertTrue(reply_event.is_set())
        self.assertEqual(
            handler.get_reply("request-1")["events"][0]["name"], "productConf"
        )

    async def test_alarm_eor_only_reply_completes_after_grace_period(self) -> None:
        """A genuinely empty TYXAL reply must still complete promptly."""
        handler = MessageHandler(MagicMock(), b"")
        handler.get_type_from_id = MagicMock(return_value="alarm")
        handler.get_name_from_id = MagicMock(return_value="Alarm")
        reply_event = asyncio.Event()
        handler._end_reply_events["request-1"] = reply_event

        await handler.parse_devices_cdata(
            [
                {
                    "id": 20,
                    "endpoints": [{"id": 10, "error": 0, "cdata": [{"EOR": True}]}],
                }
            ],
            "request-1",
        )

        await asyncio.wait_for(reply_event.wait(), timeout=0.2)
        self.assertEqual(handler.get_reply("request-1")["events"], [])

    async def test_alarm_reply_cache_rollover_keeps_new_reply(self) -> None:
        """Evicting an old reply must not redirect new data into that reply."""
        handler = MessageHandler(MagicMock(), b"")
        handler.get_type_from_id = MagicMock(return_value="alarm")
        handler.get_name_from_id = MagicMock(return_value="Alarm")
        for request_id in range(5):
            handler._cdata_replies.append(
                {
                    "transaction_id": f"old-request-{request_id}",
                    "events": [],
                    "done": False,
                }
            )
        reply_event = asyncio.Event()
        handler._end_reply_events["new-request"] = reply_event

        await handler.parse_devices_cdata(
            [
                {
                    "id": 20,
                    "endpoints": [
                        {
                            "id": 10,
                            "error": 0,
                            "cdata": [
                                {
                                    "name": "productConf",
                                    "values": {
                                        "id": 2,
                                        "common": {"inactive": False},
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
            "new-request",
        )

        self.assertTrue(reply_event.is_set())
        reply = handler.get_reply("new-request")
        self.assertIsNotNone(reply)
        self.assertEqual(reply["events"][0]["name"], "productConf")

    async def test_rejected_alarm_configuration_redacts_pin(self) -> None:
        """An alarm PIN in Uri-Origin must never be written to the log."""
        logger.reset_mock()
        handler = MessageHandler(MagicMock(), b"")
        reply_event = asyncio.Event()
        handler._end_reply_events["request-1"] = reply_event

        await handler.route_response(
            b"HTTP/1.1 403 Forbidden\r\n"
            b"Uri-Origin: /devices/20/endpoints/10/cdata?name=productConf&pwd=123456&id=4\r\n"
            b"Content-Type: text/html\r\n"
            b"Content-Length: 6\r\n"
            b"Transac-Id: request-1\r\n\r\nDenied"
        )

        warning = str(logger.warning.call_args)
        self.assertNotIn("123456", warning)
        self.assertIn("pwd=***", warning)
        self.assertTrue(reply_event.is_set())
        error = handler.get_reply_error("request-1")
        self.assertIn("HTTP 403", error)
        self.assertIn("Denied", error)

    async def test_empty_ping_acknowledgement_updates_liveness(self) -> None:
        """The gateway's bodyless ping response must clear a pending ping."""
        client = MagicMock()
        handler = MessageHandler(client, b"")

        devices = await handler.route_response(
            b"HTTP/1.1 200 OK\r\n"
            b"Uri-Origin: /ping\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 0\r\n"
            b"Transac-Id: 123\r\n\r\n"
        )

        self.assertIsNone(devices)
        client.receive_pong.assert_called_once_with()

    async def test_nested_event_refreshes_devices(self) -> None:
        """A specialised event URI must use the generic event handler."""
        logger.reset_mock()
        client = MagicMock()
        client.get_devices_data = AsyncMock()
        handler = MessageHandler(client, b"")
        body = b'{"mode":"STOP","support":["STOP","HEATING"]}'

        devices = await handler.route_response(
            b"POST /events/home/hvac HTTP/1.1\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode()
            + body
        )

        self.assertIsNone(devices)
        client.get_devices_data.assert_awaited_once_with()
        logger.warning.assert_not_called()

    async def test_light_commands_poll_regular_data_endpoint(self) -> None:
        """Light state refreshes must use the supported data endpoint."""
        client = MagicMock()
        client.put_devices_data = AsyncMock()
        light = TydomLight(
            client,
            "10_20",
            "20",
            "Kitchen",
            "light",
            "10",
            {"levelCmd": {"enum_values": ["ON", "OFF"]}},
            {"level": 0},
        )

        await light.turn_on(None)
        await light.turn_on(42)
        await light.turn_off()

        self.assertEqual(
            client.put_devices_data.await_args_list,
            [
                call("20", "10", "levelCmd", "ON"),
                call("20", "10", "level", "42"),
                call("20", "10", "levelCmd", "OFF"),
            ],
        )
        self.assertEqual(
            client.add_poll_device_url_1s.call_args_list,
            [
                call("/devices/20/endpoints/10/data"),
                call("/devices/20/endpoints/10/data"),
                call("/devices/20/endpoints/10/data"),
            ],
        )

    async def test_energy_cdata_combines_supported_readings(self) -> None:
        """Captured TYWATT cdata shapes must become one energy update."""
        handler_module.device_name["20_10"] = "TYWATT"
        handler_module.device_type["20_10"] = "conso"
        handler = MessageHandler(MagicMock(), b"")

        devices = await handler.parse_devices_cdata(
            [
                {
                    "id": 10,
                    "endpoints": [
                        {
                            "id": 20,
                            "error": 0,
                            "cdata": [
                                {
                                    "name": "energyIndex",
                                    "status": "OK",
                                    "parameters": {"dest": "ELEC_TOTAL"},
                                    "values": {"counter": 66268504},
                                },
                                {
                                    "name": "energyInstant",
                                    "status": "OK",
                                    "parameters": {"unit": "ELEC_A"},
                                    "values": {"measure": 500},
                                },
                                {
                                    "name": "energyInstant",
                                    "status": "OK",
                                    "parameters": {"unit": "ELEC_W"},
                                    "values": {"measure": 1200},
                                },
                                {
                                    "name": "energyDistrib",
                                    "status": "OK",
                                    "parameters": {"src": "ELEC", "period": "YEAR"},
                                    "values": {
                                        "date": "2095-10-07",
                                        "ELEC_HEATING": 14484,
                                        "ELEC_HOTWATER": 201117,
                                    },
                                },
                                {
                                    "name": "energyHisto",
                                    "status": "OK",
                                    "parameters": {
                                        "dest": "ELEC_TOTAL",
                                        "period": "YEAR",
                                    },
                                    "values": {"ELEC_TOTAL": 1234},
                                },
                            ],
                        }
                    ],
                }
            ]
        )

        self.assertEqual(len(devices), 1)
        device = devices[0]
        self.assertIsInstance(device, TydomEnergy)
        self.assertEqual(device.energyIndex_ELEC_TOTAL, 66268504)
        self.assertEqual(device.energyInstant_ELEC_A, 5)
        self.assertEqual(device.energyInstant_ELEC_W, 1200)
        self.assertEqual(device.energyDistrib_ELEC_HEATING, 14484)
        self.assertEqual(device.energyDistrib_ELEC_HOTWATER, 201117)
        self.assertEqual(device.energyHisto_ELEC_TOTAL, 1234)

    async def test_energy_cdata_ignores_failed_and_malformed_values(self) -> None:
        """Unsupported cdata replies must not create misleading sensors."""
        handler_module.device_name["20_10"] = "TYWATT"
        handler_module.device_type["20_10"] = "conso"
        handler = MessageHandler(MagicMock(), b"")

        devices = await handler.parse_devices_cdata(
            [
                {
                    "id": 10,
                    "endpoints": [
                        {
                            "id": 20,
                            "error": 0,
                            "cdata": [
                                {"name": "energyIndex", "status": "destNOK"},
                                {
                                    "name": "energyIndex",
                                    "status": "OK",
                                    "parameters": {"dest": "TEMP_OUTDOOR"},
                                    "values": {"counter": 18},
                                },
                                {
                                    "name": "energyInstant",
                                    "status": "OK",
                                    "parameters": {"unit": "UNKNOWN"},
                                    "values": {"measure": 500},
                                },
                                {
                                    "name": "energyDistrib",
                                    "status": "OK",
                                    "parameters": {"src": "ELEC"},
                                    "values": {"ELEC_OTHER": True},
                                },
                            ],
                        }
                    ],
                }
            ]
        )

        self.assertEqual(devices, [])


if __name__ == "__main__":
    import unittest

    unittest.main()
