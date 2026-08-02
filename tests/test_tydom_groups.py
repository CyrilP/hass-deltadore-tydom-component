"""Tests for native TYDOM group discovery."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock


_MISSING = object()
_original_modules: dict[str, object] = {}


def _module(name: str, **attributes) -> types.ModuleType:
    """Install a minimal module required to load protocol code in isolation."""
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
    DOMAIN="deltadore_tydom",
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
TydomGroup = devices_module.TydomGroup

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


class TydomGroupDiscoveryTests(IsolatedAsyncioTestCase):
    """Exercise membership filtering and names derived from TYDOM metadata."""

    def setUp(self) -> None:
        """Reset global protocol metadata."""
        handler_module.groups_metadata.clear()
        handler_module.groups_data.clear()
        handler_module.endpoint_config.clear()
        handler_module.remote_control_info.clear()
        self.handler = MessageHandler(MagicMock(), b"")

    async def test_only_non_empty_supported_total_groups_are_created(self) -> None:
        """Ignore advertised global groups that have no installed members."""
        await self.handler.parse_config_data(
            {
                "endpoints": [],
                "groups": [
                    {
                        "id": 1,
                        "name": "TOTAL",
                        "usage": "awning",
                        "group_all": True,
                    },
                    {
                        "id": 2,
                        "name": "TOTAL",
                        "usage": "light",
                        "group_all": True,
                    },
                    {
                        "id": 3,
                        "name": "TOTAL",
                        "usage": "plug",
                        "group_all": True,
                    },
                    {
                        "id": 4,
                        "name": "TOTAL",
                        "usage": "shutter",
                        "group_all": True,
                    },
                ],
            },
            None,
        )

        groups = await self.handler.parse_groups_file(
            {
                "groups": [
                    {"id": 1, "devices": [], "areas": []},
                    {
                        "id": 2,
                        "devices": [{"id": 20, "endpoints": [{"id": 21}]}],
                        "areas": [],
                    },
                    {"id": 3, "devices": [], "areas": []},
                    {
                        "id": 4,
                        "devices": [{"id": 40, "endpoints": [{"id": 41}]}],
                        "areas": [],
                    },
                ]
            },
            None,
        )

        self.assertTrue(all(isinstance(group, TydomGroup) for group in groups))
        self.assertEqual(
            [
                (group.group_id, group.device_name, group.group_usage)
                for group in groups
            ],
            [
                ("2", "All lights", "light"),
                ("4", "All shutters", "shutter"),
            ],
        )
        self.assertEqual(set(handler_module.groups_data), {"1", "2", "3", "4"})

    async def test_user_group_name_is_preserved(self) -> None:
        """Retain a meaningful name supplied by the user in the Tydom app."""
        await self.handler.parse_config_data(
            {
                "endpoints": [],
                "groups": [
                    {
                        "id": 5,
                        "name": "Ground floor lights",
                        "usage": "light",
                        "group_all": False,
                        "is_group_user": True,
                    }
                ],
            },
            None,
        )

        groups = await self.handler.parse_groups_file(
            {
                "groups": [
                    {
                        "id": 5,
                        "devices": [{"id": 50, "endpoints": [{"id": 50}]}],
                    }
                ]
            },
            None,
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].device_name, "Ground floor lights")

    async def test_non_controllable_relationship_group_is_not_created(self) -> None:
        """Keep relationship metadata without creating a meaningless control."""
        await self.handler.parse_config_data(
            {
                "endpoints": [],
                "groups": [
                    {
                        "id": 6,
                        "name": "Kitchen window",
                        "usage": "windowFrench",
                    }
                ],
            },
            None,
        )

        groups = await self.handler.parse_groups_file(
            {
                "groups": [
                    {
                        "id": 6,
                        "devices": [{"id": 60, "endpoints": [{"id": 60}]}],
                    }
                ]
            },
            None,
        )

        self.assertEqual(groups, [])
        self.assertEqual(handler_module.groups_data["6"]["name"], "Kitchen window")


if __name__ == "__main__":
    import unittest

    unittest.main()
