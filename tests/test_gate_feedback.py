"""Regression tests for feedback-capable gate covers."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock


def _load_gate_class():
    """Load HaGate in isolation without importing Home Assistant."""
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
        if isinstance(node, ast.ClassDef) and node.name == "HaGate"
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

    class CoverEntity:
        pass

    class HAEntity:
        pass

    class CoverDeviceClass:
        GATE = "gate"

    class CoverEntityFeature(int):
        pass

    namespace = {
        "ATTR_POSITION": "position",
        "Any": object,
        "CoverDeviceClass": CoverDeviceClass,
        "CoverEntity": CoverEntity,
        "CoverEntityFeature": CoverEntityFeature,
        "DeviceInfo": dict,
        "HAEntity": HAEntity,
        "LOGGER": MagicMock(),
        "TydomGate": object,
        "_level_command_cover_features": MagicMock(),
    }
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return namespace["HaGate"]


HaGate = _load_gate_class()


class GateFeedbackTests(IsolatedAsyncioTestCase):
    """Verify feedback is exposed only when a gate actually provides it."""

    @staticmethod
    def _gate(**attributes):
        entity = HaGate.__new__(HaGate)
        entity._device = SimpleNamespace(**attributes)
        return entity

    def test_level_feedback_exposes_position_and_closed_state(self) -> None:
        """A feedback-capable gate follows the established garage convention."""
        closed = self._gate(level=0)
        partially_open = self._gate(level=65)

        self.assertTrue(closed.is_closed)
        self.assertEqual(closed.current_cover_position, 0)
        self.assertFalse(partially_open.is_closed)
        self.assertEqual(partially_open.current_cover_position, 65)

    def test_open_state_feedback_remains_supported(self) -> None:
        """Legacy openState feedback remains available without a level."""
        gate = self._gate(openState="LOCKED")

        self.assertTrue(gate.is_closed)
        self.assertIsNone(gate.current_cover_position)

    def test_gate_without_feedback_remains_stateless(self) -> None:
        """Dry-contact receivers do not claim an unavailable state."""
        gate = self._gate()

        self.assertIsNone(gate.is_closed)
        self.assertIsNone(gate.current_cover_position)

    async def test_feedback_capable_gate_accepts_a_requested_position(self) -> None:
        """A writable level is forwarded as a cover position request."""
        set_level = AsyncMock()
        gate = self._gate(set_level=set_level)

        await gate.async_set_cover_position(position=100)

        set_level.assert_awaited_once_with(100)


if __name__ == "__main__":
    import unittest

    unittest.main()
