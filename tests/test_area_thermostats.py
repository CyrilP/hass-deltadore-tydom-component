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


if __name__ == "__main__":
    import unittest

    unittest.main()
