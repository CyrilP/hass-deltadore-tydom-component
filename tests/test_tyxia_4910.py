"""Tests for a TYXIA 4910 configured under the TYDOM 'others' usage."""

import importlib.util
from pathlib import Path
import sys
import types
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock


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

protocol_path = (
    Path(__file__).parents[1] / "custom_components" / "deltadore_tydom" / "tydom"
)
devices_name = "custom_components.deltadore_tydom.tydom.tydom_devices"
devices_spec = importlib.util.spec_from_file_location(
    devices_name, protocol_path / "tydom_devices.py"
)
assert devices_spec is not None and devices_spec.loader is not None
devices_module = importlib.util.module_from_spec(devices_spec)
_original_modules.setdefault(devices_name, sys.modules.get(devices_name, _MISSING))
sys.modules[devices_name] = devices_module
devices_spec.loader.exec_module(devices_module)

handler_name = "custom_components.deltadore_tydom.tydom.MessageHandler"
handler_spec = importlib.util.spec_from_file_location(
    handler_name, protocol_path / "MessageHandler.py"
)
assert handler_spec is not None and handler_spec.loader is not None
handler_module = importlib.util.module_from_spec(handler_spec)
_original_modules.setdefault(handler_name, sys.modules.get(handler_name, _MISSING))
sys.modules[handler_name] = handler_module
handler_spec.loader.exec_module(handler_module)

MessageHandler = handler_module.MessageHandler
TydomDevice = devices_module.TydomDevice
TydomLight = devices_module.TydomLight
TydomSwitch = devices_module.TydomSwitch

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


class Tyxia4910Tests(IsolatedAsyncioTestCase):
    """Exercise the captured binary series-4900 profile."""

    def setUp(self) -> None:
        """Reset module-level protocol state between tests."""
        handler_module.device_name.clear()
        handler_module.device_endpoint.clear()
        handler_module.device_type.clear()
        handler_module.device_metadata.clear()
        handler_module.device_tutorial_id.clear()
        logger.reset_mock()

    async def _configure(self, *, step: int = 100) -> str:
        """Install the sanitised configuration and metadata from issue 229."""
        uid = "20_10"
        await MessageHandler.parse_config_data(
            {
                "endpoints": [
                    {
                        "id_device": 10,
                        "id_endpoint": 20,
                        "name": "Binary output",
                        "last_usage": "others",
                        "widget_behavior": {
                            "tutorial_id": "9_Tyxia_modulaire_serie4900"
                        },
                    }
                ]
            },
            "transaction",
        )
        handler = MessageHandler(MagicMock(), b"")
        await handler.parse_devices_metadata(
            [
                {
                    "id": 10,
                    "endpoints": [
                        {
                            "id": 20,
                            "metadata": [
                                {
                                    "name": "levelCmd",
                                    "enum_values": [
                                        "ON",
                                        "OFF",
                                        "STOP",
                                        "FAVORIT1",
                                        "FAVORIT2",
                                        "TOGGLE",
                                    ],
                                },
                                {
                                    "name": "level",
                                    "min": 0,
                                    "max": 100,
                                    "step": step,
                                    "unit": "%",
                                },
                            ],
                        }
                    ],
                }
            ],
            "transaction",
        )
        return uid

    async def test_binary_other_profile_creates_tyxia_4910_switch(self) -> None:
        """The captured 'others' profile becomes a controllable switch."""
        uid = await self._configure()
        client = MagicMock()
        client.put_devices_data = AsyncMock()

        device = await MessageHandler.get_device(
            client,
            "others",
            uid,
            "10",
            "Binary output",
            "20",
            {"level": 0},
        )

        self.assertIsInstance(device, TydomSwitch)
        self.assertEqual(device.productName, "TYXIA 4910")
        self.assertEqual(device.level, 0)

        await device.turn_on()
        client.put_devices_data.assert_awaited_once_with("10", "20", "levelCmd", "ON")
        client.add_poll_device_url_1s.assert_called_once_with(
            "/devices/10/endpoints/20/data"
        )

        client.put_devices_data.reset_mock()
        client.add_poll_device_url_1s.reset_mock()
        await device.turn_off()
        client.put_devices_data.assert_awaited_once_with("10", "20", "levelCmd", "OFF")
        client.add_poll_device_url_1s.assert_called_once_with(
            "/devices/10/endpoints/20/data"
        )

    async def test_variable_series_4900_profile_is_not_reclassified(self) -> None:
        """A series-4900 dimmer is not inferred to be a TYXIA 4910."""
        uid = await self._configure(step=1)

        device = await MessageHandler.get_device(
            MagicMock(),
            "others",
            uid,
            "10",
            "Variable output",
            "20",
            {"level": 50},
        )

        self.assertIs(type(device), TydomDevice)

    async def test_unidentified_other_usage_remains_generic(self) -> None:
        """Unrelated devices using 'others' continue through generic discovery."""
        uid = "40_30"
        handler_module.device_metadata[uid] = {
            "levelCmd": {"enum_values": ["ON", "OFF"]},
            "level": {"min": 0, "max": 100, "step": 100},
        }

        device = await MessageHandler.get_device(
            MagicMock(),
            "others",
            uid,
            "30",
            "Unknown output",
            "40",
            {"level": 0},
        )

        self.assertIs(type(device), TydomDevice)

    async def test_light_usage_keeps_existing_light_entity(self) -> None:
        """A TYXIA 4910 configured as lighting retains the light path."""
        uid = await self._configure()

        device = await MessageHandler.get_device(
            MagicMock(),
            "light",
            uid,
            "10",
            "Lighting output",
            "20",
            {"level": 0},
        )

        self.assertIsInstance(device, TydomLight)
