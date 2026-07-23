"""Tests for TYDOM scene activation."""

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

_module(
    "custom_components.deltadore_tydom.const",
    LOGGER=MagicMock(),
    validate_value_with_metadata=MagicMock(return_value=(True, None)),
)

devices_path = (
    Path(__file__).parents[1]
    / "custom_components"
    / "deltadore_tydom"
    / "tydom"
    / "tydom_devices.py"
)
devices_spec = importlib.util.spec_from_file_location(
    "custom_components.deltadore_tydom.tydom.tydom_devices", devices_path
)
assert devices_spec is not None and devices_spec.loader is not None
devices_module = importlib.util.module_from_spec(devices_spec)
_original_modules.setdefault(
    devices_spec.name, sys.modules.get(devices_spec.name, _MISSING)
)
sys.modules[devices_spec.name] = devices_module
devices_spec.loader.exec_module(devices_module)

TydomScene = devices_module.TydomScene

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


class TydomSceneTests(IsolatedAsyncioTestCase):
    """Exercise scene activation used by Tywell shutter controls."""

    async def test_scene_activation_uses_scenario_endpoint(self) -> None:
        """A scene delegates activation using its scenario identifier."""
        client = MagicMock()
        client.activate_scenario = AsyncMock()
        scene = TydomScene(
            client,
            "scene_42",
            "42",
            "TWC_STOP",
            "scene",
            None,
            None,
            {"scene_id": 42},
        )

        await scene.activate()

        client.activate_scenario.assert_awaited_once_with(42)


if __name__ == "__main__":
    import unittest

    unittest.main()
