"""Platform for alarm control panel integration."""
from __future__ import annotations

import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add cover for passed config_entry in HA."""
    hub = hass.data[DOMAIN][config_entry.entry_id]
    hub.add_alarm_callback = async_add_entities