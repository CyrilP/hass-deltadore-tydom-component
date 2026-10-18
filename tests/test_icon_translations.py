"""Validate Home Assistant icon translations against entity translations."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "deltadore_tydom"


class IconTranslationTests(TestCase):
    """Keep icon keys in sync with the integration's translated entities."""

    def test_icon_translations_reference_existing_entity_keys(self):
        """Every icon translation should resolve to a translated entity."""
        icons = json.loads((INTEGRATION / "icons.json").read_text(encoding="utf-8"))
        translations = json.loads(
            (INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8")
        )

        for domain, entities in icons["entity"].items():
            with self.subTest(domain=domain):
                translated_entities = translations["entity"][domain]
                for translation_key, icon_config in entities.items():
                    with self.subTest(translation_key=translation_key):
                        self.assertIn(translation_key, translated_entities)
                        self.assertIn("default", icon_config)
                        self.assertTrue(icon_config["default"].startswith("mdi:"))

    def test_translated_entities_all_have_icons(self):
        """Every translated entity should have a dedicated icon.

        Platforms like `number`, `select` or `binary_sensor` have no
        device-class-based default icon in Home Assistant, so a missing
        entry here falls back to the generic visibility icon in the UI
        (see issue #529).
        """
        icons = json.loads((INTEGRATION / "icons.json").read_text(encoding="utf-8"))
        translations = json.loads(
            (INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8")
        )

        for domain, translated_entities in translations["entity"].items():
            with self.subTest(domain=domain):
                icon_entities = icons["entity"].get(domain, {})
                missing = sorted(set(translated_entities) - set(icon_entities))
                self.assertEqual(
                    missing, [], f"Missing icons for {domain} entities: {missing}"
                )
