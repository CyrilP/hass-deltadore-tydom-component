"""Regression coverage for the reported TYDOM total gas counter."""

from unittest import TestCase
from unittest.mock import patch

from test_cover_position_sensor import _load_generic_sensor_class
from test_entity_sensor_registration import HAEntity
from test_protocol_responses import handler_module
from test_water_index_unit import _load_energy_entity


class GasIndexTests(TestCase):
    """Check protocol parsing and actual generic sensor registration."""

    def test_total_gas_and_other_energy_counters_keep_their_meaning(self):
        """Only the reported total gas index becomes a volume counter."""
        payloads = [
            ("GAS_TOTAL", 617910),
            ("ELEC_TOTAL", 98765),
            ("WATER_TOTAL", 123456),
            ("GAS_HEATING", 1357),
            ("GAZ_TOTAL", 2468),
        ]
        values = {}
        for destination, counter in payloads:
            values.update(
                handler_module._parse_energy_cdata_element(
                    {
                        "name": "energyIndex",
                        "status": "OK",
                        "parameters": {"dest": destination},
                        "values": {"counter": counter},
                    }
                )
            )
        values["energyIndexHeatGas"] = 4321

        energy_class, symbols = _load_energy_entity()

        class Device:
            _metadata = {}
            device_id = "10_20"

            def __init__(self, attributes):
                self.__dict__.update(attributes)

        generic_sensor = _load_generic_sensor_class()
        generic_sensor.__init__.__globals__.update(
            {
                "Tydom": type("Tydom", (), {}),
                "TydomWeather": type("TydomWeather", (), {}),
                "SensorDeviceClass": symbols["SensorDeviceClass"],
                "TYDOM_UNIT_TO_HA_UNIT": {},
            }
        )
        device = Device(values)
        entity = energy_class(device, None)
        entity._restored_sensor_attributes = set()
        with patch.dict(
            HAEntity.get_sensors.__globals__, {"GenericSensor": generic_sensor}
        ):
            sensors = {sensor._attribute: sensor for sensor in entity.get_sensors()}

        gas = sensors["energyIndex_GAS_TOTAL"]
        self.assertEqual(gas._attr_device_class, symbols["SensorDeviceClass"].GAS)
        self.assertEqual(gas.native_unit_of_measurement, "L")
        self.assertEqual(
            gas._attr_state_class, symbols["SensorStateClass"].TOTAL_INCREASING
        )
        self.assertEqual(gas._attr_unique_id, "10_20_energyIndex_GAS_TOTAL")
        self.assertEqual(gas.native_value, 617910)
        # The reported meter reading is 617.91 m³ for 617910 native litres.
        self.assertAlmostEqual(gas.native_value / 1000, 617.91)
        device.energyIndex_GAS_TOTAL = 617920
        self.assertEqual(gas.native_value, 617920)

        for attribute, expected_value in (
            ("energyIndex_ELEC_TOTAL", 98765),
            ("energyIndex_GAS_HEATING", 1357),
            ("energyIndex_GAZ_TOTAL", 2468),
            ("energyIndexHeatGas", 4321),
        ):
            sensor = sensors[attribute]
            self.assertEqual(
                sensor._attr_device_class, symbols["SensorDeviceClass"].ENERGY
            )
            self.assertEqual(
                sensor.native_unit_of_measurement,
                symbols["UnitOfEnergy"].WATT_HOUR,
            )
            self.assertEqual(
                sensor._attr_state_class, symbols["SensorStateClass"].TOTAL_INCREASING
            )
            self.assertEqual(sensor.native_value, expected_value)
            self.assertEqual(sensor._attr_unique_id, f"10_20_{attribute}")

        water = sensors["energyIndex_WATER_TOTAL"]
        self.assertEqual(water._attr_device_class, symbols["SensorDeviceClass"].WATER)
        self.assertEqual(water.native_unit_of_measurement, "L")
        self.assertEqual(
            water._attr_state_class, symbols["SensorStateClass"].TOTAL_INCREASING
        )
        self.assertEqual(water.native_value, 123456)
        self.assertEqual(water._attr_unique_id, "10_20_energyIndex_WATER_TOTAL")
