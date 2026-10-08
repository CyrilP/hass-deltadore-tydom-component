"""Tests for TYDOM gateway firmware update availability."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase


def _load_haty_dom_class():
    """Load HATydom without importing Home Assistant's full runtime."""
    source_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "deltadore_tydom"
        / "ha_entities.py"
    )
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    selected_nodes = [
        node
        for node in module.body
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id in {"_BINARY_TRUE_VALUES", "_BINARY_FALSE_VALUES"}
                for target in node.targets
            )
        )
        or (isinstance(node, ast.FunctionDef) and node.name == "normalize_binary_state")
        or (isinstance(node, ast.ClassDef) and node.name == "HATydom")
    ]
    isolated_module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            *selected_nodes,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(isolated_module)
    namespace = {
        "BinarySensorDeviceClass": SimpleNamespace(UPDATE="update"),
        "UpdateDeviceClass": SimpleNamespace(FIRMWARE="firmware"),
        "UpdateEntityFeature": SimpleNamespace(INSTALL="install"),
        "UpdateEntity": type("UpdateEntity", (), {}),
        "HAEntity": type("HAEntity", (), {}),
    }
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return namespace["HATydom"]


HATydom = _load_haty_dom_class()


class TestTydomUpdateEntity(TestCase):
    """Verify the gateway update flag maps to Home Assistant's update entity."""

    def _entity(self, update_available):
        device = SimpleNamespace(
            device_id="gateway-id",
            device_name="TYDOM",
            mainVersionSW="03.24.31",
            updateAvailable=update_available,
        )
        return HATydom(device, hass=None)

    def test_available_firmware_uses_generic_latest_version(self):
        """TYDOM availability turns on HA's update entity without a target version."""
        entity = self._entity("On")

        self.assertEqual("03.24.31", entity.installed_version)
        self.assertEqual("latest", entity.latest_version)

    def test_unavailable_firmware_matches_installed_version(self):
        """An Off flag keeps the update entity in the up-to-date state."""
        for update_available in (False, "Off"):
            with self.subTest(update_available=update_available):
                entity = self._entity(update_available)

                self.assertEqual(entity.installed_version, entity.latest_version)

    def test_unrecognised_flag_does_not_claim_an_update(self):
        """Unknown TYDOM values do not produce false update notifications."""
        entity = self._entity("pending")

        self.assertEqual(entity.installed_version, entity.latest_version)
