"""Home assistant entites."""

from typing import Any
import inspect
import math

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    PRESET_NONE,
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
    SensorEntityDescription,
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
from homeassistant.components.scene import Scene
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.event import EventEntity

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
    TydomScene,
)

from .const import DOMAIN, LOGGER
from .tydom.MessageHandler import device_name


class HAEntity:
    """Generic abstract HA entity."""

    sensor_classes: dict[str, Any] = {}
    state_classes: dict[str, Any] = {}
    units: dict[str, Any] = {}
    filtered_attrs: list[str] = []
    _device: Any = None
    _registered_sensors: list[str] = []
    hass: Any = None

    def _get_hub(self):
        """Get the hub instance from hass data."""
        if self.hass is None:
            return None
        if DOMAIN not in self.hass.data:
            return None
        # Get the first hub entry (assuming single hub per instance)
        hubs = self.hass.data[DOMAIN]
        if not hubs:
            return None
        # Return the first hub (entry_id is the key)
        return next(iter(hubs.values()))

    def _get_tydom_gateway_device_id(self) -> str | None:
        """Get the Tydom gateway device_id to use as via_device_id."""
        hub_instance = self._get_hub()
        if hub_instance is None:
            return None
        # Look for the Tydom gateway device in hub devices
        if hasattr(hub_instance, "devices"):
            for _device_id, device in hub_instance.devices.items():
                if isinstance(device, Tydom):
                    return device.device_id
        # Also check ha_devices
        if hasattr(hub_instance, "ha_devices"):
            for _device_id, ha_device in hub_instance.ha_devices.items():
                if isinstance(ha_device, HATydom):
                    return ha_device._device.device_id
        return None

    def _enrich_device_info(self, info: DeviceInfo) -> DeviceInfo:
        """Enrich device info with via_device link to gateway."""
        gateway_device_id = self._get_tydom_gateway_device_id()
        if gateway_device_id is not None and self._device is not None:
            if gateway_device_id != self._device.device_id:
                info["via_device"] = (DOMAIN, gateway_device_id)
        return info

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        if self._device is not None:
            self._device.register_callback(self.async_write_ha_state)  # type: ignore[attr-defined]

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        if self._device is not None:
            self._device.remove_callback(self.async_write_ha_state)  # type: ignore[attr-defined]

    @property
    def available(self) -> bool:
        """Return True if device and hub are available."""
        if self._device is None:
            return False
        hub = self._get_hub()
        if hub is None:
            return False
        # Check hub online status
        if not getattr(hub, "online", False):
            return False
        # Check if tydom_client is available
        if hasattr(hub, "_tydom_client"):
            tydom_client = hub._tydom_client
            # Check if client has a connection attribute
            if hasattr(tydom_client, "_connection"):
                connection = getattr(tydom_client, "_connection", None)
                if connection is not None:
                    # Check if websocket is closed
                    if hasattr(connection, "closed"):
                        if connection.closed:
                            return False
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
                LOGGER.debug(
                    "Nouveau capteur créé: %s.%s (type: %s, valeur: %s)",
                    self._device.device_id,
                    attribute,
                    "binary" if isinstance(value, bool) else "sensor",
                    value,
                )

        return sensors

    def _get_device_info(self) -> dict[str, str]:
        """Get manufacturer and model from device attributes."""
        info: dict[str, str] = {}

        # Récupérer le fabricant depuis les attributs du device
        if hasattr(self._device, "manufacturer"):
            manufacturer = getattr(self._device, "manufacturer", None)
            if manufacturer is not None:
                info["manufacturer"] = str(manufacturer)

        # Fallback sur "Delta Dore" si le fabricant n'est pas disponible
        if "manufacturer" not in info:
            info["manufacturer"] = "Delta Dore"

        # Récupérer le modèle depuis productName
        if hasattr(self._device, "productName"):
            product_name = getattr(self._device, "productName", None)
            if product_name is not None:
                info["model"] = str(product_name)

        # Récupérer la version hardware si disponible
        if hasattr(self._device, "mainVersionHW"):
            hw_version = getattr(self._device, "mainVersionHW", None)
            if hw_version is not None:
                info["hw_version"] = str(hw_version)
        elif hasattr(self._device, "keyVersionHW"):
            hw_version = getattr(self._device, "keyVersionHW", None)
            if hw_version is not None:
                info["hw_version"] = str(hw_version)

        # Récupérer la version software si disponible
        if hasattr(self._device, "mainVersionSW"):
            sw_version = getattr(self._device, "mainVersionSW", None)
            if sw_version is not None:
                info["sw_version"] = str(sw_version)
        elif hasattr(self._device, "keyVersionSW"):
            sw_version = getattr(self._device, "keyVersionSW", None)
            if sw_version is not None:
                info["sw_version"] = str(sw_version)
        elif hasattr(self._device, "softVersion"):
            sw_version = getattr(self._device, "softVersion", None)
            if sw_version is not None:
                info["sw_version"] = str(sw_version)

        return info


class GenericSensor(SensorEntity):
    """Representation of a generic sensor."""

    _attr_should_poll = False
    _attr_has_entity_name = True
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
        device_class: SensorDeviceClass | None,
        state_class: SensorStateClass | None,
        name: str,
        attribute: str,
        unit_of_measurement: str | None,
    ):
        """Initialize the sensor."""
        self._device = device
        self._attr_unique_id = f"{self._device.device_id}_{name}"
        self._attr_name = name
        self._attribute = attribute
        # Create entity description with translation key
        entity_description = SensorEntityDescription(
            key=attribute,
            name=name,
            device_class=device_class,
            state_class=state_class,
            native_unit_of_measurement=unit_of_measurement,
            translation_key=f"sensor_{attribute}" if attribute else None,
        )
        self.entity_description = entity_description
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit_of_measurement
        if name in self.diagnostic_attrs:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def _get_hub(self):
        """Get the hub instance from hass data."""
        if not hasattr(self, "hass") or self.hass is None:
            return None
        if DOMAIN not in self.hass.data:
            return None
        hubs = self.hass.data[DOMAIN]
        if not hubs:
            return None
        return next(iter(hubs.values()))

    def _get_tydom_gateway_device_id(self) -> str | None:
        """Get the Tydom gateway device_id to use as via_device_id."""
        hub_instance = self._get_hub()
        if hub_instance is None:
            return None
        if hasattr(hub_instance, "devices"):
            for _device_id, device in hub_instance.devices.items():
                if isinstance(device, Tydom):
                    return device.device_id
        if hasattr(hub_instance, "ha_devices"):
            for _device_id, ha_device in hub_instance.ha_devices.items():
                if isinstance(ha_device, HATydom):
                    return ha_device._device.device_id
        return None

    @property
    def native_value(self):
        """Return the native value of the sensor."""
        # Utiliser getattr avec une valeur par défaut pour éviter AttributeError
        value = getattr(self._device, self._attribute, None)
        if (
            value is not None
            and self._attr_device_class == SensorDeviceClass.BATTERY
            and self._device._metadata is not None
            and self._attribute in self._device._metadata
        ):
            min = self._device._metadata[self._attribute]["min"]
            max = self._device._metadata[self._attribute]["max"]
            value = ranged_value_to_percentage((min, max), value)
        return value

    def _get_device_info_dict(self) -> dict[str, str]:
        """Get device info as dict (helper for GenericSensor)."""
        info: dict[str, str] = {}
        if hasattr(self._device, "manufacturer"):
            manufacturer = getattr(self._device, "manufacturer", None)
            if manufacturer is not None:
                info["manufacturer"] = str(manufacturer)
        if "manufacturer" not in info:
            info["manufacturer"] = "Delta Dore"
        if hasattr(self._device, "productName"):
            product_name = getattr(self._device, "productName", None)
            if product_name is not None:
                info["model"] = str(product_name)
        if hasattr(self._device, "mainVersionHW"):
            hw_version = getattr(self._device, "mainVersionHW", None)
            if hw_version is not None:
                info["hw_version"] = str(hw_version)
        if hasattr(self._device, "mainVersionSW"):
            sw_version = getattr(self._device, "mainVersionSW", None)
            if sw_version is not None:
                info["sw_version"] = str(sw_version)
        return info

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        device_info_dict = self._get_device_info_dict()
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
        }

        # Add name if available
        if hasattr(self._device, "device_name") and self._device.device_name:
            info["name"] = self._device.device_name
        elif "model" in device_info_dict:
            info["name"] = device_info_dict["model"]
        else:
            info["name"] = f"Tydom Device {self._device.device_id[-6:]}"

        # Add manufacturer
        if "manufacturer" in device_info_dict:
            info["manufacturer"] = device_info_dict["manufacturer"]
        else:
            info["manufacturer"] = "Delta Dore"

        # Add model
        if "model" in device_info_dict:
            info["model"] = device_info_dict["model"]

        # Add hardware version
        if "hw_version" in device_info_dict:
            info["hw_version"] = device_info_dict["hw_version"]

        # Add software version
        if "sw_version" in device_info_dict:
            info["sw_version"] = device_info_dict["sw_version"]

        # Link device to Tydom gateway via via_device
        gateway_device_id = self._get_tydom_gateway_device_id()
        if (
            gateway_device_id is not None
            and gateway_device_id != self._device.device_id
        ):
            info["via_device"] = (DOMAIN, gateway_device_id)

        return info

    @property
    def available(self) -> bool:
        """Return True if hub is available."""
        if self._device is None:
            return False
        # Use the same availability logic as HAEntity
        if hasattr(self, "hass") and self.hass is not None:
            from .const import DOMAIN

            if DOMAIN in self.hass.data:
                hubs = self.hass.data[DOMAIN]
                if hubs:
                    hub = next(iter(hubs.values()))
                    if not getattr(hub, "online", False):
                        return False
                    # Check tydom_client connection
                    if hasattr(hub, "_tydom_client"):
                        tydom_client = hub._tydom_client
                        if hasattr(tydom_client, "_connection"):
                            connection = getattr(tydom_client, "_connection", None)
                            if connection is not None and hasattr(connection, "closed"):
                                if connection.closed:
                                    return False
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

    _attr_should_poll = False
    hass: Any = None

    def __init__(self, device: TydomDevice):
        """Initialize the sensor."""
        self._device = device

    def _get_hub(self):
        """Get the hub instance from hass data."""
        if not hasattr(self, "hass") or self.hass is None:
            return None
        if DOMAIN not in self.hass.data:
            return None
        hubs = self.hass.data[DOMAIN]
        if not hubs:
            return None
        return next(iter(hubs.values()))

    def _get_tydom_gateway_device_id(self) -> str | None:
        """Get the Tydom gateway device_id to use as via_device_id."""
        hub_instance = self._get_hub()
        if hub_instance is None:
            return None
        if hasattr(hub_instance, "devices"):
            for _device_id, device in hub_instance.devices.items():
                if isinstance(device, Tydom):
                    return device.device_id
        if hasattr(hub_instance, "ha_devices"):
            for _device_id, ha_device in hub_instance.ha_devices.items():
                if isinstance(ha_device, HATydom):
                    return ha_device._device.device_id
        return None

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
        }
        # Add name if available
        if hasattr(self._device, "device_name") and self._device.device_name:
            info["name"] = self._device.device_name
        elif hasattr(self._device, "productName") and self._device.productName:
            info["name"] = str(self._device.productName)
        else:
            info["name"] = f"Tydom Device {self._device.device_id[-6:]}"
        # Try to get manufacturer and model
        if hasattr(self._device, "manufacturer"):
            manufacturer = getattr(self._device, "manufacturer", None)
            if manufacturer is not None:
                info["manufacturer"] = str(manufacturer)
        if "manufacturer" not in info:
            info["manufacturer"] = "Delta Dore"
        if hasattr(self._device, "productName"):
            product_name = getattr(self._device, "productName", None)
            if product_name is not None:
                info["model"] = str(product_name)
        # Link to gateway if available
        gateway_device_id = self._get_tydom_gateway_device_id()
        if (
            gateway_device_id is not None
            and gateway_device_id != self._device.device_id
        ):
            info["via_device"] = (DOMAIN, gateway_device_id)
        return info

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

    _attr_has_entity_name = True

    def __init__(
        self,
        device: TydomDevice,
        device_class: BinarySensorDeviceClass | None,
        name: str,
        attribute: str,
    ):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{self._device.device_id}_{name}"
        self._attr_name = name
        self._attribute = attribute
        # Create entity description with translation key
        entity_description = BinarySensorEntityDescription(
            key=attribute,
            name=name,
            device_class=device_class,
            translation_key=f"binary_sensor_{attribute}" if attribute else None,
        )
        self.entity_description = entity_description
        self._attr_device_class = device_class

    def _get_hub(self):
        """Get the hub instance from hass data."""
        if not hasattr(self, "hass") or self.hass is None:
            return None
        if DOMAIN not in self.hass.data:
            return None
        hubs = self.hass.data[DOMAIN]
        if not hubs:
            return None
        return next(iter(hubs.values()))

    def _get_tydom_gateway_device_id(self) -> str | None:
        """Get the Tydom gateway device_id to use as via_device_id."""
        hub_instance = self._get_hub()
        if hub_instance is None:
            return None
        if hasattr(hub_instance, "devices"):
            for _device_id, device in hub_instance.devices.items():
                if isinstance(device, Tydom):
                    return device.device_id
        if hasattr(hub_instance, "ha_devices"):
            for _device_id, ha_device in hub_instance.ha_devices.items():
                if isinstance(ha_device, HATydom):
                    return ha_device._device.device_id
        return None

    @property
    def available(self) -> bool:
        """Return True if hub is available."""
        if self._device is None:
            return False
        # Use the same availability logic as HAEntity
        if hasattr(self, "hass") and self.hass is not None:
            from .const import DOMAIN

            if DOMAIN in self.hass.data:
                hubs = self.hass.data[DOMAIN]
                if hubs:
                    hub = next(iter(hubs.values()))
                    if not getattr(hub, "online", False):
                        return False
                    # Check tydom_client connection
                    if hasattr(hub, "_tydom_client"):
                        tydom_client = hub._tydom_client
                        if hasattr(tydom_client, "_connection"):
                            connection = getattr(tydom_client, "_connection", None)
                            if connection is not None and hasattr(connection, "closed"):
                                if connection.closed:
                                    return False
        return True

    # The value of this sensor.
    @property
    def is_on(self):
        """Return the state of the sensor."""
        # Utiliser getattr avec une valeur par défaut pour éviter AttributeError
        return getattr(self._device, self._attribute, False)


class HATydom(UpdateEntity, HAEntity):
    """Representation of a Tydom Gateway."""

    _attr_title = "Tydom"

    _ha_device = None
    _attr_has_entity_name = False
    _attr_entity_category = None
    entity_description: str

    _attr_should_poll = False
    _attr_device_class: UpdateDeviceClass | None = None
    _attr_supported_features: UpdateEntityFeature | None = None
    _attr_icon = "mdi:update"

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
        self._device._ha_device = self  # type: ignore[assignment]
        self._attr_supported_features = UpdateEntityFeature.INSTALL
        self._attr_device_class = UpdateDeviceClass.FIRMWARE
        self._attr_unique_id = f"{self._device.device_id}"
        self._attr_name = self._device.device_name
        self._registered_sensors = []

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        device_info = self._get_device_info()
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name
            if hasattr(self._device, "device_name") and self._device.device_name
            else f"Tydom Gateway {self._device.device_id[-6:]}",
            "manufacturer": device_info["manufacturer"],
        }
        if (
            hasattr(self._device, "mainVersionSW")
            and self._device.mainVersionSW is not None
        ):
            info["sw_version"] = str(self._device.mainVersionSW)
        if "model" in device_info:
            info["model"] = device_info["model"]
        # Gateway doesn't need via_device (it's the root device)
        return info

    @property
    def installed_version(self) -> str | None:
        """Version currently in use."""
        if self._device is None:
            return None
        # return self._hub.current_firmware
        if hasattr(self._device, "mainVersionSW"):
            version = getattr(self._device, "mainVersionSW", None)
            return str(version) if version is not None else None
        else:
            return None

    @property
    def latest_version(self) -> str | None:
        """Latest version available for install."""
        if self._device is not None and hasattr(self._device, "mainVersionSW"):
            version = getattr(self._device, "mainVersionSW", None)
            if version is None:
                return None
            if hasattr(self._device, "updateAvailable") and getattr(
                self._device, "updateAvailable", False
            ):
                # If update is available, return current version as latest
                # (actual update version is not provided by the API)
                return str(version)
            return str(version)
        return None

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install an update."""
        await self._device.async_trigger_firmware_update()


class HAEnergy(SensorEntity, HAEntity):
    """Representation of an Energy sensor."""

    _attr_has_entity_name = True
    _attr_entity_category = None
    entity_description: str

    _attr_should_poll = False
    _attr_device_class: SensorDeviceClass | None = None
    _attr_supported_features: int | None = None
    _attr_icon = "mdi:lightning-bolt"

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
        # Total increasing for energy counters
        "energyIndexTi1": SensorStateClass.TOTAL_INCREASING,
        "energyTotIndexWatt": SensorStateClass.TOTAL_INCREASING,
        "energyIndexECSWatt": SensorStateClass.TOTAL_INCREASING,
        "energyIndexHeatWatt": SensorStateClass.TOTAL_INCREASING,
        "energyIndexHeatGas": SensorStateClass.TOTAL_INCREASING,
        "energyIndex": SensorStateClass.TOTAL_INCREASING,
        # Measurement for instant values
        "energyInstantTotElec": SensorStateClass.MEASUREMENT,
        "energyInstantTotElecP": SensorStateClass.MEASUREMENT,
        "energyInstantTi1P": SensorStateClass.MEASUREMENT,
        "energyInstantTi1I": SensorStateClass.MEASUREMENT,
        "outTemperature": SensorStateClass.MEASUREMENT,
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
        self._device._ha_device = self  # type: ignore[assignment]
        self._attr_unique_id = f"{self._device.device_id}_energy"
        self._attr_name = self._device.device_name
        self._registered_sensors = []

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        device_info = self._get_device_info()
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        if hasattr(self._device, "softVersion"):
            sw_version = getattr(self._device, "softVersion", None)
            if sw_version is not None:
                info["sw_version"] = str(sw_version)
        return self._enrich_device_info(info)


class HACover(CoverEntity, HAEntity):
    """Representation of a Cover."""

    _attr_should_poll = False
    _attr_supported_features: CoverEntityFeature = CoverEntityFeature(0)
    _attr_device_class = CoverDeviceClass.SHUTTER
    _attr_icon = "mdi:window-shutter"
    _attr_has_entity_name = True

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
        self._device._ha_device = self  # type: ignore[assignment]
        self._attr_unique_id = f"{self._device.device_id}_cover"
        self._attr_name = self._device.device_name
        self._registered_sensors = []
        if hasattr(device, "position"):
            self._attr_supported_features = (
                self._attr_supported_features
                | CoverEntityFeature.SET_POSITION
                | CoverEntityFeature.OPEN
                | CoverEntityFeature.CLOSE
                | CoverEntityFeature.STOP
            )
        if hasattr(device, "slope"):
            self._attr_supported_features = (
                self._attr_supported_features | CoverEntityFeature.SET_TILT_POSITION
                # | CoverEntityFeature.OPEN_TILT
                # | CoverEntityFeature.CLOSE_TILT
                # | CoverEntityFeature.STOP_TILT
            )

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        device_info = self._get_device_info()
        name = getattr(self, "name", None)
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": str(name) if name is not None else self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return self._enrich_device_info(info)

    @property
    def current_cover_position(self) -> int | None:
        """Return the current position of the cover."""
        if hasattr(self._device, "position"):
            return getattr(self._device, "position", None)
        return None

    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed, same as position 0."""
        if hasattr(self._device, "position"):
            position = getattr(self._device, "position", None)
            return position == 0 if position is not None else False
        return False

    @property
    def current_cover_tilt_position(self) -> int | None:
        """Return the current tilt position of the cover."""
        if hasattr(self._device, "slope"):
            return getattr(self._device, "slope", None)
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

    _attr_should_poll = False
    _attr_supported_features: int | None = None
    _attr_icon = "mdi:smoke-detector"
    _attr_has_entity_name = True

    sensor_classes = {"batt_defect": BinarySensorDeviceClass.PROBLEM}

    def __init__(self, device: TydomSmoke, hass) -> None:
        """Initialize TydomSmoke."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self  # type: ignore[assignment]
        self._attr_unique_id = f"{self._device.device_id}_smoke"
        self._attr_name = self._device.device_name
        self._state = False
        self._registered_sensors = []
        self._attr_device_class = BinarySensorDeviceClass.SMOKE

    @property
    def is_on(self) -> bool:
        """Return the state of the sensor."""
        if hasattr(self._device, "techSmokeDefect"):
            return bool(getattr(self._device, "techSmokeDefect", False))
        return False

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        device_info = self._get_device_info()
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return self._enrich_device_info(info)


class HaClimate(ClimateEntity, HAEntity):
    """A climate entity."""

    _attr_should_poll = False
    _attr_icon = "mdi:thermostat"
    _attr_has_entity_name = True

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

    state_classes = {
        "temperature": SensorStateClass.MEASUREMENT,
        "outTemperature": SensorStateClass.MEASUREMENT,
        "ambientTemperature": SensorStateClass.MEASUREMENT,
        "battLevel": SensorStateClass.MEASUREMENT,
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
        self._device._ha_device = self  # type: ignore[assignment]
        self._attr_unique_id = f"{self._device.device_id}_climate"
        self._attr_name = self._device.device_name
        self._enable_turn_on_off_backwards_compatibility = False

        self._attr_hvac_mode = HVACMode.OFF

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
            self._device._metadata is not None
            and "hvacMode" in self._device._metadata
            and "AUTO" in self._device._metadata["hvacMode"]["enum_values"]
        ):
            self.dict_modes_ha_to_dd[HVACMode.AUTO] = "AUTO"
        elif (
            self._device._metadata is not None
            and "hvacMode" in self._device._metadata
            and "ANTI_FROST" in self._device._metadata["hvacMode"]["enum_values"]
        ):
            self.dict_modes_ha_to_dd[HVACMode.AUTO] = "ANTI_FROST"
        else:
            self.dict_modes_ha_to_dd[HVACMode.AUTO] = "AUTO"

        if hasattr(self._device, "minSetpoint"):
            min_setpoint = getattr(self._device, "minSetpoint", None)
            if min_setpoint is not None:
                self._attr_min_temp = float(min_setpoint)

        if hasattr(self._device, "maxSetpoint"):
            max_setpoint = getattr(self._device, "maxSetpoint", None)
            if max_setpoint is not None:
                self._attr_max_temp = float(max_setpoint)

        self._attr_supported_features = (
            self._attr_supported_features
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TARGET_TEMPERATURE
        )

        if (
            self._device._metadata is not None
            and "thermicLevel" in self._device._metadata
            and (
                "NORMAL" in self._device._metadata["thermicLevel"]
                or "AUTO" in self._device._metadata["thermicLevel"]
            )
        ):
            self.dict_modes_ha_to_dd[HVACMode.HEAT] = "AUTO"

        # Initialize preset modes
        self._attr_preset_modes = []
        # Add presets based on available modes
        if (
            self._device._metadata is not None
            and "comfortMode" in self._device._metadata
            and "enum_values" in self._device._metadata["comfortMode"]
        ):
            for mode in self._device._metadata["comfortMode"]["enum_values"]:
                if mode not in ["HEATING", "COOLING", "STOP"]:
                    self._attr_preset_modes.append(mode)
        elif (
            self._device._metadata is not None
            and "thermicLevel" in self._device._metadata
            and "enum_values" in self._device._metadata["thermicLevel"]
        ):
            for mode in self._device._metadata["thermicLevel"]["enum_values"]:
                if mode not in ["STOP", "AUTO"]:
                    self._attr_preset_modes.append(mode)

        # Add common presets if available
        if not self._attr_preset_modes:
            # Default presets if none found in metadata
            if hasattr(self._device, "comfortMode") or hasattr(
                self._device, "thermicLevel"
            ):
                self._attr_preset_modes = ["NORMAL", "ECO", "COMFORT"]

        # Add PRESET_NONE if we have presets
        if self._attr_preset_modes:
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE

        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.HEAT,
            HVACMode.COOL,
            HVACMode.AUTO,
        ]

        if self._device._metadata is not None and (
            (
                "comfortMode" in self._device._metadata
                and "COOLING" in self._device._metadata["comfortMode"]["enum_values"]
            )
            or (
                "hvacMode" in self._device._metadata
                and "COOLING" in self._device._metadata["hvacMode"]["enum_values"]
            )
        ):
            self._attr_hvac_modes.append(HVACMode.COOL)

        if self._device._metadata is not None and (
            (
                "comfortMode" in self._device._metadata
                and "HEATING" in self._device._metadata["comfortMode"]["enum_values"]
            )
            or (
                "hvacMode" in self._device._metadata
                and "HEATING" in self._device._metadata["hvacMode"]["enum_values"]
            )
        ):
            self._attr_hvac_modes.append(HVACMode.HEAT)

        self._registered_sensors = []

        if (
            self._device._metadata is not None
            and "setpoint" in self._device._metadata
            and "min" in self._device._metadata["setpoint"]
        ):
            self._attr_min_temp = self._device._metadata["setpoint"]["min"]

        if (
            self._device._metadata is not None
            and "setpoint" in self._device._metadata
            and "max" in self._device._metadata["setpoint"]
        ):
            self._attr_max_temp = self._device._metadata["setpoint"]["max"]

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        device_info = self._get_device_info()
        infos: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            infos["model"] = device_info["model"]
        return self._enrich_device_info(infos)

    @property
    def temperature_unit(self) -> str:
        """Return the unit of temperature measurement for the system."""
        return UnitOfTemperature.CELSIUS

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the current operation (e.g. heat, cool, idle)."""
        mode_tydom = None
        source = None

        # Priorité au matériel récent (Logique PR)
        if hasattr(self._device, "authorization") and self._device.authorization is not None:
            mode_tydom = self._device.authorization
            source = "authorization"
        # Fallback pour les anciens matériels
        elif hasattr(self._device, "hvacMode") and self._device.hvacMode is not None:
            mode_tydom = self._device.hvacMode
            source = "hvacMode"
        elif hasattr(self._device, "thermicLevel") and self._device.thermicLevel is not None:
            mode_tydom = self._device.thermicLevel
            source = "thermicLevel"

        if mode_tydom:
            mode_ha = self.dict_modes_dd_to_ha.get(mode_tydom)
            if mode_ha:
                LOGGER.debug(
                    "hvac_mode found: Tydom='%s' (from %s) -> HA='%s'",
                    mode_tydom,
                    source,
                    mode_ha,
                )
                return mode_ha
            else:
                LOGGER.warning(
                    "Tydom mode '%s' (from %s) has no translation in HA dictionary.",
                    mode_tydom,
                    source,
                )
        else:
            LOGGER.debug("No valid Tydom hvac_mode attribute found. Returning OFF.")
            return HVACMode.OFF

        return None

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        if hasattr(self._device, "temperature"):
            temp = getattr(self._device, "temperature", None)
            if temp is not None:
                return float(temp)
        if hasattr(self._device, "ambientTemperature"):
            temp = getattr(self._device, "ambientTemperature", None)
            if temp is not None:
                return float(temp)
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature currently set to be reached."""
        # Priorité à l'attribut générique 'setpoint' (Logique PR - Nouveau matériel)
        if hasattr(self._device, "setpoint"):
            val = getattr(self._device, "setpoint", None)
            if val is not None:
                return float(val)

        # Fallback sur la logique complexe pour les anciens appareils (Logique Main)
        # qui séparent parfois heatSetpoint et coolSetpoint
        hvac_mode = getattr(self._device, "hvacMode", None)
        authorization = getattr(self._device, "authorization", None)

        if hvac_mode in ("HEATING", "NORMAL"):
            if hasattr(self._device, "heatSetpoint"):
                val = getattr(self._device, "heatSetpoint", None)
                if val is not None:
                    return float(val)
        elif hvac_mode == "COOLING":
            if hasattr(self._device, "coolSetpoint"):
                val = getattr(self._device, "coolSetpoint", None)
                if val is not None:
                    return float(val)

        if authorization == "HEATING":
            if hasattr(self._device, "heatSetpoint"):
                val = getattr(self._device, "heatSetpoint", None)
                if val is not None:
                    return float(val)
        elif authorization == "COOLING":
            if hasattr(self._device, "coolSetpoint"):
                val = getattr(self._device, "coolSetpoint", None)
                if val is not None:
                    return float(val)

        return None

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        # Logique pour le matériel récent (RE2020)
        if self._device.device_type == "re2020ControlBoiler":
            tydom_mode = "STOP" # Par défaut
            if hvac_mode == HVACMode.HEAT:
                tydom_mode = "HEATING"
            elif hvac_mode == HVACMode.COOL:
                tydom_mode = "COOLING"
            await self._device.set_area_data("authorization", tydom_mode)

        # Logique existante pour les anciens matériels
        else:
            await self._device.set_hvac_mode(self.dict_modes_ha_to_dd.get(hvac_mode))

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        if hasattr(self._device, "comfortMode"):
            comfort_mode = getattr(self._device, "comfortMode", None)
            if comfort_mode is not None and comfort_mode in self._attr_preset_modes:
                return comfort_mode
        if hasattr(self._device, "thermicLevel"):
            thermic_level = getattr(self._device, "thermicLevel", None)
            if thermic_level is not None and thermic_level in self._attr_preset_modes:
                return thermic_level
        return PRESET_NONE if self._attr_preset_modes else None

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new target preset mode."""
        if preset_mode == PRESET_NONE:
            return
        # Try to set comfortMode first
        if (
            self._device._metadata is not None
            and "comfortMode" in self._device._metadata
            and preset_mode
            in self._device._metadata["comfortMode"].get("enum_values", [])
        ):
            await self._device._tydom_client.put_devices_data(
                self._device._id, self._device._endpoint, "comfortMode", preset_mode
            )
        # Otherwise try thermicLevel
        elif (
            self._device._metadata is not None
            and "thermicLevel" in self._device._metadata
            and preset_mode
            in self._device._metadata["thermicLevel"].get("enum_values", [])
        ):
            await self._device._tydom_client.put_devices_data(
                self._device._id, self._device._endpoint, "thermicLevel", preset_mode
            )

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is not None:
            # Logique pour le matériel récent (RE2020)
            if self._device.device_type == "re2020ControlBoiler":
                await self._device.set_area_data("setpoint", str(temperature))

            # Logique existante pour les anciens matériels
            else:
                await self._device.set_temperature(str(temperature))

class HaWindow(CoverEntity, HAEntity):
    """Representation of a Window."""

    _attr_should_poll = False
    _attr_supported_features: CoverEntityFeature | None = None
    _attr_device_class = CoverDeviceClass.WINDOW
    _attr_icon = "mdi:window-open"
    _attr_has_entity_name = True

    sensor_classes = {
        "battDefect": BinarySensorDeviceClass.PROBLEM,
        "intrusionDetect": BinarySensorDeviceClass.PROBLEM,
    }

    def __init__(self, device: TydomWindow, hass) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self  # type: ignore[assignment]
        self._attr_unique_id = f"{self._device.device_id}_cover"
        self._attr_name = self._device.device_name
        self._registered_sensors = []

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        device_info = self._get_device_info()
        name = getattr(self, "name", None)
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": str(name) if name is not None else self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return self._enrich_device_info(info)

    @property
    def is_closed(self) -> bool:
        """Return if the window is closed."""
        if hasattr(self._device, "openState"):
            open_state = getattr(self._device, "openState", None)
            return open_state == "LOCKED"
        elif hasattr(self._device, "intrusionDetect"):
            intrusion_detect = getattr(self._device, "intrusionDetect", False)
            return not bool(intrusion_detect)
        else:
            LOGGER.error("Unknown state for device %s", self._device.device_id)
            return True


class HaDoor(CoverEntity, HAEntity):
    """Representation of a Door."""

    _attr_should_poll = False
    _attr_supported_features: CoverEntityFeature | None = None
    _attr_device_class = CoverDeviceClass.DOOR
    _attr_icon = "mdi:door"
    _attr_has_entity_name = True
    sensor_classes = {
        "battDefect": BinarySensorDeviceClass.PROBLEM,
        "calibrationDefect": BinarySensorDeviceClass.PROBLEM,
        "intrusionDetect": BinarySensorDeviceClass.PROBLEM,
    }

    def __init__(self, device: TydomDoor, hass) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self  # type: ignore[assignment]
        self._attr_unique_id = f"{self._device.device_id}_cover"
        self._attr_name = self._device.device_name
        self._registered_sensors = []

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        device_info = self._get_device_info()
        name = getattr(self, "name", None)
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": str(name) if name is not None else self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return self._enrich_device_info(info)

    @property
    def is_closed(self) -> bool:
        """Return if the door is locked."""
        if hasattr(self._device, "openState"):
            open_state = getattr(self._device, "openState", None)
            return open_state == "LOCKED"
        elif hasattr(self._device, "intrusionDetect"):
            intrusion_detect = getattr(self._device, "intrusionDetect", False)
            return not bool(intrusion_detect)
        else:
            raise AttributeError(
                "The required attributes 'openState' or 'intrusionDetect' are not available in the device."
            )


class HaGate(CoverEntity, HAEntity):
    """Representation of a Gate."""

    _attr_should_poll = False
    _attr_supported_features: CoverEntityFeature = CoverEntityFeature.OPEN
    _attr_device_class = CoverDeviceClass.GATE
    _attr_icon = "mdi:gate"
    _attr_has_entity_name = True
    sensor_classes = {}

    def __init__(self, device: TydomGate, hass) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self  # type: ignore[assignment]
        self._attr_unique_id = f"{self._device.device_id}_cover"
        self._attr_name = self._device.device_name
        self._registered_sensors = []
        if (
            self._device._metadata is not None
            and "levelCmd" in self._device._metadata
            and "OFF" in self._device._metadata["levelCmd"]["enum_values"]
        ):
            self._attr_supported_features = (
                self._attr_supported_features | CoverEntityFeature.CLOSE
            )

        if (
            self._device._metadata is not None
            and "levelCmd" in self._device._metadata
            and "STOP" in self._device._metadata["levelCmd"]["enum_values"]
        ):
            self._attr_supported_features = (
                self._attr_supported_features | CoverEntityFeature.STOP
            )

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        device_info = self._get_device_info()
        name = getattr(self, "name", None)
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": str(name) if name is not None else self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return info

    @property
    def is_closed(self) -> bool | None:
        """Return if the window is closed."""
        if hasattr(self._device, "openState"):
            open_state = getattr(self._device, "openState", None)
            return open_state == "LOCKED"
        else:
            LOGGER.warning(
                "no attribute 'openState' for device %s", self._device.device_id
            )
            return None

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the gate."""
        if (
            self._device._metadata is not None
            and "levelCmd" in self._device._metadata
            and "ON" in self._device._metadata["levelCmd"]["enum_values"]
        ):
            await self._device.open()
        else:
            await self._device.toggle()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Open the gate."""
        if (
            self._device._metadata is not None
            and "levelCmd" in self._device._metadata
            and "OFF" in self._device._metadata["levelCmd"]["enum_values"]
        ):
            await self._device.close()
        else:
            await self._device.toggle()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Open the gate."""
        if (
            self._device._metadata is not None
            and "levelCmd" in self._device._metadata
            and "STOP" in self._device._metadata["levelCmd"]["enum_values"]
        ):
            await self._device.stop()
        else:
            await self._device.toggle()


class HaGarage(CoverEntity, HAEntity):
    """Representation of a Garage door."""

    _attr_should_poll = False
    _attr_supported_features: CoverEntityFeature = CoverEntityFeature.OPEN
    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_icon = "mdi:garage"
    _attr_has_entity_name = True
    sensor_classes = {
        "thermic_defect": BinarySensorDeviceClass.PROBLEM,
    }

    def __init__(self, device: TydomGarage, hass) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self  # type: ignore[assignment]
        self._attr_unique_id = f"{self._device.device_id}_cover"
        self._attr_name = self._device.device_name
        self._registered_sensors = []
        if (
            self._device._metadata is not None
            and "levelCmd" in self._device._metadata
            and "OFF" in self._device._metadata["levelCmd"]["enum_values"]
        ):
            self._attr_supported_features = (
                self._attr_supported_features | CoverEntityFeature.CLOSE
            )

        if (
            self._device._metadata is not None
            and "levelCmd" in self._device._metadata
            and "STOP" in self._device._metadata["levelCmd"]["enum_values"]
        ):
            self._attr_supported_features = (
                self._attr_supported_features | CoverEntityFeature.STOP
            )

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        device_info = self._get_device_info()
        name = getattr(self, "name", None)
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": str(name) if name is not None else self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return info

    @property
    def is_closed(self) -> bool | None:
        """Return if the garage door is closed."""
        if hasattr(self._device, "level"):
            level = getattr(self._device, "level", None)
            return level == 0 if level is not None else None
        else:
            return None

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        if (
            self._device._metadata is not None
            and "levelCmd" in self._device._metadata
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

    _attr_should_poll = False
    _attr_icon = "mdi:lightbulb"
    _attr_has_entity_name = True
    sensor_classes = {
        "thermic_defect": BinarySensorDeviceClass.PROBLEM,
    }
    _attr_color_mode: ColorMode | str | None = None
    _attr_supported_color_modes: set[ColorMode] | set[str] | None = None

    BRIGHTNESS_SCALE = (0, 255)

    def __init__(self, device: TydomLight, hass) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self  # type: ignore[assignment]
        self._attr_unique_id = f"{self._device.device_id}_light"
        self._attr_name = self._device.device_name
        self._registered_sensors = []
        if self._device._metadata is not None and "level" in self._device._metadata:
            self._attr_color_mode = ColorMode.BRIGHTNESS
            if self._attr_supported_color_modes is None:
                self._attr_supported_color_modes = set()
            self._attr_supported_color_modes.add(ColorMode.BRIGHTNESS)
        else:
            self._attr_color_mode = ColorMode.ONOFF
            if self._attr_supported_color_modes is None:
                self._attr_supported_color_modes = set()
            self._attr_supported_color_modes.add(ColorMode.ONOFF)

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        device_info = self._get_device_info()
        name = getattr(self, "name", None)
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": str(name) if name is not None else self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return info

    @property
    def brightness(self) -> int | None:
        """Return the current brightness."""
        if hasattr(self._device, "level"):
            level = getattr(self._device, "level", None)
            if level is not None:
                return int(
                    percentage_to_ranged_value(self.BRIGHTNESS_SCALE, float(level))
                )
        return None

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        if hasattr(self._device, "level"):
            level = getattr(self._device, "level", None)
            return bool(level != 0 if level is not None else False)
        return False

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

    _attr_should_poll = False
    _attr_supported_features = AlarmControlPanelEntityFeature(0)
    _attr_icon = "mdi:shield-home"
    _attr_has_entity_name = True
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
        self._device._ha_device = self  # type: ignore[assignment]
        self._attr_unique_id = f"{self._device.device_id}_alarm"
        self._attr_name = self._device.device_name
        self._attr_code_format = CodeFormat.NUMBER
        self._attr_code_arm_required = True
        self._registered_sensors = []

        self._attr_supported_features = (
            self._attr_supported_features
            | AlarmControlPanelEntityFeature.ARM_AWAY
            | AlarmControlPanelEntityFeature.ARM_HOME
            | AlarmControlPanelEntityFeature.ARM_NIGHT
            | AlarmControlPanelEntityFeature.TRIGGER
        )

    @property
    def alarm_state(self) -> AlarmControlPanelState:
        """Return the alarm state."""
        # alarmMode :  "OFF", "ON", "TEST", "ZONE", "MAINTENANCE"
        # alarmState: "OFF", "DELAYED", "ON", "QUIET"
        if hasattr(self._device, "alarmMode"):
            alarm_mode = getattr(self._device, "alarmMode", None)
            if alarm_mode == "MAINTENANCE":
                return AlarmControlPanelState.DISARMED

            if alarm_mode == "OFF":
                return AlarmControlPanelState.DISARMED
            if alarm_mode == "ON":
                alarm_state = getattr(self._device, "alarmState", None)
                if alarm_state == "OFF":
                    return AlarmControlPanelState.ARMED_AWAY
                else:
                    return AlarmControlPanelState.TRIGGERED
            if alarm_mode in ("ZONE", "PART"):
                alarm_state = getattr(self._device, "alarmState", None)
                if alarm_state == "OFF":
                    return AlarmControlPanelState.ARMED_HOME
                else:
                    return AlarmControlPanelState.TRIGGERED
        return AlarmControlPanelState.TRIGGERED

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        device_info = self._get_device_info()
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return info

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
    _attr_icon = "mdi:weather-partly-cloudy"
    _attr_has_entity_name = True

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
        self._device._ha_device = self  # type: ignore[assignment]
        self._attr_unique_id = f"{self._device.device_id}_weather"
        self._attr_name = self._device.device_name
        self._registered_sensors = []
        if (
            self._device._metadata is not None
            and "dailyPower" in self._device._metadata
            and "unit" in self._device._metadata["dailyPower"]
        ):
            self.units["dailyPower"] = self._device._metadata["dailyPower"]["unit"]
        if (
            self._device._metadata is not None
            and "currentPower" in self._device._metadata
            and "unit" in self._device._metadata["currentPower"]
        ):
            self.units["currentPower"] = self._device._metadata["currentPower"]["unit"]

    @property
    def native_temperature(self) -> float | None:
        """Return current temperature in C."""
        if hasattr(self._device, "outTemperature"):
            temp = getattr(self._device, "outTemperature", None)
            if temp is not None:
                return float(temp)
        return None

    @property
    def condition(self) -> str | None:
        """Return current weather condition."""
        if hasattr(self._device, "weather"):
            weather = getattr(self._device, "weather", None)
            if weather is not None and weather in self.tydom_ha_condition:
                return self.tydom_ha_condition[weather]
        return None

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        device_info = self._get_device_info()
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return info


class HaMoisture(BinarySensorEntity, HAEntity):
    """Representation of an leak detector sensor."""

    _attr_should_poll = False
    _attr_supported_features: int | None = None
    _attr_icon = "mdi:water"
    _attr_has_entity_name = True

    sensor_classes = {"batt_defect": BinarySensorDeviceClass.PROBLEM}

    def __init__(self, device: TydomWater, hass) -> None:
        """Initialize TydomSmoke."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self  # type: ignore[assignment]
        self._attr_unique_id = f"{self._device.device_id}_moisture"
        self._attr_name = self._device.device_name
        self._state = False
        self._registered_sensors = []
        self._attr_device_class = BinarySensorDeviceClass.MOISTURE

    @property
    def is_on(self) -> bool:
        """Return the state of the sensor."""
        if hasattr(self._device, "techWaterDefect"):
            return bool(getattr(self._device, "techWaterDefect", False))
        return False

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        device_info = self._get_device_info()
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return info


class HaThermo(SensorEntity, HAEntity):
    """Representation of a thermometer."""

    _attr_icon = "mdi:thermometer"
    _attr_has_entity_name = True

    def __init__(self, device: TydomThermo, hass) -> None:
        """Initialize TydomSmoke."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self  # type: ignore[assignment]
        self._attr_unique_id = f"{self._device.device_id}_thermos"
        self._attr_name = self._device.device_name
        self._state = False
        self._registered_sensors = ["outTemperature"]
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def state(self) -> float | None:
        """Return the state of the sensor."""
        if hasattr(self._device, "outTemperature"):
            temp = getattr(self._device, "outTemperature", None)
            if temp is not None:
                return float(temp)
        return None

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        device_info = self._get_device_info()
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return info


class HASensor(SensorEntity, HAEntity):
    """Representation of a generic sensor for unknown device types."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, device: TydomDevice, hass) -> None:
        """Initialize HASensor."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self  # type: ignore[assignment]
        self._attr_unique_id = f"{self._device.device_id}_sensor"
        self._attr_name = self._device.device_name
        self._registered_sensors = []

    @property
    def native_value(self):
        """Return the native value of the sensor."""
        # Try to get a meaningful value from the device
        # Look for common attributes
        for attr in ["level", "position", "temperature", "value", "state"]:
            if hasattr(self._device, attr):
                return getattr(self._device, attr)
        # If no value found, return None (unknown state)
        return None

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        device_info = self._get_device_info()
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return info


class HAScene(Scene, HAEntity):
    """Representation of a Tydom Scene."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    # Filtrer les attributs bruts pour ne garder que les versions formatées
    filtered_attrs = ["grpAct", "epAct", "scene_id", "type", "picto", "rule_id"]

    # Mapping des pictos Tydom vers les icônes Material Design
    PICTO_ICON_MAPPING = {
        "light": "mdi:lightbulb",
        "lights": "mdi:lightbulb-group",
        "shutter": "mdi:window-shutter",
        "shutters": "mdi:window-shutter",
        "heating": "mdi:radiator",
        "thermostat": "mdi:thermostat",
        "alarm": "mdi:shield-home",
        "alarm_off": "mdi:shield-off",
        "alarm_on": "mdi:shield",
        "door": "mdi:door",
        "window": "mdi:window-open",
        "garage": "mdi:garage",
        "gate": "mdi:gate",
        "scene": "mdi:palette",
        "scenario": "mdi:palette",
        "home": "mdi:home",
        "away": "mdi:home-export",
        "night": "mdi:weather-night",
        "day": "mdi:weather-sunny",
        "comfort": "mdi:sofa",
        "eco": "mdi:leaf",
        "vacation": "mdi:airplane",
    }

    def __init__(self, device: TydomScene, hass) -> None:
        """Initialize HAScene."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self  # type: ignore[assignment]
        self._attr_unique_id = f"{self._device.device_id}_scene"
        self._attr_name = self._device.device_name

    @property
    def icon(self) -> str:
        """Return the icon for the scene based on picto."""
        picto = getattr(self._device, "picto", None)
        if not picto:
            return "mdi:palette"

        # Si le picto est déjà au format mdi:*, l'utiliser directement
        if isinstance(picto, str) and picto.startswith("mdi:"):
            return picto

        # Convertir en minuscules pour la recherche
        picto_lower = picto.lower().strip()

        # Chercher dans le mapping
        if picto_lower in self.PICTO_ICON_MAPPING:
            return self.PICTO_ICON_MAPPING[picto_lower]

        # Fallback vers l'icône par défaut
        return "mdi:palette"

    def _format_affected_items(
        self, items: list[dict] | None, item_type: str = "group"
    ) -> str:
        """Format grpAct or epAct into a readable string."""
        if not items or not isinstance(items, list):
            return ""

        formatted_items = []
        for item in items:
            if not isinstance(item, dict):
                continue

            item_id = None
            if item_type == "group":
                item_id = item.get("id")
            elif item_type == "endpoint":
                # Pour epAct, on peut avoir devId ou epId
                item_id = item.get("epId") or item.get("devId")

            if item_id is not None:
                # Essayer de résoudre le nom depuis device_name
                # Pour les groupes, l'ID peut être directement dans device_name
                # Pour les endpoints, c'est généralement "epId_deviceId"
                name = None
                if str(item_id) in device_name:
                    name = device_name[str(item_id)]
                else:
                    # Pour les endpoints, essayer avec le format "epId_deviceId"
                    if item_type == "endpoint":
                        dev_id = item.get("devId")
                        if dev_id:
                            unique_id = f"{item_id}_{dev_id}"
                            if unique_id in device_name:
                                name = device_name[unique_id]
                            # Si pas trouvé, essayer juste avec epId
                            elif str(item_id) in device_name:
                                name = device_name[str(item_id)]

                if name:
                    # Ajouter les informations d'état si disponibles
                    state_info = item.get("state", [])
                    if state_info and isinstance(state_info, list):
                        state_parts = []
                        for state_item in state_info:
                            if isinstance(state_item, dict):
                                state_name = state_item.get("name", "")
                                state_value = state_item.get("value", "")
                                if state_name and state_value:
                                    state_parts.append(f"{state_name}={state_value}")
                        if state_parts:
                            formatted_items.append(f"{name} ({', '.join(state_parts)})")
                        else:
                            formatted_items.append(name)
                    else:
                        formatted_items.append(name)
                else:
                    # Fallback : utiliser l'ID avec les infos d'état
                    state_info = item.get("state", [])
                    if state_info and isinstance(state_info, list):
                        state_parts = []
                        for state_item in state_info:
                            if isinstance(state_item, dict):
                                state_name = state_item.get("name", "")
                                state_value = state_item.get("value", "")
                                if state_name and state_value:
                                    state_parts.append(f"{state_name}={state_value}")
                        if state_parts:
                            formatted_items.append(
                                f"{item_type.capitalize()} {item_id} ({', '.join(state_parts)})"
                            )
                        else:
                            formatted_items.append(
                                f"{item_type.capitalize()} {item_id}"
                            )
                    else:
                        formatted_items.append(f"{item_type.capitalize()} {item_id}")

        return ", ".join(formatted_items) if formatted_items else ""

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes for the scene."""
        attrs: dict[str, Any] = {}

        # Scenario ID
        scenario_id = getattr(self._device, "scene_id", None) or getattr(
            self._device, "_id", None
        )
        if scenario_id is not None:
            attrs["scenario_id"] = str(scenario_id)

        # Scenario type
        scenario_type = getattr(self._device, "type", None)
        if scenario_type:
            attrs["scenario_type"] = scenario_type

        # Picto
        picto = getattr(self._device, "picto", None)
        if picto:
            attrs["picto"] = picto

        # Rule ID
        rule_id = getattr(self._device, "rule_id", None)
        if rule_id:
            attrs["rule_id"] = str(rule_id)

        # Affected groups (grpAct)
        grp_act = getattr(self._device, "grpAct", None)
        if grp_act:
            affected_groups = self._format_affected_items(grp_act, "group")
            if affected_groups:
                attrs["affected_groups"] = affected_groups

        # Affected endpoints (epAct)
        ep_act = getattr(self._device, "epAct", None)
        if ep_act:
            affected_endpoints = self._format_affected_items(ep_act, "endpoint")
            if affected_endpoints:
                attrs["affected_endpoints"] = affected_endpoints

        return attrs

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        device_info = self._get_device_info()
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return self._enrich_device_info(info)

    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the scene."""
        await self._device.activate()


class HASwitch(SwitchEntity, HAEntity):
    """Representation of a Tydom Switch."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:toggle-switch"

    def __init__(self, device: TydomDevice, hass) -> None:
        """Initialize HASwitch."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self  # type: ignore[assignment]
        self._attr_unique_id = f"{self._device.device_id}_switch"
        self._attr_name = self._device.device_name

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        device_info = self._get_device_info()
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return self._enrich_device_info(info)

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        # Check for common on/off attributes
        if hasattr(self._device, "level"):
            level = getattr(self._device, "level", None)
            return bool(level != 0 if level is not None else False)
        if hasattr(self._device, "on"):
            return bool(getattr(self._device, "on", False))
        if hasattr(self._device, "state"):
            state = getattr(self._device, "state", None)
            return state == "ON" if state is not None else False
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        if hasattr(self._device, "turn_on"):
            await self._device.turn_on()
        elif hasattr(self._device, "set_level"):
            await self._device.set_level(100)
        else:
            # Generic approach: try to set level to 100 or on to true
            if hasattr(self._device, "level"):
                await self._device._tydom_client.put_devices_data(
                    self._device._id, self._device._endpoint, "level", "100"
                )
            elif hasattr(self._device, "on"):
                await self._device._tydom_client.put_devices_data(
                    self._device._id, self._device._endpoint, "on", "true"
                )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        if hasattr(self._device, "turn_off"):
            await self._device.turn_off()
        elif hasattr(self._device, "set_level"):
            await self._device.set_level(0)
        else:
            # Generic approach: try to set level to 0 or on to false
            if hasattr(self._device, "level"):
                await self._device._tydom_client.put_devices_data(
                    self._device._id, self._device._endpoint, "level", "0"
                )
            elif hasattr(self._device, "on"):
                await self._device._tydom_client.put_devices_data(
                    self._device._id, self._device._endpoint, "on", "false"
                )


class HAButton(ButtonEntity, HAEntity):
    """Representation of a Tydom Button."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:button-cursor"

    def __init__(
        self, device: TydomDevice, hass, action_name: str, action_method: str
    ) -> None:
        """Initialize HAButton."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self  # type: ignore[assignment]
        self._action_name = action_name
        self._action_method = action_method
        self._attr_unique_id = f"{self._device.device_id}_button_{action_name}"
        self._attr_name = f"{action_name}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        device_info = self._get_device_info()
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return self._enrich_device_info(info)

    async def async_press(self) -> None:
        """Handle the button press."""
        # Execute the action method on the device
        if hasattr(self._device, self._action_method):
            method = getattr(self._device, self._action_method)
            if callable(method):
                if inspect.iscoroutinefunction(method):
                    await method()
                else:
                    method()
        else:
            # Generic approach: send a command
            await self._device._tydom_client.put_devices_data(
                self._device._id, self._device._endpoint, self._action_method, "ON"
            )


class HANumber(NumberEntity, HAEntity):
    """Representation of a Tydom Number."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        device: TydomDevice,
        hass,
        attribute_name: str,
        min_value: float | None = None,
        max_value: float | None = None,
        step: float | None = None,
        unit: str | None = None,
    ) -> None:
        """Initialize HANumber."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self  # type: ignore[assignment]
        self._attribute_name = attribute_name
        self._attr_unique_id = f"{self._device.device_id}_number_{attribute_name}"
        self._attr_name = attribute_name
        if min_value is not None:
            self._attr_native_min_value = min_value
        if max_value is not None:
            self._attr_native_max_value = max_value
        self._attr_native_step = step or 1.0
        self._attr_native_unit_of_measurement = unit

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        device_info = self._get_device_info()
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return self._enrich_device_info(info)

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        value = getattr(self._device, self._attribute_name, None)
        if value is not None:
            try:
                return float(value)
            except (ValueError, TypeError):
                return None
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        await self._device._tydom_client.put_devices_data(
            self._device._id, self._device._endpoint, self._attribute_name, str(value)
        )


class HASelect(SelectEntity, HAEntity):
    """Representation of a Tydom Select."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        device: TydomDevice,
        hass,
        attribute_name: str,
        options: list[str],
    ) -> None:
        """Initialize HASelect."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self  # type: ignore[assignment]
        self._attribute_name = attribute_name
        self._attr_unique_id = f"{self._device.device_id}_select_{attribute_name}"
        self._attr_name = attribute_name
        self._attr_options = options

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        device_info = self._get_device_info()
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return self._enrich_device_info(info)

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        value = getattr(self._device, self._attribute_name, None)
        if value is not None and str(value) in self._attr_options:
            return str(value)
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await self._device._tydom_client.put_devices_data(
            self._device._id, self._device._endpoint, self._attribute_name, option
        )


class HAEvent(EventEntity, HAEntity):
    """Representation of a Tydom Event."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, device: TydomDevice, hass, event_type: str) -> None:
        """Initialize HAEvent."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self  # type: ignore[assignment]
        self._event_type = event_type
        self._attr_unique_id = f"{self._device.device_id}_event_{event_type}"
        self._attr_name = event_type
        self._attr_event_types = [event_type]

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        device_info = self._get_device_info()
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": device_info["manufacturer"],
        }
        if "model" in device_info:
            info["model"] = device_info["model"]
        return self._enrich_device_info(info)
