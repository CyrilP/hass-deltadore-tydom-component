"""Ensure key entity names are translated in every locale."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).parents[1]
TRANSLATIONS = ROOT / "custom_components" / "deltadore_tydom" / "translations"
REFERENCE = "en.json"
PREFIX = "tywatt_energy_"
ENERGY_INDEX_SHARE_CATEGORIES = (
    "cooling",
    "heating",
    "hotwater",
    "other",
    "outlet",
    "total",
)
ENERGY_INDEX_SHARE_PREFIXES = ("energydistrib", "energyindex")
ENERGY_INDEX_SHARE_EXTRA_KEYS = (
    "energyindexheatgas",
    "energyindexti1",
    "energytotindexwatt",
)
SETPOINT_DOMAINS = ("sensor", "binary_sensor", "number", "select")
ABSOLUTE_SETPOINTS = {
    "absmaxcoolsetpoint": "maxcoolsetpoint",
    "absmaxheatsetpoint": "maxheatsetpoint",
    "absmincoolsetpoint": "mincoolsetpoint",
    "absminheatsetpoint": "minheatsetpoint",
}


def _sensor_names(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("entity", {}).get("sensor", {})


def _unique_object(pairs):
    """Reject duplicate JSON keys instead of silently discarding earlier values."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate translation key: {key}")
        result[key] = value
    return result


class TranslationKeyCompletenessTests(TestCase):
    """Guard key entity names across all supported locales."""

    def test_stored_pin_exceptions_are_unique_and_translated_everywhere(self):
        """Stored-PIN errors must be reachable in every locale JSON file."""
        required_keys = (
            "stored_alarm_pin_missing",
            "unsupported_stored_pin_alarm_mode",
        )

        for locale in sorted(TRANSLATIONS.glob("*.json")):
            with self.subTest(locale=locale.name):
                translated = json.loads(
                    locale.read_text(encoding="utf-8"),
                    object_pairs_hook=_unique_object,
                )
                exceptions = translated.get("exceptions", {})
                for key in required_keys:
                    with self.subTest(key=key):
                        self.assertIn(key, exceptions)
                        self.assertTrue(exceptions[key]["message"].strip())

    def test_tywatt_energy_keys_present_in_every_locale(self):
        """Every ``tywatt_energy_*`` key in en.json must exist in all locales."""
        reference_keys = {
            key
            for key in _sensor_names(TRANSLATIONS / REFERENCE)
            if key.startswith(PREFIX)
        }
        self.assertTrue(reference_keys, "no tywatt_energy_* keys found in en.json")

        for locale in sorted(TRANSLATIONS.glob("*.json")):
            if locale.name == REFERENCE:
                continue
            with self.subTest(locale=locale.name):
                names = _sensor_names(locale)
                missing = sorted(key for key in reference_keys if key not in names)
                self.assertEqual(
                    missing,
                    [],
                    f"{locale.name} is missing TYWATT energy names: {missing}",
                )
                for key in reference_keys:
                    with self.subTest(key=key):
                        self.assertIn("name", names[key])
                        self.assertTrue(names[key]["name"].strip())

    def test_energy_index_share_keys_present_in_every_locale(self):
        """TYWATT energy index/share labels (PR #517) must exist in all locales."""
        reference = _sensor_names(TRANSLATIONS / REFERENCE)
        reference_keys = {
            key
            for key in reference
            if key in ENERGY_INDEX_SHARE_PREFIXES
            or (
                key.startswith(ENERGY_INDEX_SHARE_PREFIXES)
                and key.rsplit("_", 1)[-1] in ENERGY_INDEX_SHARE_CATEGORIES
            )
        } | set(ENERGY_INDEX_SHARE_EXTRA_KEYS)
        self.assertTrue(
            reference_keys, "no energydistrib/energyindex keys found in en.json"
        )

        for locale in sorted(TRANSLATIONS.glob("*.json")):
            if locale.name == REFERENCE:
                continue
            with self.subTest(locale=locale.name):
                names = _sensor_names(locale)
                missing = sorted(key for key in reference_keys if key not in names)
                self.assertEqual(
                    missing,
                    [],
                    f"{locale.name} is missing energy index/share names: {missing}",
                )
                for key in reference_keys:
                    with self.subTest(key=key):
                        self.assertIn("name", names[key])
                        self.assertTrue(names[key]["name"].strip())

    def test_absolute_setpoint_names_are_distinct_in_every_locale(self):
        """Device limits must be distinguishable from configured limits."""
        english = json.loads((TRANSLATIONS / REFERENCE).read_text(encoding="utf-8"))

        for locale in sorted(TRANSLATIONS.glob("*.json")):
            translated = json.loads(locale.read_text(encoding="utf-8"))
            for domain in SETPOINT_DOMAINS:
                names = translated.get("entity", {}).get(domain, {})
                english_names = english.get("entity", {}).get(domain, {})
                for absolute_key, configured_key in ABSOLUTE_SETPOINTS.items():
                    with self.subTest(
                        locale=locale.name,
                        domain=domain,
                        key=absolute_key,
                    ):
                        absolute_name = names.get(absolute_key, {}).get("name")
                        configured_name = names.get(configured_key, {}).get(
                            "name", english_names[configured_key]["name"]
                        )
                        self.assertTrue(absolute_name)
                        self.assertNotEqual(absolute_name, configured_name)
