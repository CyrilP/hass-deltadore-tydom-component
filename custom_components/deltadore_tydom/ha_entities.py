"""Home assistant entites."""

from typing import Any
import asyncio
import inspect
import math
from datetime import datetime

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
from homeassistant.helpers import device_registry as dr
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
from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
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
    TydomGroup,
    TydomMoment,
)

from .const import DOMAIN, LOGGER, TYDOM_UNIT_TO_HA_UNIT
from .tydom.MessageHandler import device_name, groups_data


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
        """Enrich device info with via_device link to gateway.

        Note: If area information becomes available from Tydom API
        (via /areas/data endpoint), we could add 'suggested_area' to DeviceInfo
        to automatically suggest areas for devices. This would improve
        device organization in Home Assistant's Area Registry.
        See: https://developers.home-assistant.io/docs/area_registry_index
        """
        gateway_device_id = self._get_tydom_gateway_device_id()
        if gateway_device_id is not None and self._device is not None:
            if gateway_device_id != self._device.device_id:
                info["via_device"] = (DOMAIN, gateway_device_id)
        return info

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA.

        This lifecycle method is only called if the entity is actually added to
        Home Assistant (i.e., not disabled). This is the correct place to register
        entity references and callbacks, as per Home Assistant best practices.

        References should NOT be registered in __init__ because disabled entities
        will not have async_added_to_hass called, preventing proper cleanup.
        """
        if self._device is not None:
            # Register callback for state updates
            self._device.register_callback(self.async_write_ha_state)  # type: ignore[attr-defined]
            # Register entity reference (only if entity is actually added)
            self._device._ha_device = self

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass.

        Clean up entity references and callbacks when the entity is removed.
        This ensures proper cleanup even if the entity was disabled.
        """
        if self._device is not None:
            # Remove callback
            self._device.remove_callback(self.async_write_ha_state)  # type: ignore[attr-defined]
            # Clear entity reference if it points to this entity
            if hasattr(self._device, "_ha_device") and self._device._ha_device is self:
                self._device._ha_device = None

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
        """Initialize the sensor.

        The unique_id is constructed from device_id (which is based on endpoint_id + device_id
        from the Tydom API, providing a stable unique identifier) combined with the sensor name.
        This follows Home Assistant Entity Registry best practices:
        - Does not include domain or platform type (added automatically by HA)
        - Uses stable identifiers from the device API
        - Combines base unique_id with entity-specific identifier for multi-entity devices
        """
        self._device = device
        # unique_id format: {device_id}_{entity_name}
        # device_id is stable and unique (endpoint_id + "_" + device_id from Tydom API)
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

        # Handle complex values (lists, dicts) that exceed Home Assistant's 255 char limit
        if value is not None:
            # Check if value is a list or dict
            if isinstance(value, (list, dict)):
                # Convert to string to check length
                value_str = str(value)
                if len(value_str) > 255:
                    # For protocols list, return a summary
                    if self._attribute == "protocols" and isinstance(value, list):
                        # Return count of protocols
                        return len(value)
                    # For other complex types, return None to avoid state truncation
                    # The data will still be available in extra_state_attributes if needed
                    return None

        return value

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the native unit of measurement.

        Uses unit from metadata if available, otherwise falls back to
        the unit set during initialization.
        """
        # First try to get unit from metadata
        if (
            self._device._metadata is not None
            and self._attribute in self._device._metadata
        ):
            metadata = self._device._metadata[self._attribute]
            if "unit" in metadata:
                tydom_unit = metadata["unit"]
                # Map Tydom unit to Home Assistant unit
                ha_unit = TYDOM_UNIT_TO_HA_UNIT.get(tydom_unit, tydom_unit)
                if ha_unit:
                    return ha_unit

        # Fall back to the unit set during initialization
        return self._attr_native_unit_of_measurement

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
        # Avoid using generic names like "Produit 1" from productName
        generic_names = [
            "produit 1",
            "produit",
            "product 1",
            "product",
            "device",
            "appareil",
        ]

        if hasattr(self._device, "device_name") and self._device.device_name:
            info["name"] = self._device.device_name
        elif "model" in device_info_dict:
            model_name = device_info_dict["model"]
            # Check if model name is generic - if so, use device ID instead
            if model_name and model_name.lower().strip() not in generic_names:
                info["name"] = model_name
            else:
                # Use device ID for generic names
                info["name"] = f"Tydom Device {self._device.device_id[-6:]}"
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
        """Run when this Entity has been added to HA.

        This lifecycle method is only called if the entity is actually added to
        Home Assistant (i.e., not disabled). Register callbacks and entity
        references here, not in __init__.
        """
        # Sensors should also register callbacks to HA when their state changes
        self._device.register_callback(self.async_write_ha_state)
        # Register entity reference (only if entity is actually added)
        if self._device is not None:
            self._device._ha_device = self

    async def async_will_remove_from_hass(self):
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._device.remove_callback(self.async_write_ha_state)
        # Clear entity reference if it points to this entity
        if (
            self._device is not None
            and hasattr(self._device, "_ha_device")
            and self._device._ha_device is self
        ):
            self._device._ha_device = None


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
        # Avoid using generic names like "Produit 1" from productName
        generic_names = [
            "produit 1",
            "produit",
            "product 1",
            "product",
            "device",
            "appareil",
        ]

        if hasattr(self._device, "device_name") and self._device.device_name:
            info["name"] = self._device.device_name
        elif hasattr(self._device, "productName"):
            product_name = getattr(self._device, "productName", None)
            if product_name is not None:
                product_str = str(product_name)
                # Check if product name is generic - if so, use device ID instead
                if product_str.lower().strip() not in generic_names:
                    info["name"] = product_str
                else:
                    # Use device ID for generic names
                    info["name"] = f"Tydom Device {self._device.device_id[-6:]}"
            else:
                info["name"] = f"Tydom Device {self._device.device_id[-6:]}"
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
        """Run when this Entity has been added to HA.

        This lifecycle method is only called if the entity is actually added to
        Home Assistant (i.e., not disabled). Register callbacks and entity
        references here, not in __init__.
        """
        # Sensors should also register callbacks to HA when their state changes
        self._device.register_callback(self.async_write_ha_state)
        # Register entity reference (only if entity is actually added)
        if self._device is not None:
            self._device._ha_device = self

    async def async_will_remove_from_hass(self):
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._device.remove_callback(self.async_write_ha_state)
        # Clear entity reference if it points to this entity
        if (
            self._device is not None
            and hasattr(self._device, "_ha_device")
            and self._device._ha_device is self
        ):
            self._device._ha_device = None


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
        # Set entity category for diagnostic/problem sensors
        if device_class in (
            BinarySensorDeviceClass.PROBLEM,
            BinarySensorDeviceClass.UPDATE,
        ):
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


class ClockSensor(SensorEntity):
    """Sensor for clock/timezone data from Tydom gateway."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        device: Tydom,
        attribute: str,
        hass: Any,
    ):
        """Initialize clock sensor.

        Args:
            device: Tydom gateway device
            attribute: Attribute name (clock, source, timezone, summerOffset)
            hass: Home Assistant instance

        """
        self.hass = hass
        self._device = device
        self._attribute = attribute
        self._attr_unique_id = f"{self._device.device_id}_clock_{attribute}"

        # Set appropriate name and device class
        if attribute == "clock":
            self._attr_name = "Gateway Time"
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        elif attribute == "source":
            self._attr_name = "Clock Source"
        elif attribute == "timezone":
            self._attr_name = "Timezone"
        elif attribute == "summerOffset":
            self._attr_name = "Summer Offset"
        else:
            self._attr_name = attribute.title()

        # Create entity description
        entity_description = SensorEntityDescription(
            key=f"clock_{attribute}",
            name=self._attr_name,
            device_class=self._attr_device_class if attribute == "clock" else None,
            translation_key=f"clock_{attribute}",
        )
        self.entity_description = entity_description

    @property
    def native_value(self) -> datetime | str | int | None:
        """Return the clock value."""
        clock = getattr(self._device, "clock", None)
        if clock is not None and isinstance(clock, dict):
            value = clock.get(self._attribute)
            if value is not None:
                if self._attribute == "clock":
                    # Return datetime object for TIMESTAMP device class
                    try:
                        # Try to parse the value as ISO format datetime
                        if isinstance(value, str):
                            # Parse ISO format string (e.g., "2025-12-06T01:27:43+01:00")
                            # Try datetime.fromisoformat first (Python 3.7+)
                            try:
                                return datetime.fromisoformat(
                                    value.replace("Z", "+00:00")
                                )
                            except (ValueError, AttributeError):
                                # Fallback: try to parse manually or use strptime
                                # Handle common ISO formats
                                for fmt in [
                                    "%Y-%m-%dT%H:%M:%S%z",
                                    "%Y-%m-%dT%H:%M:%S.%f%z",
                                    "%Y-%m-%d %H:%M:%S%z",
                                ]:
                                    try:
                                        return datetime.strptime(value, fmt)
                                    except ValueError:
                                        continue
                                # Last resort: try to parse as timestamp if it's numeric
                                try:
                                    return datetime.fromtimestamp(float(value))
                                except (ValueError, TypeError):
                                    raise ValueError(
                                        f"Unable to parse datetime string: {value}"
                                    )
                        elif isinstance(value, (int, float)):
                            # If it's a timestamp, convert to datetime
                            return datetime.fromtimestamp(value)
                        else:
                            # Fallback: try to convert to string and parse
                            return datetime.fromisoformat(
                                str(value).replace("Z", "+00:00")
                            )
                    except (ValueError, TypeError, OverflowError) as e:
                        LOGGER.warning(
                            "Failed to parse clock value '%s' as datetime: %s",
                            value,
                            e,
                        )
                        return None
                elif self._attribute == "timezone":
                    # Return timezone offset in minutes
                    try:
                        return int(value)
                    except (ValueError, TypeError):
                        return None
                else:
                    return str(value)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        attrs = {}
        clock = getattr(self._device, "clock", None)
        if clock is not None and isinstance(clock, dict):
            if "source" in clock:
                attrs["source"] = clock["source"]
            if "timezone" in clock:
                attrs["timezone"] = clock["timezone"]
            if "summerOffset" in clock:
                attrs["summer_offset"] = clock["summerOffset"]
        return attrs

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

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the gateway device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": "Delta Dore",
            "model": getattr(self._device, "productName", "Tydom Gateway"),
        }

    @property
    def available(self) -> bool:
        """Return True if hub is available."""
        if self._device is None:
            return False
        if hasattr(self, "hass") and self.hass is not None:
            if DOMAIN in self.hass.data:
                hubs = self.hass.data[DOMAIN]
                if hubs:
                    hub = next(iter(hubs.values()))
                    if not getattr(hub, "online", False):
                        return False
        return True

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA.

        This lifecycle method is only called if the entity is actually added to
        Home Assistant (i.e., not disabled). Register callbacks and entity
        references here, not in __init__.
        """
        self._device.register_callback(self.async_write_ha_state)
        # Register entity reference (only if entity is actually added)
        if self._device is not None:
            self._device._ha_device = self

    async def async_will_remove_from_hass(self):
        """Entity being removed from hass."""
        self._device.remove_callback(self.async_write_ha_state)
        # Clear entity reference if it points to this entity
        if (
            self._device is not None
            and hasattr(self._device, "_ha_device")
            and self._device._ha_device is self
        ):
            self._device._ha_device = None


class GeolocationSensor(SensorEntity):
    """Sensor for geolocation data from Tydom gateway."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        device: Tydom,
        attribute: str,
        hass: Any,
    ):
        """Initialize geolocation sensor.

        Args:
            device: Tydom gateway device
            attribute: Attribute name (longitude or latitude)
            hass: Home Assistant instance

        """
        self.hass = hass
        self._device = device
        self._attribute = attribute
        self._attr_unique_id = f"{self._device.device_id}_geoloc_{attribute}"
        self._attr_name = attribute.title()

        # Create entity description
        entity_description = SensorEntityDescription(
            key=f"geoloc_{attribute}",
            name=attribute.title(),
            translation_key=f"geoloc_{attribute}",
        )
        self.entity_description = entity_description

    @property
    def native_value(self) -> float | None:
        """Return the geolocation value."""
        geoloc = getattr(self._device, "geoloc", None)
        if geoloc is not None and isinstance(geoloc, dict):
            value = geoloc.get(self._attribute)
            if value is not None:
                # Tydom returns coordinates in a special format (e.g., -1895574 for longitude)
                # These need to be divided by 100000 to get actual degrees
                try:
                    return float(value) / 100000.0
                except (ValueError, TypeError):
                    return None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        attrs = {}
        geoloc = getattr(self._device, "geoloc", None)
        if geoloc is not None and isinstance(geoloc, dict):
            if "longitude" in geoloc:
                attrs["raw_longitude"] = geoloc["longitude"]
            if "latitude" in geoloc:
                attrs["raw_latitude"] = geoloc["latitude"]
        return attrs

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

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the gateway device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": "Delta Dore",
            "model": getattr(self._device, "productName", "Tydom Gateway"),
        }

    @property
    def available(self) -> bool:
        """Return True if hub is available."""
        if self._device is None:
            return False
        if hasattr(self, "hass") and self.hass is not None:
            if DOMAIN in self.hass.data:
                hubs = self.hass.data[DOMAIN]
                if hubs:
                    hub = next(iter(hubs.values()))
                    if not getattr(hub, "online", False):
                        return False
        return True

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA.

        This lifecycle method is only called if the entity is actually added to
        Home Assistant (i.e., not disabled). Register callbacks and entity
        references here, not in __init__.
        """
        self._device.register_callback(self.async_write_ha_state)
        # Register entity reference (only if entity is actually added)
        if self._device is not None:
            self._device._ha_device = self

    async def async_will_remove_from_hass(self):
        """Entity being removed from hass."""
        self._device.remove_callback(self.async_write_ha_state)
        # Clear entity reference if it points to this entity
        if (
            self._device is not None
            and hasattr(self._device, "_ha_device")
            and self._device._ha_device is self
        ):
            self._device._ha_device = None


class ProtocolBinarySensor(BinarySensorBase):
    """Binary sensor for a Tydom protocol status."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        device: Tydom,
        protocol_name: str,
        protocol_data: dict,
        attribute: str,
        hass: Any,
    ):
        """Initialize protocol binary sensor.

        Args:
            device: Tydom gateway device
            protocol_name: Name of the protocol (e.g., "X3D", "ZIGBEE")
            protocol_data: Protocol data dict from /info message
            attribute: Attribute to monitor (available, installed, ready, status)
            hass: Home Assistant instance

        """
        super().__init__(device)
        self.hass = hass
        self._device = device
        self._protocol_name = protocol_name
        self._protocol_data = protocol_data
        self._attribute = attribute
        self._attr_unique_id = (
            f"{self._device.device_id}_protocol_{protocol_name.lower()}_{attribute}"
        )
        self._attr_name = f"{protocol_name} {attribute.title()}"
        self._attr_device_class = None

        # Create entity description
        entity_description = BinarySensorEntityDescription(
            key=f"protocol_{protocol_name.lower()}_{attribute}",
            name=f"{protocol_name} {attribute.title()}",
            translation_key=f"protocol_{protocol_name.lower()}_{attribute}",
        )
        self.entity_description = entity_description

    @property
    def is_on(self) -> bool:
        """Return True if protocol attribute is active."""
        value = self._protocol_data.get(self._attribute, False)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            # For status, check if it's "running" or "idle"
            return value.lower() in ("running", "idle", "on", "true", "yes", "1")
        return bool(value)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        attrs = {
            "protocol": self._protocol_name,
            "available": self._protocol_data.get("available", False),
            "installed": self._protocol_data.get("installed", False),
            "ready": self._protocol_data.get("ready", False),
            "status": self._protocol_data.get("status", "unknown"),
            "install_status": self._protocol_data.get("installStatus", "unknown"),
        }
        return attrs

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the gateway device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": "Delta Dore",
            "model": getattr(self._device, "productName", "Tydom Gateway"),
        }


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

    # Binary sensor classes for system status
    binary_sensor_classes = {
        "bddEmpty": BinarySensorDeviceClass.PROBLEM,
        "apiMode": None,  # No specific device class
        "pltRegistered": None,
        "passwordEmpty": BinarySensorDeviceClass.PROBLEM,
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
        "protocols",  # Filter protocols list, we create separate sensors
        "geoloc",  # Filter geoloc dict, we create separate sensors
        "clock",  # Filter clock dict, we create separate sensors
        "maintenance",  # Filter maintenance dict
        "moments",  # Filter moments dict
        "local_claim",  # Filter local_claim dict
        "weather",  # Filter weather dict
    ]

    def __init__(self, device: Tydom, hass) -> None:
        """Initialize HATydom."""
        self.hass = hass
        self._device = device
        # Note: _ha_device is set in async_added_to_hass (not in __init__)
        # to comply with Home Assistant best practices for disabled entities
        self._attr_supported_features = UpdateEntityFeature.INSTALL
        self._attr_device_class = UpdateDeviceClass.FIRMWARE
        self._attr_unique_id = f"{self._device.device_id}"
        self._attr_name = self._device.device_name
        self._registered_sensors = []
        # Track which protocol/geoloc/clock sensors have been created to avoid duplicates
        self._created_protocol_sensors: set[str] = set()
        self._created_geoloc_sensors: set[str] = set()
        self._created_clock_sensors: set[str] = set()

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

        # Add MAC address if available (using Home Assistant constant)
        if hasattr(self._device, "mac") and self._device.mac:
            info["connections"] = {(dr.CONNECTION_NETWORK_MAC, str(self._device.mac))}

        # Gateway doesn't need via_device (it's the root device)
        return info

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes for the gateway."""
        attrs: dict[str, Any] = {}

        # MAC address
        if hasattr(self._device, "mac") and self._device.mac:
            attrs["mac_address"] = str(self._device.mac)

        # All versions
        version_attrs = [
            "mainVersionSW",
            "mainVersionHW",
            "keyVersionSW",
            "keyVersionHW",
            "keyVersionStack",
            "zigbeeVersionSW",
            "javaVersion",
            "oryxVersion",
            "bootVersion",
        ]
        for attr in version_attrs:
            if hasattr(self._device, attr):
                value = getattr(self._device, attr, None)
                if value is not None:
                    attrs[attr] = str(value)

        # References
        if hasattr(self._device, "mainReference") and self._device.mainReference:
            attrs["main_reference"] = str(self._device.mainReference)
        if hasattr(self._device, "keyReference") and self._device.keyReference:
            attrs["key_reference"] = str(self._device.keyReference)
        if hasattr(self._device, "zigbeeReference") and self._device.zigbeeReference:
            attrs["zigbee_reference"] = str(self._device.zigbeeReference)
        if hasattr(self._device, "bootReference") and self._device.bootReference:
            attrs["boot_reference"] = str(self._device.bootReference)

        # URL mediation
        if hasattr(self._device, "urlMediation") and self._device.urlMediation:
            attrs["mediation_url"] = str(self._device.urlMediation)

        # Maintenance info
        if hasattr(self._device, "maintenance") and isinstance(
            self._device.maintenance, dict
        ):
            attrs["maintenance"] = self._device.maintenance

        # Config
        if hasattr(self._device, "config") and self._device.config:
            attrs["config"] = str(self._device.config)

        # Main ID
        if hasattr(self._device, "mainId") and self._device.mainId:
            attrs["main_id"] = str(self._device.mainId)

        return attrs

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

    def get_sensors(self):
        """Get available sensors for this entity, including protocol sensors.

        Returns only sensors that haven't been created yet to avoid duplicates.
        """
        sensors = []

        # Get standard sensors from parent class (only new ones)
        new_standard_sensors = super().get_sensors()
        sensors.extend(new_standard_sensors)

        # Add protocol binary sensors if protocols data is available
        if hasattr(self._device, "protocols") and isinstance(
            self._device.protocols, list
        ):
            for protocol in self._device.protocols:
                if isinstance(protocol, dict) and "protocol" in protocol:
                    protocol_name = protocol.get("protocol", "UNKNOWN")

                    # Create binary sensors for key protocol attributes
                    for attr in ["available", "installed", "ready"]:
                        if attr in protocol:
                            # Create unique key for this sensor to avoid duplicates
                            sensor_key = f"protocol_{protocol_name.lower()}_{attr}"
                            if sensor_key not in self._created_protocol_sensors:
                                protocol_sensor = ProtocolBinarySensor(
                                    self._device,
                                    protocol_name,
                                    protocol,
                                    attr,
                                    self.hass,
                                )
                                sensors.append(protocol_sensor)
                                self._created_protocol_sensors.add(sensor_key)
                                LOGGER.debug(
                                    "Created protocol sensor: %s.%s.%s (key: %s)",
                                    protocol_name,
                                    attr,
                                    self._device.device_id,
                                    sensor_key,
                                )
                            else:
                                LOGGER.debug(
                                    "Skipping duplicate protocol sensor: %s (already created)",
                                    sensor_key,
                                )

        # Add geolocation sensors if geoloc data is available
        if hasattr(self._device, "geoloc") and isinstance(self._device.geoloc, dict):
            geoloc = self._device.geoloc
            if "longitude" in geoloc:
                if "longitude" not in self._created_geoloc_sensors:
                    longitude_sensor = GeolocationSensor(
                        self._device,
                        "longitude",
                        self.hass,
                    )
                    sensors.append(longitude_sensor)
                    self._created_geoloc_sensors.add("longitude")
                    LOGGER.debug("Created geolocation longitude sensor")
                else:
                    LOGGER.debug("Skipping duplicate geolocation longitude sensor")

            if "latitude" in geoloc:
                if "latitude" not in self._created_geoloc_sensors:
                    latitude_sensor = GeolocationSensor(
                        self._device,
                        "latitude",
                        self.hass,
                    )
                    sensors.append(latitude_sensor)
                    self._created_geoloc_sensors.add("latitude")
                    LOGGER.debug("Created geolocation latitude sensor")
                else:
                    LOGGER.debug("Skipping duplicate geolocation latitude sensor")

        # Add clock sensors if clock data is available
        if hasattr(self._device, "clock") and isinstance(self._device.clock, dict):
            clock = self._device.clock
            for attr in ["clock", "source", "timezone", "summerOffset"]:
                if attr in clock:
                    if attr not in self._created_clock_sensors:
                        clock_sensor = ClockSensor(
                            self._device,
                            attr,
                            self.hass,
                        )
                        sensors.append(clock_sensor)
                        self._created_clock_sensors.add(attr)
                        LOGGER.debug("Created clock sensor: %s", attr)
                    else:
                        LOGGER.debug("Skipping duplicate clock sensor: %s", attr)

        # Add system status binary sensors and sensors
        # These are created automatically by get_sensors() from parent class
        # but we ensure they use the right device classes
        status_attrs = {
            "bddEmpty": BinarySensorDeviceClass.PROBLEM,
            "apiMode": None,
            "pltRegistered": None,
            "passwordEmpty": BinarySensorDeviceClass.PROBLEM,
        }

        for attr, device_class in status_attrs.items():
            if hasattr(self._device, attr) and attr not in self._registered_sensors:
                value = getattr(self._device, attr)
                if isinstance(value, bool):
                    # Create binary sensor
                    binary_sensor = GenericBinarySensor(
                        self._device,
                        device_class,
                        attr,
                        attr,
                    )
                    binary_sensor.hass = self.hass
                    sensors.append(binary_sensor)
                    self._registered_sensors.append(attr)
                    LOGGER.debug("Created system status binary sensor: %s", attr)

        # Add bddStatus as a regular sensor (it's numeric)
        if (
            hasattr(self._device, "bddStatus")
            and "bddStatus" not in self._registered_sensors
        ):
            bdd_status_sensor = GenericSensor(
                self._device,
                None,  # device_class
                None,  # state_class
                "bddStatus",
                "bddStatus",
                None,  # unit
            )
            bdd_status_sensor.hass = self.hass
            sensors.append(bdd_status_sensor)
            self._registered_sensors.append("bddStatus")
            LOGGER.debug("Created system status sensor: bddStatus")

        return sensors


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
        # Note: _ha_device is set in async_added_to_hass (not in __init__)
        # to comply with Home Assistant best practices for disabled entities
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
        self._device._ha_device = self
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

    @property
    def icon(self) -> str:
        """Return the icon for the cover based on position."""
        position = self.current_cover_position
        if position is None:
            return "mdi:window-shutter"
        if position == 0:
            return "mdi:window-shutter-closed"
        elif position == 100:
            return "mdi:window-shutter-open"
        else:
            return "mdi:window-shutter"

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
        # Check if position is writable
        if not self._is_attribute_writable("position"):
            from homeassistant.exceptions import HomeAssistantError

            raise HomeAssistantError("La position n'est pas modifiable pour ce device")
        await self._device.set_position(kwargs[ATTR_POSITION])

    def _is_attribute_writable(self, attribute_name: str) -> bool:
        """Check if an attribute is writable based on metadata permissions."""
        if not hasattr(self._device, "_metadata") or self._device._metadata is None:
            return True  # Default to writable if no metadata
        if attribute_name not in self._device._metadata:
            return True  # Default to writable if attribute not in metadata
        metadata = self._device._metadata[attribute_name]
        permission = metadata.get("permission", "rw")
        return "w" in permission.lower()

    def _is_attribute_readable(self, attribute_name: str) -> bool:
        """Check if an attribute is readable based on metadata permissions."""
        if not hasattr(self._device, "_metadata") or self._device._metadata is None:
            return True  # Default to readable if no metadata
        if attribute_name not in self._device._metadata:
            return True  # Default to readable if attribute not in metadata
        metadata = self._device._metadata[attribute_name]
        permission = metadata.get("permission", "rw")
        return "r" in permission.lower()

    def _get_permissions_for_attributes(
        self, attribute_names: list[str]
    ) -> dict[str, dict[str, bool]]:
        """Get permissions (readable/writable) for a list of attributes.

        Returns:
            Dict mapping attribute names to permission dicts with 'readable' and 'writable' keys

        """
        permissions = {}
        for attr_name in attribute_names:
            permissions[attr_name] = {
                "readable": self._is_attribute_readable(attr_name),
                "writable": self._is_attribute_writable(attr_name),
            }
        return permissions

    def _get_controlled_by_scenes(self) -> list[dict[str, Any]]:
        """Get list of scenes that control this device.

        Returns:
            List of dicts with scene information (scene_id, scene_name, entity_id)

        """
        controlled_by = []
        hub_instance = self._get_hub()

        if hub_instance and hasattr(hub_instance, "devices"):
            device_id = getattr(self._device, "device_id", None)
            if not device_id:
                return controlled_by

            # Check all scenes to see if they control this device
            for _id, device in hub_instance.devices.items():
                if isinstance(device, TydomScene):
                    affected_device_ids = self._get_scene_affected_device_ids(device)
                    if device_id in affected_device_ids:
                        scene_info = {
                            "scene_id": getattr(device, "scene_id", None)
                            or str(device.device_id),
                            "scene_name": getattr(
                                device, "device_name", "Unknown Scene"
                            ),
                        }

                        # Try to get entity_id
                        if (
                            hasattr(hub_instance, "ha_devices")
                            and device.device_id in hub_instance.ha_devices
                        ):
                            ha_scene = hub_instance.ha_devices[device.device_id]
                            if hasattr(ha_scene, "entity_id"):
                                scene_info["entity_id"] = ha_scene.entity_id

                        controlled_by.append(scene_info)

        return controlled_by

    def _get_scene_affected_device_ids(self, scene_device: TydomScene) -> set[str]:
        """Get affected device IDs from a scene device.

        Args:
            scene_device: TydomScene device

        Returns:
            Set of device IDs affected by the scene

        """
        affected_ids = set()

        # Get grpAct
        grp_act = getattr(scene_device, "grpAct", None)
        if grp_act and isinstance(grp_act, list):
            from .tydom.MessageHandler import groups_data

            for grp_action in grp_act:
                if isinstance(grp_action, dict):
                    grp_id = grp_action.get("id")
                    if grp_id:
                        grp_id_str = str(grp_id)
                        if grp_id_str in groups_data:
                            group_info = groups_data[grp_id_str]
                            device_ids = group_info.get("devices", [])
                            affected_ids.update(device_ids)

        # Get epAct
        ep_act = getattr(scene_device, "epAct", None)
        if ep_act and isinstance(ep_act, list):
            for ep_action in ep_act:
                if isinstance(ep_action, dict):
                    ep_id = ep_action.get("id")
                    if ep_id:
                        affected_ids.add(str(ep_id))

        return affected_ids

    def _enrich_extra_state_attributes(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Enrich extra_state_attributes with common attributes like controlled_by_scenes.

        Args:
            attrs: Dictionary of attributes to enrich

        Returns:
            Enriched attributes dictionary

        """
        # Add controlled_by_scenes if not already present
        if "controlled_by_scenes" not in attrs:
            controlled_by = self._get_controlled_by_scenes()
            if controlled_by:
                attrs["controlled_by_scenes"] = controlled_by

        return attrs

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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes including permissions."""
        attrs: dict[str, Any] = {}

        # Add permissions for main attributes
        main_attrs = ["position", "slope", "positionCmd", "slopeCmd"]
        permissions = self._get_permissions_for_attributes(main_attrs)
        if permissions:
            attrs["permissions"] = permissions

        # Add controlled_by_scenes
        controlled_by = self._get_controlled_by_scenes()
        if controlled_by:
            attrs["controlled_by_scenes"] = controlled_by

        return attrs


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
        self._device._ha_device = self
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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        attrs: dict[str, Any] = {}
        # HASmoke doesn't need scene enrichment, just return basic attributes
        return attrs


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
    def hvac_mode(self) -> HVACMode:
        """Return the current operation (e.g. heat, cool, idle)."""
        if hasattr(self._device, "hvacMode"):
            hvac_mode = getattr(self._device, "hvacMode", None)
            if hvac_mode is not None and hvac_mode in self.dict_modes_dd_to_ha:
                LOGGER.debug("hvac_mode = %s", self.dict_modes_dd_to_ha[hvac_mode])
                return self.dict_modes_dd_to_ha[hvac_mode]
        if hasattr(self._device, "authorization"):
            authorization = getattr(self._device, "authorization", None)
            if authorization is not None and authorization in self.dict_modes_dd_to_ha:
                thermic_level = getattr(self._device, "thermicLevel", None)
                if (
                    thermic_level is not None
                    and thermic_level in self.dict_modes_dd_to_ha
                ):
                    LOGGER.debug(
                        "authorization = %s",
                        self.dict_modes_dd_to_ha[thermic_level],
                    )
                    return self.dict_modes_dd_to_ha[thermic_level]
        if hasattr(self._device, "thermicLevel"):
            thermic_level = getattr(self._device, "thermicLevel", None)
            if thermic_level is not None and thermic_level in self.dict_modes_dd_to_ha:
                LOGGER.debug(
                    "thermicLevel = %s", self.dict_modes_dd_to_ha[thermic_level]
                )
                return self.dict_modes_dd_to_ha[thermic_level]
        return HVACMode.OFF

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
        if hasattr(self._device, "hvacMode"):
            hvac_mode = getattr(self._device, "hvacMode", None)
            if hvac_mode in ("HEATING", "NORMAL"):
                if hasattr(self._device, "setpoint"):
                    setpoint = getattr(self._device, "setpoint", None)
                    if setpoint is not None:
                        return float(setpoint)
                if hasattr(self._device, "heatSetpoint"):
                    heat_setpoint = getattr(self._device, "heatSetpoint", None)
                    if heat_setpoint is not None:
                        return float(heat_setpoint)
            elif hvac_mode == "COOLING":
                if hasattr(self._device, "setpoint"):
                    setpoint = getattr(self._device, "setpoint", None)
                    if setpoint is not None:
                        return float(setpoint)
                if hasattr(self._device, "coolSetpoint"):
                    cool_setpoint = getattr(self._device, "coolSetpoint", None)
                    if cool_setpoint is not None:
                        return float(cool_setpoint)

        if hasattr(self._device, "authorization"):
            authorization = getattr(self._device, "authorization", None)
            if authorization == "HEATING":
                if hasattr(self._device, "heatSetpoint"):
                    heat_setpoint = getattr(self._device, "heatSetpoint", None)
                    if heat_setpoint is not None:
                        return float(heat_setpoint)
                if hasattr(self._device, "setpoint"):
                    setpoint = getattr(self._device, "setpoint", None)
                    if setpoint is not None:
                        return float(setpoint)
            elif authorization == "COOLING":
                if hasattr(self._device, "coolSetpoint"):
                    cool_setpoint = getattr(self._device, "coolSetpoint", None)
                    if cool_setpoint is not None:
                        return float(cool_setpoint)
                if hasattr(self._device, "setpoint"):
                    setpoint = getattr(self._device, "setpoint", None)
                    if setpoint is not None:
                        return float(setpoint)
        return None

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        await self._device.set_hvac_mode(self.dict_modes_ha_to_dd[hvac_mode])

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
        await self._device.set_temperature(str(kwargs.get(ATTR_TEMPERATURE)))


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
        self._device._ha_device = self
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

    @property
    def icon(self) -> str:
        """Return the icon for the window based on state."""
        if self.is_closed:
            return "mdi:window-closed"
        else:
            return "mdi:window-open"


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
        self._device._ha_device = self
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

    @property
    def icon(self) -> str:
        """Return the icon for the door based on state."""
        if self.is_closed:
            return "mdi:door-closed"
        else:
            return "mdi:door-open"


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
        self._device._ha_device = self
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
        self._device._ha_device = self
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
        self._device._ha_device = self
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

    @property
    def icon(self) -> str:
        """Return the icon for the light based on state."""
        if self.is_on:
            brightness = self.brightness
            if brightness is not None and brightness > 0:
                # Use different icons based on brightness level
                if brightness < 128:
                    return "mdi:lightbulb-on-outline"
                else:
                    return "mdi:lightbulb-on"
            return "mdi:lightbulb-on"
        else:
            return "mdi:lightbulb-outline"

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
        self._device._ha_device = self
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
    def icon(self) -> str:
        """Return the icon for the alarm based on state."""
        state = self.alarm_state
        if state == AlarmControlPanelState.TRIGGERED:
            return "mdi:shield-alert"
        elif state == AlarmControlPanelState.ARMED_AWAY:
            return "mdi:shield-home"
        elif state == AlarmControlPanelState.ARMED_HOME:
            return "mdi:shield-home-outline"
        elif state == AlarmControlPanelState.ARMED_NIGHT:
            return "mdi:shield-moon"
        elif state == AlarmControlPanelState.PENDING:
            return "mdi:shield-clock"
        else:
            return "mdi:shield-off"

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
        self._device._ha_device = self
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
        self._device._ha_device = self
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
        self._device._ha_device = self
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
        self._device._ha_device = self
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
        self._device._ha_device = self
        self._attr_unique_id = f"{self._device.device_id}_scene"
        # Store base name, name with zone will be calculated in async_added_to_hass
        self._base_name = self._device.device_name
        self._attr_name = self._base_name  # Temporary name, will be updated
        # Make scene editable in Home Assistant
        self._attr_is_editable = True
        # Cache to avoid repeated searches
        self._cached_tywell_device_id: str | None = None
        self._cached_zone: str | None = None
        self._cached_affected_device_ids: set[str] | None = None
        # Store related entity IDs for scene configuration
        self._related_entity_ids: list[str] = []
        # Store entity states for scene editor (dict of entity_id -> state dict)
        self._scene_entities: dict[str, Any] = {}

    def _is_twc_scene(self) -> bool:
        """Check if this scene is a TWC (Tywell Control) scene.

        TWC scenes typically have names containing TWC_UP, TWC_DOWN, TWC_STOP,
        or variations like TWC UP, TWC DOWN, etc.
        """
        name = self._device.device_name.upper()
        # Check for common TWC patterns
        twc_patterns = [
            "TWC_DOWN",
            "TWC_STOP",
            "TWC_UP",
            "TWC DOWN",
            "TWC STOP",
            "TWC UP",
            "TWC-UP",
            "TWC-DOWN",
            "TWC-STOP",
        ]
        return any(pattern in name for pattern in twc_patterns)

    def _get_zone_from_scene(self) -> str | None:
        """Extract zone (Jour/Nuit or Day/Night) from scene name, grpAct, or epAct.

        Returns translation key: "day" or "night" (not the translated string).
        """
        # Use cache if available
        if self._cached_zone is not None:
            return self._cached_zone

        zone = None
        # Priority 1: Analyze scene name
        name = self._device.device_name.upper()
        # Detect French and English patterns
        day_patterns = ["JOUR", "DAY", " J ", "_J_", "-J-"]
        night_patterns = ["NUIT", "NIGHT", " N ", "_N_", "-N-"]

        # Check for day patterns (but not if night is also present)
        if any(pattern in name for pattern in day_patterns) and not any(
            pattern in name for pattern in night_patterns
        ):
            zone = "day"
        # Check for night patterns
        elif any(pattern in name for pattern in night_patterns):
            zone = "night"

        # Priority 2: Analyze grpAct if zone not found
        if zone is None:
            grp_act = getattr(self._device, "grpAct", None)
            if grp_act and isinstance(grp_act, list):
                for group in grp_act:
                    if isinstance(group, dict):
                        group_id = group.get("id")
                        if group_id:
                            # Try to get group name from groups_data first
                            group_id_str = str(group_id)
                            group_info = groups_data.get(group_id_str, {})
                            group_name = group_info.get("name", "").upper()

                            # Fallback to device_name if not in groups_data
                            if not group_name:
                                group_name = device_name.get(group_id_str, "").upper()

                            if any(pattern in group_name for pattern in day_patterns):
                                zone = "day"
                                break
                            if any(pattern in group_name for pattern in night_patterns):
                                zone = "night"
                                break

        # Priority 3: Analyze epAct if zone still not found
        if zone is None:
            ep_act = getattr(self._device, "epAct", None)
            if ep_act and isinstance(ep_act, list):
                for endpoint in ep_act:
                    if isinstance(endpoint, dict):
                        dev_id = endpoint.get("devId")
                        ep_id = endpoint.get("epId")

                        # Try to find device name
                        device_id_str = None
                        if ep_id and dev_id:
                            if ep_id == dev_id:
                                device_id_str = str(ep_id)
                            else:
                                device_id_str = f"{ep_id}_{dev_id}"
                        elif ep_id:
                            device_id_str = str(ep_id)
                        elif dev_id:
                            device_id_str = str(dev_id)

                        if device_id_str:
                            endpoint_name = device_name.get(device_id_str, "").upper()
                            if any(
                                pattern in endpoint_name for pattern in day_patterns
                            ):
                                zone = "day"
                                break
                            if any(
                                pattern in endpoint_name for pattern in night_patterns
                            ):
                                zone = "night"
                                break

        # Cache result
        self._cached_zone = zone
        return zone

    def _get_translated_zone_name(self, zone_key: str | None) -> str | None:
        """Get translated zone name (Jour/Nuit or Day/Night)."""
        if not zone_key:
            return None

        # Simple translation dictionary based on hass language
        if self.hass and hasattr(self.hass, "config"):
            language = self.hass.config.language
            if language.startswith("fr"):
                return (
                    "Jour"
                    if zone_key == "day"
                    else "Nuit"
                    if zone_key == "night"
                    else None
                )
            else:
                return (
                    "Day"
                    if zone_key == "day"
                    else "Night"
                    if zone_key == "night"
                    else None
                )

        # Default French fallback
        return "Jour" if zone_key == "day" else "Nuit" if zone_key == "night" else None

    def _get_translated_device_name(
        self, device_key: str, zone_key: str | None = None
    ) -> str:
        """Get translated device name."""
        # Simple translation dictionary based on hass language
        if self.hass and hasattr(self.hass, "config"):
            language = self.hass.config.language
            if language.startswith("fr"):
                if device_key == "tywell_control":
                    zone_name = (
                        self._get_translated_zone_name(zone_key) if zone_key else None
                    )
                    return f"Tywell Control {zone_name or ''}".strip()
                elif device_key == "tydom_scenes":
                    zone_name = (
                        self._get_translated_zone_name(zone_key) if zone_key else None
                    )
                    return (
                        f"Scènes Tydom {zone_name or ''}".strip()
                        if zone_name
                        else "Scènes Tydom"
                    )
            else:
                if device_key == "tywell_control":
                    zone_name = (
                        self._get_translated_zone_name(zone_key) if zone_key else None
                    )
                    return f"Tywell Control {zone_name or ''}".strip()
                elif device_key == "tydom_scenes":
                    zone_name = (
                        self._get_translated_zone_name(zone_key) if zone_key else None
                    )
                    return (
                        f"Tydom Scenes {zone_name or ''}".strip()
                        if zone_name
                        else "Tydom Scenes"
                    )

        # Default French fallback
        if device_key == "tywell_control":
            zone_name = self._get_translated_zone_name(zone_key) if zone_key else None
            return f"Tywell Control {zone_name or ''}".strip()
        elif device_key == "tydom_scenes":
            zone_name = self._get_translated_zone_name(zone_key) if zone_key else None
            return (
                f"Scènes Tydom {zone_name or ''}".strip()
                if zone_name
                else "Scènes Tydom"
            )
        return device_key

    def _get_affected_device_ids(self) -> set[str]:
        """Extract device IDs affected by this scene from grpAct and epAct.

        Returns a set of device IDs that are controlled by this scene.
        Uses groups_data to resolve group IDs to device IDs.
        Improved with better edge case handling and consistency validation.
        """
        # Use cache if available
        if self._cached_affected_device_ids is not None:
            return self._cached_affected_device_ids

        affected_device_ids: set[str] = set()
        unresolved_groups: list[str] = []
        unresolved_endpoints: list[dict] = []

        try:
            hub_instance = self._get_hub()
            if not hub_instance or not hasattr(hub_instance, "devices"):
                self._cached_affected_device_ids = affected_device_ids
                return affected_device_ids

            grp_act = getattr(self._device, "grpAct", None)
            ep_act = getattr(self._device, "epAct", None)

            # Extract IDs from grpAct using groups_data
            if grp_act and isinstance(grp_act, list):
                for group in grp_act:
                    if isinstance(group, dict):
                        group_id = group.get("id")
                        if group_id:
                            group_id_str = str(group_id)

                            # Resolve group ID to device IDs using groups_data
                            if group_id_str in groups_data:
                                group_info = groups_data[group_id_str]
                                device_ids_from_group = group_info.get("devices", [])

                                if not device_ids_from_group:
                                    LOGGER.warning(
                                        "Group %s exists but has no devices for scene %s",
                                        group_id_str,
                                        self._device.device_id,
                                    )
                                    unresolved_groups.append(group_id_str)
                                    continue

                                resolved_count = 0
                                for device_id in device_ids_from_group:
                                    # Verify the device exists in hub
                                    if device_id in hub_instance.devices:
                                        affected_device_ids.add(device_id)
                                        resolved_count += 1
                                    else:
                                        # Try to find the device with different formats
                                        # Sometimes the device ID format might differ
                                        found_match = False
                                        for (
                                            known_device_id,
                                            known_device,
                                        ) in hub_instance.devices.items():
                                            # Try exact match first
                                            if device_id == known_device_id:
                                                affected_device_ids.add(known_device_id)
                                                resolved_count += 1
                                                found_match = True
                                                break

                                            # Try device_id attribute
                                            if hasattr(known_device, "device_id"):
                                                if (
                                                    str(known_device.device_id)
                                                    == device_id
                                                ):
                                                    affected_device_ids.add(
                                                        known_device_id
                                                    )
                                                    resolved_count += 1
                                                    found_match = True
                                                    break

                                            # Try _id attribute
                                            if hasattr(known_device, "_id"):
                                                if str(known_device._id) == device_id:
                                                    affected_device_ids.add(
                                                        known_device_id
                                                    )
                                                    resolved_count += 1
                                                    found_match = True
                                                    break

                                            # Last resort: partial match
                                            if (
                                                device_id in known_device_id
                                                or known_device_id in device_id
                                            ):
                                                affected_device_ids.add(known_device_id)
                                                resolved_count += 1
                                                found_match = True
                                                LOGGER.debug(
                                                    "Partial match: group device %s -> hub device %s",
                                                    device_id,
                                                    known_device_id,
                                                )
                                                break

                                        if not found_match:
                                            LOGGER.debug(
                                                "Device %s from group %s not found in hub for scene %s",
                                                device_id,
                                                group_id_str,
                                                self._device.device_id,
                                            )

                                if resolved_count > 0:
                                    LOGGER.debug(
                                        "Resolved group %s to %d/%d device(s) for scene %s",
                                        group_id_str,
                                        resolved_count,
                                        len(device_ids_from_group),
                                        self._device.device_id,
                                    )
                                else:
                                    unresolved_groups.append(group_id_str)
                            else:
                                # Fallback: check if group ID is directly a device ID
                                if group_id_str in hub_instance.devices:
                                    affected_device_ids.add(group_id_str)
                                    LOGGER.debug(
                                        "Group ID %s resolved as direct device ID for scene %s",
                                        group_id_str,
                                        self._device.device_id,
                                    )
                                else:
                                    unresolved_groups.append(group_id_str)
                                    LOGGER.debug(
                                        "Group %s not found in groups_data for scene %s",
                                        group_id_str,
                                        self._device.device_id,
                                    )

            # Extract IDs from epAct with improved resolution
            # Format: {"devId": X, "epId": Y, "state": [...]} or {"id": X, "state": [...]}
            if ep_act and isinstance(ep_act, list):
                for endpoint in ep_act:
                    if isinstance(endpoint, dict):
                        # Handle both formats: {"devId": X, "epId": Y} and {"id": X}
                        dev_id = endpoint.get("devId") or endpoint.get("id")
                        ep_id = endpoint.get("epId") or endpoint.get("id")

                        # Priority order for device ID resolution:
                        # 1. Format "{epId}_{devId}" if both exist and different
                        # 2. Format "epId" if epId exists
                        # 3. Format "devId" if devId exists
                        # 4. Check in hub.devices for any match

                        candidate_ids = []

                        if ep_id and dev_id:
                            if ep_id == dev_id:
                                # Same ID, use epId format
                                candidate_ids.append(str(ep_id))
                            else:
                                # Different IDs, try both formats
                                candidate_ids.append(f"{ep_id}_{dev_id}")
                                candidate_ids.append(str(ep_id))
                                candidate_ids.append(str(dev_id))
                        elif ep_id:
                            candidate_ids.append(str(ep_id))
                        elif dev_id:
                            candidate_ids.append(str(dev_id))

                        if not candidate_ids:
                            unresolved_endpoints.append(endpoint)
                            LOGGER.debug(
                                "Endpoint in epAct has no valid ID for scene %s: %s",
                                self._device.device_id,
                                endpoint,
                            )
                            continue

                        # Try each candidate ID
                        found = False
                        for candidate_id in candidate_ids:
                            if candidate_id in hub_instance.devices:
                                affected_device_ids.add(candidate_id)
                                found = True
                                LOGGER.debug(
                                    "Resolved epAct endpoint (devId=%s, epId=%s) to device %s",
                                    dev_id,
                                    ep_id,
                                    candidate_id,
                                )
                                break

                            # Also check device_id and _id attributes
                            for (
                                known_device_id,
                                known_device,
                            ) in hub_instance.devices.items():
                                if (
                                    hasattr(known_device, "device_id")
                                    and str(known_device.device_id) == candidate_id
                                ):
                                    affected_device_ids.add(known_device_id)
                                    found = True
                                    LOGGER.debug(
                                        "Resolved epAct endpoint (devId=%s, epId=%s) to device %s via device_id",
                                        dev_id,
                                        ep_id,
                                        known_device_id,
                                    )
                                    break
                                if (
                                    hasattr(known_device, "_id")
                                    and str(known_device._id) == candidate_id
                                ):
                                    affected_device_ids.add(known_device_id)
                                    found = True
                                    LOGGER.debug(
                                        "Resolved epAct endpoint (devId=%s, epId=%s) to device %s via _id",
                                        dev_id,
                                        ep_id,
                                        known_device_id,
                                    )
                                    break

                            if found:
                                break

                        if not found:
                            # Last resort: try partial matches
                            for known_device_id in hub_instance.devices:
                                for candidate_id in candidate_ids:
                                    if (
                                        candidate_id in known_device_id
                                        or known_device_id in candidate_id
                                    ):
                                        affected_device_ids.add(known_device_id)
                                        LOGGER.debug(
                                            "Resolved epAct endpoint (devId=%s, epId=%s) to device %s (partial match)",
                                            dev_id,
                                            ep_id,
                                            known_device_id,
                                        )
                                        found = True
                                        break
                                if found:
                                    break

                            if not found:
                                unresolved_endpoints.append(endpoint)
                                LOGGER.debug(
                                    "Could not resolve epAct endpoint (devId=%s, epId=%s) for scene %s",
                                    dev_id,
                                    ep_id,
                                    self._device.device_id,
                                )

            # Log warnings for unresolved items
            if unresolved_groups:
                LOGGER.warning(
                    "Scene %s has %d unresolved group(s): %s",
                    self._device.device_id,
                    len(unresolved_groups),
                    unresolved_groups,
                )

            if unresolved_endpoints:
                LOGGER.warning(
                    "Scene %s has %d unresolved endpoint(s)",
                    self._device.device_id,
                    len(unresolved_endpoints),
                )

            # Cache result
            self._cached_affected_device_ids = affected_device_ids
            LOGGER.debug(
                "Scene %s affects %d device(s): %s",
                self._device.device_id,
                len(affected_device_ids),
                list(affected_device_ids),
            )
            return affected_device_ids
        except Exception as e:
            LOGGER.warning(
                "Error while extracting affected device IDs for scene %s: %s",
                self._device.device_id,
                e,
                exc_info=True,
            )
            self._cached_affected_device_ids = set()
            return set()

    def _find_tywell_device(self, zone: str | None = None) -> str | None:
        """Find Tywell Control device from grpAct/epAct.

        Args:
            zone: Optional zone filter ("day" or "night") to narrow search.

        Returns:
            Device ID of the Tywell Control device, or None if not found.

        """
        # Use cache if available
        if self._cached_tywell_device_id is not None:
            return self._cached_tywell_device_id

        try:
            hub_instance = self._get_hub()
            if not hub_instance or not hasattr(hub_instance, "devices"):
                return None

            # Use the affected device IDs method
            affected_device_ids = self._get_affected_device_ids()

            if not affected_device_ids:
                LOGGER.debug(
                    "No affected devices found for scene %s to search for Tywell Control",
                    self._device.device_id,
                )
                return None

            # Search for Tywell Control in affected devices
            tywell_keywords = ["TYWELL", "CONTROL", "TYWELL CONTROL"]

            for device_id in affected_device_ids:
                if device_id in hub_instance.devices:
                    device = hub_instance.devices[device_id]

                    # Check device name
                    device_name_attr = (
                        getattr(device, "device_name", "") or ""
                    ).upper()
                    # Check product name
                    product_name = (getattr(device, "productName", "") or "").upper()
                    # Check device type
                    device_type_attr = (
                        getattr(device, "device_type", "") or ""
                    ).upper()

                    # Check if it's a Tywell Control
                    is_tywell = any(
                        keyword in product_name
                        or keyword in device_name_attr
                        or keyword in device_type_attr
                        for keyword in tywell_keywords
                    )

                    if is_tywell:
                        # If zone filter is specified, verify device matches zone
                        if zone:
                            device_zone = self._get_zone_from_device(device)
                            if device_zone != zone:
                                LOGGER.debug(
                                    "Tywell device %s zone (%s) doesn't match requested zone (%s)",
                                    device_id,
                                    device_zone,
                                    zone,
                                )
                                continue

                        # Cache result
                        self._cached_tywell_device_id = device_id
                        LOGGER.debug(
                            "Found Tywell Control device %s for scene %s",
                            device_id,
                            self._device.device_id,
                        )
                        return device_id

            LOGGER.debug(
                "No Tywell Control device found in affected devices for scene %s",
                self._device.device_id,
            )
            return None
        except Exception as e:
            LOGGER.warning(
                "Error while searching for Tywell Control device for scene %s: %s",
                self._device.device_id,
                e,
                exc_info=True,
            )
            return None

    def _get_zone_from_device(self, device: TydomDevice) -> str | None:
        """Extract zone from device name.

        Args:
            device: The Tydom device to analyze.

        Returns:
            Zone key ("day" or "night") or None.

        """
        device_name_attr = getattr(device, "device_name", "").upper()
        day_patterns = ["JOUR", "DAY", " J ", "_J_", "-J-"]
        night_patterns = ["NUIT", "NIGHT", " N ", "_N_", "-N-"]

        if any(pattern in device_name_attr for pattern in day_patterns):
            return "day"
        elif any(pattern in device_name_attr for pattern in night_patterns):
            return "night"

        return None

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

        # Add affected device IDs for reference
        affected_device_ids = self._get_affected_device_ids()
        if affected_device_ids:
            attrs["affected_device_ids"] = list(affected_device_ids)

            # Also add device names if available
            hub_instance = self._get_hub()
            if hub_instance and hasattr(hub_instance, "devices"):
                affected_device_names = []
                for device_id in affected_device_ids:
                    if device_id in hub_instance.devices:
                        device = hub_instance.devices[device_id]
                        device_name_attr = getattr(device, "device_name", None)
                        if device_name_attr:
                            affected_device_names.append(device_name_attr)
                        elif hasattr(device, "productName"):
                            product_name = getattr(device, "productName", None)
                            if product_name:
                                affected_device_names.append(str(product_name))
                if affected_device_names:
                    attrs["affected_device_names"] = affected_device_names

        # Add detailed actions for each affected device
        detailed_actions = []
        grp_act = getattr(self._device, "grpAct", None)
        ep_act = getattr(self._device, "epAct", None)

        hub_instance = self._get_hub()

        # Process grpAct
        if grp_act and isinstance(grp_act, list):
            for grp_action in grp_act:
                if isinstance(grp_action, dict):
                    grp_id = grp_action.get("id")
                    state_info = grp_action.get("state", [])

                    if grp_id:
                        grp_id_str = str(grp_id)
                        # Resolve group to devices
                        from .tydom.MessageHandler import groups_data

                        if grp_id_str in groups_data:
                            group_info = groups_data[grp_id_str]
                            group_name = group_info.get("name", f"Group {grp_id_str}")
                            device_ids = group_info.get("devices", [])

                            for device_id in device_ids:
                                device_name = None
                                if hub_instance and hasattr(hub_instance, "devices"):
                                    if device_id in hub_instance.devices:
                                        device = hub_instance.devices[device_id]
                                        device_name = getattr(
                                            device, "device_name", None
                                        )

                                action_detail = {
                                    "device_id": device_id,
                                    "device_name": device_name or f"Device {device_id}",
                                    "group_id": grp_id_str,
                                    "group_name": group_name,
                                    "actions": [],
                                }

                                # Add state actions
                                if state_info and isinstance(state_info, list):
                                    for state_item in state_info:
                                        if isinstance(state_item, dict):
                                            action_detail["actions"].append(
                                                {
                                                    "name": state_item.get("name", ""),
                                                    "value": state_item.get(
                                                        "value", ""
                                                    ),
                                                }
                                            )

                                if action_detail["actions"]:
                                    detailed_actions.append(action_detail)

        # Process epAct
        if ep_act and isinstance(ep_act, list):
            for ep_action in ep_act:
                if isinstance(ep_action, dict):
                    ep_id = ep_action.get("id")
                    state_info = ep_action.get("state", [])

                    if ep_id:
                        ep_id_str = str(ep_id)
                        device_name = None
                        if hub_instance and hasattr(hub_instance, "devices"):
                            # Try to find device by various ID formats
                            for _id, device in hub_instance.devices.items():
                                if (
                                    _id == ep_id_str
                                    or str(getattr(device, "device_id", ""))
                                    == ep_id_str
                                    or str(getattr(device, "_id", "")) == ep_id_str
                                ):
                                    device_name = getattr(device, "device_name", None)
                                    break

                        action_detail = {
                            "device_id": ep_id_str,
                            "device_name": device_name or f"Device {ep_id_str}",
                            "actions": [],
                        }

                        # Add state actions
                        if state_info and isinstance(state_info, list):
                            for state_item in state_info:
                                if isinstance(state_item, dict):
                                    action_detail["actions"].append(
                                        {
                                            "name": state_item.get("name", ""),
                                            "value": state_item.get("value", ""),
                                        }
                                    )

                        if action_detail["actions"]:
                            detailed_actions.append(action_detail)

        if detailed_actions:
            attrs["detailed_actions"] = detailed_actions

        # Add related entity IDs and states for scene configuration
        # This allows Home Assistant to know which entities are controlled by this scene
        if hasattr(self, "_related_entity_ids") and self._related_entity_ids:
            attrs["entity_id"] = self._related_entity_ids
            attrs["entities"] = self._related_entity_ids

        # Add entity states if available (for scene editor)
        if hasattr(self, "_scene_entities") and self._scene_entities:
            attrs["scene_entities"] = self._scene_entities

        return attrs

    @property
    def is_editable(self) -> bool:
        """Return True if the scene is editable in Home Assistant."""
        return True

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return information to link this entity with the correct device.

        Scenes are grouped into virtual devices:
        - TWC scenes are grouped by zone (Day/Night) into virtual "Tywell Control [Zone]" devices
        - Other scenes are grouped into a virtual "Scènes Tydom" device
        """
        # Get gateway device ID for via_device fallback
        gateway_device_id = self._get_tydom_gateway_device_id()

        # Ensure gateway_device_id is available - if not, we can't create proper device_info
        if not gateway_device_id:
            LOGGER.warning(
                "Cannot create device_info for scene %s: gateway device ID not found",
                self._device.device_name,
            )
            # Fallback: return None to let Home Assistant handle it (should not happen in normal operation)
            return None

        # Check if this is a TWC scene
        scene_name = self._device.device_name
        is_twc = self._is_twc_scene()

        if is_twc:
            # Get zone (day/night)
            zone_key = self._get_zone_from_scene()

            # For TWC scenes, always create a virtual device, even if zone is not determined
            # If zone is not found, use a generic TWC device identifier
            # IMPORTANT: All TWC scenes must use the same device_identifier to be grouped
            if zone_key:
                # Create virtual device identifier for this zone
                device_identifier = f"tywell_control_{zone_key}"

                # Get translated device name with zone
                device_name = self._get_translated_device_name(
                    "tywell_control", zone_key
                )

                # Try to find the physical Tywell Control device for this zone
                tywell_device_id = self._find_tywell_device(zone_key)
            else:
                # TWC scene but zone not determined - create generic TWC device
                # All TWC scenes without zone will use this same identifier
                device_identifier = "tywell_control"
                device_name = self._get_translated_device_name("tywell_control", None)
                # Try to find any Tywell Control device
                tywell_device_id = self._find_tywell_device(None)

            # Determine via_device: use physical Tywell Control if found, otherwise gateway
            if tywell_device_id and gateway_device_id:
                # Verify the device exists in hub (it should be in device registry if it exists here)
                hub_instance = self._get_hub()
                if hub_instance and hasattr(hub_instance, "devices"):
                    if tywell_device_id in hub_instance.devices:
                        via_device_id = tywell_device_id
                    else:
                        via_device_id = gateway_device_id
                else:
                    via_device_id = gateway_device_id
            else:
                via_device_id = gateway_device_id

            # Create DeviceInfo for virtual device grouping TWC scenes
            # IMPORTANT: All TWC scenes must use the same device_identifier to be grouped
            device_info: DeviceInfo = {
                "identifiers": {(DOMAIN, device_identifier)},
                "name": device_name,
                "manufacturer": "Delta Dore",
                "model": "Tywell Control",
            }

            # Link to physical device or gateway
            if via_device_id:
                device_info["via_device"] = (DOMAIN, via_device_id)

            LOGGER.debug(
                "TWC scene device_info: scene=%s, is_twc=%s, zone=%s, device_identifier=%s",
                scene_name,
                is_twc,
                zone_key,
                device_identifier,
            )

            return device_info
        else:
            # Non-TWC scene - group in "Scènes Tydom" virtual device
            device_name = self._get_translated_device_name("tydom_scenes")
            info: DeviceInfo = {
                "identifiers": {(DOMAIN, "tydom_scenes")},
                "name": device_name,
                "manufacturer": "Delta Dore",
                "model": "Tydom Scenes",
            }
            if gateway_device_id:
                info["via_device"] = (DOMAIN, gateway_device_id)
            return info

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Call parent method
        await super().async_added_to_hass()

        # Update name with translated zone if it's a TWC scene
        if self._is_twc_scene():
            zone_key = self._get_zone_from_scene()
            if zone_key:
                # Check if zone is already in the name (French or English)
                base_name_upper = (self._base_name or "").upper()
                zone_already_present = (
                    "JOUR" in base_name_upper
                    or "NUIT" in base_name_upper
                    or "DAY" in base_name_upper
                    or "NIGHT" in base_name_upper
                    or " J " in base_name_upper
                    or " N " in base_name_upper
                )
                if not zone_already_present:
                    zone_name = self._get_translated_zone_name(zone_key)
                    if zone_name:
                        self._attr_name = f"{self._base_name} - {zone_name}"

        # Create relations between this scene and the devices it affects
        await self._create_scene_device_relations()

    def _invalidate_caches(self) -> None:
        """Invalidate cached data when device is updated."""
        self._cached_affected_device_ids = None
        self._cached_tywell_device_id = None
        self._cached_zone = None
        LOGGER.debug("Invalidated caches for scene %s", self._device.device_id)

    async def async_device_update(self, device: TydomScene) -> None:
        """Handle device update for scene.

        This method is called when the scene device is updated.
        It invalidates caches and recreates relations if grpAct/epAct changed.
        """
        old_grp_act = getattr(self._device, "grpAct", None)
        old_ep_act = getattr(self._device, "epAct", None)
        old_name = getattr(self._device, "device_name", None)

        # Invalidate caches
        self._invalidate_caches()

        # Check if grpAct or epAct changed
        new_grp_act = getattr(device, "grpAct", None)
        new_ep_act = getattr(device, "epAct", None)
        new_name = getattr(device, "device_name", None)

        grp_act_changed = old_grp_act != new_grp_act
        ep_act_changed = old_ep_act != new_ep_act
        name_changed = old_name != new_name

        if grp_act_changed or ep_act_changed:
            LOGGER.debug(
                "Scene %s grpAct/epAct changed, recreating relations",
                self._device.device_id,
            )
            # Recreate relations with affected devices
            await self._create_scene_device_relations()

        if name_changed:
            LOGGER.debug(
                "Scene %s name changed from '%s' to '%s'",
                self._device.device_id,
                old_name,
                new_name,
            )
            # Update base name and recalculate zone
            self._base_name = new_name
            if self._is_twc_scene():
                zone_key = self._get_zone_from_scene()
                if zone_key:
                    zone_name = self._get_translated_zone_name(zone_key)
                    if zone_name:
                        self._attr_name = f"{self._base_name} - {zone_name}"
                    else:
                        self._attr_name = self._base_name
                else:
                    self._attr_name = self._base_name
            else:
                self._attr_name = self._base_name

    async def _create_scene_device_relations(self) -> None:
        """Create relations between this scene and the devices it affects.

        This allows Home Assistant to display scenes on the devices they control.
        Stores entity IDs for scene configuration.
        """
        try:
            from homeassistant.helpers import device_registry as dr
            from homeassistant.helpers import entity_registry as er

            # Get device and entity registries
            device_registry = dr.async_get(self.hass)
            entity_registry = er.async_get(self.hass)

            # Get affected device IDs
            affected_device_ids = self._get_affected_device_ids()
            if not affected_device_ids:
                LOGGER.debug(
                    "Scene %s has no affected devices",
                    self._device.device_id,
                )
                return

            # Get the scene entity entry
            scene_entity_id = self.entity_id
            if not scene_entity_id:
                # Entity not yet registered, skip for now
                LOGGER.debug(
                    "Scene entity %s not yet registered, relations will be created later",
                    self._device.device_id,
                )
                return

            scene_entity_entry = entity_registry.async_get(scene_entity_id)
            if not scene_entity_entry:
                LOGGER.debug(
                    "Scene entity entry not found for %s",
                    scene_entity_id,
                )
                return

            # Find entities for each affected device
            related_entities = []
            found_devices = []

            for affected_device_id in affected_device_ids:
                # Find the device in the registry
                device_entry = device_registry.async_get_device(
                    identifiers={(DOMAIN, affected_device_id)}
                )

                if not device_entry:
                    continue

                found_devices.append(affected_device_id)

                # Find all entities associated with this device
                device_entities = er.async_entries_for_device(
                    entity_registry, device_entry.id
                )

                for entity_entry in device_entities:
                    # Skip the scene entity itself
                    if entity_entry.entity_id == scene_entity_id:
                        continue

                    related_entities.append(entity_entry.entity_id)

                    LOGGER.debug(
                        "Scene %s controls entity %s (device %s)",
                        self._device.device_id,
                        entity_entry.entity_id,
                        affected_device_id,
                    )

            # Store related entities for scene configuration
            if related_entities:
                # Store in a cache that can be accessed by extra_state_attributes
                if not hasattr(self, "_related_entity_ids"):
                    self._related_entity_ids = []
                self._related_entity_ids = related_entities

                # Initialize _scene_entities with empty states for each entity
                # This allows the scene editor to recognize and modify the scene
                if not hasattr(self, "_scene_entities"):
                    self._scene_entities = {}

                # Add entities to _scene_entities if not already present
                for entity_id in related_entities:
                    if entity_id not in self._scene_entities:
                        # Initialize with empty state (will be filled when scene is edited)
                        self._scene_entities[entity_id] = {}

                LOGGER.info(
                    "Scene %s (%s) is linked to %d device(s) with %d related entity/ies: %s",
                    self._device.device_id,
                    self._base_name,
                    len(found_devices),
                    len(related_entities),
                    found_devices,
                )
            else:
                LOGGER.debug(
                    "Scene %s references %d device(s) but none found in registry yet",
                    self._device.device_id,
                    len(affected_device_ids),
                )
        except Exception as e:
            LOGGER.warning(
                "Error creating scene-device relations for scene %s: %s",
                self._device.device_id,
                e,
                exc_info=True,
            )

    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the scene.

        Raises:
            HomeAssistantError: If activation fails.

        """
        try:
            await self._device.activate()
        except Exception as e:
            from homeassistant.exceptions import HomeAssistantError

            scene_name = getattr(self._device, "device_name", "Unknown")
            raise HomeAssistantError(
                f"Failed to activate scene '{scene_name}': {str(e)}"
            ) from e

    async def async_create(self, **kwargs: Any) -> None:
        """Create or update the scene with new entities.

        This method allows Home Assistant to create/modify scenes via scene.create service.
        Note: This modifies the Home Assistant representation of the scene, not the Tydom scene itself.
        The Tydom scene will still activate its predefined scenario when activated.
        """
        from homeassistant.exceptions import HomeAssistantError

        # Get entities from kwargs
        entities = kwargs.get("entities")
        if not entities:
            raise HomeAssistantError("No entities provided for scene creation")

        # Store the entities for this scene
        # This allows Home Assistant to know which entities are controlled by this scene
        if not hasattr(self, "_related_entity_ids"):
            self._related_entity_ids = []

        # Extract entity IDs from the entities dict
        entity_ids = []
        if isinstance(entities, dict):
            entity_ids = list(entities.keys())
        elif isinstance(entities, list):
            entity_ids = entities

        self._related_entity_ids = entity_ids

        # Store the full entities dict for scene.apply
        self._scene_entities = entities if isinstance(entities, dict) else {}

        LOGGER.info(
            "Scene %s (%s) created/updated with %d entities: %s",
            self._device.device_id,
            self._base_name,
            len(entity_ids),
            entity_ids,
        )

        # Update extra state attributes to reflect the new entities
        self.async_write_ha_state()

    async def async_update(self, **kwargs: Any) -> None:
        """Update the scene with new entities.

        This method allows Home Assistant to modify scenes via scene.apply service.
        """
        await self.async_create(**kwargs)


class HAMoment(SwitchEntity, HAEntity):
    """Representation of a Tydom Moment/Program."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, device: TydomMoment, hass) -> None:
        """Initialize HAMoment."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
        self._attr_unique_id = f"{self._device.device_id}_moment"
        self._attr_name = self._device.device_name

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the gateway device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": "Delta Dore",
            "model": "Tydom Moment",
            "via_device": (DOMAIN, self._get_tydom_gateway_device_id() or ""),
        }

    @property
    def is_on(self) -> bool:
        """Return True if moment is active (not suspended)."""
        return not self._device.is_suspended

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Resume the moment (turn off suspension)."""
        await self._device.suspend_moment(suspend=False, suspend_to=0)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Suspend the moment indefinitely."""
        await self._device.suspend_moment(suspend=True, suspend_to=-1)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes for the moment."""
        attrs: dict[str, Any] = {
            "moment_id": self._device.moment_id,
            "suspended": self._device.is_suspended,
            "suspend_to": self._device.suspend_to,
        }

        # Add all moment data
        if self._device.moment_data:
            for key, value in self._device.moment_data.items():
                if key not in ["id", "name"]:
                    attrs[key] = value

        return attrs


class HASwitch(SwitchEntity, HAEntity):
    """Representation of a Tydom Switch."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:toggle-switch"

    def __init__(self, device: TydomDevice, hass) -> None:
        """Initialize HASwitch."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
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

    @property
    def icon(self) -> str:
        """Return the icon for the switch based on state."""
        if self.is_on:
            return "mdi:toggle-switch"
        else:
            return "mdi:toggle-switch-off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        attrs: dict[str, Any] = {}
        return self._enrich_extra_state_attributes(attrs)  # type: ignore[attr-defined]

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


class HAGroup(ButtonEntity, HAEntity):
    """Representation of a Tydom Group."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, device: TydomGroup, hass) -> None:
        """Initialize HAGroup."""
        self.hass = hass
        self._device = device
        self._device._ha_device = self
        self._attr_unique_id = f"{self._device.device_id}_group"

        # Get usage for translation key and icon
        group_usage = getattr(self._device, "group_usage", None) or ""

        # Set icon based on usage
        usage_icons = {
            "light": "mdi:lightbulb-group",
            "shutter": "mdi:window-shutter",
            "awning": "mdi:window-shutter-open",
            "plug": "mdi:power-socket-eu",
            "heating": "mdi:radiator",
            "alarm": "mdi:shield-home",
        }
        self._attr_icon = usage_icons.get(group_usage, "mdi:group")

        # Create entity description with translation key
        translation_key = f"group_{group_usage}" if group_usage else None
        entity_description = ButtonEntityDescription(
            key=f"group_{self._device.device_id}",
            name=self._device.device_name,
            translation_key=translation_key,
        )
        self.entity_description = entity_description
        self._attr_name = self._device.device_name

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the gateway device."""
        return {
            "identifiers": {(DOMAIN, self._device.device_id)},
            "name": self._device.device_name,
            "manufacturer": "Delta Dore",
            "model": "Tydom Group",
            "via_device": (DOMAIN, self._get_tydom_gateway_device_id() or ""),
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes for the group."""
        attrs: dict[str, Any] = {
            "group_id": self._device.group_id,
            "group_usage": getattr(self._device, "group_usage", None),
            "device_count": len(self._device.device_ids),
        }

        # Add device IDs
        if self._device.device_ids:
            attrs["device_ids"] = self._device.device_ids

            # Try to get device names and types
            hub_instance = self._get_hub()
            if hub_instance and hasattr(hub_instance, "devices"):
                device_names = []
                device_types = []

                for device_id in self._device.device_ids:
                    # Try to find device by various ID formats
                    found_device = None
                    for _id, device in hub_instance.devices.items():
                        if (
                            _id == device_id
                            or str(getattr(device, "device_id", "")) == device_id
                            or str(getattr(device, "_id", "")) == device_id
                        ):
                            found_device = device
                            break

                    if found_device:
                        # Get device name
                        device_name = getattr(found_device, "device_name", None)
                        if not device_name and hasattr(found_device, "productName"):
                            device_name = getattr(found_device, "productName", None)
                        if device_name:
                            device_names.append(str(device_name))
                        else:
                            device_names.append(f"Device {device_id}")

                        # Get device type
                        device_type = getattr(found_device, "device_type", None)
                        if device_type:
                            device_types.append(str(device_type))
                        else:
                            device_types.append("unknown")

                if device_names:
                    attrs["device_names"] = device_names
                if device_types:
                    attrs["device_types"] = device_types

        return attrs

    async def async_press(self) -> None:
        """Handle the button press.

        Performs an action on all devices in the group based on the group usage:
        - shutter/awning: Open all covers
        - light: Turn on all lights
        - plug: Turn on all plugs
        - heating: Not implemented (would need specific commands)
        - alarm: Not implemented (would need specific commands)
        """
        group_usage = getattr(self._device, "group_usage", None) or ""
        hub_instance = self._get_hub()

        if not hub_instance or not hasattr(hub_instance, "devices"):
            LOGGER.warning(
                "Cannot control group %s: hub not available", self._device.device_name
            )
            return

        LOGGER.info(
            "Group %s (%s) button pressed - controlling %d device(s)",
            self._device.device_name,
            group_usage,
            len(self._device.device_ids),
        )

        # Control all devices in the group based on usage
        tasks = []
        for device_id in self._device.device_ids:
            device = hub_instance.devices.get(device_id)
            if not device:
                continue

            try:
                if group_usage in ("shutter", "awning"):
                    # Open all covers
                    if hasattr(device, "up"):
                        tasks.append(device.up())
                    elif hasattr(device, "open"):
                        tasks.append(device.open())
                elif group_usage == "light":
                    # Turn on all lights
                    if hasattr(device, "turn_on"):
                        tasks.append(
                            device.turn_on(None)
                        )  # None = toggle or default brightness
                    elif (
                        hasattr(device, "_tydom_client")
                        and hasattr(device, "_id")
                        and hasattr(device, "_endpoint")
                    ):
                        # Generic light control
                        tasks.append(
                            device._tydom_client.put_devices_data(
                                device._id, device._endpoint, "levelCmd", "ON"
                            )
                        )
                elif group_usage == "plug":
                    # Turn on all plugs
                    # Note: Some plug devices might be TydomLight instances which require brightness parameter
                    if hasattr(device, "turn_on"):
                        # Pass None as brightness to handle both TydomLight (requires brightness)
                        # and other devices (brightness is optional)
                        tasks.append(device.turn_on(None))
                    elif (
                        hasattr(device, "_tydom_client")
                        and hasattr(device, "_id")
                        and hasattr(device, "_endpoint")
                    ):
                        # Generic plug control
                        tasks.append(
                            device._tydom_client.put_devices_data(
                                device._id, device._endpoint, "levelCmd", "ON"
                            )
                        )
            except Exception as e:
                LOGGER.warning(
                    "Error controlling device %s in group %s: %s",
                    device_id,
                    self._device.device_name,
                    e,
                )

        # Execute all commands concurrently
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            LOGGER.debug("Group %s control completed", self._device.device_name)
        else:
            LOGGER.warning(
                "No devices could be controlled for group %s", self._device.device_name
            )

    async def _control_group_devices(self, action: str, **kwargs: Any) -> None:
        """Control all devices in the group with a specific action.

        Args:
            action: The action to perform (turn_on, turn_off, open, close, stop, set_position)
            **kwargs: Additional arguments for the action (e.g., position for set_position)

        """
        group_usage = getattr(self._device, "group_usage", None) or ""
        hub_instance = self._get_hub()

        if not hub_instance or not hasattr(hub_instance, "devices"):
            LOGGER.warning(
                "Cannot control group %s: hub not available", self._device.device_name
            )
            return

        LOGGER.info(
            "Group %s (%s) action %s - controlling %d device(s)",
            self._device.device_name,
            group_usage,
            action,
            len(self._device.device_ids),
        )

        tasks = []
        for device_id in self._device.device_ids:
            device = hub_instance.devices.get(device_id)
            if not device:
                continue

            try:
                if group_usage in ("shutter", "awning"):
                    # Cover control
                    if action == "open":
                        if hasattr(device, "up"):
                            tasks.append(device.up())
                        elif hasattr(device, "open"):
                            tasks.append(device.open())
                        elif (
                            hasattr(device, "_tydom_client")
                            and hasattr(device, "_id")
                            and hasattr(device, "_endpoint")
                        ):
                            tasks.append(
                                device._tydom_client.put_devices_data(
                                    device._id, device._endpoint, "levelCmd", "UP"
                                )
                            )
                    elif action == "close":
                        if hasattr(device, "down"):
                            tasks.append(device.down())
                        elif hasattr(device, "close"):
                            tasks.append(device.close())
                        elif (
                            hasattr(device, "_tydom_client")
                            and hasattr(device, "_id")
                            and hasattr(device, "_endpoint")
                        ):
                            tasks.append(
                                device._tydom_client.put_devices_data(
                                    device._id, device._endpoint, "levelCmd", "DOWN"
                                )
                            )
                    elif action == "stop":
                        if hasattr(device, "stop"):
                            tasks.append(device.stop())
                        elif (
                            hasattr(device, "_tydom_client")
                            and hasattr(device, "_id")
                            and hasattr(device, "_endpoint")
                        ):
                            tasks.append(
                                device._tydom_client.put_devices_data(
                                    device._id, device._endpoint, "levelCmd", "STOP"
                                )
                            )
                    elif action == "set_position" and "position" in kwargs:
                        position = kwargs["position"]
                        if hasattr(device, "set_position"):
                            tasks.append(device.set_position(position))
                        elif (
                            hasattr(device, "_tydom_client")
                            and hasattr(device, "_id")
                            and hasattr(device, "_endpoint")
                        ):
                            # Convert position (0-100) to levelCmd value
                            tasks.append(
                                device._tydom_client.put_devices_data(
                                    device._id,
                                    device._endpoint,
                                    "levelCmd",
                                    str(position),
                                )
                            )
                elif group_usage in ("light", "plug"):
                    # Light/plug control
                    if action == "turn_on":
                        if hasattr(device, "turn_on"):
                            # For lights, try to get brightness from kwargs or use None
                            brightness = kwargs.get("brightness")
                            tasks.append(device.turn_on(brightness))
                        elif (
                            hasattr(device, "_tydom_client")
                            and hasattr(device, "_id")
                            and hasattr(device, "_endpoint")
                        ):
                            tasks.append(
                                device._tydom_client.put_devices_data(
                                    device._id, device._endpoint, "levelCmd", "ON"
                                )
                            )
                    elif action == "turn_off":
                        if hasattr(device, "turn_off"):
                            tasks.append(device.turn_off())
                        elif (
                            hasattr(device, "_tydom_client")
                            and hasattr(device, "_id")
                            and hasattr(device, "_endpoint")
                        ):
                            tasks.append(
                                device._tydom_client.put_devices_data(
                                    device._id, device._endpoint, "levelCmd", "OFF"
                                )
                            )
            except Exception as e:
                LOGGER.warning(
                    "Error controlling device %s in group %s with action %s: %s",
                    device_id,
                    self._device.device_name,
                    action,
                    e,
                )

        # Execute all commands concurrently
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            LOGGER.debug(
                "Group %s action %s completed", self._device.device_name, action
            )
        else:
            LOGGER.warning(
                "No devices could be controlled for group %s with action %s",
                self._device.device_name,
                action,
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on all devices in the group (for lights/plugs)."""
        await self._control_group_devices("turn_on", **kwargs)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off all devices in the group (for lights/plugs)."""
        await self._control_group_devices("turn_off", **kwargs)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open all covers in the group (for shutters/awnings)."""
        await self._control_group_devices("open", **kwargs)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close all covers in the group (for shutters/awnings)."""
        await self._control_group_devices("close", **kwargs)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop all covers in the group (for shutters/awnings)."""
        await self._control_group_devices("stop", **kwargs)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set position for all covers in the group (for shutters/awnings).

        Args:
            position: Position (0-100) for the covers
            **kwargs: Additional arguments passed to the control method

        """
        await self._control_group_devices("set_position", **kwargs)

    async def async_activate_scenario(self, scenario_id: str) -> None:
        """Activate a scenario on this group."""
        await self._device.activate_scenario(scenario_id)


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
        self._device._ha_device = self
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


class HAReloadButton(ButtonEntity):
    """Button entity for reloading all devices."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:reload"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub, hass) -> None:
        """Initialize HAReloadButton."""
        self.hass = hass
        self._hub = hub
        self._attr_unique_id = f"{hub.hub_id}_reload_devices"
        self._attr_name = "Recharger les appareils"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.hub_id)},
            name=hub._name,
            manufacturer=hub.manufacturer,
        )

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._hub.reload_devices()


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
        self._device._ha_device = self
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
        self._device._ha_device = self
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
        self._device._ha_device = self
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
