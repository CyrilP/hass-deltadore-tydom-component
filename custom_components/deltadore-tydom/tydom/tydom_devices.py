"""Support for Tydom classes"""
from typing import Callable
import logging

logger = logging.getLogger(__name__)


class Tydom:
    """Tydom"""

    def __init__(
        self,
        product_name,
        main_version_sw,
        main_version_hw,
        main_id,
        main_reference,
        key_version_sw,
        key_version_hw,
        key_version_stack,
        key_reference,
        boot_reference,
        boot_version,
        update_available,
    ):
        self.product_name = product_name
        self.main_version_sw = main_version_sw
        self.main_version_hw = main_version_hw
        self.main_id = main_id
        self.main_reference = main_reference
        self.key_version_sw = key_version_sw
        self.key_version_hw = key_version_hw
        self.key_version_stack = key_version_stack
        self.key_reference = key_reference
        self.boot_reference = boot_reference
        self.boot_version = boot_version
        self.update_available = update_available
        self._callbacks = set()

    def register_callback(self, callback: Callable[[], None]) -> None:
        """Register callback, called when Roller changes state."""
        self._callbacks.add(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        """Remove previously registered callback."""
        self._callbacks.discard(callback)

    async def update_device(self, updated_entity):
        """Update the device values from another device"""
        logger.error("update Tydom ")
        self.product_name = updated_entity.product_name
        self.main_version_sw = updated_entity.main_version_sw
        self.main_version_hw = updated_entity.main_version_hw
        self.main_id = updated_entity.main_id
        self.main_reference = updated_entity.main_reference
        self.key_version_sw = updated_entity.key_version_sw
        self.key_version_hw = updated_entity.key_version_hw
        self.key_version_stack = updated_entity.key_version_stack
        self.key_reference = updated_entity.key_reference
        self.boot_reference = updated_entity.boot_reference
        self.boot_version = updated_entity.boot_version
        self.update_available = updated_entity.update_available
        await self.publish_updates()

    # In a real implementation, this library would call it's call backs when it was
    # notified of any state changeds for the relevant device.
    async def publish_updates(self) -> None:
        """Schedule call all registered callbacks."""
        for callback in self._callbacks:
            callback()


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
        for key in data:
            setattr(self, key, data[key])

    def register_callback(self, callback: Callable[[], None]) -> None:
        """Register callback, called when Roller changes state."""
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
            if attribute[:1] != "_" and value is not None:
                setattr(self, attribute, value)
        await self.publish_updates()

    # In a real implementation, this library would call it's call backs when it was
    # notified of any state changeds for the relevant device.
    async def publish_updates(self) -> None:
        """Schedule call all registered callbacks."""
        for callback in self._callbacks:
            callback()


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
    def set_hvac_mode(self, mode):
        """Set hvac mode (STOP/HEATING)"""
        logger.info("setting mode to %s", mode)
        # authorization

    def set_preset_mode(self, mode):
        """Set preset mode (NORMAL/STOP/ANTI_FROST)"""
        logger.info("setting preset to %s", mode)
        # hvacMode



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
