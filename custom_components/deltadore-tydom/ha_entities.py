"""Home assistant entites"""
from typing import Any

from homeassistant.helpers import device_registry as dr
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    FAN_OFF,
    FAN_ON,
    PRESET_ECO,
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    PERCENTAGE,
    ATTR_TEMPERATURE,
    UnitOfTemperature,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfElectricCurrent,
    EntityCategory,
)

from homeassistant.helpers.entity import Entity, DeviceInfo
from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    SUPPORT_CLOSE,
    SUPPORT_OPEN,
    SUPPORT_SET_POSITION,
    SUPPORT_STOP,
    SUPPORT_SET_TILT_POSITION,
    SUPPORT_OPEN_TILT,
    SUPPORT_CLOSE_TILT,
    SUPPORT_STOP_TILT,
    CoverEntity,
    CoverDeviceClass,
)
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass, SensorEntity
from homeassistant.components.light import LightEntity
from homeassistant.components.lock import LockEntity

from .tydom.tydom_devices import *

from .const import DOMAIN, LOGGER

class HAEntity:

    sensor_classes = {}
    state_classes = {}
    units = {}
    filtered_attrs = {}

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self._device.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self._device.remove_callback(self.async_write_ha_state)

    @property
    def available(self) -> bool:
        """Return True if roller and hub is available."""
        # FIXME
        # return self._device.online and self._device.hub.online
        return True
    
    def get_sensors(self):
        """Get available sensors for this entity"""
        sensors = []

        for attribute, value in self._device.__dict__.items():
            if (
                attribute[:1] != "_"
                and value is not None
                and attribute not in self._registered_sensors
            ):
                if attribute in self.filtered_attrs:
                    continue
                sensor_class = None
                if attribute in self.sensor_classes:
                    sensor_class = self.sensor_classes[attribute]

                state_class = None
                if attribute in self.state_classes:
                    state_class = self.state_classes[attribute]

                unit = None
                if attribute in self.units:
                    unit = self.units[attribute]

                if isinstance(value, bool):
                    sensors.append(
                        GenericBinarySensor(
                            self._device, sensor_class, attribute, attribute
                        )
                    )
                else:
                    sensors.append(
                        GenericSensor(self._device, sensor_class, state_class, attribute, attribute, unit)
                    )
                self._registered_sensors.append(attribute)

        return sensors


class GenericSensor(SensorEntity):
    """Representation of a generic sensor"""

    should_poll = False
    diagnostic_attrs = [
        "config",
        "supervisionMode",
        "bootReference",
        "bootVersion",
        "keyReference",
        "keyVersionHW",
        "keyVersionStack",
        "keyVersionSW",
        "mainId",
        "mainReference",
        "mainVersionHW",
        "productName",
        "mac",
        "jobsMP",
        "softPlan",
        "softVersion",
    ]

    def __init__(
        self,
        device: TydomDevice,
        device_class: SensorDeviceClass,
        state_class: SensorStateClass,
        name: str,
        attribute: str,
        unit_of_measurement
    ):
        """Initialize the sensor."""
        self._device = device
        self._attr_unique_id = f"{self._device.device_id}_{name}"
        self._attr_name = name
        self._attribute = attribute
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit_of_measurement
        if name in self.diagnostic_attrs:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def state(self):
        """Return the state of the sensor."""
        return getattr(self._device, self._attribute)

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._device.device_id)}}

    @property
    def available(self) -> bool:
        """Return True if hub is available."""
        # FIXME
        # return self._device.online
        return True

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        # Sensors should also register callbacks to HA when their state changes
        self._device.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self):
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._device.remove_callback(self.async_write_ha_state)


class BinarySensorBase(BinarySensorEntity):
    """Base representation of a Sensor."""

    should_poll = False

    def __init__(self, device: TydomDevice):
        """Initialize the sensor."""
        self._device = device

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._device.device_id)}}

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        # Sensors should also register callbacks to HA when their state changes
        self._device.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self):
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._device.remove_callback(self.async_write_ha_state)


class GenericBinarySensor(BinarySensorBase):
    """Generic representation of a Binary Sensor."""

    def __init__(
        self,
        device: TydomDevice,
        device_class: BinarySensorDeviceClass,
        name: str,
        attribute: str,
    ):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.device_id}_{name}"
        self._attr_name = name
        self._attribute = attribute
        self._attr_device_class = device_class

    @property
    def available(self) -> bool:
        """Return True if hub is available."""
        # FIXME
        # return self._device.online
        return True

    # The value of this sensor.
    @property
    def is_on(self):
        """Return the state of the sensor."""
        return getattr(self._device, self._attribute)

class HATydom(Entity, HAEntity):
    """Representation of a Tydom Gateway."""

    _attr_has_entity_name = False
    _attr_entity_category = None
    entity_description: str

    should_poll = False
    device_class = None
    supported_features = None

    sensor_classes = {
        "update_available": BinarySensorDeviceClass.UPDATE
    }

    filtered_attrs = [
        "absence.json",
        "anticip.json",
        "bdd_mig.json",
        "bdd.json",
        "bioclim.json",
        "collect.json",
        "config.json",
        "data_config.json",
        "gateway.dat",
        "gateway.dat",
        "groups.json",
        "info_col.json",
        "info_mig.json",
        "mom_api.json",
        "mom.json",
        "scenario.json",
        "site.json",
        "trigger.json",
        "TYDOM.dat",
    ]

    def __init__(self, device: Tydom, hass) -> None:
        self._device = device
        self._attr_unique_id = f"{self._device.device_id}"
        self._attr_name = self._device.device_name
        self._registered_sensors = []

        device_registry = dr.async_get(hass)

        device_registry.async_get_or_create(
            config_entry_id=self._device.device_id,
            identifiers={(DOMAIN, self._device.device_id)},
            name=self._device.device_id,
            manufacturer="Delta Dore",
            model=self._device.productName,
            sw_version=self._device.mainVersionSW,

        )
        
    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {
            "identifiers": {(DOMAIN, self.device.device_id)},
            "name": self._device.device_id,
            "manufacturer": "Delta Dore",
            "sw_version": self._device.mainVersionSW,
            "model": self._device.productName,
        }

class HAEnergy(Entity, HAEntity):
    """Representation of an Energy sensor"""

    _attr_has_entity_name = False
    _attr_entity_category = None
    entity_description: str

    should_poll = False
    device_class = None
    supported_features = None

    sensor_classes = {
        "energyInstantTotElec": SensorDeviceClass.CURRENT,
        "energyInstantTotElec_Min": SensorDeviceClass.CURRENT,
        "energyInstantTotElec_Max": SensorDeviceClass.CURRENT,
        "energyScaleTotElec_Min": SensorDeviceClass.CURRENT,
        "energyScaleTotElec_Max": SensorDeviceClass.CURRENT,
        "energyInstantTotElecP": SensorDeviceClass.POWER,
        "energyInstantTotElec_P_Min": SensorDeviceClass.POWER,
        "energyInstantTotElec_P_Max": SensorDeviceClass.POWER,
        "energyScaleTotElec_P_Min": SensorDeviceClass.POWER,
        "energyScaleTotElec_P_Max": SensorDeviceClass.POWER,
        "energyInstantTi1P": SensorDeviceClass.POWER,
        "energyInstantTi1P_Min": SensorDeviceClass.POWER,
        "energyInstantTi1P_Max": SensorDeviceClass.POWER,
        "energyScaleTi1P_Min": SensorDeviceClass.POWER,
        "energyScaleTi1P_Max": SensorDeviceClass.POWER,
        "energyInstantTi1I": SensorDeviceClass.CURRENT,
        "energyInstantTi1I_Min": SensorDeviceClass.CURRENT,
        "energyInstantTi1I_Max": SensorDeviceClass.CURRENT,
        "energyIndexTi1": SensorDeviceClass.ENERGY,
        "energyTotIndexWatt": SensorDeviceClass.ENERGY,
        "energyIndexHeatWatt": SensorDeviceClass.ENERGY,
        "energyIndexECSWatt": SensorDeviceClass.ENERGY,
        "energyIndexHeatGas": SensorDeviceClass.ENERGY,
        "outTemperature": SensorDeviceClass.TEMPERATURE,
    }

    state_classes = {
        "energyIndexTi1": SensorStateClass.TOTAL_INCREASING,
        "energyTotIndexWatt": SensorStateClass.TOTAL_INCREASING,
        "energyIndexECSWatt": SensorStateClass.TOTAL_INCREASING,
        "energyIndexHeatWatt": SensorStateClass.TOTAL_INCREASING,
        "energyIndexHeatGas": SensorStateClass.TOTAL_INCREASING,
    }

    units = {
        "energyInstantTotElec": UnitOfElectricCurrent.AMPERE,
        "energyInstantTotElec_Min": UnitOfElectricCurrent.AMPERE,
        "energyInstantTotElec_Max": UnitOfElectricCurrent.AMPERE,
        "energyScaleTotElec_Min": UnitOfElectricCurrent.AMPERE,
        "energyScaleTotElec_Max": UnitOfElectricCurrent.AMPERE,
        "energyInstantTotElecP": UnitOfPower.WATT,
        "energyInstantTotElec_P_Min": UnitOfPower.WATT,
        "energyInstantTotElec_P_Max": UnitOfPower.WATT,
        "energyScaleTotElec_P_Min": UnitOfPower.WATT,
        "energyScaleTotElec_P_Max": UnitOfPower.WATT,
        "energyInstantTi1P": UnitOfPower.WATT,
        "energyInstantTi1P_Min": UnitOfPower.WATT,
        "energyInstantTi1P_Max": UnitOfPower.WATT,
        "energyScaleTi1P_Min": UnitOfPower.WATT,
        "energyScaleTi1P_Max": UnitOfPower.WATT,
        "energyInstantTi1I": UnitOfElectricCurrent.AMPERE,
        "energyInstantTi1I_Min": UnitOfElectricCurrent.AMPERE,
        "energyInstantTi1I_Max": UnitOfElectricCurrent.AMPERE,
        "energyScaleTi1I_Min": UnitOfElectricCurrent.AMPERE,
        "energyScaleTi1I_Max": UnitOfElectricCurrent.AMPERE,
        "energyIndexTi1": UnitOfEnergy.WATT_HOUR,
        "energyTotIndexWatt": UnitOfEnergy.WATT_HOUR,
        "energyIndexHeatWatt": UnitOfEnergy.WATT_HOUR,
        "energyIndexECSWatt": UnitOfEnergy.WATT_HOUR,
        "energyIndexHeatGas": UnitOfEnergy.WATT_HOUR,
        "outTemperature": UnitOfTemperature.CELSIUS,
    }

    def __init__(self, device: TydomEnergy, hass) -> None:
        self._device = device
        self._attr_unique_id = f"{self._device.device_id}_energy"
        self._attr_name = self._device.device_name
        self._registered_sensors = []

        device_registry = dr.async_get(hass)

        sw_version = None
        if  hasattr(self._device, "softVersion"):
            sw_version = self._device.softVersion

        device_registry.async_get_or_create(
            config_entry_id=self._device.device_id,
            identifiers={(DOMAIN, self._device.device_id)},
            name=self._device.device_name,
            sw_version= sw_version,
        )
        
    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        sw_version = None
        if  hasattr(self._device, "softVersion"):
            sw_version = self._device.softVersion
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "sw_version": sw_version,
        }

class HACover(CoverEntity, HAEntity):
    """Representation of a Cover."""


    should_poll = False
    supported_features = 0
    device_class = CoverDeviceClass.SHUTTER

    sensor_classes = {
        "batt_defect": BinarySensorDeviceClass.PROBLEM,
        "thermic_defect": BinarySensorDeviceClass.PROBLEM,
        "up_defect": BinarySensorDeviceClass.PROBLEM,
        "down_defect": BinarySensorDeviceClass.PROBLEM,
        "obstacle_defect": BinarySensorDeviceClass.PROBLEM,
        "intrusion": BinarySensorDeviceClass.PROBLEM,
    }

    def __init__(self, device: TydomShutter) -> None:
        """Initialize the sensor."""

        self._device = device
        self._attr_unique_id = f"{self._device.device_id}_cover"
        self._attr_name = self._device.device_name
        self._registered_sensors = []
        if hasattr(device, "position"):
            self.supported_features = (
                self.supported_features
                | SUPPORT_SET_POSITION
                | SUPPORT_OPEN
                | SUPPORT_CLOSE
                | SUPPORT_STOP
            )
        if hasattr(device, "slope"):
            self.supported_features = (
                self.supported_features
                | SUPPORT_SET_TILT_POSITION
                | SUPPORT_OPEN_TILT
                | SUPPORT_CLOSE_TILT
                | SUPPORT_STOP_TILT
            )

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self.name,
        }

    @property
    def current_cover_position(self):
        """Return the current position of the cover."""
        return self._device.position

    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed, same as position 0."""
        return self._device.position == 0

    @property
    def current_cover_tilt_position(self):
        """Return the current tilt position of the cover."""
        if hasattr(self._device, "slope"):
            return self._device.slope
        else:
            return None

    # @property
    # def is_closing(self) -> bool:
    #    """Return if the cover is closing or not."""
    #    return self._device.moving < 0

    # @property
    # def is_opening(self) -> bool:
    #    """Return if the cover is opening or not."""
    #    return self._device.moving > 0

    # These methods allow HA to tell the actual device what to do. In this case, move
    # the cover to the desired position, or open and close it all the way.
    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self._device.up()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self._device.down()

    async def async_stop_cover(self, **kwargs):
        """Stop the cover."""
        await self._device.stop()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set the cover's position."""
        await self._device.set_position(kwargs[ATTR_POSITION])

    async def async_open_cover_tilt(self, **kwargs):
        """Open the cover tilt."""
        await self._device.slope_open()

    async def async_close_cover_tilt(self, **kwargs):
        """Close the cover tilt."""
        await self._device.slope_close()

    async def async_set_cover_tilt_position(self, **kwargs):
        """Move the cover tilt to a specific position."""
        await self._device.set_slope_position(kwargs[ATTR_TILT_POSITION])

    async def async_stop_cover_tilt(self, **kwargs):
        """Stop the cover tilt."""
        await self._device.slope_stop()


class HASmoke(BinarySensorEntity, HAEntity):
    """Representation of an Smoke sensor"""

    should_poll = False
    supported_features = None

    sensor_classes = {"batt_defect": BinarySensorDeviceClass.PROBLEM}

    def __init__(self, device: TydomSmoke) -> None:
        self._device = device
        self._attr_unique_id = f"{self._device.device_id}_smoke_defect"
        self._attr_name = self._device.device_name
        self._state = False
        self._registered_sensors = []
        self._attr_device_class = BinarySensorDeviceClass.SMOKE


    @property
    def is_on(self):
        """Return the state of the sensor."""
        return self._device.techSmokeDefect

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": "Delta Dore",
        }

class HaClimate(ClimateEntity, HAEntity):
    """A climate entity."""

    should_poll = True

    sensor_classes = {
        "temperature": SensorDeviceClass.TEMPERATURE,
        "TempSensorDefect": BinarySensorDeviceClass.PROBLEM,
        "TempSensorOpenCirc": BinarySensorDeviceClass.PROBLEM,
        "TempSensorShortCut": BinarySensorDeviceClass.PROBLEM,
        "ProductionDefect": BinarySensorDeviceClass.PROBLEM,
        "BatteryCmdDefect": BinarySensorDeviceClass.PROBLEM,
    }

    units = {
        "temperature": UnitOfTemperature.CELSIUS,
    }

    DICT_MODES_HA_TO_DD = {
        HVACMode.AUTO: None,
        HVACMode.COOL: None,
        HVACMode.HEAT: "HEATING",
        HVACMode.OFF: "STOP",
    }
    DICT_MODES_DD_TO_HA = {
        # "": HVACMode.AUTO,
        # "": HVACMode.COOL,
        "HEATING": HVACMode.HEAT,
        "STOP": HVACMode.OFF,
    }

    def __init__(self, device: TydomBoiler) -> None:
        super().__init__()
        self._device = device
        self._attr_unique_id = f"{self._device.device_id}_climate"
        self._attr_name = self._device.device_name

        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.HEAT,
        ]
        self._registered_sensors = []

        self._attr_preset_modes = ["NORMAL", "STOP", "ANTI_FROST"]
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
 
    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return the list of supported features."""
        features = ClimateEntityFeature(0)
        features = features | ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        return features

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
        }

    @property
    def temperature_unit(self) -> str:
        """Return the unit of temperature measurement for the system."""
        return UnitOfTemperature.CELSIUS

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current operation (e.g. heat, cool, idle)."""
        if (hasattr(self._device, 'authorization')):
            LOGGER.debug("hvac_mode = %s", self.DICT_MODES_DD_TO_HA[self._device.authorization])
            return self.DICT_MODES_DD_TO_HA[self._device.authorization]
        else:
            return None
        
    @property
    def preset_mode(self) -> HVACMode:
        """Return the current operation (e.g. heat, cool, idle)."""
        LOGGER.debug("preset_mode = %s", self._device.hvacMode)
        return self._device.hvacMode

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._device.temperature

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature currently set to be reached."""
        if self._device.authorization == "HEATING":
            return self._device.setpoint
        return None

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        await self._device.set_hvac_mode(self.DICT_MODES_HA_TO_DD[hvac_mode]) 

    async def async_set_preset_mode(self, preset_mode):
        """Set new target preset mode."""
        await self._device.set_preset_mode(preset_mode)

    async def async_set_temperature(self, target_temperature):
        """Set new target temperature."""
        await self._device.set_temperature(target_temperature)

class HaWindow(CoverEntity, HAEntity):
    """Representation of a Window."""

    should_poll = False
    supported_features = None
    device_class = CoverDeviceClass.WINDOW

    sensor_classes = {
        "battDefect": BinarySensorDeviceClass.PROBLEM,
        "intrusionDetect": BinarySensorDeviceClass.PROBLEM,
    }

    def __init__(self, device: TydomWindow) -> None:
        """Initialize the sensor."""
        self._device = device
        self._attr_unique_id = f"{self._device.device_id}_cover"
        self._attr_name = self._device.device_name
        self._registered_sensors = []

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self.name,
        }

    @property
    def is_closed(self) -> bool:
        """Return if the window is closed"""
        return self._device.openState == "LOCKED"

class HaDoor(LockEntity, HAEntity):
    """Representation of a Door."""

    should_poll = False
    supported_features = None
    device_class = CoverDeviceClass.DOOR
    sensor_classes = {
        "battDefect": BinarySensorDeviceClass.PROBLEM,
        "calibrationDefect": BinarySensorDeviceClass.PROBLEM,
        "intrusionDetect": BinarySensorDeviceClass.PROBLEM,
    }

    def __init__(self, device: TydomDoor) -> None:
        """Initialize the sensor."""
        self._device = device
        self._attr_unique_id = f"{self._device.device_id}_cover"
        self._attr_name = self._device.device_name
        self._registered_sensors = []

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self.name,
        }

    @property
    def is_locked(self) -> bool:
        """Return if the door is closed"""
        return self._device.openState == "LOCKED"

class HaGate(CoverEntity, HAEntity):
    """Representation of a Gate."""

    should_poll = False
    supported_features = None
    device_class = CoverDeviceClass.GATE
    sensor_classes = {}

    def __init__(self, device: TydomGate) -> None:
        """Initialize the sensor."""
        self._device = device
        self._attr_unique_id = f"{self._device.device_id}_cover"
        self._attr_name = self._device.device_name
        self._registered_sensors = []

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self.name,
        }

class HaGarage(CoverEntity, HAEntity):
    """Representation of a Garage door."""

    should_poll = False
    supported_features = None
    device_class = CoverDeviceClass.GARAGE
    sensor_classes = {}

    def __init__(self, device: TydomGarage) -> None:
        """Initialize the sensor."""
        self._device = device
        self._attr_unique_id = f"{self._device.device_id}_cover"
        self._attr_name = self._device.device_name
        self._registered_sensors = []

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self.name,
        }

class HaLight(LightEntity, HAEntity):
    """Representation of a Light."""

    should_poll = False
    supported_features = None
    sensor_classes = {}

    def __init__(self, device: TydomLight) -> None:
        """Initialize the sensor."""
        self._device = device
        self._attr_unique_id = f"{self._device.device_id}_cover"
        self._attr_name = self._device.device_name
        self._registered_sensors = []

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self.name,
        }

