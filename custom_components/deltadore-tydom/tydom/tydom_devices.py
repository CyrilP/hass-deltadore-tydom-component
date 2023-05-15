"""Support for Tydom classes"""
from typing import Callable
import logging

logger = logging.getLogger(__name__)

class TydomBaseEntity:
    """Tydom entity base class."""
    def __init__(self, product_name, main_version_sw, main_version_hw, main_id, main_reference,
                 key_version_sw, key_version_hw, key_version_stack, key_reference, boot_reference, boot_version, update_available):
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


class TydomDevice():
    """represents a generic device"""

    def __init__(self, uid, name, device_type, endpoint, data):
        self._uid = uid
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
            if attribute[:1] != '_' and value is not None:
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
    def __init__(self, uid, name, device_type, endpoint, data):

        super().__init__(uid, name, device_type, endpoint, data)

class TydomEnergy(TydomDevice):
    """Represents an energy sensor (for example TYWATT)"""

    def __init__(self, uid, name, device_type, endpoint, data):
        logger.info("TydomEnergy : data %s", data)

        super().__init__(uid, name, device_type, endpoint, data)


class TydomSmoke(TydomDevice):
    """Represents an smoke detector sensor"""

    def __init__(self, uid, name, device_type, endpoint, data):
        logger.info("TydomSmoke : data %s", data)
        super().__init__(uid, name, device_type, endpoint, data)

class TydomBoiler(TydomDevice):
    """represents a boiler"""

    def __init__(self, uid, name, device_type, endpoint, data):
        logger.info("TydomBoiler : data %s", data)
        # {'authorization': 'HEATING', 'setpoint': 19.0, 'thermicLevel': None, 'hvacMode': 'NORMAL', 'timeDelay': 0, 'temperature': 21.35, 'tempoOn': False, 'antifrostOn': False, 'loadSheddingOn': False,  'openingDetected': False, 'presenceDetected': False, 'absence': False, 'productionDefect': False, 'batteryCmdDefect': False, 'tempSensorDefect': False, 'tempSensorShortCut': False, 'tempSensorOpenCirc': False, 'boostOn': False, 'anticipCoeff': 30}

        super().__init__(uid, name, device_type, endpoint, data)