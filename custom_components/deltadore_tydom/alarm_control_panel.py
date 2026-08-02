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
SERVICE_GET_ALARM_PRODUCTS = "get_alarm_products"
SERVICE_GET_ALARM_PRODUCT_CONFIGURATION = "get_alarm_product_configuration"
SERVICE_CONFIGURE_ALARM_PRODUCT = "configure_alarm_product"
SERVICE_RENAME_ALARM_ZONE = "rename_alarm_zone"

ALARM_CODE_SCHEMA = vol.All(cv.string, vol.Length(min=1))
PRODUCT_ID_SCHEMA = vol.All(vol.Coerce(int), vol.Range(min=0))
ZONE_ID_SCHEMA = vol.All(vol.Coerce(int), vol.Range(min=0, max=7))


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

    platform.async_register_entity_service(
        SERVICE_GET_ALARM_PRODUCTS,
        {},
        "async_get_alarm_products",
        supports_response=SupportsResponse.ONLY,
    )

    platform.async_register_entity_service(
        SERVICE_GET_ALARM_PRODUCT_CONFIGURATION,
        {
            vol.Required("code"): ALARM_CODE_SCHEMA,
            vol.Required("product_id"): PRODUCT_ID_SCHEMA,
        },
        "async_get_alarm_product_configuration",
        supports_response=SupportsResponse.ONLY,
    )

    platform.async_register_entity_service(
        SERVICE_CONFIGURE_ALARM_PRODUCT,
        {
            vol.Required("code"): ALARM_CODE_SCHEMA,
            vol.Required("product_id"): PRODUCT_ID_SCHEMA,
            vol.Optional("active"): cv.boolean,
            vol.Optional("zone"): ZONE_ID_SCHEMA,
        },
        "async_configure_alarm_product",
    )

    platform.async_register_entity_service(
        SERVICE_RENAME_ALARM_ZONE,
        {
            vol.Required("code"): ALARM_CODE_SCHEMA,
            vol.Required("zone_id"): ZONE_ID_SCHEMA,
            vol.Required("name"): vol.All(
                cv.string, str.strip, vol.Length(min=1, max=64)
            ),
        },
        "async_rename_alarm_zone",
    )
