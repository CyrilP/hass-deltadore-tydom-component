"""Tests for metadata-driven gate and garage cover commands."""

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

TydomGarage = devices_module.TydomGarage
TydomGate = devices_module.TydomGate
TydomShutter = devices_module.TydomShutter

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


def _cover(device_class, commands, *, level_metadata=None, data=None):
    """Create a level-command cover and its mocked client."""
    client = MagicMock()
    client.put_devices_data = AsyncMock()
    metadata = {"levelCmd": {"enum_values": commands}}
    if level_metadata is not None:
        metadata["level"] = level_metadata
    device = device_class(
        client,
        "10_20",
        "20",
        "Garage",
        "garage_door",
        "10",
        metadata,
        data,
    )
    return device, client


def _position_cover(usage: str):
    """Create a position-command cover for one Delta Dore usage."""
    client = MagicMock()
    client.put_devices_data = AsyncMock()
    device = TydomShutter(
        client,
        "10_20",
        "20",
        "Cover",
        usage,
        "10",
        {"positionCmd": {"permission": "w"}},
        {"position": 0},
    )
    return device, client


class LevelCommandCoverTests(IsolatedAsyncioTestCase):
    """Exercise directional and pulse-only cover receivers."""

    async def test_toggle_only_garage_only_exposes_stateless_pulse(self) -> None:
        """A Tyxia pulse receiver does not claim directional commands."""
        garage, client = _cover(TydomGarage, ["TOGGLE"])

        self.assertEqual(
            garage.cover_capabilities,
            devices_module.TydomCoverCapabilities(
                open=False,
                close=False,
                stop=False,
                toggle=True,
                set_position=False,
            ),
        )
        self.assertTrue(garage.is_toggle_only)

        await garage.toggle()
        with self.assertRaisesRegex(ValueError, "does not support ON"):
            await garage.open()
        with self.assertRaisesRegex(ValueError, "does not support OFF"):
            await garage.close()
        with self.assertRaisesRegex(ValueError, "does not support STOP"):
            await garage.stop()

        self.assertEqual(
            client.put_devices_data.await_args_list,
            [call("20", "10", "levelCmd", "TOGGLE")],
        )

    async def test_full_garage_uses_each_advertised_command(self) -> None:
        """A feedback-capable garage retains directional and position controls."""
        garage, client = _cover(
            TydomGarage,
            ["ON", "OFF", "STOP", "TOGGLE"],
            level_metadata={"permission": "rw", "min": 0, "max": 100},
            data={"level": 0},
        )

        self.assertEqual(
            garage.cover_capabilities,
            devices_module.TydomCoverCapabilities(
                open=True,
                close=True,
                stop=True,
                toggle=True,
                set_position=True,
            ),
        )
        self.assertFalse(garage.is_toggle_only)

        await garage.open()
        await garage.close()
        await garage.stop()
        await garage.toggle()
        await garage.set_level(100)

        self.assertEqual(
            client.put_devices_data.await_args_list,
            [
                call("20", "10", "levelCmd", "ON"),
                call("20", "10", "levelCmd", "OFF"),
                call("20", "10", "levelCmd", "STOP"),
                call("20", "10", "levelCmd", "TOGGLE"),
                call("20", "10", "level", "100"),
            ],
        )

    async def test_directional_receiver_does_not_claim_toggle_or_stop(self) -> None:
        """Capabilities do not expose commands omitted by gateway metadata."""
        garage, client = _cover(TydomGarage, ["ON", "OFF"])

        self.assertTrue(garage.cover_capabilities.open)
        self.assertTrue(garage.cover_capabilities.close)
        self.assertFalse(garage.cover_capabilities.stop)
        self.assertFalse(garage.cover_capabilities.toggle)

        await garage.open()
        await garage.close()
        with self.assertRaisesRegex(ValueError, "does not support TOGGLE"):
            await garage.toggle()

        self.assertEqual(
            client.put_devices_data.await_args_list,
            [
                call("20", "10", "levelCmd", "ON"),
                call("20", "10", "levelCmd", "OFF"),
            ],
        )

    async def test_read_only_level_does_not_enable_position_writes(self) -> None:
        """Position is exposed only when level feedback is also writable."""
        garage, _client = _cover(
            TydomGarage,
            ["ON", "OFF"],
            level_metadata={"permission": "r", "min": 0, "max": 100},
            data={"level": 0},
        )

        self.assertFalse(garage.cover_capabilities.set_position)

    async def test_gate_uses_the_same_stateless_pulse_model(self) -> None:
        """Gate and garage pulse receivers share identical semantics."""
        gate, client = _cover(TydomGate, ["TOGGLE"])

        self.assertFalse(gate.cover_capabilities.open)
        self.assertFalse(gate.cover_capabilities.close)
        self.assertTrue(gate.cover_capabilities.toggle)
        self.assertTrue(gate.is_toggle_only)

        await gate.toggle()

        self.assertEqual(
            client.put_devices_data.await_args_list,
            [call("20", "10", "levelCmd", "TOGGLE")],
        )

    async def test_shutter_open_and_close_use_up_and_down(self) -> None:
        """A shutter opens upwards and closes downwards."""
        shutter, client = _position_cover("shutter")

        self.assertEqual(shutter.position_from_tydom(100), 100)
        await shutter.open()
        await shutter.close()

        self.assertEqual(
            client.put_devices_data.await_args_list,
            [
                call("20", "10", "positionCmd", "UP"),
                call("20", "10", "positionCmd", "DOWN"),
            ],
        )

    async def test_awning_open_and_close_deploy_and_retract(self) -> None:
        """An awning opens downwards and closes upwards."""
        awning, client = _position_cover("awning")

        self.assertEqual(awning.position_from_tydom(100), 0)
        self.assertEqual(awning.position_from_tydom(0), 100)
        await awning.open()
        await awning.close()
        await awning.set_position(25)

        self.assertEqual(
            client.put_devices_data.await_args_list,
            [
                call("20", "10", "positionCmd", "DOWN"),
                call("20", "10", "positionCmd", "UP"),
                call("20", "10", "position", "75"),
            ],
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
