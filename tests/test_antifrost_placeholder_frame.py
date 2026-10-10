"""Tests for the frost-protection placeholder-frame filter (issue #507).

Some gateways push a periodic full refresh in which the frost-protection
sub-block is not yet populated: ``antiFrostSetpoint`` comes back ``null`` while
``antiFrostWhenOff`` defaults to ``false``, both flagged ``upToDate``. A
correcting frame restores the real values a few seconds later. Applying the
transient ``false`` makes the "Frost protection" binary sensor flap, so the
handler drops ``antiFrostWhenOff`` whenever it arrives alongside a null
``antiFrostSetpoint`` in the same frame.
"""

import importlib.util
from pathlib import Path
import sys
import types
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock


_MISSING = object()
_original_modules: dict[str, object] = {}


def _module(name: str, **attributes) -> types.ModuleType:
    """Install a minimal module needed to load protocol code in isolation."""
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

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


class AntiFrostPlaceholderFrameTests(IsolatedAsyncioTestCase):
    """Drop the spurious antiFrostWhenOff from a placeholder refresh frame."""

    def setUp(self) -> None:
        """Register a heating zone exposing the frost-protection attributes."""
        logger.reset_mock()
        handler_module.device_name.clear()
        handler_module.device_type.clear()
        handler_module.device_metadata.clear()
        handler_module.device_command_metadata.clear()

        uid = "10_20"
        handler_module.device_name[uid] = "Living room"
        handler_module.device_type[uid] = "boiler"
        handler_module.device_metadata[uid] = {
            "antiFrostWhenOff": {"permission": "rw"},
            "antiFrostSetpoint": {"permission": "rw"},
            "ambientTemperature": {"permission": "r"},
        }
        self.handler = MessageHandler(MagicMock(), b"")

    @staticmethod
    def _response(data: list[dict]) -> list[dict]:
        """Build one endpoint response carrying the given data elements."""
        return [
            {
                "id": 20,
                "endpoints": [{"id": 10, "error": 0, "data": data}],
            }
        ]

    @staticmethod
    def _field(name: str, value: object) -> dict:
        """Build one up-to-date data element."""
        return {"name": name, "value": value, "validity": "upToDate"}

    async def test_placeholder_frame_drops_spurious_antifrost(self) -> None:
        """A null antiFrostSetpoint marks the whole frost block as not ready."""
        devices = await self.handler.parse_devices_data(
            self._response(
                [
                    self._field("antiFrostSetpoint", None),
                    self._field("antiFrostWhenOff", False),
                    self._field("ambientTemperature", 21.76),
                ]
            ),
            None,
        )

        self.assertEqual(len(devices), 1)
        device = devices[0]
        # The transient false must not reach the device...
        self.assertFalse(hasattr(device, "antiFrostWhenOff"))
        # ...while the rest of the frame is still applied.
        self.assertEqual(device.ambientTemperature, 21.76)

    async def test_real_antifrost_change_is_preserved(self) -> None:
        """A genuine frame (numeric setpoint) keeps antiFrostWhenOff=false."""
        devices = await self.handler.parse_devices_data(
            self._response(
                [
                    self._field("antiFrostSetpoint", 5.0),
                    self._field("antiFrostWhenOff", False),
                ]
            ),
            None,
        )

        self.assertEqual(len(devices), 1)
        self.assertIs(devices[0].antiFrostWhenOff, False)

    async def test_partial_frame_without_setpoint_is_untouched(self) -> None:
        """A partial update that omits the setpoint must still apply the flag."""
        devices = await self.handler.parse_devices_data(
            self._response([self._field("antiFrostWhenOff", True)]),
            None,
        )

        self.assertEqual(len(devices), 1)
        self.assertIs(devices[0].antiFrostWhenOff, True)


if __name__ == "__main__":
    import unittest

    unittest.main()
