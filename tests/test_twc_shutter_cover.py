"""Tests for the Home Assistant cover backed by Tywell shutter scenarios."""

from __future__ import annotations

import ast
from enum import IntFlag
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock


def _load_twc_cover_class():
    """Load the TWC cover without importing Home Assistant."""
    source_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "deltadore_tydom"
        / "ha_entities.py"
    )
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    class_node = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "HATwcShutterCover"
    )
    isolated_module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            class_node,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(isolated_module)

    class Entity:
        async def async_added_to_hass(self) -> None:
            pass

        async def async_will_remove_from_hass(self) -> None:
            pass

        def async_write_ha_state(self) -> None:
            pass

    class CoverEntity(Entity):
        pass

    class HAEntity:
        def _get_hub(self):
            return self.hass.hub

    class CoverEntityFeature(IntFlag):
        OPEN = 1
        CLOSE = 2
        STOP = 4

    class CoverDeviceClass:
        SHUTTER = "shutter"

    class HomeAssistantError(Exception):
        pass

    class TydomDevice:
        pass

    namespace = {
        "Any": object,
        "CoverDeviceClass": CoverDeviceClass,
        "CoverEntity": CoverEntity,
        "CoverEntityFeature": CoverEntityFeature,
        "DeviceInfo": dict,
        "HAEntity": HAEntity,
        "HAScene": object,
        "HomeAssistantError": HomeAssistantError,
        "TydomDevice": TydomDevice,
    }
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return namespace, CoverEntity, CoverEntityFeature


NAMESPACE, CoverEntity, CoverEntityFeature = _load_twc_cover_class()
HATwcShutterCover = NAMESPACE["HATwcShutterCover"]


class ProtocolScene:
    """Minimal scenario protocol object."""

    def __init__(self, scene_id: int) -> None:
        """Initialise a mockable scenario identifier."""
        self.scene_id = scene_id
        self._id = str(scene_id)
        self.activate = AsyncMock()


class SceneEntity:
    """Minimal HAScene used by the isolated cover tests."""

    def __init__(self, scene_id: int, targets: set[str]) -> None:
        """Initialise one scenario and its resolved shutter targets."""
        self._device = ProtocolScene(scene_id)
        self._targets = targets
        self.device_info = {"identifiers": {("deltadore_tydom", "controller")}}

    def _get_affected_device_ids(self) -> set[str]:
        return set(self._targets)


class TargetDevice:
    """Protocol target with callback registration."""

    def __init__(self) -> None:
        """Initialise callback mocks."""
        self.register_callback = MagicMock()
        self.remove_callback = MagicMock()


class TargetCover(CoverEntity):
    """Home Assistant cover target with position-derived closed state."""

    def __init__(self, closed: bool | None) -> None:
        """Initialise the reported closed state."""
        self._closed = closed

    @property
    def is_closed(self) -> bool | None:
        """Return the target's reported state."""
        return self._closed


class TwcShutterCoverTests(IsolatedAsyncioTestCase):
    """Exercise command routing and conservative aggregate state."""

    @staticmethod
    def _entity(
        *,
        open_targets: set[str] | None = None,
        close_targets: set[str] | None = None,
        target_states: dict[str, bool | None] | None = None,
    ):
        open_scene = SceneEntity(1, open_targets or {"shutter_1"})
        close_scene = SceneEntity(2, close_targets or {"shutter_1"})
        stop_scene = SceneEntity(3, open_targets or {"shutter_1"})
        scenes = {
            "open": open_scene,
            "close": close_scene,
            "stop": stop_scene,
        }
        protocol_targets = {
            target_id: TargetDevice()
            for target_id in set().union(
                open_scene._targets,
                close_scene._targets,
            )
        }
        ha_targets = {
            target_id: TargetCover(state)
            for target_id, state in (target_states or {}).items()
        }
        hub = SimpleNamespace(
            online=True,
            devices=protocol_targets,
            ha_devices=ha_targets,
        )
        hass = SimpleNamespace(hub=hub)
        entity = HATwcShutterCover(
            "controller:default",
            scenes,
            open_scene,
            hass,
        )
        return entity, scenes, protocol_targets

    async def test_cover_routes_open_close_and_stop_to_scenarios(self) -> None:
        """Use the app-configured scenarios rather than rebuilding commands."""
        entity, scenes, _ = self._entity()

        await entity.async_open_cover()
        await entity.async_close_cover()
        await entity.async_stop_cover()

        scenes["open"]._device.activate.assert_awaited_once_with()
        scenes["close"]._device.activate.assert_awaited_once_with()
        scenes["stop"]._device.activate.assert_awaited_once_with()
        self.assertEqual(
            entity.supported_features,
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP,
        )
        self.assertTrue(entity.available)

    def test_cover_aggregates_only_complete_consistent_feedback(self) -> None:
        """Do not invent a state when targets differ or lack feedback."""
        closed, _, _ = self._entity(
            open_targets={"one", "two"},
            close_targets={"one", "two"},
            target_states={"one": True, "two": True},
        )
        self.assertTrue(closed.is_closed)
        self.assertFalse(closed.assumed_state)

        mixed, _, _ = self._entity(
            open_targets={"one", "two"},
            close_targets={"one", "two"},
            target_states={"one": True, "two": False},
        )
        self.assertFalse(mixed.is_closed)

        mismatched, _, _ = self._entity(
            open_targets={"one"},
            close_targets={"two"},
            target_states={"one": True, "two": True},
        )
        self.assertIsNone(mismatched.is_closed)
        self.assertTrue(mismatched.assumed_state)

    async def test_cover_subscribes_to_target_updates(self) -> None:
        """Refresh aggregate state whenever a controlled shutter updates."""
        entity, _, targets = self._entity(target_states={"shutter_1": True})
        entity.async_write_ha_state = MagicMock()

        await entity.async_added_to_hass()

        targets["shutter_1"].register_callback.assert_called_once_with(
            entity._handle_target_update
        )
        entity._handle_target_update()
        entity.async_write_ha_state.assert_called_once_with()

        await entity.async_will_remove_from_hass()
        targets["shutter_1"].remove_callback.assert_called_once_with(
            entity._handle_target_update
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
