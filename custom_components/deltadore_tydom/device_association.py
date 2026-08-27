"""Capability checks and commands for TYDOM device association."""

from __future__ import annotations

from typing import Any


ASSOCIATION_COMMAND = "modeAsso"
IDENTIFY_COMMAND = "localisation"
COMMAND_START_VALUE = "START"


def supports_command(device: Any, command: str) -> bool:
    """Return whether an endpoint advertises a writable START command."""
    metadata = getattr(device, "_metadata", None)
    if not isinstance(metadata, dict):
        return False

    command_metadata = metadata.get(command)
    if not isinstance(command_metadata, dict):
        return False

    permission = str(command_metadata.get("permission", "")).lower()
    values = command_metadata.get("enum_values")
    return (
        "w" in permission and isinstance(values, list) and COMMAND_START_VALUE in values
    )


async def start_command(device: Any, command: str) -> None:
    """Start an advertised association or localisation command.

    The command is intentionally limited to values advertised in endpoint
    metadata.  This keeps association management safe across the varied TYDOM
    product families and firmware versions.
    """
    if not supports_command(device, command):
        raise ValueError(f"Device does not support the {command} command")

    endpoint_id = getattr(device, "_endpoint", None)
    if endpoint_id is None:
        raise ValueError("Device has no TYDOM endpoint")

    await device._tydom_client.put_devices_data(  # noqa: SLF001
        device._id,  # noqa: SLF001
        endpoint_id,
        command,
        COMMAND_START_VALUE,
    )
