"""Tests for the TYXAL alarm acknowledgement button."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock


def _load_acknowledgement_button():
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
        if isinstance(node, ast.ClassDef) and node.name == "HAAlarmAcknowledgeButton"
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
        pass

    class HAEntity:
        def _get_device_info(self) -> dict[str, str]:
            return {"manufacturer": "Delta Dore", "model": "CS 8000"}

        def _enrich_device_info(self, info):
            return info

    namespace = {
        "ButtonEntity": ButtonEntity,
        "DeviceInfo": dict,
        "DOMAIN": "deltadore_tydom",
        "HAEntity": HAEntity,
        "TydomAlarm": object,
    }
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return namespace["HAAlarmAcknowledgeButton"]


HAAlarmAcknowledgeButton = _load_acknowledgement_button()


class AlarmAcknowledgeButtonTests(IsolatedAsyncioTestCase):
    """Exercise the native acknowledgement button."""

    async def test_press_acknowledges_events_without_requesting_a_pin(self) -> None:
        """A press must call the existing pin-free acknowledgement command."""
        device = SimpleNamespace(
            device_id="alarm_device",
            device_name="TYXAL Alarm",
            acknowledge_events=AsyncMock(),
        )
        button = HAAlarmAcknowledgeButton(device, SimpleNamespace())

        await button.async_press()

        device.acknowledge_events.assert_awaited_once_with()
        self.assertEqual(button._attr_unique_id, "alarm_device_acknowledge_events")
        self.assertEqual(button._attr_translation_key, "acknowledge_events")
        self.assertEqual(
            button.device_info["identifiers"],
            {("deltadore_tydom", "alarm_device")},
        )
