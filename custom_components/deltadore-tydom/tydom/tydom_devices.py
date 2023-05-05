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
        logger.error("register_callback %s", callback)
        self._callbacks.add(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        """Remove previously registered callback."""
        logger.error("remove_callback")
        self._callbacks.discard(callback)

    # In a real implementation, this library would call it's call backs when it was
    # notified of any state changeds for the relevant device.
    async def publish_updates(self) -> None:
        """Schedule call all registered callbacks."""
        logger.error("publish_updates")
        for callback in self._callbacks:
            callback()


class TydomDevice():
    """represents a generic device"""

    def __init__(self, uid, name, device_type, endpoint):
        self.uid = uid
        self.name = name
        self.type = device_type
        self.endpoint = endpoint
        self._callbacks = set()

    def register_callback(self, callback: Callable[[], None]) -> None:
        """Register callback, called when Roller changes state."""
        logger.error("register_callback %s", callback)
        self._callbacks.add(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        """Remove previously registered callback."""
        logger.error("remove_callback")
        self._callbacks.discard(callback)

    @property
    def device_id(self) -> str:
        """Return ID for device."""
        return self.uid

    # In a real implementation, this library would call it's call backs when it was
    # notified of any state changeds for the relevant device.
    async def publish_updates(self) -> None:
        """Schedule call all registered callbacks."""
        logger.error("publish_updates")
        for callback in self._callbacks:
            callback()

class TydomShutter(TydomDevice):
    """Represents a shutter"""
    def __init__(self, uid, name, device_type, endpoint, data):
        logger.info("TydomShutter : data %s", data)
        self.thermic_defect = None
        logger.info("TydomShutter : pos")
        self.position = None
        logger.info("TydomShutter : on_fav_pos")
        self.on_fav_pos = None
        self.up_defect = None
        self.down_defect = None
        self.obstacle_defect = None
        self.intrusion = None
        self.batt_defect = None

        if data is not None:
            logger.info("TydomShutter : data not none %s", data)
            if "thermicDefect" in data:
                self.thermic_defect = data["thermicDefect"]
            if "position" in data:
                logger.error("positio : %s", data["position"])
                self.position = data["position"]
            if "onFavPos" in data:
                self.on_fav_pos = data["onFavPos"]
            if "upDefect" in data:
                self.up_defect = data["upDefect"]
            if "downDefect" in data:
                self.down_defect = data["downDefect"]
            if "obstacleDefect" in data:
                self.obstacle_defect = data["obstacleDefect"]
            if "intrusion" in data:
                self.intrusion = data["intrusion"]
            if "battDefect" in data:
                self.batt_defect = data["battDefect"]
        super().__init__(uid, name, device_type, endpoint)

