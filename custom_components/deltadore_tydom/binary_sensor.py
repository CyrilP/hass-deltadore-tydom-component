"""Platform for sensor integration."""

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up binary sensors for Deltadore windows."""
    hub = hass.data[DOMAIN][entry.entry_id]
    hub.add_binary_sensor_callback = async_add_entities
