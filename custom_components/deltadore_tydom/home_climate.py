"""Reported installation-wide HVAC mode and absence, independent of zones."""

from collections.abc import Callable
from typing import Any


HVAC_OPTIONS = {
    "STOP": "off",
    "HEATING": "heat",
    "COOLING": "cool",
    "VENTILATING": "fan_only",
    "DRYING": "dry",
}


class HomeClimateState:
    """Keep only authoritative general-mode data returned by the gateway."""

    def __init__(self) -> None:
        """Initialise an unknown state and an empty subscriber set."""
        self.mode: str | None = None
        self.support: tuple[str, ...] = ()
        self.absence_to: int | None = None
        self._listeners: set[Callable[[], None]] = set()

    @property
    def absence_active(self) -> bool:
        """Return whether the gateway reports a timed or permanent absence."""
        return self.absence_to is not None and self.absence_to != 0

    @property
    def lock_reason(self) -> str | None:
        """Return the general mode that currently locks zone controls."""
        if self.mode == "STOP":
            return "off"
        if self.absence_active:
            return "absence"
        return None

    @property
    def current_option(self) -> str | None:
        """Return the general state displayed by the official app."""
        if self.absence_active:
            return "away"
        if self.mode in ("UNKNOWN", "MIXED"):
            return "mixed"
        return HVAC_OPTIONS.get(self.mode)

    @property
    def options(self) -> list[str]:
        """Return supported commands and any current read-only Mixed state."""
        options = [
            option for mode, option in HVAC_OPTIONS.items() if mode in self.support
        ]
        if self.absence_to is not None:
            options.append("away")
        # Mixed is a reported aggregate, never a mode sent to the gateway.
        if self.current_option == "mixed":
            options.append("mixed")
        return options

    def add_listener(self, listener: Callable[[], None]) -> None:
        """Subscribe to real general-mode changes."""
        self._listeners.add(listener)

    def remove_listener(self, listener: Callable[[], None]) -> None:
        """Unsubscribe a previously registered listener."""
        self._listeners.discard(listener)

    def update(self, resource: str, data: Any) -> None:
        """Apply a valid gateway response and notify only actual changes."""
        if not isinstance(data, dict):
            return
        before = (self.mode, self.support, self.absence_to)
        if resource == "hvac":
            mode = data.get("mode")
            if mode in (*HVAC_OPTIONS, "UNKNOWN", "MIXED"):
                self.mode = mode
            support = data.get("support")
            if isinstance(support, list):
                self.support = tuple(mode for mode in HVAC_OPTIONS if mode in support)
        elif resource == "absence":
            until = data.get("to")
            if isinstance(until, int) and not isinstance(until, bool) and until >= -1:
                self.absence_to = until
        if before != (self.mode, self.support, self.absence_to):
            for listener in tuple(self._listeners):
                listener()
