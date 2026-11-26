"""Tests for TYDOM gateway firmware update availability."""

from __future__ import annotations

import ast
from pathlib import Path
import sys
import types
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock


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
        "EntityCategory": SimpleNamespace(CONFIG="config", DIAGNOSTIC="diagnostic"),
    }
    namespace["__package__"] = "custom_components.deltadore_tydom"
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

    def test_detailed_status_provides_the_target_version(self):
        """A pending version from update/status replaces the generic value."""
        device = SimpleNamespace(
            device_id="gateway-id",
            device_name="TYDOM",
            mainVersionSW="03.24.29",
            updateAvailable=False,
            update_available=True,
            target_firmware_version="03.25.01",
            update_in_progress=True,
        )
        entity = HATydom(device, hass=None)

        self.assertEqual("03.25.01", entity.latest_version)
        self.assertTrue(entity.in_progress)

    def test_detailed_status_without_version_keeps_latest(self):
        """Availability without a known version still uses the generic value."""
        device = SimpleNamespace(
            device_id="gateway-id",
            device_name="TYDOM",
            mainVersionSW="03.24.29",
            update_available=True,
            target_firmware_version=None,
        )
        entity = HATydom(device, hass=None)

        self.assertEqual("latest", entity.latest_version)
        self.assertFalse(entity.in_progress)

    def test_gateway_choice_overrides_the_info_flag(self):
        """The gateway device's freshest report decides, not /info alone."""
        device = SimpleNamespace(
            device_id="gateway-id",
            device_name="TYDOM",
            mainVersionSW="03.24.29",
            updateAvailable=True,
            update_available=False,
        )
        entity = HATydom(device, hass=None)

        self.assertEqual("03.24.29", entity.latest_version)


class GatewayCommandError(Exception):
    """Stand-in for the gateway command error."""


async def _confirmed(command):
    try:
        await command
    except GatewayCommandError as err:
        raise RuntimeError("reported") from err


class TestTydomUpdateInstall(IsolatedAsyncioTestCase):
    """Installing the gateway firmware goes through the confirmed path."""

    async def test_rejected_install_is_reported(self):
        """A refusal from the gateway reaches the user."""
        gateway_entities = types.ModuleType(
            "custom_components.deltadore_tydom.gateway_entities"
        )
        gateway_entities.async_confirmed = _confirmed
        packages = {
            "custom_components": types.ModuleType("custom_components"),
            "custom_components.deltadore_tydom": types.ModuleType(
                "custom_components.deltadore_tydom"
            ),
            "custom_components.deltadore_tydom.gateway_entities": gateway_entities,
        }
        originals = {name: sys.modules.get(name) for name in packages}
        sys.modules.update(packages)
        try:
            device = SimpleNamespace(
                device_id="gateway-id",
                device_name="TYDOM",
                async_trigger_firmware_update=AsyncMock(),
            )
            entity = HATydom(device, hass=None)
            await entity.async_install(None, False)
            device.async_trigger_firmware_update.side_effect = GatewayCommandError()
            with self.assertRaisesRegex(RuntimeError, "reported"):
                await entity.async_install(None, False)
        finally:
            for name, module in originals.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
