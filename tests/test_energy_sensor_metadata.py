"""Regression tests for cumulative TYDOM energy sensor metadata."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest import TestCase


def _energy_mapping(name: str) -> dict[str, str]:
    """Return one HAEnergy class mapping without importing Home Assistant."""
    source_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "deltadore_tydom"
        / "ha_entities.py"
    )
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    energy_class = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "HAEnergy"
    )
    assignment = next(
        node
        for node in energy_class.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        )
    )
    assert isinstance(assignment.value, ast.Dict)
    return {
        ast.literal_eval(key): ast.unparse(value)
        for key, value in zip(
            assignment.value.keys, assignment.value.values, strict=True
        )
    }


class EnergySensorMetadataTests(TestCase):
    """Ensure every cumulative heat-pump index is Energy-compatible."""

    def test_cooling_index_matches_heating_and_dhw_metadata(self) -> None:
        """Expose the cooling counter directly to the Energy dashboard."""
        self.assertEqual(
            _energy_mapping("sensor_classes")["energyIndexCoolWatt"],
            "SensorDeviceClass.ENERGY",
        )
        self.assertEqual(
            _energy_mapping("state_classes")["energyIndexCoolWatt"],
            "SensorStateClass.TOTAL_INCREASING",
        )
        self.assertEqual(
            _energy_mapping("units")["energyIndexCoolWatt"],
            "UnitOfEnergy.WATT_HOUR",
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
