"""Authorise user-requested removal of TYDOM registry devices."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN


def _device_config_entry_ids(device_entry: Any) -> set[str]:
    """Return config entry IDs across old and new device-registry models."""
    config_entry_id = getattr(device_entry, "config_entry_id", None)
    if config_entry_id is not None:
        return {str(config_entry_id)}

    return {
        str(entry_id) for entry_id in getattr(device_entry, "config_entries", set())
    }


def _tydom_identifier_values(device_entry: Any) -> set[str]:
    """Return this integration's identifiers from a device-registry entry."""
    return {
        str(value)
        for domain, value in getattr(device_entry, "identifiers", set())
        if domain == DOMAIN
    }


def can_remove_device(
    device_entry: Any,
    config_entry_id: str,
) -> bool:
    """Allow the user to remove a device owned by this TYDOM config entry."""
    if str(config_entry_id) not in _device_config_entry_ids(device_entry):
        return False

    return bool(_tydom_identifier_values(device_entry))
