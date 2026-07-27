"""Safe repairs for legacy Delta Dore TYDOM registry entries."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN, LOGGER


def remove_malformed_orphan_devices(
    device_registry: Any,
    entity_registry: Any,
    config_entry_id: str,
) -> list[str]:
    """Remove malformed numeric-ID devices only when a valid duplicate exists.

    Older entity grouping code could pass a numeric TYDOM identifier and name to
    Home Assistant. A later entity would then create the correct string-ID
    device, leaving an entity-less malformed duplicate in the registry.

    Devices with entities, without a matching string-ID device, or belonging to
    another config entry are deliberately left untouched.
    """
    entity_device_ids = {
        entity.device_id
        for entity in entity_registry.entities.values()
        if entity.device_id is not None
    }
    removed_device_ids: list[str] = []

    for device in list(device_registry.devices.values()):
        config_entries = getattr(device, "config_entries", set())
        if config_entry_id not in config_entries or device.id in entity_device_ids:
            continue

        malformed_identifiers = [
            identifier
            for domain, identifier in device.identifiers
            if domain == DOMAIN and not isinstance(identifier, str)
        ]
        if len(malformed_identifiers) != 1:
            continue

        malformed_identifier = malformed_identifiers[0]
        valid_duplicate = device_registry.async_get_device(
            identifiers={(DOMAIN, str(malformed_identifier))}
        )
        if valid_duplicate is None or valid_duplicate.id == device.id:
            continue

        device_registry.async_remove_device(device.id)
        removed_device_ids.append(device.id)
        LOGGER.warning(
            "Removed malformed orphan TYDOM device registry entry %s "
            "(numeric identifier %s); valid string-ID device %s is retained",
            device.id,
            malformed_identifier,
            valid_duplicate.id,
        )

    return removed_device_ids


def cleanup_malformed_orphan_devices(hass: Any, config_entry_id: str) -> list[str]:
    """Repair malformed registry entries for one configured TYDOM gateway."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    return remove_malformed_orphan_devices(
        dr.async_get(hass),
        er.async_get(hass),
        config_entry_id,
    )
