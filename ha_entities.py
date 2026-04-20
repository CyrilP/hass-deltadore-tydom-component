"""Home assistant entities for Delta Dore Tydom."""

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
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
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


# ─── Shared mixin ──────────────────────────────────────────────────────────────


class TydomMixin:
    """Shared helpers for all Tydom HA entities."""

    _device: Any = None
    hass: Any = None

    def _get_hub(self):
        """Get the first hub instance from hass data."""
        if self.hass is None or DOMAIN not in self.hass.data:
            return None
        hubs = self.hass.data[DOMAIN]
        return next(iter(hubs.values())) if hubs else None

    def _get_gateway_id(self) -> str | None:
        """Get the Tydom gateway device_id for via_device linking."""
        hub = self._get_hub()
        if hub is None:
            return None
        for dev in getattr(hub, "devices", {}).values():
            if isinstance(dev, Tydom):
                return dev.device_id
        for ha_dev in getattr(hub, "ha_devices", {}).values():
            if isinstance(ha_dev, HATydom):
                return ha_dev._device.device_id
        return None

    def _build_device_info(self, *, via_gateway=True) -> DeviceInfo:
        """Build a standard DeviceInfo dict from device attributes."""
        d = self._device
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, d.device_id)},
            "name": getattr(d, "device_name", None)
            or f"Tydom Device {d.device_id[-6:]}",
            "manufacturer": str(getattr(d, "manufacturer", None) or "Delta Dore"),
        }
        if pn := getattr(d, "productName", None):
            info["model"] = str(pn)
        for attr in ("mainVersionHW", "keyVersionHW"):
            if (v := getattr(d, attr, None)) is not None:
                info["hw_version"] = str(v)
                break
        for attr in ("mainVersionSW", "keyVersionSW", "softVersion"):
            if (v := getattr(d, attr, None)) is not None:
                info["sw_version"] = str(v)
                break
        if via_gateway:
            gw_id = self._get_gateway_id()
            if gw_id and gw_id != d.device_id:
                info["via_device"] = (DOMAIN, gw_id)
        return info

    def _check_available(self) -> bool:
        """Check hub and connection availability."""
        if self._device is None:
            return False
        hub = self._get_hub()
        if hub is None or not getattr(hub, "online", False):
            return False
        client = getattr(hub, "_tydom_client", None)
        if client:
            conn = getattr(client, "_connection", None)
            if conn and getattr(conn, "closed", False):
                return False
        return True

    @property
    def available(self) -> bool:
        """Return True if device and hub are available."""
        return self._check_available()

    async def async_added_to_hass(self) -> None:
        """Register callback when entity is added to HA."""
        if self._device is not None:
            self._device.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Remove callback when entity is removed from HA."""
        if self._device is not None:
            self._device.remove_callback(self.async_write_ha_state)


# ─── Base HA entity with sensor auto-discovery ─────────────────────────────────


class HAEntity(TydomMixin):
    """Base for Tydom device HA entities with sensor auto-discovery."""

    sensor_classes: dict[str, Any] = {}
    state_classes: dict[str, Any] = {}
    units: dict[str, Any] = {}
    filtered_attrs: list[str] = []
    _registered_sensors: list[str] = []

    def _init_device(self, device, hass, suffix):
        """Common device initialization."""
        self.hass = hass
        self._device = device
        device._ha_device = self
        self._attr_unique_id = f"{device.device_id}_{suffix}"
        self._attr_name = device.device_name
        self._registered_sensors = []

    def get_sensors(self):
        """Auto-discover sensors from device attributes."""
        sensors = []
        for attribute, value in self._device.__dict__.items():
            if attribute.startswith("_") or value is None:
                continue
            if attribute in self._registered_sensors:
                continue
            alt_name = attribute.split("_")[0]
            if attribute in self.filtered_attrs or alt_name in self.filtered_attrs:
                continue

            def _lookup(mapping, key, alt):
                return mapping.get(key) or mapping.get(alt)

            sensor_class = _lookup(self.sensor_classes, attribute, alt_name)
            state_class = _lookup(self.state_classes, attribute, alt_name)
            unit = _lookup(self.units, attribute, alt_name)

            if isinstance(value, bool):
                sensors.append(
                    GenericBinarySensor(
                        self._device, sensor_class, attribute, attribute
                    )
                )
            else:
                sensors.append(
                    GenericSensor(
                        self._device, sensor_class, state_class,
                        attribute, attribute, unit,
                    )
                )
            self._registered_sensors.append(attribute)
            LOGGER.debug(
                "Nouveau capteur créé: %s.%s (type: %s, valeur: %s)",
                self._device.device_id, attribute,
                "binary" if isinstance(value, bool) else "sensor", value,
            )
        return sensors


# ─── Generic auto-discovered sensors ───────────────────────────────────────────


class GenericSensor(TydomMixin, SensorEntity):
    """Auto-discovered sensor from device attributes."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    diagnostic_attrs = [
        "config", "supervisionMode", "bootReference", "bootVersion",
        "keyReference", "keyVersionHW", "keyVersionStack", "keyVersionSW",
        "mainId", "mainReference", "mainVersionHW", "productName", "mac",
        "jobsMP", "softPlan", "softVersion",
    ]

    def __init__(self, device, device_class, state_class, name, attribute, unit):
        """Initialize the sensor."""
        self._device = device
        self._attr_unique_id = f"{device.device_id}_{name}"
        self._attr_name = name
        self._attribute = attribute
        self.entity_description = SensorEntityDescription(
            key=attribute, name=name, device_class=device_class,
            state_class=state_class, native_unit_of_measurement=unit,
            translation_key=f"sensor_{attribute}" if attribute else None,
        )
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit
        if name in self.diagnostic_attrs:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the native value of the sensor."""
        value = getattr(self._device, self._attribute, None)
        if (
            value is not None
            and self._attr_device_class == SensorDeviceClass.BATTERY
            and self._device._metadata is not None
            and self._attribute in self._device._metadata
        ):
            meta = self._device._metadata[self._attribute]
            value = ranged_value_to_percentage((meta["min"], meta["max"]), value)
        return value

    @property
    def device_info(self):
        """Return device info."""
        return self._build_device_info()


class GenericBinarySensor(TydomMixin, BinarySensorEntity):
    """Auto-discovered binary sensor from device attributes."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, device, device_class, name, attribute):
        """Initialize the sensor."""
        self._device = device
        self._attr_unique_id = f"{device.device_id}_{name}"
        self._attr_name = name
        self._attribute = attribute
        self.entity_description = BinarySensorEntityDescription(
            key=attribute, name=name, device_class=device_class,
            translation_key=f"binary_sensor_{attribute}" if attribute else None,
        )
        self._attr_device_class = device_class

    @property
    def is_on(self):
        """Return the state of the sensor."""
        return getattr(self._device, self._attribute, False)

    @property
    def device_info(self):
        """Return device info."""
        return self._build_device_info()


# ─── Tydom Gateway ─────────────────────────────────────────────────────────────


class HATydom(UpdateEntity, HAEntity):
    """Tydom Gateway update entity."""

    _attr_title = "Tydom"
    _attr_has_entity_name = False
    _attr_entity_category = None
    _attr_should_poll = False
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = UpdateEntityFeature.INSTALL
    _attr_icon = "mdi:update"

    sensor_classes = {"update_available": BinarySensorDeviceClass.UPDATE}
    filtered_attrs = [
        "absence.json", "anticip.json", "bdd_mig.json", "bdd.json",
        "bioclim.json", "collect.json", "config.json", "data_config.json",
        "gateway.dat", "groups.json", "info_col.json", "info_mig.json",
        "mom_api.json", "mom.json", "scenario.json", "site.json",
        "trigger.json", "TYDOM.dat",
    ]

    def __init__(self, device: Tydom, hass) -> None:
        """Initialize HATydom."""
        self._init_device(device, hass, "")
        self._attr_unique_id = device.device_id

    @property
    def device_info(self) -> DeviceInfo:
        """Gateway is the root device — no via_device."""
        return self._build_device_info(via_gateway=False)

    @property
    def installed_version(self) -> str | None:
        """Version currently installed."""
        v = getattr(self._device, "mainVersionSW", None)
        return str(v) if v is not None else None

    @property
    def latest_version(self) -> str | None:
        """Latest version available."""
        v = getattr(self._device, "mainVersionSW", None)
        return str(v) if v is not None else None

    async def async_install(self, version=None, backup=False, **kwargs) -> None:
        """Install firmware update."""
        await self._device.async_trigger_firmware_update()


# ─── Energy sensor ─────────────────────────────────────────────────────────────


class HAEnergy(SensorEntity, HAEntity):
    """Energy consumption sensor (Tywatt, etc.)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
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
        "energyDistrib": SensorDeviceClass.ENERGY,
        "outTemperature": SensorDeviceClass.TEMPERATURE,
    }

    state_classes = {
        "energyIndexTi1": SensorStateClass.TOTAL_INCREASING,
        "energyTotIndexWatt": SensorStateClass.TOTAL_INCREASING,
        "energyIndexECSWatt": SensorStateClass.TOTAL_INCREASING,
        "energyIndexHeatWatt": SensorStateClass.TOTAL_INCREASING,
        "energyIndexHeatGas": SensorStateClass.TOTAL_INCREASING,
        "energyIndex": SensorStateClass.TOTAL_INCREASING,
        "energyDistrib": SensorStateClass.TOTAL_INCREASING,
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
        "energyDistrib": UnitOfEnergy.WATT_HOUR,
        "outTemperature": UnitOfTemperature.CELSIUS,
    }

    def __init__(self, device: TydomEnergy, hass) -> None:
        """Initialize HAEnergy."""
        self._init_device(device, hass, "energy")

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return self._build_device_info()


# ─── Cover / Shutter ──────────────────────────────────────────────────────────


class HACover(CoverEntity, HAEntity):
    """Shutter cover entity."""

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
        """Initialize the cover."""
        self._init_device(device, hass, "cover")
        if hasattr(device, "position"):
            self._attr_supported_features |= (
                CoverEntityFeature.SET_POSITION
                | CoverEntityFeature.OPEN
                | CoverEntityFeature.CLOSE
                | CoverEntityFeature.STOP
            )
        if hasattr(device, "slope"):
            self._attr_supported_features |= CoverEntityFeature.SET_TILT_POSITION

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return self._build_device_info()

    @property
    def current_cover_position(self) -> int | None:
        """Return the current position of the cover."""
        return getattr(self._device, "position", None)

    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed (position 0)."""
        pos = getattr(self._device, "position", None)
        return pos == 0 if pos is not None else False

    @property
    def current_cover_tilt_position(self) -> int | None:
        """Return current tilt position."""
        return getattr(self._device, "slope", None)

    async def async_open_cover(self, **kwargs) -> None:
        """Open the cover."""
        await self._device.up()

    async def async_close_cover(self, **kwargs) -> None:
        """Close the cover."""
        await self._device.down()

    async def async_stop_cover(self, **kwargs):
        """Stop the cover."""
        await self._device.stop()

    async def async_set_cover_position(self, **kwargs) -> None:
        """Set the cover position."""
        await self._device.set_position(kwargs[ATTR_POSITION])

    async def async_open_cover_tilt(self, **kwargs):
        """Open the cover tilt."""
        await self._device.slope_open()

    async def async_close_cover_tilt(self, **kwargs):
        """Close the cover tilt."""
        await self._device.slope_close()

    async def async_set_cover_tilt_position(self, **kwargs):
        """Set the tilt position."""
        await self._device.set_slope_position(kwargs[ATTR_TILT_POSITION])

    async def async_stop_cover_tilt(self, **kwargs):
        """Stop the cover tilt."""
        await self._device.slope_stop()


# ─── Smoke detector ────────────────────────────────────────────────────────────


class HASmoke(BinarySensorEntity, HAEntity):
    """Smoke detector binary sensor."""

    _attr_should_poll = False
    _attr_icon = "mdi:smoke-detector"
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.SMOKE
    sensor_classes = {"batt_defect": BinarySensorDeviceClass.PROBLEM}

    def __init__(self, device: TydomSmoke, hass) -> None:
        """Initialize HASmoke."""
        self._init_device(device, hass, "smoke")

    @property
    def is_on(self) -> bool:
        """Return the state of the smoke sensor."""
        return bool(getattr(self._device, "techSmokeDefect", False))

    @property
    def device_info(self):
        """Return device info."""
        return self._build_device_info()


# ─── Climate / Boiler ──────────────────────────────────────────────────────────


class HaClimate(ClimateEntity, HAEntity):
    """Climate entity for boiler/thermostat."""

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
        self._init_device(device, hass, "climate")
        self._enable_turn_on_off_backwards_compatibility = False
        meta = device._metadata or {}

        # Mode mappings
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

        # Auto mode mapping
        hvac_enums = meta.get("hvacMode", {}).get("enum_values", [])
        if "AUTO" in hvac_enums:
            self.dict_modes_ha_to_dd[HVACMode.AUTO] = "AUTO"
        elif "ANTI_FROST" in hvac_enums:
            self.dict_modes_ha_to_dd[HVACMode.AUTO] = "ANTI_FROST"
        else:
            self.dict_modes_ha_to_dd[HVACMode.AUTO] = "AUTO"

        # Temperature limits
        if (v := getattr(device, "minSetpoint", None)) is not None:
            self._attr_min_temp = float(v)
        if (v := getattr(device, "maxSetpoint", None)) is not None:
            self._attr_max_temp = float(v)

        # Features
        self._attr_supported_features = (
            ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TARGET_TEMPERATURE
        )

        # Thermic level heat mode
        thermic_meta = meta.get("thermicLevel", {})
        if isinstance(thermic_meta, dict) and (
            "NORMAL" in thermic_meta or "AUTO" in thermic_meta
        ):
            self.dict_modes_ha_to_dd[HVACMode.HEAT] = "AUTO"

        # Preset modes
        self._attr_preset_modes = []
        comfort_enums = meta.get("comfortMode", {}).get("enum_values", [])
        thermic_enums = thermic_meta.get("enum_values", []) if isinstance(thermic_meta, dict) else []

        if comfort_enums:
            self._attr_preset_modes = [
                m for m in comfort_enums if m not in ("HEATING", "COOLING", "STOP")
            ]
        elif thermic_enums:
            self._attr_preset_modes = [
                m for m in thermic_enums if m not in ("STOP", "AUTO")
            ]
        if not self._attr_preset_modes and (
            hasattr(device, "comfortMode") or hasattr(device, "thermicLevel")
        ):
            self._attr_preset_modes = ["NORMAL", "ECO", "COMFORT"]

        if self._attr_preset_modes:
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE

        # HVAC modes
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.AUTO]
        for mode_dd, mode_ha in [("COOLING", HVACMode.COOL), ("HEATING", HVACMode.HEAT)]:
            if mode_dd in comfort_enums or mode_dd in hvac_enums:
                self._attr_hvac_modes.append(mode_ha)

        # Setpoint limits from metadata
        sp_meta = meta.get("setpoint", {})
        if "min" in sp_meta:
            self._attr_min_temp = sp_meta["min"]
        if "max" in sp_meta:
            self._attr_max_temp = sp_meta["max"]

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return self._build_device_info()

    @property
    def temperature_unit(self) -> str:
        """Return temperature unit."""
        return UnitOfTemperature.CELSIUS

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        for attr in ("hvacMode", "authorization", "thermicLevel"):
            v = getattr(self._device, attr, None)
            if v is not None and v in self.dict_modes_dd_to_ha:
                if attr == "authorization":
                    tl = getattr(self._device, "thermicLevel", None)
                    if tl in self.dict_modes_dd_to_ha:
                        return self.dict_modes_dd_to_ha[tl]
                return self.dict_modes_dd_to_ha[v]
        return HVACMode.OFF

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        for attr in ("temperature", "ambientTemperature"):
            if (v := getattr(self._device, attr, None)) is not None:
                return float(v)
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        mode = getattr(self._device, "hvacMode", None) or getattr(
            self._device, "authorization", None
        )
        if mode in ("HEATING", "NORMAL"):
            for attr in ("setpoint", "heatSetpoint"):
                if (v := getattr(self._device, attr, None)) is not None:
                    return float(v)
        elif mode == "COOLING":
            for attr in ("setpoint", "coolSetpoint"):
                if (v := getattr(self._device, attr, None)) is not None:
                    return float(v)
        return None

    async def async_set_hvac_mode(self, hvac_mode):
        """Set HVAC mode."""
        await self._device.set_hvac_mode(self.dict_modes_ha_to_dd[hvac_mode])

    @property
    def preset_mode(self) -> str | None:
        """Return current preset mode."""
        for attr in ("comfortMode", "thermicLevel"):
            v = getattr(self._device, attr, None)
            if v is not None and v in self._attr_preset_modes:
                return v
        return PRESET_NONE if self._attr_preset_modes else None

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode."""
        if preset_mode == PRESET_NONE:
            return
        meta = self._device._metadata or {}
        for field in ("comfortMode", "thermicLevel"):
            if preset_mode in meta.get(field, {}).get("enum_values", []):
                await self._device._tydom_client.put_devices_data(
                    self._device._id, self._device._endpoint, field, preset_mode
                )
                return

    async def async_set_temperature(self, **kwargs):
        """Set target temperature."""
        await self._device.set_temperature(str(kwargs.get(ATTR_TEMPERATURE)))


# ─── Window / Door (cover or binary_sensor) ───────────────────────────────────


class _OpenStateMixin:
    """Shared is_closed logic for Window and Door."""

    _device: Any

    @property
    def is_closed(self) -> bool | None:
        """Return True if closed, False if open, None if unknown."""
        v = getattr(self._device, "openState", None)
        if v is not None:
            return v == "LOCKED"
        v = getattr(self._device, "intrusionDetect", None)
        if v is not None:
            return not bool(v)
        return None


class HaWindow(_OpenStateMixin, CoverEntity, HAEntity):
    """Window entity (cover or binary sensor depending on attributes)."""

    _attr_should_poll = False
    _attr_device_class = CoverDeviceClass.WINDOW
    _attr_icon = "mdi:window-open"
    _attr_has_entity_name = True
    sensor_classes = {
        "battDefect": BinarySensorDeviceClass.PROBLEM,
        "intrusionDetect": BinarySensorDeviceClass.PROBLEM,
    }

    def __init__(self, device: TydomWindow, hass) -> None:
        """Initialize HaWindow."""
        self._init_device(device, hass, "cover")

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return self._build_device_info()


class HaDoor(_OpenStateMixin, CoverEntity, HAEntity):
    """Door entity (cover or binary sensor depending on attributes)."""

    _attr_should_poll = False
    _attr_device_class = CoverDeviceClass.DOOR
    _attr_icon = "mdi:door"
    _attr_has_entity_name = True
    sensor_classes = {
        "battDefect": BinarySensorDeviceClass.PROBLEM,
        "calibrationDefect": BinarySensorDeviceClass.PROBLEM,
        "intrusionDetect": BinarySensorDeviceClass.PROBLEM,
    }

    def __init__(self, device: TydomDoor, hass) -> None:
        """Initialize HaDoor."""
        self._init_device(device, hass, "cover")

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return self._build_device_info()


# ─── Gate / Garage (toggle covers) ────────────────────────────────────────────


class _ToggleCoverMixin:
    """Shared logic for Gate and Garage toggle covers."""

    _device: Any
    _attr_supported_features: CoverEntityFeature

    def _init_toggle_features(self):
        """Detect CLOSE and STOP capabilities from metadata."""
        meta = getattr(self._device, "_metadata", None) or {}
        level_meta = meta.get("levelCmd", {})
        enums = level_meta.get("enum_values", [])
        if "OFF" in enums:
            self._attr_supported_features |= CoverEntityFeature.CLOSE
        if "STOP" in enums:
            self._attr_supported_features |= CoverEntityFeature.STOP

    def _has_level_cmd(self, cmd: str) -> bool:
        meta = getattr(self._device, "_metadata", None) or {}
        return cmd in meta.get("levelCmd", {}).get("enum_values", [])

    async def async_open_cover(self, **kwargs) -> None:
        """Open the cover."""
        if self._has_level_cmd("ON"):
            await self._device.open()
        else:
            await self._device.toggle()

    async def async_close_cover(self, **kwargs) -> None:
        """Close the cover."""
        if self._has_level_cmd("OFF"):
            await self._device.close()
        else:
            await self._device.toggle()

    async def async_stop_cover(self, **kwargs) -> None:
        """Stop the cover."""
        if self._has_level_cmd("STOP"):
            await self._device.stop()
        else:
            await self._device.toggle()


class HaGate(_ToggleCoverMixin, CoverEntity, HAEntity):
    """Gate cover entity."""

    _attr_should_poll = False
    _attr_supported_features = CoverEntityFeature.OPEN
    _attr_device_class = CoverDeviceClass.GATE
    _attr_icon = "mdi:gate"
    _attr_has_entity_name = True

    def __init__(self, device: TydomGate, hass) -> None:
        """Initialize HaGate."""
        self._init_device(device, hass, "cover")
        self._init_toggle_features()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return self._build_device_info()

    @property
    def is_closed(self) -> bool | None:
        """Return if the gate is closed."""
        v = getattr(self._device, "openState", None)
        return v == "LOCKED" if v is not None else None


class HaGarage(_ToggleCoverMixin, CoverEntity, HAEntity):
    """Garage door cover entity."""

    _attr_should_poll = False
    _attr_supported_features = CoverEntityFeature.OPEN
    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_icon = "mdi:garage"
    _attr_has_entity_name = True
    sensor_classes = {"thermic_defect": BinarySensorDeviceClass.PROBLEM}

    def __init__(self, device: TydomGarage, hass) -> None:
        """Initialize HaGarage."""
        self._init_device(device, hass, "cover")
        self._init_toggle_features()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return self._build_device_info()

    @property
    def is_closed(self) -> bool | None:
        """Return if the garage door is closed."""
        level = getattr(self._device, "level", None)
        return level == 0 if level is not None else None


# ─── Light ─────────────────────────────────────────────────────────────────────


class HaLight(LightEntity, HAEntity):
    """Light entity."""

    _attr_should_poll = False
    _attr_icon = "mdi:lightbulb"
    _attr_has_entity_name = True
    sensor_classes = {"thermic_defect": BinarySensorDeviceClass.PROBLEM}

    BRIGHTNESS_SCALE = (0, 255)

    def __init__(self, device: TydomLight, hass) -> None:
        """Initialize HaLight."""
        self._init_device(device, hass, "light")
        has_level = device._metadata is not None and "level" in device._metadata
        mode = ColorMode.BRIGHTNESS if has_level else ColorMode.ONOFF
        self._attr_color_mode = mode
        self._attr_supported_color_modes = {mode}

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return self._build_device_info()

    @property
    def brightness(self) -> int | None:
        """Return brightness."""
        level = getattr(self._device, "level", None)
        if level is not None:
            return int(percentage_to_ranged_value(self.BRIGHTNESS_SCALE, float(level)))
        return None

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        level = getattr(self._device, "level", None)
        return bool(level != 0 if level is not None else False)

    async def async_turn_on(self, **kwargs):
        """Turn light on."""
        brightness = None
        if ATTR_BRIGHTNESS in kwargs:
            brightness = math.ceil(
                ranged_value_to_percentage(self.BRIGHTNESS_SCALE, kwargs[ATTR_BRIGHTNESS])
            )
        await self._device.turn_on(brightness)

    async def async_turn_off(self, **kwargs):
        """Turn light off."""
        await self._device.turn_off()


# ─── Alarm ─────────────────────────────────────────────────────────────────────


class HaAlarm(AlarmControlPanelEntity, HAEntity):
    """Alarm control panel entity."""

    _attr_should_poll = False
    _attr_icon = "mdi:shield-home"
    _attr_has_entity_name = True
    _attr_code_format = CodeFormat.NUMBER
    _attr_code_arm_required = True

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
    units = {"outTemperature": UnitOfTemperature.CELSIUS}

    def __init__(self, device: TydomAlarm, hass) -> None:
        """Initialize HaAlarm."""
        self._init_device(device, hass, "alarm")
        self._attr_supported_features = (
            AlarmControlPanelEntityFeature.ARM_AWAY
            | AlarmControlPanelEntityFeature.ARM_HOME
            | AlarmControlPanelEntityFeature.ARM_NIGHT
            | AlarmControlPanelEntityFeature.TRIGGER
        )

    def _get_active_zones(self) -> set[str]:
        """Return the set of currently active zone numbers (as strings)."""
        active = set()
        for i in range(1, 9):
            if getattr(self._device, f"zone{i}State", None) == "ON":
                active.add(str(i))
        return active

    @staticmethod
    def _parse_zone_config(zone_cfg: str | None) -> set[str]:
        """Parse a comma-separated zone config string into a set."""
        if not zone_cfg:
            return set()
        return {z.strip() for z in zone_cfg.split(",") if z.strip()}

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        """Return the alarm state."""
        mode = getattr(self._device, "alarmMode", None)
        state = getattr(self._device, "alarmState", None)
        if mode is None:
            return None
        if mode in ("OFF", "MAINTENANCE"):
            return AlarmControlPanelState.DISARMED
        if mode == "ON":
            return (
                AlarmControlPanelState.ARMED_AWAY
                if state == "OFF"
                else AlarmControlPanelState.TRIGGERED
            )
        if mode in ("ZONE", "PART"):
            if state != "OFF":
                return AlarmControlPanelState.TRIGGERED
            active = self._get_active_zones()
            night_zones = self._parse_zone_config(
                self._device._tydom_client._zone_night
            )
            if active and night_zones and active == night_zones:
                return AlarmControlPanelState.ARMED_NIGHT
            return AlarmControlPanelState.ARMED_HOME
        return None

    @property
    def device_info(self):
        """Return device info."""
        return self._build_device_info()

    async def async_alarm_disarm(self, code=None) -> None:
        """Disarm alarm."""
        await self._device.alarm_disarm(code)

    async def async_alarm_arm_away(self, code=None) -> None:
        """Arm away."""
        await self._device.alarm_arm_away(code)

    async def async_alarm_arm_home(self, code=None) -> None:
        """Arm home."""
        await self._device.alarm_arm_home(code)

    async def async_alarm_arm_night(self, code=None) -> None:
        """Arm night."""
        await self._device.alarm_arm_night(code)

    async def async_alarm_trigger(self, code=None) -> None:
        """Trigger alarm."""
        await self._device.alarm_trigger(code)

    async def async_acknowledge_events(self, code=None) -> None:
        """Acknowledge alarm events."""
        await self._device.acknowledge_events(code)

    async def async_get_events(self, event_type=None) -> list:
        """Get alarm events."""
        return await self._device.get_events(event_type or "UNACKED_EVENTS")


# ─── Weather ───────────────────────────────────────────────────────────────────


class HaWeather(WeatherEntity, HAEntity):
    """Weather entity."""

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
        """Initialize HaWeather."""
        self._init_device(device, hass, "weather")
        meta = device._metadata or {}
        for key in ("dailyPower", "currentPower"):
            unit = meta.get(key, {}).get("unit")
            if unit:
                self.units[key] = unit

    @property
    def native_temperature(self) -> float | None:
        """Return current temperature."""
        v = getattr(self._device, "outTemperature", None)
        return float(v) if v is not None else None

    @property
    def condition(self) -> str | None:
        """Return current weather condition."""
        w = getattr(self._device, "weather", None)
        return self.tydom_ha_condition.get(w) if w else None

    @property
    def device_info(self):
        """Return device info."""
        return self._build_device_info()


# ─── Water leak / Moisture ─────────────────────────────────────────────────────


class HaMoisture(BinarySensorEntity, HAEntity):
    """Water leak detector binary sensor."""

    _attr_should_poll = False
    _attr_icon = "mdi:water"
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    sensor_classes = {"batt_defect": BinarySensorDeviceClass.PROBLEM}

    def __init__(self, device: TydomWater, hass) -> None:
        """Initialize HaMoisture."""
        self._init_device(device, hass, "moisture")

    @property
    def is_on(self) -> bool:
        """Return the state of the sensor."""
        return bool(getattr(self._device, "techWaterDefect", False))

    @property
    def device_info(self):
        """Return device info."""
        return self._build_device_info()


# ─── Thermometer ───────────────────────────────────────────────────────────────


class HaThermo(SensorEntity, HAEntity):
    """Thermometer sensor entity."""

    _attr_icon = "mdi:thermometer"
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, device: TydomThermo, hass) -> None:
        """Initialize HaThermo."""
        self._init_device(device, hass, "thermos")
        self._registered_sensors = ["outTemperature"]

    @property
    def state(self) -> float | None:
        """Return the temperature."""
        v = getattr(self._device, "outTemperature", None)
        return float(v) if v is not None else None

    @property
    def device_info(self):
        """Return device info."""
        return self._build_device_info()


# ─── Generic sensor (unknown device types) ────────────────────────────────────


class HASensor(SensorEntity, HAEntity):
    """Generic sensor for unknown device types."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, device: TydomDevice, hass) -> None:
        """Initialize HASensor."""
        self._init_device(device, hass, "sensor")

    @property
    def native_value(self):
        """Return sensor value from common attributes."""
        for attr in ("level", "position", "temperature", "value", "state"):
            v = getattr(self._device, attr, None)
            if v is not None:
                return v
        return None

    @property
    def device_info(self):
        """Return device info."""
        return self._build_device_info()


# ─── Scene ─────────────────────────────────────────────────────────────────────


class HAScene(Scene, HAEntity):
    """Tydom scene entity."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    filtered_attrs = ["grpAct", "epAct", "scene_id", "type", "picto", "rule_id"]

    PICTO_ICON_MAPPING = {
        "light": "mdi:lightbulb", "lights": "mdi:lightbulb-group",
        "shutter": "mdi:window-shutter", "shutters": "mdi:window-shutter",
        "heating": "mdi:radiator", "thermostat": "mdi:thermostat",
        "alarm": "mdi:shield-home", "alarm_off": "mdi:shield-off",
        "alarm_on": "mdi:shield", "door": "mdi:door",
        "window": "mdi:window-open", "garage": "mdi:garage",
        "gate": "mdi:gate", "scene": "mdi:palette",
        "scenario": "mdi:palette", "home": "mdi:home",
        "away": "mdi:home-export", "night": "mdi:weather-night",
        "day": "mdi:weather-sunny", "comfort": "mdi:sofa",
        "eco": "mdi:leaf", "vacation": "mdi:airplane",
    }

    def __init__(self, device: TydomScene, hass) -> None:
        """Initialize HAScene."""
        self.hass = hass
        self._device = device
        device._ha_device = self
        self._attr_unique_id = f"{device.device_id}_scene"
        self._attr_name = device.device_name
        self._registered_sensors = []

    @property
    def icon(self) -> str:
        """Return the icon based on picto attribute."""
        picto = getattr(self._device, "picto", None)
        if not picto:
            return "mdi:palette"
        if isinstance(picto, str) and picto.startswith("mdi:"):
            return picto
        return self.PICTO_ICON_MAPPING.get(picto.lower().strip(), "mdi:palette")

    def _format_affected_items(self, items, item_type="group") -> str:
        """Format grpAct or epAct into a readable string."""
        if not items or not isinstance(items, list):
            return ""
        formatted = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item_type == "group":
                item_id = item.get("id")
            else:
                item_id = item.get("epId") or item.get("devId")
            if item_id is None:
                continue

            # Resolve name
            name = device_name.get(str(item_id))
            if not name and item_type == "endpoint":
                dev_id = item.get("devId")
                if dev_id:
                    name = device_name.get(f"{item_id}_{dev_id}") or device_name.get(
                        str(item_id)
                    )

            # Format state info
            state_parts = []
            for s in item.get("state", []):
                if isinstance(s, dict) and s.get("name") and s.get("value"):
                    state_parts.append(f"{s['name']}={s['value']}")
            suffix = f" ({', '.join(state_parts)})" if state_parts else ""
            label = name or f"{item_type.capitalize()} {item_id}"
            formatted.append(f"{label}{suffix}")
        return ", ".join(formatted)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs: dict[str, Any] = {}
        for src, key in [
            ("scene_id", "scenario_id"), ("_id", "scenario_id"),
            ("type", "scenario_type"), ("picto", "picto"), ("rule_id", "rule_id"),
        ]:
            v = getattr(self._device, src, None)
            if v is not None and key not in attrs:
                attrs[key] = str(v)

        grp = getattr(self._device, "grpAct", None)
        if grp:
            s = self._format_affected_items(grp, "group")
            if s:
                attrs["affected_groups"] = s
        ep = getattr(self._device, "epAct", None)
        if ep:
            s = self._format_affected_items(ep, "endpoint")
            if s:
                attrs["affected_endpoints"] = s
        return attrs

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return self._build_device_info()

    async def async_activate(self, **kwargs) -> None:
        """Activate the scene."""
        await self._device.activate()


# ─── Switch ────────────────────────────────────────────────────────────────────


class HASwitch(SwitchEntity, HAEntity):
    """Tydom switch entity."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:toggle-switch"

    def __init__(self, device: TydomDevice, hass) -> None:
        """Initialize HASwitch."""
        self._init_device(device, hass, "switch")

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return self._build_device_info()

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        level = getattr(self._device, "level", None)
        if level is not None:
            return bool(level != 0)
        if getattr(self._device, "on", None) is not None:
            return bool(self._device.on)
        state = getattr(self._device, "state", None)
        return state == "ON" if state is not None else False

    async def async_turn_on(self, **kwargs) -> None:
        """Turn switch on."""
        d = self._device
        if hasattr(d, "turn_on"):
            await d.turn_on()
        elif hasattr(d, "set_level"):
            await d.set_level(100)
        elif hasattr(d, "level"):
            await d._tydom_client.put_devices_data(d._id, d._endpoint, "level", "100")
        elif hasattr(d, "on"):
            await d._tydom_client.put_devices_data(d._id, d._endpoint, "on", "true")

    async def async_turn_off(self, **kwargs) -> None:
        """Turn switch off."""
        d = self._device
        if hasattr(d, "turn_off"):
            await d.turn_off()
        elif hasattr(d, "set_level"):
            await d.set_level(0)
        elif hasattr(d, "level"):
            await d._tydom_client.put_devices_data(d._id, d._endpoint, "level", "0")
        elif hasattr(d, "on"):
            await d._tydom_client.put_devices_data(d._id, d._endpoint, "on", "false")


# ─── Button ────────────────────────────────────────────────────────────────────


class HAButton(ButtonEntity, HAEntity):
    """Tydom button entity."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:button-cursor"

    def __init__(self, device: TydomDevice, hass, action_name: str, action_method: str) -> None:
        """Initialize HAButton."""
        self.hass = hass
        self._device = device
        device._ha_device = self
        self._action_method = action_method
        self._attr_unique_id = f"{device.device_id}_button_{action_name}"
        self._attr_name = action_name
        self._registered_sensors = []

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return self._build_device_info()

    async def async_press(self) -> None:
        """Handle the button press."""
        method = getattr(self._device, self._action_method, None)
        if method and callable(method):
            if inspect.iscoroutinefunction(method):
                await method()
            else:
                method()
        else:
            await self._device._tydom_client.put_devices_data(
                self._device._id, self._device._endpoint, self._action_method, "ON"
            )


# ─── Number ────────────────────────────────────────────────────────────────────


class HANumber(NumberEntity, HAEntity):
    """Tydom number entity."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, device, hass, attribute_name, min_value=None, max_value=None, step=None, unit=None):
        """Initialize HANumber."""
        self.hass = hass
        self._device = device
        device._ha_device = self
        self._attribute_name = attribute_name
        self._attr_unique_id = f"{device.device_id}_number_{attribute_name}"
        self._attr_name = attribute_name
        self._registered_sensors = []
        if min_value is not None:
            self._attr_native_min_value = min_value
        if max_value is not None:
            self._attr_native_max_value = max_value
        self._attr_native_step = step or 1.0
        self._attr_native_unit_of_measurement = unit

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return self._build_device_info()

    @property
    def native_value(self) -> float | None:
        """Return current value."""
        v = getattr(self._device, self._attribute_name, None)
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                return None
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        await self._device._tydom_client.put_devices_data(
            self._device._id, self._device._endpoint, self._attribute_name, str(value)
        )


# ─── Select ────────────────────────────────────────────────────────────────────


class HASelect(SelectEntity, HAEntity):
    """Tydom select entity."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, device, hass, attribute_name, options):
        """Initialize HASelect."""
        self.hass = hass
        self._device = device
        device._ha_device = self
        self._attribute_name = attribute_name
        self._attr_unique_id = f"{device.device_id}_select_{attribute_name}"
        self._attr_name = attribute_name
        self._attr_options = options
        self._registered_sensors = []

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return self._build_device_info()

    @property
    def current_option(self) -> str | None:
        """Return current selected option."""
        v = getattr(self._device, self._attribute_name, None)
        return str(v) if v is not None and str(v) in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await self._device._tydom_client.put_devices_data(
            self._device._id, self._device._endpoint, self._attribute_name, option
        )


# ─── Event ─────────────────────────────────────────────────────────────────────


class HAEvent(EventEntity, HAEntity):
    """Tydom event entity."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, device: TydomDevice, hass, event_type: str) -> None:
        """Initialize HAEvent."""
        self.hass = hass
        self._device = device
        device._ha_device = self
        self._attr_unique_id = f"{device.device_id}_event_{event_type}"
        self._attr_name = event_type
        self._attr_event_types = [event_type]
        self._registered_sensors = []

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return self._build_device_info()
