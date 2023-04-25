"""The Detailed Hello World Push integration."""
from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PASSWORD, CONF_PIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import hub
from .const import DOMAIN

# List of platforms to support. There should be a matching .py file for each,
# eg <cover.py> and <sensor.py>
PLATFORMS: list[str] = ["cover", "sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Delta Dore Tydom from a config entry."""
    # Store an instance of the "connecting" class that does the work of speaking
    # with your actual devices.
    pin = None
    if CONF_PIN in entry.data:
        pin = entry.data[CONF_PIN]

    tydom_hub = hub.Hub(
        hass,
        entry.data[CONF_HOST],
        entry.data[CONF_MAC],
        entry.data[CONF_PASSWORD],
        pin,
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = tydom_hub

    await tydom_hub.setup()

    # This creates each HA object for each platform your device requires.
    # It's done by calling the `async_setup_entry` function in each platform module.
    hass.config_entries.async_setup_platforms(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # This is called when an entry/configured device is to be removed. The class
    # needs to unload itself, and remove callbacks. See the classes for further
    # details
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
