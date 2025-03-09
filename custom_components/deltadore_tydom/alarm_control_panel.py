"""Platform for alarm control panel integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)
from homeassistant.helpers import config_validation as cv
from .const import DOMAIN

SERVICE_ACKNOWLEDGE_EVENTS = "acknowledge_events"
SERVICE_GET_EVENTS = "get_events"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add cover for passed config_entry in HA."""
    hub = hass.data[DOMAIN][config_entry.entry_id]
    hub.add_alarm_callback = async_add_entities

    platform = async_get_current_platform()

    # This will call Entity.async_acknowledge_events(code=VALUE)
    platform.async_register_entity_service(
        SERVICE_ACKNOWLEDGE_EVENTS,
        {
            vol.Optional("code"): cv.string,
        },
        "async_acknowledge_events",
    )

    # This will call Entity.async_get_events(event_type=VALUE)
    platform.async_register_entity_service(
        SERVICE_GET_EVENTS,
        {
            vol.Optional("event_type"): vol.Any(
                "ALL", "EVENTS", "ON_OFF", "UNACKED_EVENTS"
            ),
        },
        "async_get_events",
        supports_response=SupportsResponse.ONLY,
    )
