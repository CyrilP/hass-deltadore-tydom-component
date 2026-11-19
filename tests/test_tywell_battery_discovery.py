"""Regression tests for delayed Tywell battery discovery."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from test_climate_filpilote_detection import devices_module, entities_module


class TywellBatteryDiscoveryTests(TestCase):
    """Keep battery classification stable regardless of data arrival order."""

    def setUp(self):
        """Use a type for the shared Home Assistant binary-class stub."""
        # The shared HA stub uses a MagicMock where isinstance needs a type.
        binary_class = type("BinarySensorDeviceClass", (), {})
        patcher = patch.object(entities_module, "BinarySensorDeviceClass", binary_class)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def device(kind="re2020ControlBoiler", metadata=None, data=None):
        """Create an endpoint with controlled metadata and initial values."""
        return devices_module.TydomDevice(
            MagicMock(), "10_20", "20", "Controller", kind, "10", metadata, data
        )

    @staticmethod
    def battery(entity):
        """Return the discovered battery sensor."""
        return next(
            sensor
            for sensor in entity.get_sensors()
            if sensor._attribute == "battLevel"
        )

    def assert_battery(self, sensor):
        """Verify the existing entity identity and battery conversion."""
        self.assertEqual(sensor._attr_unique_id, "10_20_battLevel")
        self.assertEqual(sensor._attr_device_class, "battery")
        self.assertEqual(sensor._attr_state_class, "measurement")
        self.assertEqual(sensor.native_unit_of_measurement, "%")
        with patch.object(
            entities_module, "ranged_value_to_percentage", return_value=100
        ) as convert:
            self.assertEqual(sensor.native_value, 100)
            convert.assert_called_once_with((0, 2), 2)

    def test_late_value_and_metadata_get_battery_classification(self):
        """Late battery values are classified for both controller profiles."""
        for kind in ("re2020ControlBoiler", "re2020ControlPassive"):
            with self.subTest(kind=kind):
                device = self.device(kind, metadata={}, data={})
                entity = entities_module.HASensor(device, None)
                self.assertEqual(entity.get_sensors(), [])
                device._metadata = {"battLevel": {"min": 0, "max": 2, "unit": "NA"}}
                device.battLevel = 2
                self.assert_battery(self.battery(entity))
                self.assertEqual(entity.get_sensors(), [])

    def test_value_available_on_initial_discovery_is_unchanged(self):
        """An initial battery reading retains its existing behaviour."""
        device = self.device(
            metadata={"battLevel": {"min": 0, "max": 2}}, data={"battLevel": 2}
        )
        self.assert_battery(self.battery(entities_module.HASensor(device, None)))

    def test_registered_battery_restored_before_first_reading(self):
        """Restore an existing registered sensor from battery metadata."""
        device = self.device(metadata={"battLevel": {"min": 0, "max": 2}}, data={})
        entity = entities_module.HASensor(device, object())
        entity._get_hub = MagicMock(
            return_value=SimpleNamespace(_entry=SimpleNamespace(entry_id="entry"))
        )
        registry_api = SimpleNamespace(
            async_get=lambda _hass: object(),
            async_entries_for_config_entry=lambda _registry, _entry: [
                SimpleNamespace(
                    domain="sensor",
                    platform="deltadore_tydom",
                    unique_id="10_20_battLevel",
                )
            ],
        )
        with patch.object(
            entities_module, "_get_entity_registry_api", return_value=registry_api
        ):
            sensor = self.battery(entity)
        self.assertEqual(sensor._attr_unique_id, "10_20_battLevel")
        self.assertEqual(sensor._attr_state_class, "measurement")
        self.assertIsNone(sensor.native_value)
        device.battLevel = 2
        self.assert_battery(sensor)
        self.assertEqual(entity.get_sensors(), [])

    def test_other_device_types_do_not_gain_battery_classification(self):
        """Other device families keep their existing classification."""
        for kind in ("boiler", "weather", "shutter"):
            with self.subTest(kind=kind):
                device = self.device(kind, metadata={}, data={})
                entity = entities_module.HASensor(device, None)
                entity.get_sensors()
                device.battLevel = 2
                sensor = self.battery(entity)
                self.assertIsNone(sensor._attr_device_class)
                self.assertIsNone(sensor._attr_state_class)
                self.assertEqual(sensor.native_value, 2)
