"""Tests for dedicated Tysense Sun protocol support."""

import importlib.util
from pathlib import Path
import sys
import types
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock


_MISSING = object()
_original_modules: dict[str, object] = {}


def _module(name: str, **attributes) -> types.ModuleType:
    """Install a minimal module required to load the protocol code."""
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
devices_name = "custom_components.deltadore_tydom.tydom.tydom_devices"
devices_path = (
    root / "custom_components" / "deltadore_tydom" / "tydom" / "tydom_devices.py"
)
devices_spec = importlib.util.spec_from_file_location(devices_name, devices_path)
assert devices_spec is not None and devices_spec.loader is not None
devices_module = importlib.util.module_from_spec(devices_spec)
_original_modules.setdefault(devices_name, sys.modules.get(devices_name, _MISSING))
sys.modules[devices_name] = devices_module
devices_spec.loader.exec_module(devices_module)

handler_name = "custom_components.deltadore_tydom.tydom.MessageHandler"
handler_path = (
    root / "custom_components" / "deltadore_tydom" / "tydom" / "MessageHandler.py"
)
handler_spec = importlib.util.spec_from_file_location(handler_name, handler_path)
assert handler_spec is not None and handler_spec.loader is not None
handler_module = importlib.util.module_from_spec(handler_spec)
_original_modules.setdefault(handler_name, sys.modules.get(handler_name, _MISSING))
sys.modules[handler_name] = handler_module
handler_spec.loader.exec_module(handler_module)

MessageHandler = handler_module.MessageHandler
TydomSun = devices_module.TydomSun

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


class TestTySenseSun(IsolatedAsyncioTestCase):
    """Exercise discovery and live state for Tysense Sun probes."""

    def setUp(self) -> None:
        """Reset global protocol metadata."""
        handler_module.device_name.clear()
        handler_module.device_type.clear()
        handler_module.device_metadata.clear()
        logger.reset_mock()
        self.handler = MessageHandler(MagicMock(), b"")

    @staticmethod
    def _payload(device_id: int, irradiance: int) -> list[dict]:
        """Build a payload matching the two live Tysense Sun captures."""
        return [
            {
                "id": device_id,
                "endpoints": [
                    {
                        "id": device_id,
                        "error": 0,
                        "data": [
                            {
                                "name": "battDefect",
                                "validity": "upToDate",
                                "value": False,
                            },
                            {
                                "name": "configSensor",
                                "validity": "upToDate",
                                "value": 8,
                            },
                            {
                                "name": "lightPower",
                                "validity": "upToDate",
                                "value": irradiance,
                            },
                            {
                                "name": "configTemp",
                                "validity": "upToDate",
                                "value": 0,
                            },
                        ],
                    }
                ],
            }
        ]

    async def test_sensor_sun_creates_a_dedicated_device(self) -> None:
        """The sensorSun usage must no longer fall back to a generic sensor."""
        device_id = 1752177761
        unique_id = f"{device_id}_{device_id}"
        handler_module.device_name[unique_id] = "Sonde Soleil Ouest"
        handler_module.device_type[unique_id] = "sensorSun"
        handler_module.device_metadata[unique_id] = {
            "lightPower": {
                "type": "numeric",
                "permission": "r",
                "validity": "SENSOR_SUPERVISION",
                "min": 0,
                "max": 65534,
                "step": 1,
                "unit": "W/m2",
            }
        }

        devices = await self.handler.parse_devices_data(
            self._payload(device_id, 45), None
        )

        self.assertEqual(len(devices), 1)
        self.assertIsInstance(devices[0], TydomSun)
        self.assertEqual(devices[0].device_id, unique_id)
        self.assertEqual(devices[0].device_name, "Sonde Soleil Ouest")
        self.assertEqual(devices[0].lightPower, 45)
        self.assertFalse(devices[0].battDefect)
        self.assertEqual(devices[0].configSensor, 8)
        self.assertEqual(devices[0].configTemp, 0)
        self.assertEqual(devices[0]._metadata["lightPower"]["unit"], "W/m2")
        self.assertFalse(
            any(
                call.args and "Unknown usage" in str(call.args[0])
                for call in logger.info.call_args_list
            )
        )

    async def test_two_sun_probes_remain_independent(self) -> None:
        """Separate façade probes must retain their own values and identities."""
        devices = []
        for device_id, name, irradiance in (
            (1752177761, "Sonde Soleil Ouest", 45),
            (1771919164, "Sonde Soleil Est", 528),
        ):
            unique_id = f"{device_id}_{device_id}"
            handler_module.device_name[unique_id] = name
            handler_module.device_type[unique_id] = "sensorSun"
            devices.extend(
                await self.handler.parse_devices_data(
                    self._payload(device_id, irradiance), None
                )
            )

        self.assertEqual(
            [(device.device_name, device.lightPower) for device in devices],
            [("Sonde Soleil Ouest", 45), ("Sonde Soleil Est", 528)],
        )

    async def test_expired_irradiance_is_not_published_as_fresh(self) -> None:
        """An expired measurement must not overwrite the last valid reading."""
        device_id = 1752177761
        unique_id = f"{device_id}_{device_id}"
        handler_module.device_name[unique_id] = "Sonde Soleil Ouest"
        handler_module.device_type[unique_id] = "sensorSun"
        payload = self._payload(device_id, 45)
        payload[0]["endpoints"][0]["data"][2]["validity"] = "expired"

        devices = await self.handler.parse_devices_data(payload, None)

        self.assertEqual(len(devices), 1)
        self.assertIsInstance(devices[0], TydomSun)
        self.assertFalse(hasattr(devices[0], "lightPower"))


if __name__ == "__main__":
    import unittest

    unittest.main()
