"""Home assistant entites."""

from typing import Any
from datetime import date
import math

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfElectricCurrent,
    EntityCategory,
    PERCENTAGE,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverEntity,
    CoverDeviceClass,
    CoverEntityFeature,
)

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
    SensorEntity,
)
from homeassistant.components.light import LightEntity, ColorMode, ATTR_BRIGHTNESS
from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityFeature,
    UpdateDeviceClass,
)
from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    CodeFormat,
)
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)
from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)

from homeassistant.components.weather import (
    WeatherEntity,
    ATTR_CONDITION_CLEAR_NIGHT,
    ATTR_CONDITION_CLOUDY,
    ATTR_CONDITION_FOG,
    ATTR_CONDITION_LIGHTNING,
    ATTR_CONDITION_POURING,
    ATTR_CONDITION_RAINY,
    ATTR_CONDITION_SNOWY,
    ATTR_CONDITION_SUNNY,
)

from homeassistant.components.switch import (
    SwitchEntity,
)

from .tydom.tydom_devices import (
    Tydom,
    TydomDevice,
    TydomEnergy,
    TydomShutter,
    TydomSmoke,
    TydomBoiler,
    TydomWindow,
    TydomDoor,
    TydomGate,
    TydomGarage,
    TydomLight,
    TydomAlarm,
    TydomWeather,
    TydomWater,
    TydomThermo,
    TydomSwitch,
    TydomRemote,
)

from .const import DOMAIN, LOGGER


class HAEntity:
    """Generic abstract HA entity."""

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
        """Get available sensors for this entity."""
        sensors = []

        for attribute, value in self._device.__dict__.items():
            if (
                attribute[:1] != "_"
                and value is not None
                and attribute not in self._registered_sensors
            ):
                alt_name = attribute.split("_")[0]
                if attribute in self.filtered_attrs or alt_name in self.filtered_attrs:
                    continue
                sensor_class = None
                if attribute in self.sensor_classes:
                    sensor_class = self.sensor_classes[attribute]
                elif alt_name in self.sensor_classes:
                    sensor_class = self.sensor_classes[alt_name]

                state_class = None
                if attribute in self.state_classes:
                    state_class = self.state_classes[attribute]
                elif alt_name in self.state_classes:
                    state_class = self.state_classes[alt_name]

                unit = None
                if attribute in self.units:
                    unit = self.units[attribute]
                elif alt_name in self.units:
                    unit = self.units[alt_name]

                if isinstance(value, bool):
                    sensors.append(
                        GenericBinarySensor(
                            self._device, sensor_class, attribute, attribute
                        )
                    )
                else:
                    sensors.append(
                        GenericSensor(
                            self._device,
                            sensor_class,
                            state_class,
                            attribute,
                            attribute,
                            unit,
                        )
                    )
                self._registered_sensors.append(attribute)

        return sensors


class GenericSensor(SensorEntity):
    """Representation of a generic sensor."""

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
        unit_of_measurement,
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
        value = getattr(self._device, self._attribute)
        if self._attr_device_class == SensorDeviceClass.BATTERY:
            min = self._device._metadata[self._attribute]["min"]
            max = self._device._metadata[self._attribute]["max"]
            value = ranged_value_to_percentage((min, max), value)
        return value

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


class HATydom(UpdateEntity, HAEntity):
    """Representation of a Tydom Gateway."""

    _attr_title = "Tydom"

    _ha_device = None
    _attr_has_entity_name = False
    _attr_entity_category = None
    entity_description: str

    should_poll = False
    device_class = None
    supported_features = None

    sensor_classes = {"update_available": BinarySensorDeviceClass.UPDATE}

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
        """Initialize HATydom."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
        self.supported_features = UpdateEntityFeature.INSTALL
        self._attr_device_class = UpdateDeviceClass.FIRMWARE
        self._attr_unique_id = f"{self._device.device_id}"
        self._attr_name = self._device.device_name
        self._registered_sensors = []

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_id,
            "manufacturer": "Delta Dore",
            "sw_version": self._device.mainVersionSW,
            "model": self._device.productName,
        }

    @property
    def installed_version(self) -> str | None:
        """Version currently in use."""
        if self._device is None:
            return None
        # return self._hub.current_firmware
        if hasattr(self._device, "mainVersionSW"):
            return self._device.mainVersionSW
        else:
            return None

    @property
    def latest_version(self) -> str | None:
        """Latest version available for install."""
        if self._device is not None and hasattr(self._device, "mainVersionSW"):
            if self._device.updateAvailable:
                # return version based on today's date for update version
                return date.today().strftime("%y.%m.%d")
            return self._device.mainVersionSW
        # FIXME : return correct version on update
        return None

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install an update."""
        await self._device.async_trigger_firmware_update()


class HAEnergy(SensorEntity, HAEntity):
    """Representation of an Energy sensor."""

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
        "energyIndex": SensorDeviceClass.ENERGY,
        "outTemperature": SensorDeviceClass.TEMPERATURE,
    }

    state_classes = {
        "energyIndexTi1": SensorStateClass.TOTAL_INCREASING,
        "energyTotIndexWatt": SensorStateClass.TOTAL_INCREASING,
        "energyIndexECSWatt": SensorStateClass.TOTAL_INCREASING,
        "energyIndexHeatWatt": SensorStateClass.TOTAL_INCREASING,
        "energyIndexHeatGas": SensorStateClass.TOTAL_INCREASING,
        "energyIndex": SensorStateClass.TOTAL_INCREASING,
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
        "energyIndex": UnitOfEnergy.WATT_HOUR,
        "outTemperature": UnitOfTemperature.CELSIUS,
    }

    def __init__(self, device: TydomEnergy, hass) -> None:
        """Initialize HAEnergy."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
        self._attr_unique_id = f"{self._device.device_id}_energy"
        self._attr_name = self._device.device_name
        self._registered_sensors = []

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        sw_version = None
        if hasattr(self._device, "softVersion"):
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

    def __init__(self, device: TydomShutter, hass) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
        self._attr_unique_id = f"{self._device.device_id}_cover"
        self._attr_name = self._device.device_name
        self._registered_sensors = []
        if hasattr(device, "position"):
            self.supported_features = (
                self.supported_features
                | CoverEntityFeature.SET_POSITION
                | CoverEntityFeature.OPEN
                | CoverEntityFeature.CLOSE
                | CoverEntityFeature.STOP
            )
        if hasattr(device, "slope"):
            self.supported_features = (
                self.supported_features | CoverEntityFeature.SET_TILT_POSITION
                # | CoverEntityFeature.OPEN_TILT
                # | CoverEntityFeature.CLOSE_TILT
                # | CoverEntityFeature.STOP_TILT
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
    """Representation of an Smoke sensor."""

    should_poll = False
    supported_features = None

    sensor_classes = {"batt_defect": BinarySensorDeviceClass.PROBLEM}

    def __init__(self, device: TydomSmoke, hass) -> None:
        """Initialize TydomSmoke."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
        self._attr_unique_id = f"{self._device.device_id}_smoke"
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

    should_poll = False

    sensor_classes = {
        "temperature": SensorDeviceClass.TEMPERATURE,
        "outTemperature": SensorDeviceClass.TEMPERATURE,
        "TempSensorDefect": BinarySensorDeviceClass.PROBLEM,
        "TempSensorOpenCirc": BinarySensorDeviceClass.PROBLEM,
        "TempSensorShortCut": BinarySensorDeviceClass.PROBLEM,
        "ProductionDefect": BinarySensorDeviceClass.PROBLEM,
        "BatteryCmdDefect": BinarySensorDeviceClass.PROBLEM,
        "battLevel": SensorDeviceClass.BATTERY,
    }

    units = {
        "temperature": UnitOfTemperature.CELSIUS,
        "outTemperature": UnitOfTemperature.CELSIUS,
        "ambientTemperature": UnitOfTemperature.CELSIUS,
        "hygroIn": PERCENTAGE,
    }

    def __init__(self, device: TydomBoiler, hass) -> None:
        """Initialize Climate."""
        super().__init__()
        self.hass = hass
        self._device = device
        self._device._ha_device = self
        self._attr_unique_id = f"{self._device.device_id}_climate"
        self._attr_name = self._device.device_name
        self._enable_turn_on_off_backwards_compatibility = False

        self.dict_modes_ha_to_dd = {
            HVACMode.COOL: "COOLING",
            HVACMode.HEAT: "NORMAL",
            HVACMode.OFF: "STOP",
            HVACMode.FAN_ONLY: "VENTILATING",
            HVACMode.DRY: "DRYING",
        }
        self.dict_modes_dd_to_ha = {
            "COOLING": HVACMode.COOL,
            "ANTI_FROST": HVACMode.AUTO,
            "NORMAL": HVACMode.HEAT,
            "HEATING": HVACMode.HEAT,
            "STOP": HVACMode.OFF,
            "AUTO": HVACMode.AUTO,
            "VENTILATING": HVACMode.FAN_ONLY,
            "DRYING": HVACMode.DRY,
        }

        if (
            "hvacMode" in self._device._metadata
            and "AUTO" in self._device._metadata["hvacMode"]["enum_values"]
        ):
            self.dict_modes_ha_to_dd[HVACMode.AUTO] = "AUTO"
        elif (
            "hvacMode" in self._device._metadata
            and "ANTI_FROST" in self._device._metadata["hvacMode"]["enum_values"]
        ):
            self.dict_modes_ha_to_dd[HVACMode.AUTO] = "ANTI_FROST"
        else:
            self.dict_modes_ha_to_dd[HVACMode.AUTO] = "AUTO"

        if hasattr(self._device, "minSetpoint"):
            self._attr_min_temp = self._device.minSetpoint

        if hasattr(self._device, "maxSetpoint"):
            self._attr_max_temp = self._device.maxSetpoint

        self._attr_supported_features = (
            self._attr_supported_features
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TARGET_TEMPERATURE
        )

        if hasattr(self._device._metadata, "thermicLevel") and (
            "NORMAL" in self._device._metadata["thermicLevel"]
            or "AUTO" in self._device._metadata["thermicLevel"]
        ):
            self.dict_modes_ha_to_dd[HVACMode.HEAT] = "AUTO"

        # self._attr_preset_modes = ["NORMAL", "STOP", "ANTI_FROST"]
        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.AUTO,
        ]

        if (
            "comfortMode" in self._device._metadata
            and "COOLING" in self._device._metadata["comfortMode"]["enum_values"]
        ) or (
            "hvacMode" in self._device._metadata
            and "COOLING" in self._device._metadata["hvacMode"]["enum_values"]
        ):
            self._attr_hvac_modes.append(HVACMode.COOL)

        if (
            "comfortMode" in self._device._metadata
            and "HEATING" in self._device._metadata["comfortMode"]["enum_values"]
        ) or (
            "hvacMode" in self._device._metadata
            and "HEATING" in self._device._metadata["hvacMode"]["enum_values"]
        ):
            self._attr_hvac_modes.append(HVACMode.HEAT)

        self._registered_sensors = []

        if (
            hasattr(self._device._metadata, "setpoint")
            and "min" in self._device._metadata["setpoint"]
        ):
            self._attr_min_temp = self._device._metadata["setpoint"]["min"]

        if (
            hasattr(self._device._metadata, "setpoint")
            and "max" in self._device._metadata["setpoint"]
        ):
            self._attr_max_temp = self._device._metadata["setpoint"]["max"]

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        infos = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
        }

        if hasattr(self._device, "manufacturer"):
            infos["manufacturer"] = self._device.manufacturer

        return infos

    @property
    def temperature_unit(self) -> str:
        """Return the unit of temperature measurement for the system."""
        return UnitOfTemperature.CELSIUS

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current operation (e.g. heat, cool, idle)."""
        if hasattr(self._device, "hvacMode") and self._device.hvacMode is not None:
            LOGGER.debug(
                "hvac_mode = %s", self.dict_modes_dd_to_ha[self._device.hvacMode]
            )
            return self.dict_modes_dd_to_ha[self._device.hvacMode]
        elif hasattr(self._device, "authorization"):
            LOGGER.debug(
                "authorization = %s",
                self.dict_modes_dd_to_ha[self._device.thermicLevel],
            )
            return self.dict_modes_dd_to_ha[self._device.authorization]
        elif hasattr(self._device, "thermicLevel"):
            LOGGER.debug(
                "thermicLevel = %s", self.dict_modes_dd_to_ha[self._device.thermicLevel]
            )
            return self.dict_modes_dd_to_ha[self._device.thermicLevel]
        else:
            return None

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        if hasattr(self._device, "temperature"):
            return self._device.temperature
        elif hasattr(self._device, "ambientTemperature"):
            return self._device.ambientTemperature
        else:
            return None

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature currently set to be reached."""
        if hasattr(self._device, "hvacMode"):
            if (
                self._device.hvacMode == "HEATING" or self._device.hvacMode == "NORMAL"
            ) and hasattr(self._device, "setpoint"):
                return self._device.setpoint
            elif (
                self._device.hvacMode == "HEATING" or self._device.hvacMode == "NORMAL"
            ) and hasattr(self._device, "heatSetpoint"):
                return self._device.heatSetpoint
            elif self._device.hvacMode == "COOLING" and hasattr(
                self._device, "setpoint"
            ):
                return self._device.setpoint
            elif self._device.hvacMode == "COOLING" and hasattr(
                self._device, "coolSetpoint"
            ):
                return self._device.coolSetpoint

        elif hasattr(self._device, "authorization"):
            if self._device.authorization == "HEATING" and hasattr(
                self._device, "heatSetpoint"
            ):
                return self._device.heatSetpoint
            elif self._device.authorization == "HEATING" and hasattr(
                self._device, "setpoint"
            ):
                return self._device.setpoint
            elif self._device.authorization == "COOLING" and hasattr(
                self._device, "coolSetpoint"
            ):
                return self._device.coolSetpoint
            elif self._device.authorization == "COOLING" and hasattr(
                self._device, "setpoint"
            ):
                return self._device.setpoint
        return None

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        await self._device.set_hvac_mode(self.dict_modes_ha_to_dd[hvac_mode])

    async def async_set_preset_mode(self, preset_mode):
        """Set new target preset mode."""
        await self._device.set_preset_mode(preset_mode)

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        await self._device.set_temperature(str(kwargs.get(ATTR_TEMPERATURE)))


class HaWindow(CoverEntity, HAEntity):
    """Representation of a Window."""

    should_poll = False
    supported_features = None
    device_class = CoverDeviceClass.WINDOW

    sensor_classes = {
        "battDefect": BinarySensorDeviceClass.PROBLEM,
        "intrusionDetect": BinarySensorDeviceClass.PROBLEM,
    }

    def __init__(self, device: TydomWindow, hass) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
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
        """Return if the window is closed."""
        if hasattr(self._device, "openState"):
            return self._device.openState == "LOCKED"
        elif hasattr(self._device, "intrusionDetect"):
            return not self._device.intrusionDetect
        else:
            LOGGER.error("Unknown state for device %s", self._device.device_id)
            return True


class HaDoor(CoverEntity, HAEntity):
    """Representation of a Door."""

    should_poll = False
    supported_features = None
    device_class = CoverDeviceClass.DOOR
    sensor_classes = {
        "battDefect": BinarySensorDeviceClass.PROBLEM,
        "calibrationDefect": BinarySensorDeviceClass.PROBLEM,
        "intrusionDetect": BinarySensorDeviceClass.PROBLEM,
    }

    def __init__(self, device: TydomDoor, hass) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
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
        """Return if the door is locked."""
        if hasattr(self._device, "openState"):
            return self._device.openState == "LOCKED"
        elif hasattr(self._device, "intrusionDetect"):
            return not self._device.intrusionDetect
        else:
            raise AttributeError(
                "The required attributes 'openState' or 'intrusionDetect' are not available in the device."
            )


class HaGate(CoverEntity, HAEntity):
    """Representation of a Gate."""

    should_poll = False
    supported_features = CoverEntityFeature.OPEN
    device_class = CoverDeviceClass.GATE
    sensor_classes = {}

    def __init__(self, device: TydomGate, hass) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
        self._attr_unique_id = f"{self._device.device_id}_cover"
        self._attr_name = self._device.device_name
        self._registered_sensors = []
        if (
            "levelCmd" in self._device._metadata
            and "OFF" in self._device._metadata["levelCmd"]["enum_values"]
        ):
            self.supported_features = self.supported_features | CoverEntityFeature.CLOSE

        if (
            "levelCmd" in self._device._metadata
            and "STOP" in self._device._metadata["levelCmd"]["enum_values"]
        ):
            self.supported_features = self.supported_features | CoverEntityFeature.STOP

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self.name,
        }

    @property
    def is_closed(self) -> bool | None:
        """Return if the window is closed."""
        if hasattr(self._device, "openState"):
            return self._device.openState == "LOCKED"
        else:
            LOGGER.warning(
                "no attribute 'openState' for device %s", self._device.device_id
            )
            return None

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the gate."""
        if (
            "levelCmd" in self._device._metadata
            and "ON" in self._device._metadata["levelCmd"]["enum_values"]
        ):
            await self._device.open()
        else:
            await self._device.toggle()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Open the gate."""
        if (
            "levelCmd" in self._device._metadata
            and "OFF" in self._device._metadata["levelCmd"]["enum_values"]
        ):
            await self._device.close()
        else:
            await self._device.toggle()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Open the gate."""
        if (
            "levelCmd" in self._device._metadata
            and "STOP" in self._device._metadata["levelCmd"]["enum_values"]
        ):
            await self._device.stop()
        else:
            await self._device.toggle()


class HaGarage(CoverEntity, HAEntity):
    """Representation of a Garage door."""

    should_poll = False
    supported_features = CoverEntityFeature.OPEN
    device_class = CoverDeviceClass.GARAGE
    sensor_classes = {
        "thermic_defect": BinarySensorDeviceClass.PROBLEM,
    }

    def __init__(self, device: TydomGarage, hass) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
        self._attr_unique_id = f"{self._device.device_id}_cover"
        self._attr_name = self._device.device_name
        self._registered_sensors = []
        if (
            "levelCmd" in self._device._metadata
            and "OFF" in self._device._metadata["levelCmd"]["enum_values"]
        ):
            self.supported_features = self.supported_features | CoverEntityFeature.CLOSE

        if (
            "levelCmd" in self._device._metadata
            and "STOP" in self._device._metadata["levelCmd"]["enum_values"]
        ):
            self.supported_features = self.supported_features | CoverEntityFeature.STOP

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self.name,
        }

    @property
    def is_closed(self) -> bool | None:
        """Return if the garage door is closed."""
        if hasattr(self._device, "level"):
            return self._device.level == 0
        else:
            return None

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        if (
            "levelCmd" in self._device._metadata
            and "OFF" in self._device._metadata["levelCmd"]["enum_values"]
        ):
            await self._device.open()
        else:
            await self._device.toggle()

    async def async_close_cover(self, **kwargs):
        """Close the cover."""
        await self._device.close()

    async def async_stop_cover(self, **kwargs):
        """Stop the cover."""
        await self._device.stop()


class HaLight(LightEntity, HAEntity):
    """Representation of a Light."""

    should_poll = False
    sensor_classes = {
        "thermic_defect": BinarySensorDeviceClass.PROBLEM,
    }
    color_mode = None
    supported_color_modes = set()

    BRIGHTNESS_SCALE = (0, 255)

    def __init__(self, device: TydomLight, hass) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
        self._attr_unique_id = f"{self._device.device_id}_light"
        self._attr_name = self._device.device_name
        self._registered_sensors = []
        if "level" in self._device._metadata:
            self.color_mode = ColorMode.BRIGHTNESS
            self.supported_color_modes.add(ColorMode.BRIGHTNESS)
        else:
            self.color_mode = ColorMode.ONOFF
            self.supported_color_modes.add(ColorMode.ONOFF)

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self.name,
        }

    @property
    def brightness(self) -> int | None:
        """Return the current brightness."""
        return percentage_to_ranged_value(self.BRIGHTNESS_SCALE, self._device.level)

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return bool(self._device.level != 0)

    async def async_turn_on(self, **kwargs):
        """Turn device on."""
        brightness = None
        if ATTR_BRIGHTNESS in kwargs:
            brightness = math.ceil(
                ranged_value_to_percentage(
                    self.BRIGHTNESS_SCALE, kwargs[ATTR_BRIGHTNESS]
                )
            )
        await self._device.turn_on(brightness)

    async def async_turn_off(self, **kwargs):
        """Turn device off."""
        await self._device.turn_off()


class HaAlarm(AlarmControlPanelEntity, HAEntity):
    """Representation of an Alarm."""

    should_poll = False
    supported_features = 0
    sensor_classes = {
        "networkDefect": BinarySensorDeviceClass.PROBLEM,
        "remoteSurveyDefect": BinarySensorDeviceClass.PROBLEM,
        "simDefect": BinarySensorDeviceClass.PROBLEM,
        "systAlarmDefect": BinarySensorDeviceClass.PROBLEM,
        "systBatteryDefect": BinarySensorDeviceClass.PROBLEM,
        "systSectorDefect": BinarySensorDeviceClass.PROBLEM,
        "systSupervisionDefect": BinarySensorDeviceClass.PROBLEM,
        "systTechnicalDefect": BinarySensorDeviceClass.PROBLEM,
        "unitBatteryDefect": BinarySensorDeviceClass.PROBLEM,
        "unitInternalDefect": BinarySensorDeviceClass.PROBLEM,
        "videoLinkDefect": BinarySensorDeviceClass.PROBLEM,
        "outTemperature": SensorDeviceClass.TEMPERATURE,
    }

    units = {
        "outTemperature": UnitOfTemperature.CELSIUS,
    }

    def __init__(self, device: TydomAlarm, hass) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
        self._attr_unique_id = f"{self._device.device_id}_alarm"
        self._attr_name = self._device.device_name
        self._attr_code_format = CodeFormat.NUMBER
        self._attr_code_arm_required = True
        self._registered_sensors = []

        self.supported_features = (
            self.supported_features
            | AlarmControlPanelEntityFeature.ARM_AWAY
            | AlarmControlPanelEntityFeature.ARM_HOME
            | AlarmControlPanelEntityFeature.ARM_NIGHT
            | AlarmControlPanelEntityFeature.TRIGGER
        )

    @property
    def alarm_state(self):
        """Return the alarm state."""
        # alarmMode :  "OFF", "ON", "TEST", "ZONE", "MAINTENANCE"
        # alarmState: "OFF", "DELAYED", "ON", "QUIET"
        if self._device.alarmMode == "MAINTENANCE":
            return AlarmControlPanelState.DISARMED

        match self._device.alarmMode:
            case "MAINTENANCE":
                return AlarmControlPanelState.DISARMED
            case "OFF":
                return AlarmControlPanelState.DISARMED
            case "ON":
                if self._device.alarmState == "OFF":
                    return AlarmControlPanelState.ARMED_AWAY
                else:
                    return AlarmControlPanelState.TRIGGERED
            case "ZONE" | "PART":
                if self._device.alarmState == "OFF":
                    return AlarmControlPanelState.ARMED_HOME
                else:
                    return AlarmControlPanelState.TRIGGERED
            case _:
                return AlarmControlPanelState.TRIGGERED

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
        }

    async def async_alarm_disarm(self, code=None) -> None:
        """Send disarm command."""
        await self._device.alarm_disarm(code)

    async def async_alarm_arm_away(self, code=None) -> None:
        """Send arm away command."""
        await self._device.alarm_arm_away(code)

    async def async_alarm_arm_home(self, code=None) -> None:
        """Send arm home command."""
        await self._device.alarm_arm_home(code)

    async def async_alarm_arm_night(self, code=None) -> None:
        """Send arm night command."""
        await self._device.alarm_arm_night(code)

    async def async_alarm_trigger(self, code=None) -> None:
        """Send alarm trigger command."""
        await self._device.alarm_trigger(code)

    async def async_acknowledge_events(self, code=None) -> None:
        """Acknowledge alarm events."""
        await self._device.acknowledge_events(code)

    async def async_get_events(self, event_type=None) -> list:
        """Get alarm events."""
        return await self._device.get_events(event_type or "UNACKED_EVENTS")


class HaWeather(WeatherEntity, HAEntity):
    """Representation of a weather entity."""

    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS

    tydom_ha_condition = {
        "UNAVAILABLE": None,
        "DAY_CLEAR_SKY": ATTR_CONDITION_SUNNY,
        "DAY_FEW_CLOUDS": ATTR_CONDITION_CLOUDY,
        "DAY_SCATTERED_CLOUDS": ATTR_CONDITION_CLOUDY,
        "DAY_BROKEN_CLOUDS": ATTR_CONDITION_CLOUDY,
        "DAY_SHOWER_RAIN": ATTR_CONDITION_POURING,
        "DAY_RAIN": ATTR_CONDITION_RAINY,
        "DAY_THUNDERSTORM": ATTR_CONDITION_LIGHTNING,
        "DAY_SNOW": ATTR_CONDITION_SNOWY,
        "DAY_MIST": ATTR_CONDITION_FOG,
        "NIGHT_CLEAR_SKY": ATTR_CONDITION_CLEAR_NIGHT,
        "NIGHT_FEW_CLOUDS": ATTR_CONDITION_CLOUDY,
        "NIGHT_SCATTERED_CLOUDS": ATTR_CONDITION_CLOUDY,
        "NIGHT_BROKEN_CLOUDS": ATTR_CONDITION_CLOUDY,
        "NIGHT_SHOWER_RAIN": ATTR_CONDITION_POURING,
        "NIGHT_RAIN": ATTR_CONDITION_RAINY,
        "NIGHT_THUNDERSTORM": ATTR_CONDITION_LIGHTNING,
        "NIGHT_SNOW": ATTR_CONDITION_SNOWY,
        "NIGHT_MIST": ATTR_CONDITION_FOG,
    }

    units = {
        "outTemperature": UnitOfTemperature.CELSIUS,
        "maxDailyOutTemp": UnitOfTemperature.CELSIUS,
    }

    def __init__(self, device: TydomWeather, hass) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
        self._attr_unique_id = f"{self._device.device_id}_weather"
        self._attr_name = self._device.device_name
        self._registered_sensors = []
        if (
            "dailyPower" in self._device._metadata
            and "unit" in self._device._metadata["dailyPower"]
        ):
            self.units["dailyPower"] = self._device._metadata["dailyPower"]["unit"]
        if (
            "currentPower" in self._device._metadata
            and "unit" in self._device._metadata["currentPower"]
        ):
            self.units["currentPower"] = self._device._metadata["currentPower"]["unit"]

    @property
    def native_temperature(self) -> float | None:
        """Return current temperature in C."""
        return self._device.outTemperature

    @property
    def condition(self) -> str:
        """Return current weather condition."""
        return self.tydom_ha_condition[self._device.weather]

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
        }


class HaMoisture(BinarySensorEntity, HAEntity):
    """Representation of an leak detector sensor."""

    should_poll = False
    supported_features = None

    sensor_classes = {"batt_defect": BinarySensorDeviceClass.PROBLEM}

    def __init__(self, device: TydomWater, hass) -> None:
        """Initialize TydomSmoke."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
        self._attr_unique_id = f"{self._device.device_id}_moisture"
        self._attr_name = self._device.device_name
        self._state = False
        self._registered_sensors = []
        self._attr_device_class = BinarySensorDeviceClass.MOISTURE

    @property
    def is_on(self):
        """Return the state of the sensor."""
        return self._device.techWaterDefect

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": "Delta Dore",
        }


class HaThermo(SensorEntity, HAEntity):
    """Representation of a thermometer."""

    def __init__(self, device: TydomThermo, hass) -> None:
        """Initialize TydomSmoke."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
        self._attr_unique_id = f"{self._device.device_id}_thermos"
        self._attr_name = self._device.device_name
        self._state = False
        self._registered_sensors = ["outTemperature"]
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._device.outTemperature

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
        }


class HaSwitch(SwitchEntity, HAEntity):
    """Representation of a switch."""

    sensor_classes = {
        "energyInstantTotElecP": SensorDeviceClass.POWER,
        "energyTotIndexWatt": SensorDeviceClass.ENERGY,
    }

    state_classes = {
        "energyTotIndexWatt": SensorStateClass.TOTAL_INCREASING,
    }

    units = {
        "energyInstantTotElecP": UnitOfPower.WATT,
        "energyTotIndexWatt": UnitOfEnergy.WATT_HOUR,
    }

    def __init__(self, device: TydomSwitch, hass) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
        self._attr_unique_id = f"{self._device.device_id}"
        self._attr_name = self._device.device_name
        self._registered_sensors = []

    async def async_turn_on(self, **kwargs):
        """Open the switch."""
        await self._device.turn_on()

    async def async_turn_off(self, **kwargs):
        """Open the switch."""
        await self._device.turn_off()

    @property
    def is_on(self):
        """Return true if switch is on."""
        if self._device.plugCmd == "ON":
            return True
        else:
            return False

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
        }


class HaRemote(SensorEntity, HAEntity):
    """Representation of a remote."""

    def __init__(self, device: TydomRemote, hass) -> None:
        """Initialize TydomRemote."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
        self._attr_unique_id = f"{self._device.device_id}"
        self._attr_name = self._device.device_name
        self._registered_sensors = []
