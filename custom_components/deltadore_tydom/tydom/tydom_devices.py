"""Support for Tydom classes."""
from collections.abc import Callable
from ..const import LOGGER

class TydomDevice:
    """represents a generic device."""

    _ha_device = None

    def __init__(self, tydom_client, uid, device_id, name, device_type, endpoint, metadata, data):
        """Initialize a TydomDevice."""
        self._tydom_client = tydom_client
        self._uid = uid
        self._id = device_id
        self._name = name
        self._type = device_type
        self._endpoint = endpoint
        self._metadata = metadata
        self._callbacks = set()
        if data is not None:
            for key in data:
                if isinstance(data[key], dict):
                    LOGGER.debug("type of %s : %s", key, type(data[key]))
                    LOGGER.debug("%s => %s", key, data[key])
                elif isinstance(data[key], list):
                    LOGGER.debug("type of %s : %s", key, type(data[key]))
                    LOGGER.debug("%s => %s", key, data[key])
                else:
                    setattr(self, key, data[key])

    def register_callback(self, callback: Callable[[], None]) -> None:
        """Register callback, called when state changes."""
        self._callbacks.add(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        """Remove previously registered callback."""
        self._callbacks.discard(callback)

    @property
    def device_id(self) -> str:
        """Return ID for device."""
        return self._uid

    @property
    def device_name(self) -> str:
        """Return name for device."""
        return self._name

    @property
    def device_type(self) -> str:
        """Return type for device."""
        return self._type

    @property
    def device_endpoint(self) -> str:
        """Return endpoint for device."""
        return self._endpoint

    async def update_device(self, device):
        """Update the device values from another device."""
        LOGGER.debug("Update device %s", device.device_id)
        for attribute, value in device.__dict__.items():
            if (attribute == "_uid" or attribute[:1] != "_") and value is not None:
                setattr(self, attribute, value)
        await self.publish_updates()
        if hasattr(self,"_ha_device") and self._ha_device is not None:
            try:
                self._ha_device.async_write_ha_state()
            except Exception:
                LOGGER.exception("update failed")

    async def publish_updates(self) -> None:
        """Schedule call all registered callbacks."""
        for callback in self._callbacks:
            callback()


class Tydom(TydomDevice):
    """Tydom Gateway."""

    async def async_trigger_firmware_update(self) -> None:
        """Trigger firmware update."""
        LOGGER.debug("Installing firmware update...")
        await self._tydom_client.update_firmware()

class TydomShutter(TydomDevice):
    """Represents a shutter."""

    async def down(self) -> None:
        """Tell cover to go down."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "positionCmd", "DOWN"
        )

    async def up(self) -> None:
        """Tell cover to go up."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "positionCmd", "UP"
        )

    async def stop(self) -> None:
        """Tell cover to stop moving."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "positionCmd", "STOP"
        )

    async def set_position(self, position: int) -> None:
        """Set cover to the given position."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "position", str(position)
        )

    # FIXME replace command
    async def slope_open(self) -> None:
        """Tell the cover to tilt open."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "positionCmd", "DOWN"
        )

    # FIXME replace command
    async def slope_close(self) -> None:
        """Tell the cover to tilt closed."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "positionCmd", "UP"
        )

    # FIXME replace command
    async def slope_stop(self) -> None:
        """Tell the cover to stop tilt."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "positionCmd", "STOP"
        )

    # FIXME replace command
    async def set_slope_position(self, position: int) -> None:
        """Set cover to the given position."""
        LOGGER.debug("set roller tilt position (device) to : %s", position)

        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "position", str(position)
        )


class TydomEnergy(TydomDevice):
    """Represents an energy sensor (for example TYWATT)."""


class TydomSmoke(TydomDevice):
    """Represents an smoke detector sensor."""


class TydomBoiler(TydomDevice):
    """Represents a Boiler."""

    async def set_hvac_mode(self, mode):
        """Set hvac mode (ANTI_FROST/NORMAL/STOP)."""
        LOGGER.debug("setting hvac mode to %s", mode)
        if mode == "ANTI_FROST":
            #await self._tydom_client.put_devices_data(
            #    self._id, self._endpoint, "thermicLevel", None
            #)
            #await self._tydom_client.put_devices_data(
            #    self._id, self._endpoint, "authorization", mode
            #)
            #await self._tydom_client.put_devices_data(
            #    self._id, self._endpoint, "antifrostOn", False
            #)
            #await self.set_temperature("19.0")
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "setpoint", None
            )
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "thermicLevel", "STOP"
            )
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "hvacMode", "ANTI_FROST"
            )
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "antifrostOn", True
            )
            await self._tydom_client.put_data(
                "/home/absence", "to", -1
            )
            await self._tydom_client.put_data(
                "/events/home/absence", "to", -1
            )
            await self._tydom_client.put_data(
                "/events/home/absence", "actions", "in"
            )
        elif mode == "NORMAL":
            if self.hvacMode == "ANTI_FROST":
                await self._tydom_client.put_data(
                    "/home/absence", "to", 0
                )
                await self._tydom_client.put_data(
                    "/events/home/absence", "to", 0
                )
                await self._tydom_client.put_data(
                    "/events/home/absence", "actions", "in"
                )
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "hvacMode", "NORMAL"
            )
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "authorization", "HEATING"
            )
            await self.set_temperature("19.0")
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "antifrostOn", False
            )
        elif mode == "STOP":
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "hvacMode", "STOP"
            )
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "authorization", "STOP"
            )
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "thermicLevel", "STOP"
            )
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "setpoint", None
            )
        else:
            LOGGER.error("Unknown hvac mode: %s", mode)

    async def set_temperature(self, temperature):
        """Set target temperature."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "setpoint", temperature
        )

class TydomWindow(TydomDevice):
    """represents a window."""

class TydomDoor(TydomDevice):
    """represents a door."""

class TydomGate(TydomDevice):
    """represents a gate."""

class TydomGarage(TydomDevice):
    """represents a garage door."""

class TydomLight(TydomDevice):
    """represents a light."""

    async def turn_on(self, brightness) -> None:
        """Tell light to turn on."""
        if brightness is None:
            command = "TOGGLE"
            if "ON" in self._metadata["levelCmd"]["enum_values"]:
                command = "ON"

            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "levelCmd", command
            )
        else:
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "level", str(brightness)
            )

    async def turn_off(self) -> None:
        """Tell light to turn off."""

        command = "TOGGLE"
        if "OFF" in self._metadata["levelCmd"]["enum_values"]:
            command = "OFF"

        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "levelCmd", command
        )

class TydomAlarm(TydomDevice):
    """represents an alarm."""
