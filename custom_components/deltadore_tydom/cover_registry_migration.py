"""Registry migration for toggle-only gate and garage controls."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN, LOGGER


def remove_legacy_toggle_cover(
    entity_registry: Any,
    config_entry_id: str,
    endpoint_unique_id: str,
) -> str | None:
    """Remove the obsolete cover replaced by a toggle-only button.

    The device registry entry is deliberately retained because the replacement
    button and any diagnostic entities continue to use it.
    """
    legacy_unique_id = f"{endpoint_unique_id}_cover"

    for entity_id, entity in list(entity_registry.entities.items()):
        if (
            entity_id.split(".", 1)[0] != "cover"
            or entity.platform != DOMAIN
            or entity.unique_id != legacy_unique_id
            or entity.config_entry_id != config_entry_id
        ):
            continue

        entity_registry.async_remove(entity_id)
        LOGGER.info(
            "Removed legacy cover %s replaced by a toggle-only button",
            entity_id,
        )
        return entity_id

    return None


def migrate_toggle_only_cover(
    hass: Any,
    config_entry_id: str,
    endpoint_unique_id: str,
) -> str | None:
    """Remove one legacy cover after its endpoint becomes a pulse button."""
    from homeassistant.helpers import entity_registry as er

    return remove_legacy_toggle_cover(
        er.async_get(hass),
        config_entry_id,
        endpoint_unique_id,
    )
