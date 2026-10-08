"""Regression tests for native, multilingual entity names and stable identity."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.deltadore_tydom.entity_names import ENTITY_NAMES
from custom_components.deltadore_tydom.ha_entities import (
    ASSOCIATION_COMMAND,
    IDENTIFY_COMMAND,
    ClockSensor,
    GenericBinarySensor,
    GenericSensor,
    HAEntity,
    HAButton,
    HADeviceAssociationButton,
    HAGatewayAssociationCategorySelect,
    HAGatewayAssociationNameText,
    HAGroupableProductFinalizeAssociationButton,
    HANumber,
    HASelect,
    ProtocolBinarySensor,
)

from custom_components.deltadore_tydom.hub import Hub

ROOT = Path(__file__).parents[1]
TRANSLATIONS = ROOT / "custom_components/deltadore_tydom/translations"
LANGUAGES = ("en", "fr", "de", "es", "it", "pt", "nl", "pl")


def attach_platform(entity, language, domain):
    """Supply the translations normally loaded by HA's entity platform."""
    document = json.loads(
        (TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8")
    )
    names = {
        f"component.deltadore_tydom.entity.{domain}.{key}.name": data["name"]
        for key, data in document["entity"][domain].items()
    }
    entity.platform_data = SimpleNamespace(
        platform_name="deltadore_tydom",
        domain=domain,
        platform_translations=names,
        object_id_platform_translations=names,
        component_translations={},
        object_id_component_translations={},
    )
    return entity


class EntityNameTests(TestCase):
    """Exercise actual HA entity naming, rather than only translation metadata."""

    def device(self):
        """Return one device identifier shared by wrappers from all families."""
        return SimpleNamespace(device_id="43_42", _metadata={}, hygroIn=56.0)

    def test_association_text_keeps_native_capabilities(self):
        """Translated text controls must remain valid for the HA text platform."""
        hub = SimpleNamespace(
            hub_id="gateway",
            _name="TYDOM",
            manufacturer="Delta Dore",
            association_name="Test device",
        )
        text = attach_platform(HAGatewayAssociationNameText(hub), "fr", "text")

        self.assertEqual(text.capability_attributes["min"], 0)
        self.assertEqual(text.capability_attributes["max"], 64)
        self.assertEqual(text.capability_attributes["mode"], "text")
        self.assertEqual(text.unique_id, "gateway_association_name")
        self.assertEqual(text.native_value, "Test device")
        self.assertEqual(text.name, "Nom de l’appareil (facultatif)")

    def test_humidity_uses_all_eight_languages(self):
        """Translate the raw hygroIn name without shadowing HA's translation."""
        expected = (
            "Humidity",
            "Humidité",
            "Luftfeuchtigkeit",
            "Humedad",
            "Umidità",
            "Humidade",
            "Luchtvochtigheid",
            "Wilgotność",
        )
        for language, name in zip(LANGUAGES, expected, strict=True):
            with self.subTest(language=language):
                sensor = attach_platform(
                    GenericSensor(self.device(), None, None, "hygroIn", "hygroIn", "%"),
                    language,
                    "sensor",
                )
                self.assertEqual(sensor.name, name)
                self.assertEqual(sensor.unique_id, "43_42_hygroIn")
                self.assertEqual(sensor.native_value, 56.0)
                self.assertEqual(sensor.native_unit_of_measurement, "%")

    def test_numbers_and_selects_keep_raw_attributes_and_values(self):
        """Presentation must not translate the API fields or selectable values."""
        device = self.device()
        device.heatSetpoint = 21.0
        device.comfortMode = "HEATING"
        number = attach_platform(HANumber(device, None, "heatSetpoint"), "fr", "number")
        select = attach_platform(
            HASelect(device, None, "comfortMode", ["HEATING", "COOLING"]),
            "fr",
            "select",
        )
        self.assertEqual(number.name, "Consigne de chauffage")
        self.assertEqual(number.unique_id, "43_42_number_heatSetpoint")
        self.assertEqual(number._attribute_name, "heatSetpoint")
        self.assertEqual(number.native_value, 21.0)
        self.assertEqual(select.name, "Mode confort")
        self.assertEqual(select.unique_id, "43_42_select_comfortMode")
        self.assertEqual(select.options, ["HEATING", "COOLING"])
        self.assertEqual(select.current_option, "HEATING")

    def test_generic_faults_have_translated_names(self):
        """Use the same naming mechanism for alarm and thermostat faults."""
        sensor = attach_platform(
            GenericBinarySensor(
                self.device(), None, "tempSensorOpenCirc", "tempSensorOpenCirc"
            ),
            "fr",
            "binary_sensor",
        )
        self.assertEqual(sensor.name, "Sonde coupée")
        self.assertEqual(sensor.unique_id, "43_42_tempSensorOpenCirc")

    def test_clock_and_protocol_names_keep_distinguishing_context(self):
        """Translate nested gateway data and preserve the protocol identifier."""
        clock = attach_platform(
            ClockSensor(self.device(), "source", None), "fr", "sensor"
        )
        self.assertEqual(clock.name, "Source de l’horloge")
        self.assertEqual(clock.unique_id, "43_42_clock_source")
        protocol = attach_platform(
            ProtocolBinarySensor(self.device(), "X3D", {"ready": True}, "ready", None),
            "fr",
            "binary_sensor",
        )
        self.assertEqual(protocol.name, "X3D — Prêt")
        self.assertEqual(protocol.unique_id, "43_42_protocol_x3d_ready")

    def test_association_controls_keep_command_identity(self):
        """Translate buttons without modifying the command dispatched to TYDOM."""
        for command in (ASSOCIATION_COMMAND, IDENTIFY_COMMAND):
            with self.subTest(command=command):
                button = attach_platform(
                    HADeviceAssociationButton(self.device(), None, command),
                    "de",
                    "button",
                )
                self.assertEqual(button._association_command, command)
                self.assertEqual(button.unique_id, f"43_42_button_{command}")
                self.assertNotIn("Démarrer", button.name)
                self.assertNotIn("Identifier", button.name)

    def test_finalisation_names_keep_channel_and_device_family(self):
        """Retain the target channel when translating final configuration buttons."""
        names = []
        for channel, usage in (
            ("A", "télécommande"),
            ("B", "interrupteur"),
            ("A", "clavier"),
        ):
            button = attach_platform(
                HAGroupableProductFinalizeAssociationButton(
                    self.device(), None, "TYXIA 2600", channel, usage, None
                ),
                "en",
                "button",
            )
            self.assertIn(channel, button.name)
            self.assertEqual(button.unique_id, "43_42_button_finalize_tyxia_2600")
            names.append(button.name)
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("remote control", names[0])
        self.assertIn("wall switch", names[1])
        self.assertIn("keypad", names[2])

    def test_gateway_selector_translates_name_and_preserves_choices(self):
        """Localise the label without changing the selected API workflow values."""
        hub = SimpleNamespace(
            hub_id="test_gateway",
            _name="Test gateway",
            manufacturer="Delta Dore",
            association_categories=("Éclairage", "Volets"),
            association_category="Éclairage",
        )
        entity = attach_platform(
            HAGatewayAssociationCategorySelect(hub), "fr", "select"
        )
        self.assertEqual(entity.name, "1. Catégorie à associer")
        self.assertEqual(entity.unique_id, "test_gateway_association_category")
        self.assertEqual(entity.options, ["Éclairage", "Volets"])
        self.assertEqual(entity.current_option, "Éclairage")

    def test_apk_detection_labels_are_not_reported_as_detector_faults(self):
        """Smoke and water detection attributes describe detection, not a broken sensor."""
        for attr, label in (
            ("techSmokeDefect", "Fumée détectée"),
            ("techWaterDefect", "Fuite détectée"),
        ):
            entity = attach_platform(
                GenericBinarySensor(self.device(), None, attr, attr),
                "fr",
                "binary_sensor",
            )
            self.assertEqual(entity.name, label)

    def test_unsupported_language_uses_english_description(self):
        """Fall back to an English label when HA has no translated name."""
        sensor = attach_platform(
            GenericSensor(self.device(), None, None, "hygroIn", "hygroIn", "%"),
            "en",
            "sensor",
        )
        sensor.platform_data.platform_translations = {}
        self.assertEqual(sensor.name, "Humidity")

    def test_unknown_protocol_field_keeps_its_protocol_identifier(self):
        """Keep context for new protocol diagnostic attributes."""
        protocol = attach_platform(
            ProtocolBinarySensor(
                self.device(), "X3D", {"newFlag": True}, "newFlag", None
            ),
            "fr",
            "binary_sensor",
        )
        self.assertIn("X3D", protocol.name)

    def test_primary_entity_preserves_the_user_device_name(self):
        """The primary gate impulse inherits its device name, in any locale."""
        button = attach_platform(
            HAButton(self.device(), None, "Toggle", "toggle", primary=True),
            "fr",
            "button",
        )
        self.assertIsNone(button.name)
        self.assertEqual(button.unique_id, "43_42_button_Toggle")

    def test_unknown_attribute_stays_available_with_a_readable_name(self):
        """New firmware attributes must not disappear because of the catalogue."""
        device = self.device()
        device.newReading = 7
        sensor = attach_platform(
            GenericSensor(device, None, None, "newReading", "newReading", None),
            "fr",
            "sensor",
        )
        self.assertEqual(sensor.name, "new Reading")
        self.assertEqual(sensor.unique_id, "43_42_newReading")
        self.assertEqual(sensor.native_value, 7)

    def test_energy_channels_and_min_max_readings_remain_distinct(self):
        """Keep the measurement, circuit and limit visible in each translated name."""
        attrs = (
            "energyDistrib_ELEC_HEATING",
            "energyIndex_ELEC_HEATING",
            "energyInstantTi1P_Max",
            "energyInstantTi1P_Min",
            "energyScaleTi1P_Max",
            "energyScaleTi1P_Min",
        )
        for language in LANGUAGES:
            with self.subTest(language=language):
                names = []
                for attribute in attrs:
                    sensor = attach_platform(
                        GenericSensor(
                            self.device(), None, None, attribute, attribute, None
                        ),
                        language,
                        "sensor",
                    )
                    names.append(sensor.name)
                    self.assertEqual(sensor.unique_id, f"43_42_{attribute}")
                self.assertEqual(len(names), len(set(names)))

    def test_catalogue_and_placeholder_coverage_is_consistent(self):
        """Every catalogue label and placeholder must exist in all eight languages."""
        english = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))[
            "entity"
        ]
        for language in LANGUAGES:
            translated = json.loads(
                (TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8")
            )["entity"]
            for domain, entries in english.items():
                for key, data in entries.items():
                    if "name" not in data:
                        continue
                    with self.subTest(language=language, domain=domain, key=key):
                        value = translated[domain][key]["name"]
                        self.assertTrue(value.strip())
                        self.assertEqual(
                            set(re.findall(r"{([^{}]+)}", value)),
                            set(re.findall(r"{([^{}]+)}", data["name"])),
                        )
        for key, name in ENTITY_NAMES.items():
            matches = [
                data["name"]
                for entries in english.values()
                for entry_key, data in entries.items()
                if entry_key == key
            ]
            self.assertTrue(matches, key)
            self.assertTrue(all(value == name for value in matches), key)
        self.assertIn("hygroin", ENTITY_NAMES)

    def test_supported_metadata_maps_are_covered(self):
        """Cover every measurement explicitly declared by current device wrappers."""
        tree = ast.parse(
            (ROOT / "custom_components/deltadore_tydom/ha_entities.py").read_text(
                encoding="utf-8"
            )
        )
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Dict)
                and any(
                    isinstance(target, ast.Name)
                    and target.id in {"sensor_classes", "state_classes", "units"}
                    for target in node.targets
                )
            ):
                for key in node.value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        self.assertIn(key.value.lower(), ENTITY_NAMES, key.value)


class DiagnosticSensorTests(TestCase):
    """Keep secondary API readings available in HA's diagnostic section."""

    technical_values = {
        "activationCpt": 42,
        "activationIndex": 3,
        "area_id": "7",
        "uid": "device-identifier",
        "jobs": [1, 2],
        "jobsMP": [1],
        "jobsRM": [2],
        "indexTimeOn": 5,
        "timeOnCpt": 12,
        "loadSheddingOn": False,
        "maintenanceNeeded": True,
    }

    def test_technical_sensors_keep_identity_values_and_enabled_default(self):
        """Categorisation must not remove or disable existing readings."""
        device = SimpleNamespace(
            device_id="43_42", _metadata={}, **self.technical_values
        )
        for attribute, value in self.technical_values.items():
            with self.subTest(attribute=attribute):
                sensor = GenericSensor(device, None, None, attribute, attribute, None)
                self.assertEqual(sensor.entity_category, EntityCategory.DIAGNOSTIC)
                self.assertEqual(sensor.unique_id, f"43_42_{attribute}")
                self.assertEqual(sensor.native_value, value)
                self.assertTrue(sensor.entity_registry_enabled_default)

    def test_binary_technical_sensors_are_also_diagnostic(self):
        """Boolean metadata must not leave the same reading in the main section."""
        device = SimpleNamespace(device_id="43_42", _metadata={})
        for attribute in self.technical_values:
            with self.subTest(attribute=attribute):
                setattr(device, attribute, True)
                sensor = GenericBinarySensor(device, None, attribute, attribute)
                self.assertEqual(sensor.entity_category, EntityCategory.DIAGNOSTIC)
                self.assertEqual(sensor.unique_id, f"43_42_{attribute}")
                self.assertTrue(sensor.is_on)
                self.assertTrue(sensor.entity_registry_enabled_default)

    def test_category_uses_api_attribute_instead_of_display_name(self):
        """A custom presentation label must not determine the API classification."""
        device = SimpleNamespace(
            device_id="43_42", _metadata={}, activationCpt=42, maintenanceNeeded=True
        )
        scalar = GenericSensor(
            device, None, None, "Friendly counter", "activationCpt", None
        )
        binary = GenericBinarySensor(
            device, None, "Friendly maintenance label", "maintenanceNeeded"
        )
        self.assertEqual(scalar.entity_category, EntityCategory.DIAGNOSTIC)
        self.assertEqual(binary.entity_category, EntityCategory.DIAGNOSTIC)
        self.assertEqual(scalar.unique_id, "43_42_Friendly counter")
        self.assertEqual(binary.unique_id, "43_42_Friendly maintenance label")

    def test_functional_readings_remain_primary(self):
        """Keep measurements, setpoints and operating settings in the main view."""
        device = SimpleNamespace(device_id="43_42", _metadata={})
        for attribute in (
            "temperature",
            "hygroIn",
            "setpoint",
            "localMode",
            "useMode",
            "authorization",
            "minHeatSetpoint",
            "maxHeatSetpoint",
            "anticpCoeff",
            "antiSeizurePeriod",
            "newReading",
        ):
            with self.subTest(attribute=attribute):
                sensor = GenericSensor(device, None, None, attribute, attribute, None)
                self.assertIsNone(sensor.entity_category)
                self.assertTrue(sensor.entity_registry_enabled_default)
        for attribute in ("openingDetected", "techSmokeDefect", "techWaterDefect"):
            with self.subTest(attribute=attribute):
                sensor = GenericBinarySensor(device, None, attribute, attribute)
                self.assertIsNone(sensor.entity_category)

    def test_existing_firmware_and_problem_diagnostics_are_preserved(self):
        """Retain the existing gateway and fault categorisation."""
        device = SimpleNamespace(device_id="43_42", _metadata={})
        for attribute in ("config", "jobsMP", "mainVersionHW", "softVersion"):
            sensor = GenericSensor(device, None, None, attribute, attribute, None)
            self.assertEqual(sensor.entity_category, EntityCategory.DIAGNOSTIC)
        for device_class in (
            BinarySensorDeviceClass.PROBLEM,
            BinarySensorDeviceClass.UPDATE,
        ):
            sensor = GenericBinarySensor(device, device_class, "newFault", "newFault")
            self.assertEqual(sensor.entity_category, EntityCategory.DIAGNOSTIC)

    def test_discovery_keeps_every_technical_entity_and_late_updates(self):
        """Classify both discovered platforms without filtering API attributes."""
        device = SimpleNamespace(
            device_id="43_42",
            _metadata={},
            temperature=21.5,
            hygroIn=56.5,
            **self.technical_values,
        )
        wrapper = HAEntity()
        wrapper._device = device
        wrapper._registered_sensors = []
        wrapper.filtered_attrs = ["device_id"]
        sensors = wrapper.get_sensors()
        by_attribute = {sensor._attribute: sensor for sensor in sensors}
        self.assertEqual(
            set(by_attribute), {*self.technical_values, "temperature", "hygroIn"}
        )
        for attribute in self.technical_values:
            self.assertEqual(
                by_attribute[attribute].entity_category, EntityCategory.DIAGNOSTIC
            )
        self.assertIsInstance(by_attribute["activationCpt"], GenericSensor)
        self.assertIsInstance(by_attribute["loadSheddingOn"], GenericBinarySensor)
        self.assertIsNone(by_attribute["temperature"].entity_category)
        self.assertIsNone(by_attribute["hygroIn"].entity_category)
        self.assertEqual(wrapper.get_sensors(), [])
        device.activationCpt = 43
        device.loadSheddingOn = True
        self.assertEqual(by_attribute["activationCpt"].native_value, 43)
        self.assertTrue(by_attribute["loadSheddingOn"].is_on)


class EntityDiscoveryNameTests(IsolatedAsyncioTestCase):
    """Exercise discovery with native translated HA sensor objects."""

    async def test_late_translated_sensor_is_added_to_home_assistant(self):
        """Discovery logging must not prevent a new sensor reaching its platform."""
        device = SimpleNamespace(device_id="43_42", _metadata={}, hygroIn=56.0)
        sensor = GenericSensor(device, None, None, "hygroIn", "hygroIn", "%")
        stored = SimpleNamespace(update_device=AsyncMock())
        hub = SimpleNamespace(
            ha_devices={"43_42": SimpleNamespace(get_sensors=lambda: [sensor])},
            _add_discovered_entities=Mock(),
            _maybe_create_device_association_buttons=Mock(),
        )

        with patch("custom_components.deltadore_tydom.hub.LOGGER") as logger:
            await Hub.update_ha_device(hub, stored, device)

        hub._add_discovered_entities.assert_called_once_with([sensor])
        logger.exception.assert_not_called()
        stored.update_device.assert_awaited_once_with(device)
        self.assertEqual(attach_platform(sensor, "fr", "sensor").name, "Humidité")
        self.assertEqual(sensor.unique_id, "43_42_hygroIn")
        self.assertEqual(sensor.native_value, 56.0)


class EntityRegistryNameTests(IsolatedAsyncioTestCase):
    """Confirm language changes do not rename IDs or erase user customisations."""

    async def test_diagnostic_category_preserves_registry_choices(self):
        """Moving technical entities keeps IDs, custom names and disabled choices."""
        with TemporaryDirectory() as config_dir:
            hass = HomeAssistant(config_dir)
            dr.async_setup(hass)
            await dr.async_load(hass)
            registry = er.async_get(hass)
            await registry.async_load()
            for domain, attribute in (
                ("sensor", "activationCpt"),
                ("binary_sensor", "maintenanceNeeded"),
            ):
                for disabled_by in (None, er.RegistryEntryDisabler.USER):
                    with self.subTest(domain=domain, disabled_by=disabled_by):
                        unique_id = f"43_42_{attribute}_{disabled_by}"
                        original = registry.async_get_or_create(
                            domain,
                            "deltadore_tydom",
                            unique_id,
                            suggested_object_id=f"tybox_{attribute}_{disabled_by}",
                            entity_category=None,
                            disabled_by=disabled_by,
                        )
                        registry.async_update_entity(
                            original.entity_id, name="My technical reading"
                        )
                        updated = registry.async_get_or_create(
                            domain,
                            "deltadore_tydom",
                            unique_id,
                            entity_category=EntityCategory.DIAGNOSTIC,
                        )
                        self.assertEqual(updated.entity_id, original.entity_id)
                        self.assertEqual(updated.name, "My technical reading")
                        self.assertEqual(updated.disabled_by, disabled_by)
                        self.assertEqual(
                            updated.entity_category, EntityCategory.DIAGNOSTIC
                        )
            await hass.async_stop()

    async def test_existing_registry_entry_and_custom_name_survive(self):
        """Reuse the existing registry ID after translating its original name."""
        with TemporaryDirectory() as config_dir:
            hass = HomeAssistant(config_dir)
            dr.async_setup(hass)
            await dr.async_load(hass)
            registry = er.async_get(hass)
            await registry.async_load()
            original = registry.async_get_or_create(
                "sensor",
                "deltadore_tydom",
                "43_42_hygroIn",
                suggested_object_id="tybox_hygroin",
                original_name="hygroIn",
            )
            registry.async_update_entity(original.entity_id, name="My humidity sensor")
            updated = registry.async_get_or_create(
                "sensor",
                "deltadore_tydom",
                "43_42_hygroIn",
                suggested_object_id="tybox_humidity",
                original_name="Humidité",
            )
            self.assertEqual(updated.entity_id, original.entity_id)
            self.assertEqual(updated.name, "My humidity sensor")
            await hass.async_stop()


if __name__ == "__main__":
    from unittest import main

    main()
