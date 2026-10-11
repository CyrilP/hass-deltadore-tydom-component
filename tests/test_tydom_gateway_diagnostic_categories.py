"""Regression tests for technical TYDOM gateway entity categories."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase


def _load_generic_sensor_classes():
    """Load generic entity constructors with minimal Home Assistant stubs."""
    source_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "deltadore_tydom"
        / "ha_entities.py"
    )
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    class_names = {"GenericSensor", "BinarySensorBase", "GenericBinarySensor"}
    selected_nodes = [
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name in class_names
    ]
    isolated_module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            *selected_nodes,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(isolated_module)

    class SensorEntity:
        pass

    class BinarySensorEntity:
        pass

    class SensorDeviceClass:
        BATTERY = "battery"

    class BinarySensorDeviceClass:
        PROBLEM = "problem"
        UPDATE = "update"

    class EntityCategory:
        DIAGNOSTIC = "diagnostic"

    class Tydom:
        """Stand-in for the TYDOM gateway device class."""

    namespace = {
        "SensorEntity": SensorEntity,
        "BinarySensorEntity": BinarySensorEntity,
        "SensorDeviceClass": SensorDeviceClass,
        "BinarySensorDeviceClass": BinarySensorDeviceClass,
        "EntityCategory": EntityCategory,
        "Tydom": Tydom,
        "SensorEntityDescription": lambda **kwargs: SimpleNamespace(**kwargs),
        "BinarySensorEntityDescription": lambda **kwargs: SimpleNamespace(**kwargs),
        "PERCENTAGE": "%",
        "set_entity_name": lambda *_args, **_kwargs: None,
        "normalize_binary_state": lambda value, **_kwargs: (
            value if isinstance(value, bool) else None
        ),
    }
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return (
        namespace["GenericSensor"],
        namespace["GenericBinarySensor"],
        EntityCategory,
        Tydom,
    )


GenericSensor, GenericBinarySensor, EntityCategory, Tydom = (
    _load_generic_sensor_classes()
)


class TydomGatewayDiagnosticCategoryTests(TestCase):
    """Technical gateway readings remain usable while grouped as diagnostics."""

    SENSOR_ATTRIBUTES = (
        "bddStatus",
        "grp_proto.json",
        "javaVersion",
        "mainVersionSW",
        "oryxVersion",
        "urlMediation",
        "zigbeeReference",
        "zigbeeVersionSW",
    )
    BINARY_SENSOR_ATTRIBUTES = ("apiMode", "pltRegistered", "updateAvailable")

    # Firmware/library versions and identifiers reported by the gateway that are
    # not individually listed in ``diagnostic_attrs`` but must still be grouped
    # as diagnostics rather than surfaced as regular sensors.
    UNLISTED_GATEWAY_ATTRIBUTES = (
        "libwebsocketsVersion",
        "LwIPVersion",
        "MbedTLSVersion",
        "siteId",
    )

    def test_technical_gateway_sensors_keep_identity_and_value(self) -> None:
        """Moving gateway metadata must not change IDs or reported values."""
        for attribute in self.SENSOR_ATTRIBUTES:
            with self.subTest(attribute=attribute):
                value = f"value-{attribute}"
                device = SimpleNamespace(device_id="gateway_072a1f")
                setattr(device, attribute, value)

                entity = GenericSensor(
                    device,
                    None,
                    None,
                    attribute,
                    attribute,
                    None,
                )

                self.assertEqual(
                    entity._attr_entity_category, EntityCategory.DIAGNOSTIC
                )
                self.assertEqual(entity._attr_unique_id, f"gateway_072a1f_{attribute}")
                self.assertEqual(entity.native_value, value)

    def test_technical_gateway_binary_sensors_keep_identity_and_state(self) -> None:
        """System flags are diagnostic without changing their binary state."""
        for attribute in self.BINARY_SENSOR_ATTRIBUTES:
            with self.subTest(attribute=attribute):
                device = SimpleNamespace(device_id="gateway_072a1f")
                setattr(device, attribute, True)

                entity = GenericBinarySensor(
                    device,
                    None,
                    attribute,
                    attribute,
                )

                self.assertEqual(
                    entity._attr_entity_category, EntityCategory.DIAGNOSTIC
                )
                self.assertEqual(entity._attr_unique_id, f"gateway_072a1f_{attribute}")
                self.assertTrue(entity.is_on)

    def test_unlisted_gateway_sensors_are_diagnostic(self) -> None:
        """Gateway firmware fields absent from the list are still diagnostic."""
        for attribute in self.UNLISTED_GATEWAY_ATTRIBUTES:
            with self.subTest(attribute=attribute):
                self.assertNotIn(attribute, GenericSensor.diagnostic_attrs)
                value = f"value-{attribute}"
                device = Tydom()
                device.device_id = "gateway_072a1f"
                setattr(device, attribute, value)

                entity = GenericSensor(
                    device,
                    None,
                    None,
                    attribute,
                    attribute,
                    None,
                )

                self.assertEqual(
                    entity._attr_entity_category, EntityCategory.DIAGNOSTIC
                )
                self.assertEqual(entity.native_value, value)

    def test_non_gateway_generic_sensor_is_not_diagnostic(self) -> None:
        """Ordinary device readings keep their default (non-diagnostic) category."""
        attribute = "libwebsocketsVersion"
        self.assertNotIn(attribute, GenericSensor.diagnostic_attrs)
        device = SimpleNamespace(device_id="shutter_0a1b2c")
        setattr(device, attribute, "irrelevant")

        entity = GenericSensor(device, None, None, attribute, attribute, None)

        self.assertIsNone(getattr(entity, "_attr_entity_category", None))


if __name__ == "__main__":
    import unittest

    unittest.main()
