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

    # In a real implementation, this library would call it's call backs when it was
    # notified of any state changeds for the relevant device.
    async def publish_updates(self) -> None:
        """Schedule call all registered callbacks."""
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
        self._callbacks.add(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        """Remove previously registered callback."""
        self._callbacks.discard(callback)

    @property
    def device_id(self) -> str:
        """Return ID for device."""
        return self.uid

    # In a real implementation, this library would call it's call backs when it was
    # notified of any state changeds for the relevant device.
    async def publish_updates(self) -> None:
        """Schedule call all registered callbacks."""
        for callback in self._callbacks:
            callback()

class TydomShutter(TydomDevice):
    """Represents a shutter"""
    def __init__(self, uid, name, device_type, endpoint, data):
        self.thermic_defect = None
        self.position = None
        self.on_fav_pos = None
        self.up_defect = None
        self.down_defect = None
        self.obstacle_defect = None
        self.intrusion = None
        self.batt_defect = None

        if data is not None:
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

    async def update_device(self, device):
        """Update the device values from another device"""
        logger.debug("Update device %s", device.uid)
        self.thermic_defect = device.thermic_defect
        self.position = device.position
        self.on_fav_pos = device.on_fav_pos
        self.up_defect = device.up_defect
        self.down_defect = device.down_defect
        self.obstacle_defect = device.obstacle_defect
        self.intrusion = device.intrusion
        self.batt_defect = device.batt_defect
        await self.publish_updates()

class TydomEnergy(TydomDevice):
    """Represents an energy sensor (for example TYWATT)"""

    def __init__(self, uid, name, device_type, endpoint, data):
        logger.info("TydomEnergy : data %s", data)
        self.energyInstantTotElec = None
        self.energyInstantTotElec_Min = None
        self.energyInstantTotElec_Max = None
        self.energyScaleTotElec_Min = None
        self.energyScaleTotElec_Max = None
        self.energyInstantTotElecP = None
        self.energyInstantTotElec_P_Min = None
        self.energyInstantTotElec_P_Max = None
        self.energyScaleTotElec_P_Min = None
        self.energyScaleTotElec_P_Max = None
        self.energyInstantTi1P = None
        self.energyInstantTi1P_Min = None
        self.energyInstantTi1P_Max = None
        self.energyScaleTi1P_Min = None
        self.energyScaleTi1P_Max = None
        self.energyInstantTi1I = None
        self.energyInstantTi1I_Min = None
        self.energyInstantTi1I_Max = None
        self.energyScaleTi1I_Min = None
        self.energyScaleTi1I_Max = None
        self.energyTotIndexWatt = None
        self.energyIndexHeatWatt = None
        self.energyIndexECSWatt = None
        self.energyIndexHeatGas = None
        self.outTemperature = None

        if data is not None:
            if "energyInstantTotElec" in data:
                self.energyInstantTotElec = data["energyInstantTotElec"]
            if "energyInstantTotElec_Min" in data:
                self.energyInstantTotElec_Min = data["energyInstantTotElec_Min"]
            if "energyInstantTotElec_Max" in data:
                self.energyInstantTotElec_Max = data["energyInstantTotElec_Max"]
            if "energyScaleTotElec_Min" in data:
                self.energyScaleTotElec_Min = data["energyScaleTotElec_Min"]
            if "energyScaleTotElec_Max" in data:
                self.energyScaleTotElec_Max = data["energyScaleTotElec_Max"]
            if "energyInstantTotElecP" in data:
                self.energyInstantTotElecP = data["energyInstantTotElecP"]
            if "energyInstantTotElec_P_Min" in data:
                self.energyInstantTotElec_P_Min = data["energyInstantTotElec_P_Min"]
            if "energyInstantTotElec_P_Max" in data:
                self.energyInstantTotElec_P_Max = data["energyInstantTotElec_P_Max"]
            if "energyScaleTotElec_P_Min" in data:
                self.energyScaleTotElec_P_Min = data["energyScaleTotElec_P_Min"]
            if "energyScaleTotElec_P_Max" in data:
                self.energyScaleTotElec_P_Max = data["energyScaleTotElec_P_Max"]
            if "energyInstantTi1P" in data:
                self.energyInstantTi1P = data["energyInstantTi1P"]
            if "energyInstantTi1P_Min" in data:
                self.energyInstantTi1P_Min = data["energyInstantTi1P_Min"]
            if "energyInstantTi1P_Max" in data:
                self.energyInstantTi1P_Max = data["energyInstantTi1P_Max"]
            if "energyScaleTi1P_Min" in data:
                self.energyScaleTi1P_Min = data["energyScaleTi1P_Min"]
            if "energyScaleTi1P_Max" in data:
                self.energyScaleTi1P_Max = data["energyScaleTi1P_Max"]
            if "energyInstantTi1I" in data:
                self.energyInstantTi1I = data["energyInstantTi1I"]
            if "energyInstantTi1I_Min" in data:
                self.energyInstantTi1I_Min = data["energyInstantTi1I_Min"]
            if "energyInstantTi1I_Max" in data:
                self.energyInstantTi1I_Max = data["energyInstantTi1I_Max"]
            if "energyScaleTi1I_Min" in data:
                self.energyScaleTi1I_Min = data["energyScaleTi1I_Min"]
            if "energyScaleTi1I_Max" in data:
                self.energyScaleTi1I_Max = data["energyScaleTi1I_Max"]
            if "energyTotIndexWatt" in data:
                self.energyTotIndexWatt = data["energyTotIndexWatt"]
            if "energyIndexHeatWatt" in data:
                self.energyIndexHeatWatt = data["energyIndexHeatWatt"]
            if "energyIndexECSWatt" in data:
                self.energyIndexECSWatt = data["energyIndexECSWatt"]
            if "energyIndexHeatGas" in data:
                self.energyIndexHeatGas = data["energyIndexHeatGas"]
            if "outTemperature" in data:
                self.outTemperature = data["outTemperature"]
        super().__init__(uid, name, device_type, endpoint)


    async def update_device(self, device):
        """Update the device values from another device"""
        logger.debug("Update device %s", device.uid)
        if device.energyInstantTotElec is not None:
            self.energyInstantTotElec = device.energyInstantTotElec
        if device.energyInstantTotElec_Min is not None:
            self.energyInstantTotElec_Min = device.energyInstantTotElec_Min
        if device.energyInstantTotElec_Max is not None:
            self.energyInstantTotElec_Max = device.energyInstantTotElec_Max
        if device.energyScaleTotElec_Min is not None:
            self.energyScaleTotElec_Min = device.energyScaleTotElec_Min
        if device.energyScaleTotElec_Max is not None:
            self.energyScaleTotElec_Max = device.energyScaleTotElec_Max
        if device.energyInstantTotElecP is not None:
            self.energyInstantTotElecP = device.energyInstantTotElecP
        if device.energyInstantTotElec_P_Min is not None:
            self.energyInstantTotElec_P_Min = device.energyInstantTotElec_P_Min
        if device.energyInstantTotElec_P_Max is not None:
            self.energyInstantTotElec_P_Max = device.energyInstantTotElec_P_Max
        if device.energyScaleTotElec_P_Min is not None:
            self.energyScaleTotElec_P_Min = device.energyScaleTotElec_P_Min
        if device.energyScaleTotElec_P_Max is not None:
            self.energyScaleTotElec_P_Max = device.energyScaleTotElec_P_Max
        if device.energyInstantTi1P is not None:
            self.energyInstantTi1P = device.energyInstantTi1P
        if device.energyInstantTi1P_Min is not None:
            self.energyInstantTi1P_Min = device.energyInstantTi1P_Min
        if device.energyInstantTi1P_Max is not None:
            self.energyInstantTi1P_Max = device.energyInstantTi1P_Max
        if device.energyScaleTi1P_Min is not None:
            self.energyScaleTi1P_Min = device.energyScaleTi1P_Min
        if device.energyScaleTi1P_Max is not None:
            self.energyScaleTi1P_Max = device.energyScaleTi1P_Max
        if device.energyInstantTi1I is not None:
            self.energyInstantTi1I = device.energyInstantTi1I
        if device.energyInstantTi1I_Min is not None:
            self.energyInstantTi1I_Min = device.energyInstantTi1I_Min
        if device.energyInstantTi1I_Max is not None:
            self.energyInstantTi1I_Max = device.energyInstantTi1I_Max
        if device.energyScaleTi1I_Min is not None:
            self.energyScaleTi1I_Min = device.energyScaleTi1I_Min
        if device.energyScaleTi1I_Max is not None:
            self.energyScaleTi1I_Max = device.energyScaleTi1I_Max
        if device.energyTotIndexWatt is not None:
            self.energyTotIndexWatt = device.energyTotIndexWatt
        if device.energyIndexHeatWatt is not None:
            self.energyIndexHeatWatt = device.energyIndexHeatWatt
        if device.energyIndexECSWatt is not None:
            self.energyIndexECSWatt = device.energyIndexECSWatt
        if device.energyIndexHeatGas is not None:
            self.energyIndexHeatGas = device.energyIndexHeatGas
        if device.outTemperature is not None:
            self.outTemperature = device.outTemperature
        await self.publish_updates()