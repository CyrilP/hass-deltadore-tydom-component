"""The Detailed Delta Dore Tydom Push integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PIN, Platform
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from . import hub
from .const import (
    DOMAIN,
    CONF_TYDOM_PASSWORD,
    CONF_ZONES_HOME,
    CONF_ZONES_AWAY,
    CONF_ZONES_NIGHT,
    CONF_REFRESH_INTERVAL,
)

# List of platforms to support. There should be a matching .py file for each,
# eg <cover.py> and <sensor.py>
PLATFORMS: list[str] = [
    # Platform.ALARM_CONTROL_PANEL,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.SENSOR,
    Platform.LOCK,
    Platform.LIGHT,
    Platform.UPDATE,
    Platform.ALARM_CONTROL_PANEL,
    Platform.WEATHER,
    Platform.BINARY_SENSOR,
    Platform.SCENE,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.EVENT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Delta Dore Tydom from a config entry."""

    entry.async_on_unload(entry.add_update_listener(update_listener))

    # Store an instance of the "connecting" class that does the work of speaking
    # with your actual devices.
    zone_home = entry.data.get(CONF_ZONES_HOME) or ""
    zone_away = entry.data.get(CONF_ZONES_AWAY) or ""
    zone_night = entry.data.get(CONF_ZONES_NIGHT) or ""

    pin = entry.data.get(CONF_PIN) or ""

    refresh_interval = "30"
    if CONF_REFRESH_INTERVAL in entry.data:
        refresh_interval = entry.data[CONF_REFRESH_INTERVAL]

    tydom_hub = hub.Hub(
        hass,
        entry,
        entry.data[CONF_HOST],
        entry.data[CONF_MAC],
        entry.data[CONF_TYDOM_PASSWORD],
        refresh_interval,
        str(zone_home),
        str(zone_away),
        str(zone_night),
        str(pin),
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
            target=tydom_hub.refresh_all(),
            hass=hass,
            name="Tydom refresh all metadata and data",
        )
        entry.async_create_background_task(
            target=tydom_hub.refresh_data_1s(), hass=hass, name="Tydom refresh data 1s"
        )
        entry.async_create_background_task(
            target=tydom_hub.refresh_data(), hass=hass, name="Tydom refresh data"
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


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener."""
    tydom_hub = hass.data[DOMAIN][entry.entry_id]
    tydom_hub.update_config(
        entry.data[CONF_REFRESH_INTERVAL],
        entry.data[CONF_ZONES_HOME],
        entry.data[CONF_ZONES_AWAY],
        entry.data[CONF_ZONES_NIGHT],
    )
