"""Diagnostics support for the Delta Dore TYDOM integration.

Home Assistant discovers this module automatically and adds a "Download
diagnostics" button both on the integration's config-entry page and on every
device page. No manifest/strings/translations change is required.

The dump is rebuilt from the already-populated in-memory ``hub.devices`` state
(no extra gateway round-trip), so the button works reliably on HAOS even when
the gateway is slow. Every device exposes its ``cmetadata`` (the parsed
``/devices/cmeta`` payload) and its raw ``/devices/data`` values -- including
the ``energyIndex``/``energyDistrib`` registers of a TYWATT.
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.helpers.redact import REDACTED, async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_EMAIL,
    CONF_HOST,
    CONF_MAC,
    CONF_PASSWORD,
    CONF_PIN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .const import CONF_TYDOM_PASSWORD, DOMAIN

# Config-entry fields that identify the user or the gateway.
TO_REDACT_CONFIG: set[str] = {
    CONF_HOST,
    CONF_MAC,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_TYDOM_PASSWORD,
    CONF_PIN,
    "mac",
    "host",
    "email",
    "password",
    "unique_id",
}

# Keys that may appear in a device's raw ``/devices/data`` payload and that
# could carry network-identifying or secret values.
TO_REDACT_DEVICE: set[str] = {
    "mac",
    "macAddress",
    "ip",
    "ipAddress",
    "ipv6",
    "ssid",
    "password",
    "pwd",
    "key",
    "token",
    "serial",
    "serialNumber",
    "collectId",
    "latitude",
    "longitude",
    "geoloc",
    # Per-product radio hardware UID (hexstring, serial-number equivalent).
    "uid",
}

# A gateway's own device identifier is its MAC address (12 hex chars, no
# separators). Radio endpoint ids are decimal integers, so this pattern masks
# the gateway while keeping the endpoint ids needed to cross-reference devices.
_MAC_LIKE = re.compile(r"[0-9A-Fa-f]{12}")


def _mask_identifier(value: Any) -> Any:
    """Redact an identifier that looks like a gateway MAC address."""
    if value is not None and _MAC_LIKE.fullmatch(str(value)):
        return REDACTED
    return value


def _device_snapshot(device: Any) -> dict[str, Any]:
    """Return a redacted snapshot of one in-memory TYDOM device.

    Public (non ``_``) attributes carry the raw ``/devices/data`` values; the
    private ``_metadata`` dict is the parsed ``/devices/cmeta`` payload. The
    device name is kept (it may be a room name) because redacting it would make
    the dump unusable, and it carries no network-identifying value.
    """
    data = {
        key: value
        for key, value in vars(device).items()
        if not key.startswith("_") and not callable(value)
    }
    return {
        "device_id": _mask_identifier(device.device_id),
        "id": _mask_identifier(getattr(device, "_id", None)),
        "registry_device_id": _mask_identifier(device.registry_device_id),
        "name": device.device_name,
        "type": device.device_type,
        "endpoint": _mask_identifier(device.device_endpoint),
        "class": type(device).__name__,
        "cmetadata": getattr(device, "_metadata", None),
        "data": async_redact_data(data, TO_REDACT_DEVICE),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    hub = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    devices = (
        [_device_snapshot(device) for device in getattr(hub, "devices", {}).values()]
        if hub is not None
        else []
    )

    return {
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "data": async_redact_data(dict(entry.data), TO_REDACT_CONFIG),
            "options": async_redact_data(dict(entry.options), TO_REDACT_CONFIG),
        },
        "hub": None
        if hub is None
        else {
            "online": getattr(hub, "online", None),
            "device_count": len(devices),
            "remote_mode": getattr(
                getattr(hub, "_tydom_client", None), "_remote_mode", None
            ),
        },
        "devices": devices,
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for a single device."""
    hub = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    product_ids = {
        str(identifier[1])
        for identifier in device_entry.identifiers
        if identifier[0] == DOMAIN
    }

    snapshots: list[dict[str, Any]] = []
    if hub is not None:
        for device in getattr(hub, "devices", {}).values():
            device_keys = {
                str(device.device_id),
                str(getattr(device, "_id", None)),
                str(device.registry_device_id),
            }
            if device_keys & product_ids:
                snapshots.append(_device_snapshot(device))

    return {
        "device": {
            "name": device_entry.name,
            "model": device_entry.model,
            "sw_version": device_entry.sw_version,
            "identifiers": [
                list(identifier) for identifier in device_entry.identifiers
            ],
        },
        "tydom_devices": snapshots,
    }
