"""Regression tests for native Home Assistant TYDOM group entities."""

from __future__ import annotations

import ast
import asyncio
from contextlib import suppress
from enum import IntFlag
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock


def _load_group_entity_classes():
    """Load only the group classes without Home Assistant dependencies."""
    source_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "deltadore_tydom"
        / "ha_entities.py"
    )
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    class_names = {
        "HAGroupEntity",
        "HALightGroup",
        "HACoverGroup",
        "HASwitchGroup",
    }
    class_nodes = [
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name in class_names
    ]
    isolated_module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            *class_nodes,
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

    class LightEntity(Entity):
        pass

    class CoverEntity(Entity):
        pass

    class SwitchEntity(Entity):
        pass

    class HAEntity:
        def _get_hub(self):
            return self.hass.hub

        def _get_tydom_gateway_device_id(self):
            return "gateway"

    class CoverEntityFeature(IntFlag):
        OPEN = 1
        CLOSE = 2
        STOP = 4

    class CoverDeviceClass:
        AWNING = "awning"
        SHUTTER = "shutter"

    class ColorMode:
        ONOFF = "onoff"

    class TydomGroup:
        pass

    namespace = {
        "Any": object,
        "asyncio": asyncio,
        "ColorMode": ColorMode,
        "CoverDeviceClass": CoverDeviceClass,
        "CoverEntity": CoverEntity,
        "CoverEntityFeature": CoverEntityFeature,
        "DeviceInfo": dict,
        "DOMAIN": "deltadore_tydom",
        "HAEntity": HAEntity,
        "LightEntity": LightEntity,
        "LOGGER": MagicMock(),
        "suppress": suppress,
        "SwitchEntity": SwitchEntity,
        "TydomGroup": TydomGroup,
    }
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return namespace


GROUP_CLASSES = _load_group_entity_classes()
HALightGroup = GROUP_CLASSES["HALightGroup"]
HACoverGroup = GROUP_CLASSES["HACoverGroup"]
HASwitchGroup = GROUP_CLASSES["HASwitchGroup"]
TydomGroup = GROUP_CLASSES["TydomGroup"]


class GroupDevice(TydomGroup):
    """Minimal protocol group used by the isolated entity tests."""

    def __init__(self, usage: str, member_ids: list[str]) -> None:
        """Initialise group identity, usage and membership."""
        self.device_id = "group_1"
        self.device_name = f"All {usage}s"
        self.device_ids = member_ids
        self.group_id = self.device_id
        self.group_usage = usage
        self._ha_device = None


class MemberDevice:
    """Minimal controllable member with update callback support."""

    def __init__(
        self,
        device_id: str,
        *,
        level: int | None = None,
        position: int | None = None,
        on: bool | None = None,
    ) -> None:
        """Initialise state and mockable member operations."""
        self.device_id = f"{device_id}_{device_id}"
        self._id = device_id
        self.device_name = f"Device {device_id}"
        self.device_type = "test"
        if level is not None:
            self.level = level
        if position is not None:
            self.position = position
        if on is not None:
            self.on = on
        self.turn_on = AsyncMock()
        self.turn_off = AsyncMock()
        self.up = AsyncMock()
        self.down = AsyncMock()
        self.stop = AsyncMock()
        self.register_callback = MagicMock()
        self.remove_callback = MagicMock()


class NativeGroupEntityTests(IsolatedAsyncioTestCase):
    """Exercise aggregate state and command fan-out."""

    @staticmethod
    def _entity(entity_class, usage: str, members: list[MemberDevice]):
        member_ids = []
        stored_devices = {}
        for member in members:
            member_ids.extend([member._id, member.device_id])
            stored_devices[member.device_id] = member
        group = GroupDevice(usage, member_ids)
        hass = SimpleNamespace(hub=SimpleNamespace(devices=stored_devices))
        return entity_class(group, hass)

    async def test_light_group_aggregates_state_and_deduplicates_commands(self) -> None:
        """Report any light on and command each physical member only once."""
        first = MemberDevice("1", level=0)
        second = MemberDevice("2", level=50)
        entity = self._entity(HALightGroup, "light", [first, second])

        self.assertTrue(entity.is_on)
        self.assertEqual(entity.extra_state_attributes["device_count"], 2)

        await entity.async_turn_off()

        first.turn_off.assert_awaited_once_with()
        second.turn_off.assert_awaited_once_with()
        self.assertFalse(entity.is_on)
        entity._clear_assumed_state()

    async def test_light_group_keeps_requested_state_until_members_converge(self) -> None:
        """Avoid presenting a stale light state while TYDOM polls each member."""
        first = MemberDevice("1", level=100)
        second = MemberDevice("2", level=100)
        entity = self._entity(HALightGroup, "light", [first, second])

        await entity.async_turn_off()

        self.assertFalse(entity.is_on)
        first.level = 0
        entity._handle_member_update()
        self.assertFalse(entity.is_on)
        self.assertIsNotNone(entity._assumed_is_on)

        second.level = 0
        entity._handle_member_update()
        self.assertFalse(entity.is_on)
        self.assertIsNone(entity._assumed_is_on)

    async def test_light_group_assumed_state_expires(self) -> None:
        """Fall back to member reports when they do not reach the requested state."""
        member = MemberDevice("1", level=100)
        entity = self._entity(HALightGroup, "light", [member])
        entity._ASSUMED_STATE_TIMEOUT = 0

        await entity.async_turn_off()
        self.assertFalse(entity.is_on)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        self.assertTrue(entity.is_on)
        self.assertIsNone(entity._assumed_is_on)

    async def test_cover_group_requires_all_members_to_be_closed(self) -> None:
        """Aggregate closed state and fan out native cover commands."""
        first = MemberDevice("1", position=0)
        second = MemberDevice("2", position=0)
        entity = self._entity(HACoverGroup, "shutter", [first, second])

        self.assertTrue(entity.is_closed)
        second.position = 25
        self.assertFalse(entity.is_closed)

        await entity.async_open_cover()
        await entity.async_stop_cover()

        first.up.assert_awaited_once_with()
        second.up.assert_awaited_once_with()
        first.stop.assert_awaited_once_with()
        second.stop.assert_awaited_once_with()
        entity._clear_assumed_state()

    async def test_cover_group_enables_close_while_positions_catch_up(self) -> None:
        """Do not leave Close disabled while TYDOM still reports old positions."""
        first = MemberDevice("1", position=0)
        second = MemberDevice("2", position=0)
        entity = self._entity(HACoverGroup, "shutter", [first, second])

        await entity.async_open_cover()

        self.assertFalse(entity.is_closed)
        first.position = 50
        entity._handle_member_update()
        self.assertFalse(entity.is_closed)
        self.assertIsNotNone(entity._assumed_is_closed)

        second.position = 25
        entity._handle_member_update()
        self.assertFalse(entity.is_closed)
        self.assertIsNone(entity._assumed_is_closed)

    async def test_awning_group_opens_downwards_and_closes_upwards(self) -> None:
        """Translate HA awning semantics into Delta Dore movement commands."""
        member = MemberDevice("1", position=100)
        entity = self._entity(HACoverGroup, "awning", [member])

        self.assertTrue(entity.is_closed)
        await entity.async_open_cover()
        await entity.async_close_cover()

        member.down.assert_awaited_once_with()
        member.up.assert_awaited_once_with()
        entity._clear_assumed_state()

    async def test_switch_group_reports_any_member_on(self) -> None:
        """Represent plug groups as switches with aggregate state."""
        first = MemberDevice("1", on=False)
        second = MemberDevice("2", on=True)
        entity = self._entity(HASwitchGroup, "plug", [first, second])

        self.assertTrue(entity.is_on)

        await entity.async_turn_on()

        first.turn_on.assert_awaited_once_with()
        second.turn_on.assert_awaited_once_with()

    def test_groups_never_create_generic_diagnostic_sensors(self) -> None:
        """Keep membership fields out of the sensor platform."""
        entity = self._entity(HALightGroup, "light", [MemberDevice("1", level=0)])

        self.assertEqual(entity.get_sensors(), [])

    def test_group_registers_members_discovered_after_entity_creation(self) -> None:
        """Recover when TYDOM sends the group before its physical members."""
        group = GroupDevice("light", ["1", "2"])
        hass = SimpleNamespace(hub=SimpleNamespace(devices={}))
        entity = HALightGroup(group, hass)
        entity.entity_id = "light.all_lights"
        entity.async_write_ha_state = MagicMock()
        first = MemberDevice("1", level=0)
        second = MemberDevice("2", level=0)
        hass.hub.devices = {first.device_id: first, second.device_id: second}

        entity.refresh_members()

        first.register_callback.assert_called_once_with(entity._handle_member_update)
        second.register_callback.assert_called_once_with(entity._handle_member_update)
        entity.async_write_ha_state.assert_called_once_with()
        self.assertFalse(entity.is_on)


if __name__ == "__main__":
    import unittest

    unittest.main()
