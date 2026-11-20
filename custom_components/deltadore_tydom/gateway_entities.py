"""Gateway maintenance entities: status LED, restart and firmware updates.

The resources used here were identified in the official Tydom application:

* ``/configs/gateway/led``: colour of the status LED for each gateway state;
* ``/configs/gateway/reboot``: restart the gateway;
* ``/configs/gateway/update/status`` and ``/configs/gateway/update/setup``:
  detailed gateway firmware status and manual/automatic update mode;
* ``/devices/update/status`` and ``/devices/update``: firmware of the radio
  products, deployed by the gateway;
* ``/configs/gateway/network/status``: IP and internet connectivity.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN
from .entity_names import set_entity_name
from .tydom.tydom_devices import (
    GATEWAY_LED_COLORS,
    GATEWAY_UPDATE_MODES,
    Tydom,
)

# Firmware states reported in ``fwList[].status`` by the gateway.
_FIRMWARE_BUSY_STATES = {"downloading"}


class GatewayEntity(Entity):
    """Base class for an entity attached to the Tydom gateway device."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        device: Tydom,
        key: str,
        unique_suffix: str,
        placeholders: dict[str, str] | None = None,
    ) -> None:
        """Attach the entity to the gateway device and name it."""
        self._device = device
        self._attr_unique_id = f"{device.device_id}_{unique_suffix}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device.device_id)})
        set_entity_name(self, key, placeholders=placeholders)

    async def async_added_to_hass(self) -> None:
        """Refresh the entity whenever the gateway publishes new data."""
        await super().async_added_to_hass()
        self._device.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Stop following gateway updates."""
        self._device.remove_callback(self.async_write_ha_state)
        await super().async_will_remove_from_hass()


# ----------------------------------------------------------------------
# Status LED
# ----------------------------------------------------------------------


class GatewayLedSwitch(GatewayEntity, SwitchEntity):
    """Switch the gateway status LED on or off."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:led-on"

    def __init__(self, device: Tydom) -> None:
        """Initialise the LED switch."""
        super().__init__(device, "gateway_led", "gateway_led")

    @property
    def available(self) -> bool:
        """Available once the gateway has reported its LED configuration."""
        return self._device.led_is_on is not None

    @property
    def is_on(self) -> bool | None:
        """Return whether the LED is lit while the gateway is connected."""
        return self._device.led_is_on

    @property
    def icon(self) -> str:
        """Reflect the LED state in the icon."""
        return "mdi:led-on" if self._device.led_is_on else "mdi:led-off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the colour of every gateway state."""
        config = self._device.led_config or {}
        return {"colors": dict(config.get("color", {})), "power": config.get("power")}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Light the LED with the last colour used."""
        await self._device.async_turn_led_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the LED off."""
        await self._device.async_turn_led_off()


class GatewayLedColorSelect(GatewayEntity, SelectEntity):
    """Choose the colour of the status LED while the gateway is connected."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:palette"

    def __init__(self, device: Tydom) -> None:
        """Initialise the LED colour select."""
        super().__init__(device, "gateway_led_color", "gateway_led_color")
        # HA state translations require lowercase option keys.
        self._options = {color.lower(): color for color in GATEWAY_LED_COLORS}
        self._attr_options = list(self._options)

    @property
    def available(self) -> bool:
        """Available once the gateway has reported its LED configuration."""
        return self._device.led_color is not None

    @property
    def current_option(self) -> str | None:
        """Return the current colour (None while the LED is off)."""
        color = self._device.led_color
        if color is None or color.lower() not in self._options:
            return None
        return color.lower()

    async def async_select_option(self, option: str) -> None:
        """Apply a colour; this also switches the LED on."""
        await self._device.async_set_led_color(self._options[option])


# ----------------------------------------------------------------------
# Maintenance
# ----------------------------------------------------------------------


class GatewayRebootButton(GatewayEntity, ButtonEntity):
    """Restart the gateway."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, device: Tydom) -> None:
        """Initialise the restart button."""
        super().__init__(device, "reboot_gateway", "reboot_gateway")

    async def async_press(self) -> None:
        """Restart the gateway."""
        await self._device.async_reboot()


class GatewayConnectivitySensor(GatewayEntity, BinarySensorEntity):
    """Report one connectivity status from ``/configs/gateway/network/status``."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, device: Tydom, attribute: str, key: str) -> None:
        """Initialise the connectivity sensor for ``attribute``."""
        self._attribute = attribute
        super().__init__(device, key, key)

    @property
    def available(self) -> bool:
        """Available once the gateway has reported this status."""
        return self._attribute in self._device.network_status

    @property
    def is_on(self) -> bool | None:
        """Return True when the gateway reports ``OK``."""
        value = self._device.network_status.get(self._attribute)
        return None if value is None else str(value).upper() == "OK"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the raw status reported by the gateway."""
        return {"status": self._device.network_status.get(self._attribute)}


class GatewayUpdateModeSelect(GatewayEntity, SelectEntity):
    """Choose manual or automatic gateway firmware updates."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:update"

    def __init__(self, device: Tydom) -> None:
        """Initialise the update mode select."""
        super().__init__(device, "gateway_update_mode", "gateway_update_mode")
        self._options = {mode.lower(): mode for mode in GATEWAY_UPDATE_MODES}
        self._attr_options = list(self._options)

    @property
    def available(self) -> bool:
        """Available once the gateway has reported its update mode."""
        return self._device.update_mode is not None

    @property
    def current_option(self) -> str | None:
        """Return the current mode."""
        mode = self._device.update_mode
        return mode.lower() if mode else None

    async def async_select_option(self, option: str) -> None:
        """Apply the selected mode."""
        await self._device.async_set_update_mode(self._options[option])


# ----------------------------------------------------------------------
# Radio product firmware
# ----------------------------------------------------------------------


class RadioFirmwareUpdateAvailableSensor(GatewayEntity, BinarySensorEntity):
    """Report whether a radio product firmware update is available."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.UPDATE

    def __init__(self, device: Tydom) -> None:
        """Initialise the radio firmware availability sensor."""
        super().__init__(
            device,
            "radio_firmware_update_available",
            "radio_firmware_update_available",
        )

    @property
    def available(self) -> bool:
        """Available once the gateway has reported the radio firmware status."""
        return "updateAvailable" in self._device.devices_update_status

    @property
    def is_on(self) -> bool | None:
        """Return whether an update is available for at least one product."""
        value = self._device.devices_update_status.get("updateAvailable")
        return None if value is None else bool(value)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the deployment mode and the firmware slots left."""
        status = self._device.devices_update_status
        setup = status.get("setup")
        return {
            "mode": setup.get("mode") if isinstance(setup, dict) else None,
            "free_firmware_slots": status.get("nbFwFreeSlots"),
            "firmware_count": len(self._device.device_firmwares),
        }


class RadioFirmwareUpdate(GatewayEntity, UpdateEntity):
    """Firmware of one radio product model, deployed by the gateway."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = UpdateEntityFeature.INSTALL

    def __init__(self, device: Tydom, fw_id: str) -> None:
        """Initialise the update entity of firmware ``fw_id``."""
        self._fw_id = fw_id
        firmware = device.device_firmwares.get(fw_id, {})
        model = str(firmware.get("modelId") or fw_id)
        self._attr_title = model
        super().__init__(
            device,
            "radio_firmware",
            f"radio_firmware_{fw_id}",
            placeholders={"model": model},
        )

    @property
    def _firmware(self) -> dict[str, Any] | None:
        return self._device.device_firmwares.get(self._fw_id)

    @property
    def available(self) -> bool:
        """Available while the gateway still lists this firmware."""
        return self._firmware is not None

    @property
    def installed_version(self) -> str | None:
        """Return the version currently running on the products."""
        firmware = self._firmware or {}
        version = firmware.get("running")
        return str(version) if version not in (None, "") else None

    @property
    def latest_version(self) -> str | None:
        """Return the version the gateway offers (installed one when up to date)."""
        firmware = self._firmware or {}
        version = firmware.get("wish")
        if version in (None, ""):
            return self.installed_version
        return str(version)

    @property
    def in_progress(self) -> bool:
        """Return whether the gateway is downloading this firmware."""
        firmware = self._firmware or {}
        return firmware.get("status") in _FIRMWARE_BUSY_STATES

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the raw gateway status of this firmware."""
        firmware = self._firmware or {}
        return {
            "firmware_id": self._fw_id,
            "model_id": firmware.get("modelId"),
            "status": firmware.get("status"),
        }

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Ask the gateway to deploy this firmware."""
        await self._device.async_install_device_firmware(self._fw_id)


def gateway_firmware_ids(device: Tydom) -> list[str]:
    """Return the radio firmware currently listed by the gateway."""
    return list(device.device_firmwares)
