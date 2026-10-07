"""Diagnostics support for the Delta Dore TYDOM integration.

Home Assistant discovers this module automatically and adds a "Download
diagnostics" button both on the integration's config-entry page and on every
device page. No manifest/strings/translations change is required.

The dump is rebuilt from the already-populated in-memory ``hub.devices`` state
(no extra gateway round-trip), so the button works reliably on HAOS even when
the gateway is slow. Every device exposes its ``cmetadata`` (the parsed
``/devices/cmeta`` payload) and its raw ``/devices/data`` values -- including
the ``energyIndex``/``energyDistrib`` registers of a TYWATT.

Because users attach these reports to public GitHub issues, the dump is
anonymised before it leaves the instance:

* gateway/device identifiers that look like a MAC address (or the ``Tydom-XXXX``
  gateway id) are masked;
* the config-entry title and every device name are redacted -- a name may be a
  room or an occupant;
* ``cmetadata`` and the raw ``/devices/data`` payloads are passed through a
  recursive redactor that masks any key which is explicitly listed *or* whose
  name merely looks sensitive (e.g. an unexpected ``gatewaySerialNumber``), so a
  new or renamed field cannot slip an identifier or secret through.
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.helpers.redact import REDACTED
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

# Exact key names (compared case-insensitively) whose value is a credential or a
# network/hardware identifier and must never appear in a shared report. Covers
# both config-entry fields and raw ``/devices/data`` / ``/devices/cmeta`` keys.
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    key.lower()
    for key in {
        CONF_EMAIL,
        CONF_HOST,
        CONF_MAC,
        CONF_PASSWORD,
        CONF_PIN,
        CONF_TYDOM_PASSWORD,
        "mac",
        "macAddress",
        "ip",
        "ipAddress",
        "ipv6",
        "ssid",
        "bssid",
        "password",
        "pwd",
        "key",
        "token",
        "secret",
        "serial",
        "serialNumber",
        "collectId",
        # Per-product radio hardware UID (hexstring, serial-number equivalent).
        "uid",
        "latitude",
        "longitude",
        "geoloc",
        "gps",
        "phone",
        "unique_id",
    }
)

# Substrings that make a key sensitive even when its exact name is not listed
# above (e.g. ``wifiMac``, ``gatewaySerialNumber``, ``tydom_password``). Only
# substrings that cannot reasonably appear in a benign TYDOM field are used, to
# avoid over-redacting ordinary telemetry.
_SENSITIVE_KEY_SUBSTRINGS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "serial",
    "geoloc",
    "latitude",
    "longitude",
    "ssid",
    "mac",
    "collectid",
)

# A gateway's own device identifier is its MAC address (12 hex chars, no
# separators) or its ``Tydom-XXXX`` short id. Radio endpoint ids are decimal
# integers (optionally ``<endpoint>_<device>``), so these patterns mask the
# gateway while keeping the endpoint ids needed to cross-reference devices.
_MAC_LIKE = re.compile(r"[0-9A-Fa-f]{12}")
_GATEWAY_ID_LIKE = re.compile(r"Tydom-[0-9A-Za-z]+", re.IGNORECASE)


def _is_sensitive_key(key: Any) -> bool:
    """Return True if a payload key must have its value redacted."""
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    if lowered in _SENSITIVE_KEYS:
        return True
    return any(token in lowered for token in _SENSITIVE_KEY_SUBSTRINGS)


def _redact(value: Any) -> Any:
    """Recursively redact sensitive keys in dicts/lists of the payload.

    A key is redacted when :func:`_is_sensitive_key` matches it and its value is
    not empty (an empty value carries nothing to leak and masking it would only
    add noise). Non-container values are returned unchanged.
    """
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(key) and item not in (None, ""):
                redacted[key] = REDACTED
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _mask_identifier(value: Any) -> Any:
    """Redact an identifier that looks like a gateway MAC or ``Tydom-XXXX`` id."""
    if value is None:
        return value
    text = str(value)
    if _MAC_LIKE.fullmatch(text) or _GATEWAY_ID_LIKE.fullmatch(text):
        return REDACTED
    return value


def _redact_name(value: Any) -> Any:
    """Redact a user-facing name (may be a room or occupant) while keeping None."""
    if value in (None, ""):
        return value
    return REDACTED


def _device_snapshot(device: Any) -> dict[str, Any]:
    """Return a redacted snapshot of one in-memory TYDOM device.

    Public (non ``_``) attributes carry the raw ``/devices/data`` values; the
    private ``_metadata`` dict is the parsed ``/devices/cmeta`` payload. The
    device name is redacted (it may be a room or occupant name); its type,
    class and (masked) ids remain so the report stays usable for debugging.
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
        "name": _redact_name(device.device_name),
        "type": device.device_type,
        "endpoint": _mask_identifier(device.device_endpoint),
        "class": type(device).__name__,
        "cmetadata": _redact(getattr(device, "_metadata", None)),
        "data": _redact(data),
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
            "title": _redact_name(entry.title),
            "version": entry.version,
            "data": _redact(dict(entry.data)),
            "options": _redact(dict(entry.options)),
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
            "name": _redact_name(device_entry.name),
            "model": device_entry.model,
            "sw_version": device_entry.sw_version,
            "identifiers": [
                [_mask_identifier(part) for part in identifier]
                for identifier in device_entry.identifiers
            ],
        },
        "tydom_devices": snapshots,
    }
