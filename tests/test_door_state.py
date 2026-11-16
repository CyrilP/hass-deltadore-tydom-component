"""Regression tests for the door cover state and icon."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock


def _load_door_class():
    """Load HaDoor in isolation without importing Home Assistant."""
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
        if isinstance(node, ast.ClassDef) and node.name == "HaDoor"
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

    class CoverEntity:
        pass

    class HAEntity:
        pass

    class CoverDeviceClass:
        DOOR = "door"

    class CoverEntityFeature(int):
        OPEN = 1
        CLOSE = 2

        def __or__(self, other):
            return CoverEntityFeature(int(self) | int(other))

    namespace = {
        "Any": object,
        "CoverDeviceClass": CoverDeviceClass,
        "CoverEntity": CoverEntity,
        "CoverEntityFeature": CoverEntityFeature(0),
        "DOMAIN": "deltadore_tydom",
        "DeviceInfo": dict,
        "HAEntity": HAEntity,
        "LOGGER": MagicMock(),
        "TydomDoor": object,
        "get_consumed_opening_attrs": MagicMock(),
    }
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return namespace["HaDoor"]


HaDoor = _load_door_class()


class DoorStateTests(TestCase):
    """Verify the door reports a state only when the gateway provided one."""

    @staticmethod
    def _door(**attributes):
        entity = HaDoor.__new__(HaDoor)
        entity._device = SimpleNamespace(device_id=1, **attributes)
        return entity

    def test_pod_position_maps_closed_and_locked_to_closed(self) -> None:
        """CLOSE and LOCK are closed; OPEN is open."""
        self.assertTrue(self._door(podPosition="CLOSE").is_closed)
        self.assertTrue(self._door(podPosition="LOCK").is_closed)
        self.assertFalse(self._door(podPosition="OPEN").is_closed)

    def test_open_state_maps_locked_to_closed(self) -> None:
        """Only LOCKED is closed for openState doors."""
        self.assertTrue(self._door(openState="LOCKED").is_closed)
        self.assertFalse(self._door(openState="UNLOCKED").is_closed)

    def test_intrusion_detect_maps_to_inverted_closed_state(self) -> None:
        """An intrusionDetect door is closed while no intrusion is reported."""
        self.assertTrue(self._door(intrusionDetect=False).is_closed)
        self.assertFalse(self._door(intrusionDetect=True).is_closed)

    def test_missing_attributes_report_unknown_instead_of_raising(self) -> None:
        """A door that reported nothing yet must not crash the entity."""
        self.assertIsNone(self._door().is_closed)

    def test_attributes_present_without_a_value_report_unknown(self) -> None:
        """A None value is not evidence that the door is open or closed."""
        self.assertIsNone(self._door(podPosition=None).is_closed)
        self.assertIsNone(self._door(openState=None).is_closed)
        self.assertIsNone(self._door(intrusionDetect=None).is_closed)

    def test_attribute_priority_is_unchanged(self) -> None:
        """The podPosition attribute still wins over the two other attributes."""
        door = self._door(podPosition="CLOSE", openState="UNLOCKED", intrusionDetect=1)

        self.assertTrue(door.is_closed)

    def test_unknown_state_keeps_the_neutral_door_icon(self) -> None:
        """An unknown door must not be drawn as open."""
        self.assertEqual(self._door().icon, "mdi:door")
        self.assertEqual(self._door(openState=None).icon, "mdi:door")

    def test_known_states_pick_the_matching_icon(self) -> None:
        """Closed and open doors keep their dedicated icons."""
        self.assertEqual(self._door(podPosition="LOCK").icon, "mdi:door-closed")
        self.assertEqual(self._door(podPosition="OPEN").icon, "mdi:door-open")
