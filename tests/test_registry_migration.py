"""Tests for safe TYDOM device-registry repairs."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    "custom_components.deltadore_tydom.registry_migration",
    root / "custom_components" / "deltadore_tydom" / "registry_migration.py",
)
assert migration_spec is not None and migration_spec.loader is not None
migration_module = importlib.util.module_from_spec(migration_spec)
_original_modules.setdefault(
    migration_spec.name, sys.modules.get(migration_spec.name, _MISSING)
)
sys.modules[migration_spec.name] = migration_module
migration_spec.loader.exec_module(migration_module)
remove_malformed_orphan_devices = migration_module.remove_malformed_orphan_devices

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


@dataclass
class FakeDevice:
    """Minimal device-registry entry."""

    id: str
    identifiers: set[tuple[str, object]]
    config_entries: set[str] = field(default_factory=lambda: {"entry"})


@dataclass
class FakeEntity:
    """Minimal entity-registry entry."""

    device_id: str | None


class FakeDeviceRegistry:
    """Minimal device registry supporting lookup and removal."""

    def __init__(self, *devices: FakeDevice) -> None:
        """Initialise the registry with devices."""
        self.devices = {device.id: device for device in devices}
        self.removed: list[str] = []

    def async_get_device(self, *, identifiers):
        """Return the device matching an identifier set."""
        return next(
            (
                device
                for device in self.devices.values()
                if device.identifiers & identifiers
            ),
            None,
        )

    def async_remove_device(self, device_id: str) -> None:
        """Record and apply a removal."""
        self.removed.append(device_id)
        self.devices.pop(device_id)


class FakeEntityRegistry:
    """Minimal entity registry."""

    def __init__(self, *entities: FakeEntity) -> None:
        """Initialise the registry with entities."""
        self.entities = {
            f"sensor.test_{index}": entity for index, entity in enumerate(entities)
        }


class TestRegistryMigration(unittest.TestCase):
    """Validate the conservative cleanup safeguards."""

    @staticmethod
    def malformed(device_id: str = "bad") -> FakeDevice:
        """Return a malformed numeric-ID device."""
        return FakeDevice(device_id, {(DOMAIN, 1749541099)})

    @staticmethod
    def valid() -> FakeDevice:
        """Return the corresponding valid string-ID device."""
        return FakeDevice("good", {(DOMAIN, "1749541099")})

    def test_removes_orphan_when_valid_duplicate_exists(self) -> None:
        """An entity-less numeric duplicate is removed."""
        registry = FakeDeviceRegistry(self.malformed(), self.valid())

        removed = remove_malformed_orphan_devices(
            registry, FakeEntityRegistry(), "entry"
        )

        self.assertEqual(removed, ["bad"])
        self.assertEqual(registry.removed, ["bad"])
        self.assertIn("good", registry.devices)

    def test_keeps_device_with_an_entity(self) -> None:
        """A malformed device with an entity is never removed."""
        registry = FakeDeviceRegistry(self.malformed(), self.valid())

        removed = remove_malformed_orphan_devices(
            registry, FakeEntityRegistry(FakeEntity("bad")), "entry"
        )

        self.assertEqual(removed, [])
        self.assertEqual(registry.removed, [])

    def test_keeps_orphan_without_valid_duplicate(self) -> None:
        """An orphan is retained when no safe replacement exists."""
        registry = FakeDeviceRegistry(self.malformed())

        removed = remove_malformed_orphan_devices(
            registry, FakeEntityRegistry(), "entry"
        )

        self.assertEqual(removed, [])
        self.assertEqual(registry.removed, [])

    def test_keeps_device_from_another_config_entry(self) -> None:
        """Cleanup is scoped to the config entry being set up."""
        malformed = self.malformed()
        malformed.config_entries = {"other-entry"}
        registry = FakeDeviceRegistry(malformed, self.valid())

        removed = remove_malformed_orphan_devices(
            registry, FakeEntityRegistry(), "entry"
        )

        self.assertEqual(removed, [])
        self.assertEqual(registry.removed, [])
