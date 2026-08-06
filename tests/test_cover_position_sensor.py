"""Regression tests for cover position diagnostic sensors."""

from __future__ import annotations

import ast
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase


def _load_generic_sensor_class():
    """Load GenericSensor without importing Home Assistant."""
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
        if isinstance(node, ast.ClassDef) and node.name == "GenericSensor"
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

    class SensorEntity:
        pass

    class SensorDeviceClass:
        BATTERY = "battery"

    class EntityCategory:
        DIAGNOSTIC = "diagnostic"

    class SensorEntityDescription:
        def __init__(self, **kwargs) -> None:
            self.__dict__.update(kwargs)

    namespace = {
        "DOMAIN": "deltadore_tydom",
        "EntityCategory": EntityCategory,
        "SensorDeviceClass": SensorDeviceClass,
        "SensorEntity": SensorEntity,
        "SensorEntityDescription": SensorEntityDescription,
        "ranged_value_to_percentage": lambda _range, value: value,
        "suppress": suppress,
    }
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return namespace["GenericSensor"]


GenericSensor = _load_generic_sensor_class()


class CoverPositionSensorTests(TestCase):
    """Exercise translation of raw cover positions shown as sensors."""

    @staticmethod
    def _sensor(device):
        return GenericSensor(device, None, None, "Position", "position", "%")

    def test_awning_position_uses_home_assistant_semantics(self) -> None:
        """Convert the raw retracted percentage exposed by an awning."""
        device = SimpleNamespace(
            device_id="awning_1",
            position="64",
            position_from_tydom=lambda position: 100 - position,
        )

        self.assertEqual(self._sensor(device).native_value, 36)

    def test_shutter_position_remains_unchanged(self) -> None:
        """Do not invert the position of an ordinary shutter."""
        device = SimpleNamespace(
            device_id="shutter_1",
            position=64,
            position_from_tydom=lambda position: position,
        )

        self.assertEqual(self._sensor(device).native_value, 64)


if __name__ == "__main__":
    import unittest

    unittest.main()
