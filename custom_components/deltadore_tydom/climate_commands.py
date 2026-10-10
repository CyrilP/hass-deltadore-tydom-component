"""Track thermostat requests separately from the reported device state."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import math
from typing import Any


CONFIRMATION_TIMEOUT = 120.0


@dataclass
class PendingCommand:
    """One requested value and its confirmation deadline."""

    value: Any
    timeout: asyncio.TimerHandle | None = None
    overdue: bool = False


class ClimateCommandTracker:
    """Keep requests pending until a device update reports the requested state."""

    def __init__(self, notify: Callable[[], None]) -> None:
        """Initialise an empty tracker and its state-change callback."""
        self._notify = notify
        self._pending: dict[str, PendingCommand] = {}
        self._last_status = "idle"

    @property
    def pending(self) -> bool:
        """Return whether at least one request lacks device confirmation."""
        return bool(self._pending)

    @property
    def attributes(self) -> dict[str, Any]:
        """Return requested values without replacing the actual climate state."""
        status = self._last_status
        if self._pending:
            status = (
                "unconfirmed"
                if any(command.overdue for command in self._pending.values())
                else "pending"
            )
        return {
            "command_status": status,
            **{
                f"requested_{key}": command.value
                for key, command in self._pending.items()
            },
        }

    def begin(self, key: str, value: Any) -> PendingCommand:
        """Start or supersede one request without resending it."""
        previous = self._pending.pop(key, None)
        if previous is not None and previous.timeout is not None:
            previous.timeout.cancel()
        command = PendingCommand(value)
        self._pending[key] = command
        command.timeout = asyncio.get_running_loop().call_later(
            CONFIRMATION_TIMEOUT, self._mark_unconfirmed, key, command
        )
        self._notify()
        return command

    def _mark_unconfirmed(self, key: str, command: PendingCommand) -> None:
        """Signal a slow device; an elapsed deadline is not a confirmation."""
        if self._pending.get(key) is command:
            command.overdue = True
            command.timeout = None
            self._notify()

    def fail(
        self, key: str, command: PendingCommand, *, cancelled: bool = False
    ) -> None:
        """Do not let failure of an older request remove a newer one."""
        if self._pending.get(key) is not command:
            return
        self._remove(key)
        self._last_status = "cancelled" if cancelled else "failed"
        self._notify()

    def confirm(self, reported: dict[str, Any]) -> None:
        """Confirm only matching values from a real device update."""
        confirmed = []
        for key, command in self._pending.items():
            actual = reported.get(key)
            matches = actual is not None and actual == command.value
            if key == "temperature" and actual is not None:
                try:
                    matches = math.isclose(
                        float(actual), float(command.value), rel_tol=0, abs_tol=0.0001
                    )
                except (TypeError, ValueError):
                    matches = False
            if matches:
                confirmed.append(key)
        for key in confirmed:
            self._remove(key)
        if confirmed:
            self._last_status = "confirmed"
            self._notify()

    def _remove(self, key: str) -> None:
        command = self._pending.pop(key)
        if command.timeout is not None:
            command.timeout.cancel()

    def close(self) -> None:
        """Cancel timers when the climate entity is unloaded."""
        had_pending = self.pending
        for key in tuple(self._pending):
            self._remove(key)
        self._last_status = "idle"
        if had_pending:
            self._notify()
