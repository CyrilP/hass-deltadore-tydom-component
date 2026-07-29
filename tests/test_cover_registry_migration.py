"""Tests for toggle-only cover registry migration."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock

DOMAIN = "deltadore_tydom"
_MISSING = object()
_original_modules: dict[str, object] = {}


def _module(name: str, **attributes) -> types.ModuleType:
    """Install a minimal module needed to load the migration in isolation."""
    _original_modules.setdefault(name, sys.modules.get(name, _MISSING))
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    sys.modules[name] = module
    return module


for package_name in (
    "custom_components",
    "custom_components.deltadore_tydom",
):
    package = _module(package_name)
    package.__path__ = []

_module(
    "custom_components.deltadore_tydom.const",
    DOMAIN=DOMAIN,
    LOGGER=MagicMock(),
)

root = Path(__file__).parents[1]
migration_spec = importlib.util.spec_from_file_location(
    "custom_components.deltadore_tydom.cover_registry_migration",
    root / "custom_components" / "deltadore_tydom" / "cover_registry_migration.py",
)
assert migration_spec is not None and migration_spec.loader is not None
migration_module = importlib.util.module_from_spec(migration_spec)
_original_modules.setdefault(
    migration_spec.name, sys.modules.get(migration_spec.name, _MISSING)
)
sys.modules[migration_spec.name] = migration_module
migration_spec.loader.exec_module(migration_module)
remove_legacy_toggle_cover = migration_module.remove_legacy_toggle_cover

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


@dataclass
class FakeEntity:
    """Minimal entity-registry entry."""

    platform: str = DOMAIN
    unique_id: str = ""
    config_entry_id: str = "entry"


class FakeEntityRegistry:
    """Minimal entity registry supporting removal."""

    def __init__(self, entities: dict[str, FakeEntity]) -> None:
        """Initialise registry entries."""
        self.entities = entities
        self.removed: list[str] = []

    def async_remove(self, entity_id: str) -> None:
        """Record and apply an entity removal."""
        self.removed.append(entity_id)
        self.entities.pop(entity_id)


class TestToggleCoverMigration(unittest.TestCase):
    """Validate cleanup when a pulse-only cover becomes a button."""

    endpoint_unique_id = "1693565309_1693565309"

    @staticmethod
    def legacy_cover(**overrides) -> FakeEntity:
        """Return the exact legacy cover registry entry."""
        values = {
            "platform": DOMAIN,
            "unique_id": "1693565309_1693565309_cover",
            "config_entry_id": "entry",
        }
        values.update(overrides)
        return FakeEntity(**values)

    def test_removes_exact_legacy_cover_only(self) -> None:
        """The obsolete cover is removed without touching diagnostics."""
        registry = FakeEntityRegistry(
            {
                "cover.portail_coulissant": self.legacy_cover(),
                "sensor.thermic_defect": FakeEntity(
                    unique_id=f"{self.endpoint_unique_id}_thermicDefect"
                ),
            }
        )

        removed = remove_legacy_toggle_cover(
            registry,
            "entry",
            self.endpoint_unique_id,
        )

        self.assertEqual(removed, "cover.portail_coulissant")
        self.assertEqual(registry.removed, ["cover.portail_coulissant"])
        self.assertIn("sensor.thermic_defect", registry.entities)

    def test_keeps_cover_from_another_config_entry(self) -> None:
        """A similarly named entity owned by another gateway is retained."""
        registry = FakeEntityRegistry(
            {
                "cover.portail_coulissant": self.legacy_cover(
                    config_entry_id="other-entry"
                )
            }
        )

        removed = remove_legacy_toggle_cover(
            registry,
            "entry",
            self.endpoint_unique_id,
        )

        self.assertIsNone(removed)
        self.assertEqual(registry.removed, [])

    def test_keeps_non_cover_domain_with_matching_unique_id(self) -> None:
        """Only the obsolete cover domain is eligible for migration."""
        registry = FakeEntityRegistry(
            {"button.portail_coulissant": self.legacy_cover()}
        )

        removed = remove_legacy_toggle_cover(
            registry,
            "entry",
            self.endpoint_unique_id,
        )

        self.assertIsNone(removed)
        self.assertEqual(registry.removed, [])


if __name__ == "__main__":
    unittest.main()
