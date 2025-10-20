"""Platform for sensor integration."""

import logging
from homeassistant.components.binary_sensor import BinarySensorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up binary sensors for Deltadore windows."""
    hub = hass.data[DOMAIN][entry.entry_id]
    hub.add_binary_sensor_callback = async_add_entities
