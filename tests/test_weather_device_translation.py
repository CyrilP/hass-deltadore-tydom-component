"""Tests for TYDOM weather-device name translations."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase


TRANSLATIONS = {
    "cs": "Počasí",
    "de": "Wetter",
    "en": "Weather",
    "es": "Tiempo",
    "fr": "Météo",
    "it": "Meteo",
    "nb": "Vær",
    "nl": "Weer",
    "pl": "Pogoda",
    "pt": "Tempo",
}


def _load_weather_device_info_property():
    """Load HaWeather.device_info without importing Home Assistant."""
    source_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "deltadore_tydom"
        / "ha_entities.py"
    )
    source = ast.parse(source_path.read_text(encoding="utf-8"))
    weather_class = next(
        node
        for node in source.body
        if isinstance(node, ast.ClassDef) and node.name == "HaWeather"
    )
    device_info_property = next(
        node
        for node in weather_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "device_info"
    )
    isolated_class = ast.ClassDef(
        name="WeatherDeviceInfoHarness",
        bases=[],
        keywords=[],
        body=[device_info_property],
        decorator_list=[],
    )
    isolated_module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            isolated_class,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(isolated_module)
    namespace = {"DOMAIN": "deltadore_tydom"}
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return namespace["WeatherDeviceInfoHarness"]


def _load_generic_sensor_translation_keys():
    """Read the generic sensor attribute-to-translation-key mapping."""
    source_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "deltadore_tydom"
        / "ha_entities.py"
    )
    source = ast.parse(source_path.read_text(encoding="utf-8"))
    sensor_class = next(
        node
        for node in source.body
        if isinstance(node, ast.ClassDef) and node.name == "GenericSensor"
    )
    mapping = next(
        node.value
        for node in sensor_class.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "TRANSLATION_KEYS"
            for target in node.targets
        )
    )
    return ast.literal_eval(mapping)


def _load_generic_sensor_device_info_property():
    """Load GenericSensor.device_info without importing Home Assistant."""
    source_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "deltadore_tydom"
        / "ha_entities.py"
    )
    source = ast.parse(source_path.read_text(encoding="utf-8"))
    sensor_class = next(
        node
        for node in source.body
        if isinstance(node, ast.ClassDef) and node.name == "GenericSensor"
    )
    device_info_property = next(
        node
        for node in sensor_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "device_info"
    )
    isolated_class = ast.ClassDef(
        name="GenericSensorDeviceInfoHarness",
        bases=[],
        keywords=[],
        body=[device_info_property],
        decorator_list=[],
    )
    isolated_module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            isolated_class,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(isolated_module)
    namespace = {"DOMAIN": "deltadore_tydom"}
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return namespace["GenericSensorDeviceInfoHarness"]


class WeatherDeviceTranslationTests(TestCase):
    """Ensure every TYDOM app language has a shared weather-device name."""

    def test_all_ten_tydom_languages_translate_shared_weather_device(self) -> None:
        """The shared endpoint name is localised in every supported language."""
        translations_dir = (
            Path(__file__).parents[1]
            / "custom_components"
            / "deltadore_tydom"
            / "translations"
        )

        for language, expected_name in TRANSLATIONS.items():
            with self.subTest(language=language):
                data = json.loads(
                    (translations_dir / f"{language}.json").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    data["device"]["tywell_weather"]["name"], expected_name
                )

    def test_weather_sensor_translation_keys_exist_in_all_languages(self) -> None:
        """Weather attributes resolve to translated entity names in every locale."""
        expected_keys = {
            "outTemperature": "outtemperature",
            "dailyPower": "dailypower",
            "currentPower": "power",
            "maxDailyOutTemp": "maxdailyouttemp",
            "weather": "weather",
        }
        sensor_keys = _load_generic_sensor_translation_keys()
        self.assertEqual(
            {attribute: sensor_keys.get(attribute) for attribute in expected_keys},
            expected_keys,
        )

        translations_dir = (
            Path(__file__).parents[1]
            / "custom_components"
            / "deltadore_tydom"
            / "translations"
        )
        for language in TRANSLATIONS:
            with self.subTest(language=language):
                data = json.loads(
                    (translations_dir / f"{language}.json").read_text(encoding="utf-8")
                )
                for translation_key in expected_keys.values():
                    self.assertTrue(data["entity"]["sensor"][translation_key]["name"])

        french = json.loads((translations_dir / "fr.json").read_text(encoding="utf-8"))[
            "entity"
        ]["sensor"]
        self.assertEqual(french["weather"]["name"], "Météo")
        self.assertEqual(french["dailypower"]["name"], "Puissance journalière")
        self.assertEqual(
            french["maxdailyouttemp"]["name"],
            "Température extérieure maximale du jour",
        )

    def test_shared_weather_device_uses_native_device_translation_key(self) -> None:
        """The shared endpoint passes its translated name to the device registry."""
        weather_class = _load_weather_device_info_property()
        weather = object.__new__(weather_class)
        weather._device = SimpleNamespace(
            device_id="weather-endpoint",
            registry_device_id="weather-endpoint",
            registry_device_name="Product 1",
        )
        weather._get_device_info = lambda: {"manufacturer": "Delta Dore"}
        weather._enrich_device_info = lambda info: info
        weather._registry_device_id_override = "weather-endpoint"
        weather._registry_device_name_override = "Weather"
        weather._registry_translation_key_override = "tywell_weather"

        self.assertEqual(weather.device_info["translation_key"], "tywell_weather")
        self.assertNotIn("name", weather.device_info)

    def test_shared_weather_sensor_does_not_override_translated_device_name(
        self,
    ) -> None:
        """Generic sensors must not replace a localized device name with English."""
        sensor_class = _load_generic_sensor_device_info_property()
        sensor = object.__new__(sensor_class)
        sensor._device = SimpleNamespace(
            device_id="weather-endpoint",
            registry_device_id="weather-endpoint",
            registry_device_name="Weather",
            device_name="Weather",
        )
        sensor._get_device_info_dict = lambda: {"manufacturer": "Delta Dore"}
        sensor._get_tydom_gateway_device_id = lambda: None
        sensor.hass = object()
        sensor._registry_device_id_override = "weather-endpoint"
        sensor._registry_device_name_override = "Weather"
        sensor._registry_translation_key_override = "tywell_weather"

        self.assertEqual(sensor.device_info["translation_key"], "tywell_weather")
        self.assertNotIn("name", sensor.device_info)
