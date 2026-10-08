"""Tests for the optional humidity value exposed by climate entities."""

import ast
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase


def _load_current_humidity_property():
    """Load the HaClimate humidity property without importing Home Assistant."""
    source_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "deltadore_tydom"
        / "ha_entities.py"
    )
    source = ast.parse(source_path.read_text(encoding="utf-8"))
    climate_class = next(
        node
        for node in source.body
        if isinstance(node, ast.ClassDef) and node.name == "HaClimate"
    )
    humidity_property = next(
        node
        for node in climate_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "current_humidity"
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="contextlib",
                names=[ast.alias(name="suppress")],
                level=0,
            ),
            ast.ClassDef(
                name="ClimateProbe",
                bases=[],
                keywords=[],
                body=[humidity_property],
                decorator_list=[],
            ),
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace = {"suppress": suppress}
    exec(compile(module, source_path, "exec"), namespace)
    return namespace["ClimateProbe"]


ClimateProbe = _load_current_humidity_property()


class ClimateCurrentHumidityTests(TestCase):
    """Verify humidity is exposed only when its metadata is advertised."""

    def test_returns_fractional_humidity_without_rounding(self) -> None:
        """Keep the precision reported by the gateway metadata."""
        entity = ClimateProbe()
        entity._device = SimpleNamespace(
            _metadata={"hygroIn": {"unit": "%", "step": 0.1}},
            hygroIn=56.7,
        )

        self.assertEqual(entity.current_humidity, 56.7)

    def test_returns_none_when_humidity_is_not_advertised(self) -> None:
        """Do not expose a humidity value unsupported by the device metadata."""
        entity = ClimateProbe()
        entity._device = SimpleNamespace(_metadata={}, hygroIn=56.7)

        self.assertIsNone(entity.current_humidity)

    def test_returns_none_when_the_advertised_value_is_unavailable(self) -> None:
        """Handle devices that advertise humidity before a value arrives."""
        entity = ClimateProbe()
        entity._device = SimpleNamespace(_metadata={"hygroIn": {}})

        self.assertIsNone(entity.current_humidity)

    def test_returns_none_for_a_non_numeric_humidity_value(self) -> None:
        """Ignore malformed gateway values instead of breaking entity updates."""
        entity = ClimateProbe()
        entity._device = SimpleNamespace(
            _metadata={"hygroIn": {}}, hygroIn="unavailable"
        )

        self.assertIsNone(entity.current_humidity)
