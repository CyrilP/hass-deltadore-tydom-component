"""Platform updateintegration."""

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, LOGGER
from .hub import Hub


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Tydom update entities."""
    LOGGER.debug("Setting up Tydom update entities")
    hub: Hub = hass.data[DOMAIN][entry.entry_id]

    entities = [TydomUpdateEntity(hub, entry.title)]

    async_add_entities(entities)

class TydomUpdateEntity(UpdateEntity):
    """Mixin for update entity specific attributes."""

    _attr_supported_features = UpdateEntityFeature.INSTALL
    _attr_title = "Tydom"

    def __init__(
        self,
        hub: Hub,
        device_friendly_name: str,
    ) -> None:
        """Init Tydom connectivity class."""
        self._attr_name = f"{device_friendly_name} Tydom"
        # self._attr_unique_id = f"{hub.hub_id()}-update"
        self._hub = hub

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        self._hub.device_info.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._hub.device_info.remove_callback(self.async_write_ha_state)

    @property
    def installed_version(self) -> str | None:
        """Version currently in use."""
        if self._hub.device_info is None:
            return None
        # return self._hub.current_firmware
        return self._hub.device_info.main_version_sw

    @property
    def latest_version(self) -> str | None:
        """Latest version available for install."""
        if self._hub.device_info is not None:
            if self._hub.device_info.update_available:
                return self._hub.device_info.main_version_sw
            return self._hub.device_info.main_version_sw
        # FIXME : return correct version on update
        return None

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install an update."""
        await self._hub.async_trigger_firmware_update()