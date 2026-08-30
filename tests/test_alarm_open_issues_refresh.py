"""Tests for refreshing TYXAL open issues after arm commands."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase


class _AlarmCommandError(Exception):
    """Stand-in for the gateway command error."""

    def __init__(self, result: str) -> None:
        self.result = result


class _HomeAssistantError(Exception):
    """Stand-in for Home Assistant's user-facing error."""


def _load_run_alarm_command():
    """Load just the command helper without importing Home Assistant."""
    source_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "deltadore_tydom"
        / "ha_entities.py"
    )
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    alarm_node = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "HaAlarm"
    )
    method = next(
        node
        for node in alarm_node.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_alarm_command"
    )
    isolated_module = ast.Module(
        body=[
            ast.ClassDef(
                name="Harness", bases=[], keywords=[], body=[method], decorator_list=[]
            )
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(isolated_module)
    namespace = {
        "TydomAlarmCommandError": _AlarmCommandError,
        "HomeAssistantError": _HomeAssistantError,
    }
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return namespace["Harness"]._run_alarm_command


_RUN_ALARM_COMMAND = _load_run_alarm_command()


class _Harness:
    """Minimal alarm entity state used by the extracted command helper."""

    _run_alarm_command = _RUN_ALARM_COMMAND

    def __init__(self) -> None:
        self._device = SimpleNamespace(clear_open_issues=self._clear_open_issues)
        self.clear_calls = 0
        self.refresh_calls = 0
        self.write_calls = 0

    def _clear_open_issues(self) -> None:
        self.clear_calls += 1

    def _schedule_open_issues_refresh(self) -> None:
        self.refresh_calls += 1

    def async_write_ha_state(self) -> None:
        self.write_calls += 1


class AlarmOpenIssuesRefreshTests(IsolatedAsyncioTestCase):
    """Ensure detailed issues follow the outcome of an arm attempt."""

    async def test_refused_arming_schedules_one_open_issues_refresh(self) -> None:
        """A central refusal is the only automatic detailed-history trigger."""
        entity = _Harness()

        async def command() -> None:
            raise _AlarmCommandError("DENIED")

        with self.assertRaises(_HomeAssistantError):
            await entity._run_alarm_command(command(), "arming")

        self.assertEqual(entity.refresh_calls, 1)
        self.assertEqual(entity.clear_calls, 0)

    async def test_successful_arming_clears_previous_open_issues(self) -> None:
        """An accepted arm invalidates blockers from a previous refusal."""
        entity = _Harness()

        async def command() -> None:
            return None

        await entity._run_alarm_command(command(), "arming")

        self.assertEqual(entity.refresh_calls, 0)
        self.assertEqual(entity.clear_calls, 1)
        self.assertEqual(entity.write_calls, 1)

    async def test_non_arming_denial_does_not_refresh_open_issues(self) -> None:
        """Disarming failures are unrelated to arming blockers."""
        entity = _Harness()

        async def command() -> None:
            raise _AlarmCommandError("DENIED")

        with self.assertRaises(_HomeAssistantError):
            await entity._run_alarm_command(command(), "disarming")

        self.assertEqual(entity.refresh_calls, 0)
