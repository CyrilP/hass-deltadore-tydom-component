"""Tests for expected and repeated TYDOM endpoint responses."""

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


class EndpointLoggingTests(IsolatedAsyncioTestCase):
    """Exercise captured Calybox response shapes and warning throttling."""

    def setUp(self) -> None:
        """Reset protocol registries and logging."""
        logger.reset_mock()
        handler_module.device_name.clear()
        handler_module.device_type.clear()
        handler_module.device_metadata.clear()
        self.handler = MessageHandler(MagicMock(), b"")

    @staticmethod
    def _response(error: int = 0, data: list[dict] | None = None) -> list[dict]:
        """Build one endpoint response."""
        return [
            {
                "id": 20,
                "endpoints": [
                    {
                        "id": 10,
                        "error": error,
                        "data": [] if data is None else data,
                    }
                ],
            }
        ]

    async def test_cdata_consumption_endpoint_does_not_warn(self) -> None:
        """An empty Calybox consumption endpoint is an expected response."""
        uid = "10_20"
        handler_module.device_name[uid] = "Consumption"
        handler_module.device_type[uid] = "conso"

        devices = await self.handler.parse_devices_data(self._response(), None)

        logger.warning.assert_not_called()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].device_name, "Consumption")

    async def test_repeated_empty_heating_endpoint_is_rate_limited(self) -> None:
        """A temporarily silent heating zone must not flood HA warnings."""
        uid = "10_20"
        handler_module.device_name[uid] = "Bedrooms"
        handler_module.device_type[uid] = "boiler"
        handler_module.device_metadata[uid] = {
            "thermicLevel": {"permission": "rw"}
        }

        for _ in range(12):
            await self.handler.parse_devices_data(self._response(), None)

        warning_counts = [call.args[-1] for call in logger.warning.call_args_list]
        self.assertEqual(warning_counts, [1, 10])

    async def test_error_does_not_emit_a_second_missing_data_warning(self) -> None:
        """One errored response represents one issue, not two warnings."""
        uid = "10_20"
        handler_module.device_name[uid] = "Bedrooms"
        handler_module.device_type[uid] = "boiler"
        handler_module.device_metadata[uid] = {
            "thermicLevel": {"permission": "rw"}
        }

        await self.handler.parse_devices_data(self._response(error=5), None)

        logger.warning.assert_called_once()
        self.assertEqual(logger.warning.call_args.args[1], "reported an error")
        self.assertEqual(logger.warning.call_args.args[-2], 5)

    async def test_different_error_codes_remain_visible(self) -> None:
        """A new gateway error code starts its own diagnostic series."""
        uid = "10_20"
        handler_module.device_name[uid] = "Bedrooms"
        handler_module.device_type[uid] = "boiler"
        handler_module.device_metadata[uid] = {
            "thermicLevel": {"permission": "rw"}
        }

        await self.handler.parse_devices_data(self._response(error=1), None)
        await self.handler.parse_devices_data(self._response(error=5), None)

        self.assertEqual(logger.warning.call_count, 2)


if __name__ == "__main__":
    import unittest

    unittest.main()
