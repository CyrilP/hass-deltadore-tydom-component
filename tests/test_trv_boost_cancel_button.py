"""Tests for the area-backed TRV Boost cancellation button."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock


def _load_cancel_boost_button():
    """Load the button class without importing Home Assistant."""
    source_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "deltadore_tydom"
        / "ha_entities.py"
    )
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    class_node = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "HACancelBoostButton"
    )
    isolated_module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            class_node,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(isolated_module)

    class ButtonEntity:
        @property
        def available(self) -> bool:
            return True

        async def async_added_to_hass(self) -> None:
            pass

        async def async_will_remove_from_hass(self) -> None:
            pass

    class HAEntity:
        def _get_device_info(self) -> dict[str, str]:
            return {"manufacturer": "Delta Dore", "model": "TRV 1.0"}

        def _enrich_device_info(self, info):
            return info

    namespace = {
        "ButtonEntity": ButtonEntity,
        "DeviceInfo": dict,
        "DOMAIN": "deltadore_tydom",
        "HAEntity": HAEntity,
        "TydomBoiler": object,
    }
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return namespace["HACancelBoostButton"]


HACancelBoostButton = _load_cancel_boost_button()


class CancelBoostButtonTests(IsolatedAsyncioTestCase):
    """Exercise the native area TRV Boost cancellation button."""

    async def test_button_tracks_boost_state_and_cancels_it(self) -> None:
        """The button is actionable only during Boost and calls no other action."""
        device = SimpleNamespace(
            device_id="trv_device",
            device_name="Radiator head",
            boost_active=True,
            cancel_boost=AsyncMock(),
            register_callback=lambda callback: None,
            remove_callback=lambda callback: None,
        )
        button = HACancelBoostButton(device, SimpleNamespace())

        self.assertTrue(button.available)
        await button.async_press()
        device.cancel_boost.assert_awaited_once_with()

        device.boost_active = False
        self.assertFalse(button.available)
        self.assertEqual(button._attr_unique_id, "trv_device_cancel_boost")
        self.assertEqual(button._attr_translation_key, "cancel_boost")
        self.assertEqual(
            button.device_info["identifiers"],
            {("deltadore_tydom", "trv_device")},
        )
