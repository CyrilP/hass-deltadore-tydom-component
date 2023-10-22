"""Support for Tydom classes"""
from typing import Callable
import logging
from ..const import LOGGER

logger = logging.getLogger(__name__)

class TydomDevice:
    """represents a generic device"""

    def __init__(self, tydom_client, uid, device_id, name, device_type, endpoint, data):
        self._tydom_client = tydom_client
        self._uid = uid
        self._id = device_id
        self._name = name
        self._type = device_type
        self._endpoint = endpoint
        self._callbacks = set()
        if data is not None:
            for key in data:
                
                if isinstance(data[key], dict):
                    logger.warning("type of %s : %s", key, type(data[key]))
                    logger.warning("%s => %s", key, data[key])
                elif isinstance(data[key], list):
                    logger.warning("type of %s : %s", key, type(data[key]))
                    logger.warning("%s => %s", key, data[key])
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
        """Return name for device"""
        return self._name

    @property
    def device_type(self) -> str:
        """Return type for device"""
        return self._type

    @property
    def device_endpoint(self) -> str:
        """Return endpoint for device"""
        return self._endpoint

    async def update_device(self, device):
        """Update the device values from another device"""
        logger.debug("Update device %s", device.device_id)
        for attribute, value in device.__dict__.items():
#            if device._type == "boiler":
#                LOGGER.debug("updating device attr %s=>%s", attribute, value)
            if (attribute == "_uid" or attribute[:1] != "_") and value is not None:
                setattr(self, attribute, value)
        await self.publish_updates()

    # In a real implementation, this library would call it's call backs when it was
    # notified of any state changeds for the relevant device.
    async def publish_updates(self) -> None:
        """Schedule call all registered callbacks."""
        for callback in self._callbacks:
#            LOGGER.debug("calling callback%s", callback)
            callback()


class Tydom(TydomDevice):
    """Tydom Gateway"""

class TydomShutter(TydomDevice):
    """Represents a shutter"""

    async def down(self) -> None:
        """Tell cover to go down"""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "positionCmd", "DOWN"
        )

    async def up(self) -> None:
        """Tell cover to go up"""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "positionCmd", "UP"
        )

    async def stop(self) -> None:
        """Tell cover to stop moving"""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "positionCmd", "STOP"
        )

    async def set_position(self, position: int) -> None:
        """
        Set cover to the given position.
        """
        logger.error("set roller position (device) to : %s", position)

        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "position", str(position)
        )

    # FIXME replace command
    async def slope_open(self) -> None:
        """Tell the cover to tilt open"""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "positionCmd", "DOWN"
        )

    # FIXME replace command
    async def slope_close(self) -> None:
        """Tell the cover to tilt closed"""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "positionCmd", "UP"
        )

    # FIXME replace command
    async def slope_stop(self) -> None:
        """Tell the cover to stop tilt"""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "positionCmd", "STOP"
        )

    # FIXME replace command
    async def set_slope_position(self, position: int) -> None:
        """
        Set cover to the given position.
        """
        logger.error("set roller tilt position (device) to : %s", position)

        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "position", str(position)
        )


class TydomEnergy(TydomDevice):
    """Represents an energy sensor (for example TYWATT)"""


class TydomSmoke(TydomDevice):
    """Represents an smoke detector sensor"""


class TydomBoiler(TydomDevice):
    """represents a boiler"""
    async def set_hvac_mode(self, mode):
        """Set hvac mode (STOP/HEATING)"""
        logger.error("setting mode to %s", mode)
        LOGGER.debug("setting mode to %s", mode)
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "authorization", mode
        )

    async def set_preset_mode(self, mode):
        """Set preset mode (NORMAL/STOP/ANTI_FROST)"""
        logger.error("setting preset to %s", mode)
        LOGGER.debug("setting preset to %s", mode)
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "hvacMode", mode
        )
    async def set_temperature(self, temperature):
        """Set target temperature"""
        logger.error("setting target temperature to %s", temperature)
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "setpoint", temperature
        )


class TydomWindow(TydomDevice):
    """represents a window"""


class TydomDoor(TydomDevice):
    """represents a door"""


class TydomGate(TydomDevice):
    """represents a gate"""


class TydomGarage(TydomDevice):
    """represents a garage door"""

    def __init__(self, tydom_client, uid, device_id, name, device_type, endpoint, data):
        logger.info("TydomGarage : data %s", data)
        super().__init__(
            tydom_client, uid, device_id, name, device_type, endpoint, data
        )


class TydomLight(TydomDevice):
    """represents a light"""


class TydomAlarm(TydomDevice):
    """represents an alarm"""
