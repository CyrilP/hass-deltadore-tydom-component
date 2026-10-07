"""Regression tests for native, multilingual entity names and stable identity."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.deltadore_tydom.entity_names import ENTITY_NAMES
from custom_components.deltadore_tydom.ha_entities import (
    ASSOCIATION_COMMAND,
    IDENTIFY_COMMAND,
    ClockSensor,
    GenericBinarySensor,
    GenericSensor,
    HAButton,
    HADeviceAssociationButton,
    HAGatewayAssociationCategorySelect,
    HAGroupableProductFinalizeAssociationButton,
    HANumber,
    HASelect,
    ProtocolBinarySensor,
)

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


class EntityRegistryNameTests(IsolatedAsyncioTestCase):
    """Confirm language changes do not rename IDs or erase user customisations."""

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
