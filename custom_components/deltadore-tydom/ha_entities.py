"""Home assistant entites"""
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.entity import Entity, DeviceInfo, Entity
from homeassistant.components.cover import (
    ATTR_POSITION,
    SUPPORT_CLOSE,
    SUPPORT_OPEN,
    SUPPORT_SET_POSITION,
    SUPPORT_STOP,
    CoverEntity,
    CoverDeviceClass
)
from homeassistant.components.sensor import SensorDeviceClass


from .tydom.tydom_devices import TydomShutter, TydomEnergy

from .const import DOMAIN, LOGGER


class HAEnergy(Entity):
    """Representation of an energy sensor"""

    should_poll = False
    device_class = None
    supported_features = None

    def __init__(self, energy: TydomEnergy) -> None:
        self._energy = energy
        self._attr_unique_id = f"{self._energy.uid}_energy"
        self._attr_name = self._energy.name

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        self._energy.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._energy.remove_callback(self.async_write_ha_state)

    # To link this entity to the cover device, this property must return an
    # identifiers value matching that used in the cover, but no other information such
    # as name. If name is returned, this entity will then also become a device in the
    # HA UI.
    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._energy.uid)}, "name": self._energy.name}

    def get_sensors(self):
        """Get available sensors for this entity"""
        sensors = []
        if self._energy.energyInstantTotElec is not None:
            sensors.append(EnergyInstantTotElecSensor(self._energy))
        if self._energy.energyInstantTotElec_Min is not None:
            sensors.append(EnergyInstantTotElec_MinSensor(self._energy))
        if self._energy.energyInstantTotElec_Max is not None:
            sensors.append(EnergyInstantTotElec_MaxSensor(self._energy))
        if self._energy.energyScaleTotElec_Min is not None:
            sensors.append(EnergyScaleTotElec_MinSensor(self._energy))
        if self._energy.energyScaleTotElec_Max is not None:
            sensors.append(EnergyScaleTotElec_MaxSensor(self._energy))
        if self._energy.energyInstantTotElecP is not None:
            sensors.append(EnergyInstantTotElecPSensor(self._energy))
        if self._energy.energyInstantTotElec_P_Min is not None:
            sensors.append(EnergyInstantTotElec_P_MinSensor(self._energy))
        if self._energy.energyInstantTotElec_P_Max is not None:
            sensors.append(EnergyInstantTotElec_P_MaxSensor(self._energy))
        if self._energy.energyScaleTotElec_P_Min is not None:
            sensors.append(EnergyScaleTotElec_P_MinSensor(self._energy))
        if self._energy.energyScaleTotElec_P_Max is not None:
            sensors.append(EnergyScaleTotElec_P_MaxSensor(self._energy))
        if self._energy.energyInstantTi1P is not None:
            sensors.append(EnergyInstantTi1PSensor(self._energy))
        if self._energy.energyInstantTi1P_Min is not None:
           sensors.append(EnergyInstantTi1P_MinSensor(self._energy))
        if self._energy.energyInstantTi1P_Max is not None:
            sensors.append(EnergyInstantTi1P_MaxSensor(self._energy))
        if self._energy.energyScaleTi1P_Min is not None:
            sensors.append(EnergyScaleTi1P_MinSensor(self._energy))
        if self._energy.energyScaleTi1P_Max is not None:
            sensors.append(EnergyScaleTi1P_MaxSensor(self._energy))
        if self._energy.energyInstantTi1I is not None:
            sensors.append(EnergyInstantTi1ISensor(self._energy))
        if self._energy.energyInstantTi1I_Min is not None:
            sensors.append(EnergyInstantTi1I_MinSensor(self._energy))
        if self._energy.energyInstantTi1I_Max is not None:
            sensors.append(EnergyInstantTi1I_MaxSensor(self._energy))
        if self._energy.energyTotIndexWatt is not None:
            sensors.append(EnergyTotIndexWattSensor(self._energy))
        if self._energy.energyIndexHeatWatt is not None:
            sensors.append(EnergyIndexHeatWattSensor(self._energy))
        if self._energy.energyIndexECSWatt is not None:
            sensors.append(EnergyIndexECSWattSensor(self._energy))
        if self._energy.energyIndexHeatGas is not None:
            sensors.append(EnergyIndexHeatGasSensor(self._energy))
        if self._energy.outTemperature is not None:
            sensors.append(OutTemperatureSensor(self._energy))
        return sensors

class EnergySensorBase(Entity):
    """Base representation of a Sensor."""

    should_poll = False

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        self._device = device

    # To link this entity to the cover device, this property must return an
    # identifiers value matching that used in the cover, but no other information such
    # as name. If name is returned, this entity will then also become a device in the
    # HA UI.
    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._device.uid)}}

    # This property is important to let HA know if this entity is online or not.
    # If an entity is offline (return False), the UI will refelect this.
    @property
    def available(self) -> bool:
        """Return True if roller and hub is available."""
        # FIXME
        #return self._device.online and self._device.hub.online
        return True

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        # Sensors should also register callbacks to HA when their state changes
        self._device.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self):
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._device.remove_callback(self.async_write_ha_state)

class EnergyInstantTotElecSensor(EnergySensorBase):
    """energyInstantTotElec sensor"""

    device_class = SensorDeviceClass.CURRENT
    #_attr_unit_of_measurement = "lx"

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        # As per the sensor, this must be a unique value within this domain. This is done
        # by using the device ID, and appending "_battery"
        self._attr_unique_id = f"{self._device.uid}_energyInstantTotElec"

        # The name of the entity
        self._attr_name = f"{self._device.name} energyInstantTotElec"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyInstantTotElec

class EnergyInstantTotElec_MinSensor(EnergySensorBase):
    """energyInstantTotElec_Min sensor"""

    device_class = SensorDeviceClass.CURRENT
    #_attr_unit_of_measurement = "lx"

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        # As per the sensor, this must be a unique value within this domain. This is done
        # by using the device ID, and appending "_battery"
        self._attr_unique_id = f"{self._device.uid}_energyInstantTotElec_Min"

        # The name of the entity
        self._attr_name = f"{self._device.name} energyInstantTotElec_Min"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyInstantTotElec_Min

class EnergyInstantTotElec_MaxSensor(EnergySensorBase):
    """energyInstantTotElec_Max sensor"""

    device_class = SensorDeviceClass.CURRENT
    #_attr_unit_of_measurement = "lx"

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        # As per the sensor, this must be a unique value within this domain. This is done
        # by using the device ID, and appending "_battery"
        self._attr_unique_id = f"{self._device.uid}_energyInstantTotElec_Max"

        # The name of the entity
        self._attr_name = f"{self._device.name} energyInstantTotElec_Max"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyInstantTotElec_Max


class EnergyScaleTotElec_MinSensor(EnergySensorBase):
    """energyScaleTotElec_Min sensor"""

    device_class = SensorDeviceClass.CURRENT

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyScaleTotElec_Min"
        self._attr_name = f"{self._device.name} energyScaleTotElec_Min"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyScaleTotElec_Min

class EnergyScaleTotElec_MaxSensor(EnergySensorBase):
    """energyScaleTotElec_Min sensor"""

    device_class = SensorDeviceClass.CURRENT

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyScaleTotElec_Max"
        self._attr_name = f"{self._device.name} energyScaleTotElec_Max"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyScaleTotElec_Max

class EnergyInstantTotElecPSensor(EnergySensorBase):
    """energyInstantTotElecP sensor"""

    device_class = SensorDeviceClass.POWER

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyInstantTotElecP"
        self._attr_name = f"{self._device.name} energyInstantTotElecP"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyInstantTotElecP

class EnergyInstantTotElec_P_MinSensor(EnergySensorBase):
    """energyInstantTotElec_P_Min sensor"""

    device_class = SensorDeviceClass.POWER

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyInstantTotElec_P_Min"
        self._attr_name = f"{self._device.name} energyInstantTotElec_P_Min"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyInstantTotElec_P_Min

class EnergyInstantTotElec_P_MaxSensor(EnergySensorBase):
    """energyInstantTotElec_P_Max sensor"""

    device_class = SensorDeviceClass.POWER

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyInstantTotElec_P_Max"
        self._attr_name = f"{self._device.name} energyInstantTotElec_P_Max"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyInstantTotElec_P_Max

class EnergyScaleTotElec_P_MinSensor(EnergySensorBase):
    """energyScaleTotElec_P_Min sensor"""

    device_class = SensorDeviceClass.POWER

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyScaleTotElec_P_Min"
        self._attr_name = f"{self._device.name} energyScaleTotElec_P_Min"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyScaleTotElec_P_Min

class EnergyScaleTotElec_P_MaxSensor(EnergySensorBase):
    """energyScaleTotElec_P_Max sensor"""

    device_class = SensorDeviceClass.POWER

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyScaleTotElec_P_Max"
        self._attr_name = f"{self._device.name} energyScaleTotElec_P_Max"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyScaleTotElec_P_Max

class EnergyInstantTi1PSensor(EnergySensorBase):
    """energyInstantTi1P sensor"""

    device_class = SensorDeviceClass.POWER

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyInstantTi1P"
        self._attr_name = f"{self._device.name} energyInstantTi1P"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyInstantTi1P

class EnergyInstantTi1P_MinSensor(EnergySensorBase):
    """energyInstantTi1P_Min sensor"""

    device_class = SensorDeviceClass.POWER

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyInstantTi1P_Min"
        self._attr_name = f"{self._device.name} energyInstantTi1P_Min"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyInstantTi1P_Min

class EnergyInstantTi1P_MaxSensor(EnergySensorBase):
    """energyInstantTi1P_Max sensor"""

    device_class = SensorDeviceClass.POWER

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyInstantTi1P_Max"
        self._attr_name = f"{self._device.name} energyInstantTi1P_Max"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyInstantTi1P_Max

class EnergyScaleTi1P_MinSensor(EnergySensorBase):
    """energyInstantenergyScaleTi1P_MinTi1P sensor"""

    device_class = SensorDeviceClass.POWER

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyScaleTi1P_Min"
        self._attr_name = f"{self._device.name} energyScaleTi1P_Min"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyScaleTi1P_Min

class EnergyScaleTi1P_MaxSensor(EnergySensorBase):
    """energyScaleTi1P_Max sensor"""

    device_class = SensorDeviceClass.POWER

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyScaleTi1P_Max"
        self._attr_name = f"{self._device.name} energyScaleTi1P_Max"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyScaleTi1P_Max

class EnergyInstantTi1ISensor(EnergySensorBase):
    """energyInstantTi1I sensor"""

    device_class = SensorDeviceClass.CURRENT

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyInstantTi1I"
        self._attr_name = f"{self._device.name} energyInstantTi1I"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyInstantTi1I

class EnergyInstantTi1I_MinSensor(EnergySensorBase):
    """energyInstantTi1I_Min sensor"""

    device_class = SensorDeviceClass.CURRENT

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyInstantTi1I_Min"
        self._attr_name = f"{self._device.name} energyInstantTi1I_Min"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyInstantTi1I_Min

class EnergyInstantTi1I_MaxSensor(EnergySensorBase):
    """energyInstantTi1I_Max sensor"""

    device_class = SensorDeviceClass.CURRENT

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyInstantTi1I_Max"
        self._attr_name = f"{self._device.name} energyInstantTi1I_Max"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyInstantTi1I_Max

class EnergyScaleTi1I_MinSensor(EnergySensorBase):
    """energyScaleTi1I_Min sensor"""

    device_class = SensorDeviceClass.CURRENT

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyScaleTi1I_Min"
        self._attr_name = f"{self._device.name} energyScaleTi1I_Min"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyScaleTi1I_Min

class EnergyScaleTi1I_MaxSensor(EnergySensorBase):
    """energyScaleTi1I_Max sensor"""

    device_class = SensorDeviceClass.CURRENT

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyScaleTi1I_Max"
        self._attr_name = f"{self._device.name} energyScaleTi1I_Max"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyScaleTi1I_Max

class EnergyTotIndexWattSensor(EnergySensorBase):
    """energyTotIndexWatt sensor"""

    device_class = SensorDeviceClass.ENERGY

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyTotIndexWatt"
        self._attr_name = f"{self._device.name} energyTotIndexWatt"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyTotIndexWatt

class EnergyIndexHeatWattSensor(EnergySensorBase):
    """energyIndexHeatWatt sensor"""

    device_class = SensorDeviceClass.ENERGY

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyIndexHeatWatt"
        self._attr_name = f"{self._device.name} energyIndexHeatWatt"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyIndexHeatWatt

class EnergyIndexECSWattSensor(EnergySensorBase):
    """energyIndexECSWatt sensor"""

    device_class = SensorDeviceClass.ENERGY

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyIndexECSWatt"
        self._attr_name = f"{self._device.name} energyIndexECSWatt"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyIndexECSWatt

class EnergyIndexHeatGasSensor(EnergySensorBase):
    """energyIndexHeatGas sensor"""

    device_class = SensorDeviceClass.ENERGY

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_energyIndexHeatGas"
        self._attr_name = f"{self._device.name} energyIndexHeatGas"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.energyIndexHeatGas

class OutTemperatureSensor(EnergySensorBase):
    """outTemperature sensor"""

    device_class = SensorDeviceClass.POWER

    def __init__(self, device: TydomEnergy):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.uid}_outTemperature"
        self._attr_name = f"{self._device.name} outTemperature"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.outTemperature

# This entire class could be written to extend a base class to ensure common attributes
# are kept identical/in sync. It's broken apart here between the Cover and Sensors to
# be explicit about what is returned, and the comments outline where the overlap is.
class HACover(CoverEntity):
    """Representation of a Cover."""

    # Our dummy class is PUSH, so we tell HA that it should not be polled
    should_poll = False
    # The supported features of a cover are done using a bitmask. Using the constants
    # imported above, we can tell HA the features that are supported by this entity.
    # If the supported features were dynamic (ie: different depending on the external
    # device it connected to), then this should be function with an @property decorator.
    supported_features = SUPPORT_SET_POSITION | SUPPORT_OPEN | SUPPORT_CLOSE | SUPPORT_STOP
    device_class= CoverDeviceClass.SHUTTER

    def __init__(self, shutter: TydomShutter) -> None:
        """Initialize the sensor."""
        # Usual setup is done here. Callbacks are added in async_added_to_hass.
        self._shutter = shutter

        # A unique_id for this entity with in this domain. This means for example if you
        # have a sensor on this cover, you must ensure the value returned is unique,
        # which is done here by appending "_cover". For more information, see:
        # https://developers.home-assistant.io/docs/entity_registry_index/#unique-id-requirements
        # Note: This is NOT used to generate the user visible Entity ID used in automations.
        self._attr_unique_id = f"{self._shutter.uid}_cover"

        # This is the name for this *entity*, the "name" attribute from "device_info"
        # is used as the device name for device screens in the UI. This name is used on
        # entity screens, and used to build the Entity ID that's used is automations etc.
        self._attr_name = self._shutter.name

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        self._shutter.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._shutter.remove_callback(self.async_write_ha_state)

    # Information about the devices that is partially visible in the UI.
    # The most critical thing here is to give this entity a name so it is displayed
    # as a "device" in the HA UI. This name is used on the Devices overview table,
    # and the initial screen when the device is added (rather than the entity name
    # property below). You can then associate other Entities (eg: a battery
    # sensor) with this device, so it shows more like a unified element in the UI.
    # For example, an associated battery sensor will be displayed in the right most
    # column in the Configuration > Devices view for a device.
    # To associate an entity with this device, the device_info must also return an
    # identical "identifiers" attribute, but not return a name attribute.
    # See the sensors.py file for the corresponding example setup.
    # Additional meta data can also be returned here, including sw_version (displayed
    # as Firmware), model and manufacturer (displayed as <model> by <manufacturer>)
    # shown on the device info screen. The Manufacturer and model also have their
    # respective columns on the Devices overview table. Note: Many of these must be
    # set when the device is first added, and they are not always automatically
    # refreshed by HA from it's internal cache.
    # For more information see:
    # https://developers.home-assistant.io/docs/device_registry_index/#device-properties
    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._shutter.uid)},
            # If desired, the name for the device could be different to the entity
            "name": self.name,
            #"sw_version": self._shutter.firmware_version,
            #"model": self._shutter.model,
            #"manufacturer": self._shutter.hub.manufacturer,
        }

    # This property is important to let HA know if this entity is online or not.
    # If an entity is offline (return False), the UI will refelect this.
    @property
    def available(self) -> bool:
        """Return True if roller and hub is available."""
        # return self._shutter.online and self._shutter.hub.online
        # FIXME
        return True

    # The following properties are how HA knows the current state of the device.
    # These must return a value from memory, not make a live query to the device/hub
    # etc when called (hence they are properties). For a push based integration,
    # HA is notified of changes via the async_write_ha_state call. See the __init__
    # method for hos this is implemented in this example.
    # The properties that are expected for a cover are based on the supported_features
    # property of the object. In the case of a cover, see the following for more
    # details: https://developers.home-assistant.io/docs/core/entity/cover/
    @property
    def current_cover_position(self):
        """Return the current position of the cover."""
        return self._shutter.position

    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed, same as position 0."""
        return self._shutter.position == 0

    #@property
    #def is_closing(self) -> bool:
    #    """Return if the cover is closing or not."""
    #    return self._shutter.moving < 0

    #@property
    #def is_opening(self) -> bool:
    #    """Return if the cover is opening or not."""
    #    return self._shutter.moving > 0



        #self.on_fav_pos = None
        #self.up_defect = None
        #self.down_defect = None
        #self.obstacle_defect = None
        #self.intrusion = None
        #self.batt_defect = None

    @property
    def is_thermic_defect(self) -> bool:
        """Return the thermic_defect status"""
        return self._shutter.thermic_defect

    # These methods allow HA to tell the actual device what to do. In this case, move
    # the cover to the desired position, or open and close it all the way.
    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self._shutter.set_position(100)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self._shutter.set_position(0)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self._shutter.set_position(kwargs[ATTR_POSITION])


class CoverBinarySensorBase(BinarySensorEntity):
    """Base representation of a Sensor."""

    should_poll = False

    def __init__(self, shutter: TydomShutter):
        """Initialize the sensor."""
        self._shutter = shutter

    # To link this entity to the cover device, this property must return an
    # identifiers value matching that used in the cover, but no other information such
    # as name. If name is returned, this entity will then also become a device in the
    # HA UI.
    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._shutter.uid)}}

    # This property is important to let HA know if this entity is online or not.
    # If an entity is offline (return False), the UI will refelect this.
    @property
    def available(self) -> bool:
        """Return True if roller and hub is available."""
        #return self._roller.online and self._roller.hub.online
        # FIXME
        return True

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        # Sensors should also register callbacks to HA when their state changes
        self._shutter.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self):
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._shutter.remove_callback(self.async_write_ha_state)

class BatteryDefectSensor(CoverBinarySensorBase):
    """Representation of a Battery Defect Sensor."""

    # The class of this device. Note the value should come from the homeassistant.const
    # module. More information on the available devices classes can be seen here:
    # https://developers.home-assistant.io/docs/core/entity/sensor
    device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, shutter):
        """Initialize the sensor."""
        super().__init__(shutter)

        # As per the sensor, this must be a unique value within this domain. This is done
        # by using the device ID, and appending "_battery"
        self._attr_unique_id = f"{self._shutter.uid}_battery"

        # The name of the entity
        self._attr_name = f"{self._shutter.name} Battery defect"

        self._state = False

    # The value of this sensor. As this is a DEVICE_CLASS_BATTERY, this value must be
    # the battery level as a percentage (between 0 and 100)
    @property
    def is_on(self):
        """Return the state of the sensor."""
        return self._shutter.batt_defect

class ThermicDefectSensor(CoverBinarySensorBase):
    """Representation of a Thermic Defect Sensor."""
        # The class of this device. Note the value should come from the homeassistant.const
    # module. More information on the available devices classes can be seen here:
    # https://developers.home-assistant.io/docs/core/entity/sensor
    device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, shutter):
        """Initialize the sensor."""
        super().__init__(shutter)

        # As per the sensor, this must be a unique value within this domain. This is done
        # by using the device ID, and appending "_battery"
        self._attr_unique_id = f"{self._shutter.uid}_thermic"

        # The name of the entity
        self._attr_name = f"{self._shutter.name} Thermic defect"

        self._state = False

    # The value of this sensor. As this is a DEVICE_CLASS_BATTERY, this value must be
    # the battery level as a percentage (between 0 and 100)
    @property
    def is_on(self):
        """Return the state of the sensor."""
        return self._shutter.thermic_defect

class OnFavPosSensor(CoverBinarySensorBase):
    """Representation of a fav position Sensor."""
    device_class = None

    def __init__(self, shutter):
        """Initialize the sensor."""
        super().__init__(shutter)

        self._attr_unique_id = f"{self._shutter.uid}_on_fav_pos"
        self._attr_name = f"{self._shutter.name} On favorite position"
        self._state = False

    @property
    def is_on(self):
        """Return the state of the sensor."""
        return self._shutter.on_fav_pos

class UpDefectSensor(CoverBinarySensorBase):
    """Representation of a Up Defect Sensor."""
    device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, shutter):
        """Initialize the sensor."""
        super().__init__(shutter)

        self._attr_unique_id = f"{self._shutter.uid}_up_defect"
        self._attr_name = f"{self._shutter.name} Up defect"
        self._state = False

    @property
    def is_on(self):
        """Return the state of the sensor."""
        return self._shutter.up_defect

class DownDefectSensor(CoverBinarySensorBase):
    """Representation of a Down Defect Sensor."""
    device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, shutter):
        """Initialize the sensor."""
        super().__init__(shutter)

        self._attr_unique_id = f"{self._shutter.uid}_down_defect"
        self._attr_name = f"{self._shutter.name} Down defect"
        self._state = False

    @property
    def is_on(self):
        """Return the state of the sensor."""
        return self._shutter.down_defect

class ObstacleDefectSensor(CoverBinarySensorBase):
    """Representation of a Obstacle Defect Sensor."""
    device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, shutter):
        """Initialize the sensor."""
        super().__init__(shutter)

        self._attr_unique_id = f"{self._shutter.uid}_obstacle_defect"
        self._attr_name = f"{self._shutter.name} Obstacle defect"
        self._state = False

    @property
    def is_on(self):
        """Return the state of the sensor."""
        return self._shutter.obstacle_defect

class IntrusionDefectSensor(CoverBinarySensorBase):
    """Representation of a Obstacle Defect Sensor."""
    device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, shutter):
        """Initialize the sensor."""
        super().__init__(shutter)

        self._attr_unique_id = f"{self._shutter.uid}_intrusion_defect"
        self._attr_name = f"{self._shutter.name} Intrusion defect"
        self._state = False

    @property
    def is_on(self):
        """Return the state of the sensor."""
        return self._shutter.intrusion
