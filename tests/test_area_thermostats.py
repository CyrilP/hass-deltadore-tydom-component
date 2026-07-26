"""Tests for area-backed thermostat support."""

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
TydomBoiler = devices_module.TydomBoiler

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


class AreaThermostatTests(IsolatedAsyncioTestCase):
    """Exercise discovery, updates, and writes for area-backed thermostats."""

    def setUp(self) -> None:
        """Reset parser registries before each test."""
        handler_module.device_name.clear()
        handler_module.device_type.clear()
        handler_module.device_endpoint.clear()
        handler_module.device_metadata.clear()
        handler_module.device_name["10_20"] = "Living room"
        handler_module.device_type["10_20"] = "re2020ControlBoiler"
        handler_module.device_metadata["10_20"] = {}
        self.client = MagicMock()
        self.handler = MessageHandler(self.client, b"")

    async def _discover(self):
        """Return the thermostat created from an area-linked endpoint."""
        devices = await self.handler.parse_devices_data(
            [
                {
                    "id": 20,
                    "endpoints": [
                        {
                            "id": 10,
                            "error": 0,
                            "link": {"type": "area", "id": 7},
                            "data": [
                                {
                                    "name": "temperature",
                                    "value": 20.5,
                                    "validity": "upToDate",
                                }
                            ],
                        }
                    ],
                }
            ],
            None,
        )
        return devices[0]

    async def test_area_link_discovers_re2020_thermostat(self) -> None:
        """The linked endpoint is retained as an area-backed boiler."""
        device = await self._discover()

        self.assertIsInstance(device, TydomBoiler)
        self.assertEqual(device.area_id, "7")
        self.assertEqual(device.temperature, 20.5)
        self.assertEqual(device.area_hvac_modes(), {"STOP", "HEATING"})

    async def test_unlinked_re2020_endpoint_does_not_create_climate(self) -> None:
        """A shutter-only Tywell must not produce a climate device."""
        devices = await self.handler.parse_devices_data(
            [
                {
                    "id": 20,
                    "endpoints": [
                        {
                            "id": 10,
                            "error": 0,
                            "data": [
                                {
                                    "name": "temperature",
                                    "value": 20.5,
                                    "validity": "upToDate",
                                }
                            ],
                        }
                    ],
                }
            ],
            None,
        )

        self.assertEqual(devices, [])

    async def test_linked_passive_control_keeps_sensor_and_adds_climate(self) -> None:
        """A passive Tywell retains its sensor device and gains a climate device."""
        handler_module.device_name["10_20"] = "Tywell Ctrl RdC"
        handler_module.device_type["10_20"] = "re2020ControlPassive"

        devices = await self.handler.parse_devices_data(
            [
                {
                    "id": 20,
                    "endpoints": [
                        {
                            "id": 10,
                            "error": 0,
                            "link": {"type": "area", "id": 7},
                            "data": [
                                {
                                    "name": "ambientTemperature",
                                    "value": 20.5,
                                    "validity": "upToDate",
                                },
                                {
                                    "name": "hygroIn",
                                    "value": 49.0,
                                    "validity": "upToDate",
                                },
                            ],
                        }
                    ],
                }
            ],
            None,
        )

        self.assertEqual(len(devices), 2)
        passive, climate = devices
        self.assertNotIsInstance(passive, TydomBoiler)
        self.assertEqual(passive.device_id, "10_20")
        self.assertEqual(passive.ambientTemperature, 20.5)
        self.assertEqual(passive.hygroIn, 49.0)
        self.assertIsInstance(climate, TydomBoiler)
        self.assertEqual(climate.device_id, "10_20_area_climate")
        self.assertTrue(climate.is_derived_area_climate)
        self.assertEqual(climate.source_device_id, passive.device_id)
        self.assertEqual(climate.device_name, "Tywell Ctrl RdC Thermostat")
        self.assertEqual(climate.area_id, "7")
        self.assertEqual(climate.ambientTemperature, 20.5)
        self.assertFalse(hasattr(climate, "hygroIn"))

    async def test_passive_climate_inherits_linked_area_control_metadata(self) -> None:
        """The derived climate uses receiver limits rather than passive metadata."""
        handler_module.device_name.update(
            {
                "10_20": "Tywell Ctrl RdC",
                "11_21": "Tybox 5101 RdC",
            }
        )
        handler_module.device_type.update(
            {
                "10_20": "re2020ControlPassive",
                "11_21": "boiler",
            }
        )
        handler_module.device_metadata.update(
            {
                "10_20": {"ambientTemperature": {"min": -327.67, "max": 327.66}},
                "11_21": {
                    "authorization": {"enum_values": ["STOP", "HEATING"]},
                    "setpoint": {"min": 1.0, "max": 50.0, "step": 0.5},
                },
            }
        )

        devices = await self.handler.parse_devices_data(
            [
                {
                    "id": 20,
                    "endpoints": [
                        {
                            "id": 10,
                            "error": 0,
                            "link": {"type": "area", "id": 7},
                            "data": [],
                        }
                    ],
                },
                {
                    "id": 21,
                    "endpoints": [
                        {
                            "id": 11,
                            "error": 0,
                            "link": {"type": "area", "id": 7},
                            "data": [],
                        }
                    ],
                },
            ],
            None,
        )

        derived_climate = devices[1]
        self.assertIsInstance(derived_climate, TydomBoiler)
        self.assertEqual(
            derived_climate._metadata,
            {
                "authorization": {"enum_values": ["STOP", "HEATING"]},
                "setpoint": {"min": 1.0, "max": 50.0, "step": 0.5},
            },
        )
        self.assertEqual(derived_climate.area_temperature_limits(), (1.0, 50.0))
        self.assertEqual(derived_climate.area_temperature_step(), 0.5)

        area_devices = await self.handler.parse_areas_data(
            [
                {
                    "id": 7,
                    "data": [
                        {
                            "name": "authorization",
                            "value": "HEATING",
                            "validity": "upToDate",
                        },
                        {
                            "name": "minSetpoint",
                            "value": 10.0,
                            "validity": "upToDate",
                        },
                        {
                            "name": "maxSetpoint",
                            "value": 30.0,
                            "validity": "upToDate",
                        },
                    ],
                }
            ],
            None,
        )

        self.assertEqual(area_devices[0].area_temperature_limits(), (10.0, 30.0))

    async def test_partial_update_keeps_strongest_area_metadata(self) -> None:
        """A passive-only update must not discard linked controller limits."""
        handler_module.device_name.update(
            {"10_20": "Tywell Ctrl RdC", "11_21": "Tybox 5101 RdC"}
        )
        handler_module.device_type.update(
            {"10_20": "re2020ControlPassive", "11_21": "boiler"}
        )
        controller_metadata = {
            "authorization": {"enum_values": ["STOP", "HEATING"]},
            "setpoint": {"min": 1.0, "max": 50.0, "step": 0.5},
        }
        handler_module.device_metadata.update(
            {
                "10_20": {"ambientTemperature": {"min": -327.67, "max": 327.66}},
                "11_21": controller_metadata,
            }
        )
        full_response = [
            {
                "id": 20,
                "endpoints": [
                    {
                        "id": 10,
                        "error": 0,
                        "link": {"type": "area", "id": 7},
                        "data": [],
                    }
                ],
            },
            {
                "id": 21,
                "endpoints": [
                    {
                        "id": 11,
                        "error": 0,
                        "link": {"type": "area", "id": 7},
                        "data": [],
                    }
                ],
            },
        ]
        await self.handler.parse_devices_data(full_response, None)

        devices = await self.handler.parse_devices_data(full_response[:1], None)

        derived_climate = devices[1]
        self.assertEqual(derived_climate._metadata, controller_metadata)

    async def test_area_state_updates_derived_passive_climate(self) -> None:
        """Area pushes target the derived climate rather than the passive sensor."""
        handler_module.device_name["10_20"] = "Tywell Ctrl RdC"
        handler_module.device_type["10_20"] = "re2020ControlPassive"
        await self.handler.parse_devices_data(
            [
                {
                    "id": 20,
                    "endpoints": [
                        {
                            "id": 10,
                            "error": 0,
                            "link": {"type": "area", "id": 7},
                            "data": [],
                        }
                    ],
                }
            ],
            None,
        )

        devices = await self.handler.parse_areas_data(
            [
                {
                    "id": 7,
                    "data": [
                        {
                            "name": "authorization",
                            "value": "HEATING",
                            "validity": "upToDate",
                        },
                        {
                            "name": "setpoint",
                            "value": 21.0,
                            "validity": "upToDate",
                        },
                    ],
                }
            ],
            None,
        )

        self.assertEqual(len(devices), 1)
        climate = devices[0]
        self.assertIsInstance(climate, TydomBoiler)
        self.assertEqual(climate.device_id, "10_20_area_climate")
        self.assertEqual(climate.authorization, "HEATING")
        self.assertEqual(climate.setpoint, 21.0)

    async def test_unlinked_passive_control_remains_sensor_only(self) -> None:
        """An unlinked passive Tywell must not gain a climate device."""
        handler_module.device_name["10_20"] = "Tywell Ctrl RdC"
        handler_module.device_type["10_20"] = "re2020ControlPassive"

        devices = await self.handler.parse_devices_data(
            [
                {
                    "id": 20,
                    "endpoints": [
                        {
                            "id": 10,
                            "error": 0,
                            "data": [
                                {
                                    "name": "ambientTemperature",
                                    "value": 20.5,
                                    "validity": "upToDate",
                                }
                            ],
                        }
                    ],
                }
            ],
            None,
        )

        self.assertEqual(len(devices), 1)
        self.assertNotIsInstance(devices[0], TydomBoiler)
        self.assertEqual(devices[0].device_id, "10_20")

    async def test_area_modes_include_only_advertised_cooling(self) -> None:
        """Cooling is exposed only when TYDOM advertises the capability."""
        handler_module.device_metadata["10_20"] = {
            "authorization": {
                "enum_values": ["STOP", "HEATING", "COOLING"],
            }
        }

        device = await self._discover()

        self.assertEqual(device.area_hvac_modes(), {"STOP", "HEATING", "COOLING"})

    async def test_area_state_updates_linked_thermostat(self) -> None:
        """Area state is returned under the linked endpoint's stable uid."""
        await self._discover()

        devices = await self.handler.parse_areas_data(
            [
                {
                    "id": 7,
                    "data": [
                        {
                            "name": "authorization",
                            "value": "HEATING",
                            "validity": "upToDate",
                        },
                        {
                            "name": "setpoint",
                            "value": 21.0,
                            "validity": "upToDate",
                        },
                    ],
                }
            ],
            None,
        )

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].device_id, "10_20")
        self.assertEqual(devices[0].authorization, "HEATING")
        self.assertEqual(devices[0].setpoint, 21.0)

    async def test_single_area_uri_is_routed_as_area_data(self) -> None:
        """A pushed /areas/{id}/data update must not enter the device parser."""
        await self._discover()

        devices = await self.handler.parse_response(
            b'{"data":[{"name":"authorization","value":"COOLING",'
            b'"validity":"upToDate"}]}',
            "/areas/7/data",
            "application/json",
            None,
        )

        self.assertIsNotNone(devices)
        self.assertEqual(devices[0].authorization, "COOLING")

    async def test_area_state_received_before_discovery_is_retained(self) -> None:
        """Out-of-order initial responses must not discard area state."""
        devices = await self.handler.parse_areas_data(
            [
                {
                    "id": 7,
                    "error": 0,
                    "data": [
                        {
                            "name": "setpoint",
                            "value": 22.0,
                            "validity": "upToDate",
                        }
                    ],
                }
            ],
            None,
        )
        self.assertEqual(devices, [])
        await self.handler.parse_areas_data(
            [
                {
                    "id": 7,
                    "error": 0,
                    "data": [
                        {
                            "name": "authorization",
                            "value": "HEATING",
                            "validity": "upToDate",
                        }
                    ],
                }
            ],
            None,
        )

        device = await self._discover()

        self.assertEqual(device.setpoint, 22.0)
        self.assertEqual(device.authorization, "HEATING")

    async def test_area_error_does_not_replace_cached_state(self) -> None:
        """An errored area response must not overwrite the last valid state."""
        await self.handler.parse_areas_data(
            [
                {
                    "id": 7,
                    "error": 0,
                    "data": [
                        {
                            "name": "setpoint",
                            "value": 22.0,
                            "validity": "upToDate",
                        }
                    ],
                }
            ],
            None,
        )
        await self.handler.parse_areas_data([{"id": 7, "error": 1, "data": []}], None)

        device = await self._discover()

        self.assertEqual(device.setpoint, 22.0)

    async def test_area_thermostat_commands_use_area_endpoint(self) -> None:
        """Mode and setpoint writes do not fall back to device endpoints."""
        device = await self._discover()
        self.client.put_area_data = AsyncMock()

        await device.set_hvac_mode("NORMAL")
        await device.set_temperature("21.5")

        self.assertEqual(
            self.client.put_area_data.await_args_list,
            [
                call("7", "authorization", "HEATING"),
                call("7", "setpoint", "21.5"),
            ],
        )

    async def test_reversible_area_uses_mode_specific_setpoint(self) -> None:
        """A reversible system writes the register matching its current mode."""
        handler_module.device_metadata["10_20"] = {
            "authorization": {"enum_values": ["STOP", "HEATING", "COOLING"]},
            "heatSetpoint": {"min": 7.0, "max": 32.0, "step": 0.5},
            "coolSetpoint": {"min": 7.0, "max": 32.0, "step": 0.5},
        }
        device = await self._discover()
        device.authorization = "COOLING"
        device.coolSetpoint = 24.0
        device.minCoolSetpoint = 18.0
        device.maxCoolSetpoint = 30.0
        self.client.put_area_data = AsyncMock()

        await device.set_temperature("23.5")

        self.client.put_area_data.assert_awaited_once_with("7", "coolSetpoint", "23.5")
        self.assertEqual(device.area_temperature_limits(), (18.0, 30.0))
        self.assertEqual(device.area_temperature_step(), 0.5)


if __name__ == "__main__":
    import unittest

    unittest.main()
