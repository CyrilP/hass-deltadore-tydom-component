"""Tests for preserving thermostat setpoints across HVAC mode changes."""

import importlib.util
from pathlib import Path
import sys
import types
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, call


_MISSING = object()
_original_modules: dict[str, object] = {}


def _module(name: str, **attributes) -> types.ModuleType:
    """Install a minimal module needed to load protocol devices in isolation."""
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

_module(
    "custom_components.deltadore_tydom.const",
    LOGGER=MagicMock(),
    validate_value_with_metadata=MagicMock(return_value=(True, None)),
)

module_name = "custom_components.deltadore_tydom.tydom.tydom_devices"
module_path = (
    Path(__file__).parents[1]
    / "custom_components"
    / "deltadore_tydom"
    / "tydom"
    / "tydom_devices.py"
)
spec = importlib.util.spec_from_file_location(module_name, module_path)
assert spec is not None and spec.loader is not None
devices_module = importlib.util.module_from_spec(spec)
_original_modules.setdefault(module_name, sys.modules.get(module_name, _MISSING))
sys.modules[module_name] = devices_module
spec.loader.exec_module(devices_module)

TydomBoiler = devices_module.TydomBoiler

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


def _boiler(*, metadata, data):
    """Create a thermostat and its mocked client."""
    client = MagicMock()
    client.put_devices_data = AsyncMock()
    client.put_home_hvac_mode = AsyncMock()
    device = TydomBoiler(
        client,
        "10_20",
        "20",
        "Thermostat",
        "boiler",
        "10",
        metadata,
        data,
    )
    return device, client


class ClimateSetpointPreservationTests(IsolatedAsyncioTestCase):
    """Ensure mode-only commands leave the device-owned setpoint untouched."""

    async def test_standard_thermostat_keeps_setpoint_when_toggled(self) -> None:
        """Off and heat commands must not clear or replace the last setpoint."""
        device, client = _boiler(
            metadata={
                "hvacMode": {"enum_values": ["STOP", "NORMAL"]},
                "setpoint": {"min": 5, "max": 30, "step": 0.5},
            },
            data={"hvacMode": "NORMAL", "setpoint": 21.5},
        )

        await device.set_hvac_mode("STOP")
        await device.set_hvac_mode("NORMAL")

        self.assertEqual(
            client.put_devices_data.await_args_list,
            [
                call("20", "10", "hvacMode", "STOP"),
                call("20", "10", "antifrostOn", True),
                call("20", "10", "hvacMode", "NORMAL"),
                call("20", "10", "antifrostOn", False),
            ],
        )
        self.assertEqual(device.setpoint, 21.5)

    async def test_zone_thermostat_keeps_heating_and_cooling_setpoints(self) -> None:
        """Changing a zone direction must not inject a synthetic temperature."""
        device, client = _boiler(
            metadata={
                "authorization": {"enum_values": ["STOP", "HEATING", "COOLING"]},
                "setpoint": {"min": 5, "max": 30, "step": 0.5},
            },
            data={
                "authorization": "STOP",
                "thermicLevel": "STOP",
                "setpoint": 22.5,
            },
        )

        await device.set_hvac_mode("NORMAL")
        await device.set_hvac_mode("COOLING")

        self.assertEqual(
            client.put_home_hvac_mode.await_args_list,
            [call("HEATING"), call("COOLING")],
        )
        self.assertEqual(
            client.put_devices_data.await_args_list,
            [
                call("20", "10", "thermicLevel", ""),
                call("20", "10", "thermicLevel", ""),
            ],
        )
        self.assertEqual(device.setpoint, 22.5)

    async def test_antifrost_does_not_clear_standard_setpoint(self) -> None:
        """Frost-protection mode must preserve the user's heating target."""
        device, client = _boiler(
            metadata={
                "hvacMode": {"enum_values": ["STOP", "NORMAL", "ANTI_FROST"]},
                "setpoint": {"min": 5, "max": 30, "step": 0.5},
            },
            data={"hvacMode": "NORMAL", "setpoint": 20},
        )

        await device.set_hvac_mode("ANTI_FROST")

        self.assertEqual(
            client.put_devices_data.await_args_list,
            [
                call("20", "10", "thermicLevel", "STOP"),
                call("20", "10", "hvacMode", "ANTI_FROST"),
                call("20", "10", "antifrostOn", True),
            ],
        )
        self.assertEqual(device.setpoint, 20)


if __name__ == "__main__":
    import unittest

    unittest.main()
