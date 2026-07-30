"""Tests for user-controlled removal of TYDOM registry devices."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
from unittest import TestCase


def _module(name: str, **attributes) -> types.ModuleType:
    """Install a minimal module needed to load the helper in isolation."""
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    sys.modules[name] = module
    return module


for package_name in ("custom_components", "custom_components.deltadore_tydom"):
    package = _module(package_name)
    package.__path__ = []

_module(
    "custom_components.deltadore_tydom.const",
    DOMAIN="deltadore_tydom",
)

root = Path(__file__).parents[1]
helper_path = root / "custom_components" / "deltadore_tydom" / "device_removal.py"
helper_spec = importlib.util.spec_from_file_location(
    "custom_components.deltadore_tydom.device_removal",
    helper_path,
)
assert helper_spec is not None and helper_spec.loader is not None
helper_module = importlib.util.module_from_spec(helper_spec)
sys.modules[helper_spec.name] = helper_module
helper_spec.loader.exec_module(helper_module)

can_remove_device = helper_module.can_remove_device


class FakeDeviceEntry:
    """Minimal Home Assistant device-registry entry."""

    def __init__(
        self,
        identifiers: set[tuple[str, str]],
        config_entries: set[str] | None = None,
        config_entry_id: str | None = None,
    ) -> None:
        """Initialise registry ownership and identifiers."""
        self.identifiers = identifiers
        if config_entry_id is not None:
            self.config_entry_id = config_entry_id
        else:
            self.config_entries = config_entries or set()


class DeviceRemovalTests(TestCase):
    """Validate user-requested removal ownership safeguards."""

    def test_allows_integration_owned_device(self) -> None:
        """An owned device may be removed even while TYDOM still supplies it."""
        entry = FakeDeviceEntry({("deltadore_tydom", "10_20")}, {"entry"})

        self.assertTrue(can_remove_device(entry, "entry"))

    def test_refuses_device_owned_by_another_config_entry(self) -> None:
        """One gateway must not approve removal for another gateway."""
        entry = FakeDeviceEntry({("deltadore_tydom", "30_40")}, {"other"})

        self.assertFalse(can_remove_device(entry, "entry"))

    def test_refuses_entry_without_tydom_identifier(self) -> None:
        """Unrelated registry entries must never be approved."""
        entry = FakeDeviceEntry({("another_domain", "30_40")}, {"entry"})

        self.assertFalse(can_remove_device(entry, "entry"))

    def test_supports_single_config_entry_device_registry_model(self) -> None:
        """The Home Assistant 2026.8 ownership model is also supported."""
        entry = FakeDeviceEntry(
            {("deltadore_tydom", "30_40")},
            config_entry_id="entry",
        )

        self.assertTrue(can_remove_device(entry, "entry"))


if __name__ == "__main__":
    import unittest

    unittest.main()
