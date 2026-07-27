"""Registry migration for dedicated remote-control entities."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN, LOGGER


def remove_legacy_remote_endpoint(
    device_registry: Any,
    entity_registry: Any,
    config_entry_id: str,
    endpoint_unique_id: str,
) -> list[str]:
    """Remove one obsolete generic endpoint when it is safe to do so."""
    legacy_device = device_registry.async_get_device(
        identifiers={(DOMAIN, endpoint_unique_id)}
    )
    if legacy_device is None:
        return []

    if config_entry_id not in getattr(legacy_device, "config_entries", set()):
        return []

    allowed_unique_ids = {
        f"{endpoint_unique_id}_sensor",
        f"{endpoint_unique_id}_action",
        f"{endpoint_unique_id}_battDefect",
    }
    attached_entities = [
        (entity_id, entity)
        for entity_id, entity in entity_registry.entities.items()
        if entity.device_id == legacy_device.id
    ]
    if any(
        entity.platform != DOMAIN or entity.unique_id not in allowed_unique_ids
        for _, entity in attached_entities
    ):
        LOGGER.warning(
            "Keeping legacy remote-control device %s because it has "
            "unrecognised entities",
            legacy_device.id,
        )
        return []

    removed_entity_ids = [entity_id for entity_id, _ in attached_entities]
    for entity_id in removed_entity_ids:
        entity_registry.async_remove(entity_id)
    device_registry.async_remove_device(legacy_device.id)

    LOGGER.info(
        "Removed legacy generic remote-control endpoint %s (%d entities)",
        endpoint_unique_id,
        len(removed_entity_ids),
    )
    return removed_entity_ids


def migrate_legacy_remote_endpoint(
    hass: Any,
    config_entry_id: str,
    endpoint_unique_id: str,
) -> list[str]:
    """Remove the generic registry records replaced by a remote event entity."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    return remove_legacy_remote_endpoint(
        dr.async_get(hass),
        er.async_get(hass),
        config_entry_id,
        endpoint_unique_id,
    )
