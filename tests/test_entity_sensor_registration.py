"""Regression tests for per-device generic sensor registration."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock


def _load_ha_entity_class():
    """Load HAEntity alone without requiring Home Assistant test dependencies."""
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
        if isinstance(node, ast.ClassDef) and node.name == "HAEntity"
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

    class GenericBinarySensor:
        def __init__(self, *_args) -> None:
            pass

    class GenericSensor:
        def __init__(self, *_args) -> None:
            pass

    class BinarySensorDeviceClass:
        PROBLEM = "problem"

    namespace = {
        "Any": object,
        "BinarySensorDeviceClass": BinarySensorDeviceClass,
        "DOMAIN": "deltadore_tydom",
        "LOGGER": MagicMock(),
        "GenericBinarySensor": GenericBinarySensor,
        "GenericSensor": GenericSensor,
        "is_binary_attribute": lambda _device, _attribute, value, _class: isinstance(
            value, bool
        ),
        "is_problem_attribute": lambda attribute: "defect" in attribute.casefold(),
    }
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return namespace["HAEntity"]


HAEntity = _load_ha_entity_class()


class EntitySensorRegistrationTests(TestCase):
    """Ensure generic sensor discovery is isolated between entity instances."""

    @staticmethod
    def _entity(device_id: str, *, supports_generic_sensors: bool = True):
        class Device:
            def __init__(self) -> None:
                self._device_id = device_id
                self.thermicDefect = False

            @property
            def device_id(self) -> str:
                return self._device_id

        entity = HAEntity()
        entity._device = Device()
        if supports_generic_sensors:
            entity._registered_sensors = []
        return entity

    def test_same_attribute_is_registered_for_each_device(self) -> None:
        """One device must not suppress a matching sensor on another device."""
        first = self._entity("gate_1")
        second = self._entity("gate_2")

        self.assertEqual(len(first.get_sensors()), 1)
        self.assertEqual(len(second.get_sensors()), 1)

    def test_attribute_is_not_registered_twice_on_one_device(self) -> None:
        """Repeated discovery for one device must not duplicate its sensor."""
        entity = self._entity("gate_1")

        self.assertEqual(len(entity.get_sensors()), 1)
        self.assertEqual(entity.get_sensors(), [])

    def test_registration_lists_are_not_shared(self) -> None:
        """Every entity wrapper owns its registration state."""
        first = self._entity("switch_1")
        second = self._entity("switch_2")

        first.get_sensors()
        second.get_sensors()

        self.assertIsNot(first._registered_sensors, second._registered_sensors)

    def test_non_sensor_entity_does_not_expose_internal_data(self) -> None:
        """Scenes, groups and events must not gain generic sensors on updates."""
        entity = self._entity("scene_1", supports_generic_sensors=False)

        self.assertEqual(entity.get_sensors(), [])
        self.assertNotIn("_registered_sensors", entity.__dict__)

    def test_smoke_detector_primary_entity_remains_a_smoke_sensor(self) -> None:
        """Binary normalisation must not turn a DFR into a hidden diagnostic."""
        source_path = (
            Path(__file__).parents[1]
            / "custom_components"
            / "deltadore_tydom"
            / "ha_entities.py"
        )
        module = ast.parse(source_path.read_text(encoding="utf-8"))
        smoke_class = next(
            node
            for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == "HASmoke"
        )
        init = next(
            node
            for node in smoke_class.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        assignments = {
            target.attr: ast.unparse(statement.value)
            for statement in init.body
            if isinstance(statement, ast.Assign)
            for target in statement.targets
            if isinstance(target, ast.Attribute)
        }

        self.assertEqual(
            assignments["_attr_device_class"], "BinarySensorDeviceClass.SMOKE"
        )
        self.assertNotIn("_attr_entity_category", assignments)


if __name__ == "__main__":
    import unittest

    unittest.main()
