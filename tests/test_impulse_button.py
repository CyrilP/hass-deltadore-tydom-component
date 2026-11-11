"""Exercise Home Assistant registration of stateless pulse devices."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

from test_tyxia_4910 import MessageHandler, TydomDevice, devices_module, handler_module


def _load_button_and_factory():
    """Exercise the actual HA button and hub factory without Home Assistant."""
    root = Path(__file__).parents[1] / "custom_components" / "deltadore_tydom"
    entities_path = root / "ha_entities.py"
    hub_path = root / "hub.py"
    entities_tree = ast.parse(entities_path.read_text(encoding="utf-8"))
    hub_tree = ast.parse(hub_path.read_text(encoding="utf-8"))
    button = next(
        node
        for node in entities_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "HAButton"
    )
    hub_class = next(
        node
        for node in hub_tree.body
        if isinstance(node, ast.ClassDef)
        and any(
            isinstance(item, ast.AsyncFunctionDef)
            and item.name == "_create_impulse_device"
            for item in node.body
        )
    )
    factory = next(
        item
        for item in hub_class.body
        if getattr(item, "name", None) == "_create_impulse_device"
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            button,
            factory,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)

    class ButtonEntity:
        pass

    class HAEntity:
        def get_sensors(self):
            return []

    namespace = {
        "ButtonEntity": ButtonEntity,
        "HAEntity": HAEntity,
        "inspect": inspect,
        "set_entity_name": MagicMock(),
    }
    exec(compile(module, str(entities_path), "exec"), namespace)
    return namespace["HAButton"], namespace["_create_impulse_device"]


class ImpulseButtonTests(IsolatedAsyncioTestCase):
    """Verify the pulse button created by the hub."""

    async def test_factory_registers_neutral_button_and_press_sends_toggle(self):
        """Register a stable, neutral button that sends one TOGGLE."""
        button_class, create = _load_button_and_factory()
        create.__globals__["HAButton"] = button_class
        client = SimpleNamespace(put_devices_data=AsyncMock())
        device = devices_module.TydomImpulse(
            client,
            "40_30",
            "30",
            "Shutter",
            "others",
            "40",
            {"levelCmd": {"enum_values": ["TOGGLE"]}},
            {},
        )
        hub = SimpleNamespace(
            _hass=MagicMock(),
            add_button_callback=MagicMock(),
            ha_devices={},
            _add_discovered_entities=MagicMock(),
        )

        await create(hub, device)

        button = hub.add_button_callback.call_args.args[0][0]
        self.assertIsInstance(button, button_class)
        self.assertIs(hub.ha_devices["40_30"], button)
        self.assertEqual(button._attr_unique_id, "40_30_button_Toggle")
        self.assertEqual(button._attr_icon, "mdi:button-cursor")
        self.assertIsNone(button._attr_name)
        await button.async_press()
        client.put_devices_data.assert_awaited_once_with(
            "30", "40", "levelCmd", "TOGGLE"
        )


class StatelessOtherPulseTests(IsolatedAsyncioTestCase):
    """Detect only the reported stateless Other profile."""

    def setUp(self) -> None:
        """Reset shared metadata for each case."""
        handler_module.device_metadata.clear()
        handler_module.device_tutorial_id.clear()

    async def _discover(self, metadata, *, data=None, usage="others"):
        client = MagicMock()
        client.put_devices_data = AsyncMock()
        uid = "40_30"
        handler_module.device_metadata[uid] = metadata
        device = await MessageHandler.get_device(
            client, usage, uid, "30", "Impulse", "40", data
        )
        return device, client

    async def test_toggle_only_sends_a_single_pulse(self) -> None:
        """The reported endpoint gets a neutral button-capable pulse device."""
        for metadata in (
            {"levelCmd": {"enum_values": ["TOGGLE"]}},
            {"levelCmd": {"permission": "w", "enum_values": ["TOGGLE"]}},
        ):
            with self.subTest(metadata=metadata):
                device, client = await self._discover(metadata)
                self.assertIs(type(device), devices_module.TydomImpulse)
                await device.toggle()
                client.put_devices_data.assert_awaited_once_with(
                    "30", "40", "levelCmd", "TOGGLE"
                )

    async def test_other_profiles_are_not_reclassified(self) -> None:
        """Keep directional, stateful, read-only and malformed profiles unchanged."""
        cases = (
            ({"levelCmd": {"enum_values": ["TOGGLE", "ON"]}}, None),
            ({"levelCmd": {"enum_values": ["TOGGLE", "FAVORIT1"]}}, None),
            ({"levelCmd": {"permission": "r", "enum_values": ["TOGGLE"]}}, None),
            ({"levelCmd": {"enum_values": "TOGGLE"}}, None),
            ({"levelCmd": {"enum_values": ["TOGGLE"]}, "level": {}}, None),
            ({"levelCmd": {"enum_values": ["TOGGLE"]}, "positionCmd": {}}, None),
            ({"levelCmd": {"enum_values": ["TOGGLE"]}}, {"state": "ON"}),
            ({"levelCmd": {"enum_values": ["TOGGLE"]}}, {"position": 50}),
        )
        for metadata, data in cases:
            with self.subTest(metadata=metadata, data=data):
                device, client = await self._discover(metadata, data=data)
                self.assertIs(type(device), TydomDevice)
                client.put_devices_data.assert_not_awaited()

    async def test_gate_and_garage_usages_keep_existing_classes(self) -> None:
        """Other detection never changes existing gate/garage classification."""
        for usage, expected in (
            ("gate", devices_module.TydomGate),
            ("garage_door", devices_module.TydomGarage),
        ):
            with self.subTest(usage=usage):
                device, _ = await self._discover(
                    {"levelCmd": {"enum_values": ["TOGGLE"]}}, usage=usage
                )
                self.assertIs(type(device), expected)
