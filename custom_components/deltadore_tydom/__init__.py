"""The Detailed Delta Dore Tydom Push integration."""
from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PIN, Platform
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from . import hub
from .const import DOMAIN, CONF_TYDOM_PASSWORD

# List of platforms to support. There should be a matching .py file for each,
# eg <cover.py> and <sensor.py>
PLATFORMS: list[str] = [
    # Platform.ALARM_CONTROL_PANEL,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.SENSOR,
    Platform.LOCK,
    Platform.LIGHT,
    Platform.UPDATE
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Delta Dore Tydom from a config entry."""
    # Store an instance of the "connecting" class that does the work of speaking
    # with your actual devices.
    pin = None
    if CONF_PIN in entry.data:
        pin = entry.data[CONF_PIN]

    tydom_hub = hub.Hub(
        hass,
        entry,
        entry.data[CONF_HOST],
        entry.data[CONF_MAC],
        entry.data[CONF_TYDOM_PASSWORD],
        pin,
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = tydom_hub

    try:
        connection = await tydom_hub.connect()
        entry.async_create_background_task(
            target=tydom_hub.setup(connection), hass=hass, name="Tydom"
        )
        entry.async_create_background_task(
           target=tydom_hub.ping(), hass=hass, name="Tydom ping"
        )
        entry.async_create_background_task(
           target=tydom_hub.refresh_all(), hass=hass, name="Tydom refresh metadata and data"
        )

    except Exception as err:
        raise ConfigEntryNotReady from err

    # This creates each HA object for each platform your device requires.
    # It's done by calling the `async_setup_entry` function in each platform module.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
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
