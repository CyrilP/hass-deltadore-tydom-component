"""Ensure TYWATT energy sensor names are translated in every locale."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).parents[1]
TRANSLATIONS = ROOT / "custom_components" / "deltadore_tydom" / "translations"
REFERENCE = "en.json"
PREFIX = "tywatt_energy_"


def _sensor_names(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("entity", {}).get("sensor", {})


class TranslationKeyCompletenessTests(TestCase):
    """Guard against a locale missing a TYWATT energy entity name."""

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
