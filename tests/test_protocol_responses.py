"""Tests for Tydom protocol response handling."""

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

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


class ProtocolResponseTests(IsolatedAsyncioTestCase):
    """Exercise response acknowledgements and light refresh polling."""

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


if __name__ == "__main__":
    import unittest

    unittest.main()
