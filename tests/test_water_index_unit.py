"""Tests for the TYDOM total water counter sensor."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from test_entity_sensor_registration import HAEntity
from test_cover_position_sensor import _load_generic_sensor_class


class _Constants(type):
    """Provide distinct Home Assistant enum values to the isolated class."""

    def __getattr__(cls, name):
        return f"{cls.__name__}.{name}"


def _load_energy_entity():
    """Load the production energy entity with lightweight HA constants."""
    path = (
        Path(__file__).parents[1] / "custom_components/deltadore_tydom/ha_entities.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    energy = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "HAEnergy"
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            energy,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace = {"HAEntity": HAEntity, "SensorEntity": type("SensorEntity", (), {})}
    for name in (
        "SensorDeviceClass",
        "SensorStateClass",
        "UnitOfEnergy",
        "UnitOfPower",
        "UnitOfElectricCurrent",
        "UnitOfTemperature",
        "UnitOfVolume",
    ):
        namespace[name] = _Constants(name, (), {})
    exec(compile(module, str(path), "exec"), namespace)
    return namespace["HAEnergy"], namespace


class WaterIndexTests(TestCase):
    """Check actual generic sensor registration for water and electricity."""

    def test_total_water_is_volume_and_electricity_stays_energy(self):
        """Only the reported total water index changes class and unit."""
        energy_class, symbols = _load_energy_entity()

        class Device:
            _metadata = {}
            device_id = "10_20"
            energyIndex_WATER_TOTAL = 123456
            energyIndex_ELEC_TOTAL = 98765
            energyIndex_WATER_HEATING = 1357

            def __init__(self):
                self.energyIndex_WATER_TOTAL = 123456
                self.energyIndex_ELEC_TOTAL = 98765
                self.energyIndex_WATER_HEATING = 1357

        generic_sensor = _load_generic_sensor_class()
        generic_globals = generic_sensor.__init__.__globals__
        generic_globals.update(
            {
                "Tydom": type("Tydom", (), {}),
                "TydomWeather": type("TydomWeather", (), {}),
                "SensorDeviceClass": symbols["SensorDeviceClass"],
                "TYDOM_UNIT_TO_HA_UNIT": {},
            }
        )

        entity = energy_class(Device(), None)
        entity._restored_sensor_attributes = set()
        with patch.dict(
            HAEntity.get_sensors.__globals__, {"GenericSensor": generic_sensor}
        ):
            sensors = {sensor._attribute: sensor for sensor in entity.get_sensors()}

        water = sensors["energyIndex_WATER_TOTAL"]
        self.assertEqual(water._attr_device_class, symbols["SensorDeviceClass"].WATER)
        self.assertEqual(water.native_unit_of_measurement, "L")
        self.assertEqual(
            water._attr_state_class, symbols["SensorStateClass"].TOTAL_INCREASING
        )
        self.assertEqual(water._attr_unique_id, "10_20_energyIndex_WATER_TOTAL")
        self.assertEqual(water.native_value, 123456)
        for key in ("energyIndex_ELEC_TOTAL", "energyIndex_WATER_HEATING"):
            self.assertEqual(
                sensors[key]._attr_device_class, symbols["SensorDeviceClass"].ENERGY
            )
            self.assertEqual(
                sensors[key].native_unit_of_measurement,
                symbols["UnitOfEnergy"].WATT_HOUR,
            )
