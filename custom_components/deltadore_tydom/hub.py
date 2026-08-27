"""A demonstration 'hub' that connects several devices."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientWebSocketResponse, ClientSession

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from .tydom.tydom_client import TydomClient
from .tydom.tydom_devices import (
    Tydom,
    TydomShutter,
    TydomEnergy,
    TydomSmoke,
    TydomBoiler,
    TydomWindow,
    TydomDoor,
    TydomGate,
    TydomGarage,
    TydomLight,
    TydomSwitch,
    TydomInterrupter,
    TydomPlug,
    TydomAlarm,
    TydomWeather,
    TydomWater,
    TydomThermo,
    TydomSun,
    TydomDevice,
    TydomScene,
    TydomGroup,
    TydomMoment,
    TydomRemoteControl,
)
from .ha_entities import (
    HATydom,
    HACover,
    HAEnergy,
    HASmoke,
    HaClimate,
    HaWindow,
    HaDoor,
    HaWindowOpening,
    HaDoorOpening,
    HaGate,
    HaGarage,
    HaLight,
    HAInterrupterBattery,
    HAInterrupterEvent,
    HaAlarm,
    HaWeather,
    HaMoisture,
    HaThermo,
    HaSun,
    HAGenericBinarySensor,
    HASensor,
    HAScene,
    HATwcShutterCover,
    HASwitch,
    HAButton,
    HADeviceAssociationButton,
    HAAlarmAcknowledgeButton,
    HAAlarmPendingEventsSensor,
    HAReloadButton,
    HARefreshEnergyButton,
    HACoverGroup,
    HALightGroup,
    HASwitchGroup,
    HAMoment,
    HARemoteBattery,
    HARemoteEvent,
    is_binary_attribute,
)

from .const import DOMAIN, LOGGER, get_polling_interval_for_validity, STRUCTURED_LOGGER
from .remote_registry_migration import migrate_legacy_remote_endpoint


ASSOCIATION_COMMAND = "modeAsso"
IDENTIFY_COMMAND = "localisation"
COMMAND_START_VALUE = "START"


@dataclass(frozen=True, slots=True)
class DiscoveryProfile:
    """One radio/product family accepted by the gateway install API."""

    label: str
    protocol: str
    type: str
    profile: str


@dataclass(frozen=True, slots=True)
class AssociationChoice:
    """A product-family choice shown under one user-facing category."""

    label: str
    profile_id: str | None


# These profiles are the request values used by the official TYDOM app. The
# gateway stays authoritative and accepts only values supported by its firmware.
DISCOVERY_PROFILES: dict[str, DiscoveryProfile] = {
    "alarm_x2d": DiscoveryProfile("TYXAL / alarm X2D", "X3D", "x2d_a", "alarm"),
    "alarm_x3d": DiscoveryProfile("TYXAL+ / alarm X3D", "X3D", "x3d_ppa", "alarm"),
    "aeraulic_zigbee": DiscoveryProfile("Aéraulique Zigbee", "ZIGBEE", "", "aeraulic"),
    "awning_x3d": DiscoveryProfile("Store banne X3D", "X3D", "x3d_rm", "awning"),
    "boiler_drive_x3d": DiscoveryProfile(
        "Chaudière Drive X3D", "X3D", "x3d_rm", "boilerDrive"
    ),
    "controller_x3d": DiscoveryProfile(
        "Contrôleur X3D", "X3D", "x3d_pps", "controller"
    ),
    "detector_x3d": DiscoveryProfile("Détecteur X3D", "X3D", "direct", "detector"),
    "electric_zigbee": DiscoveryProfile(
        "Équipement électrique Zigbee", "ZIGBEE", "", "electric"
    ),
    "light_x3d": DiscoveryProfile("Éclairage X3D", "X3D", "x3d_rm", "light"),
    "light_zigbee": DiscoveryProfile("Éclairage Zigbee", "ZIGBEE", "", "light"),
    "generic_x3d": DiscoveryProfile(
        "Produit générique X3D", "X3D", "x3d_pp", "generic"
    ),
    "meter_x3d": DiscoveryProfile("Compteur / mesure X3D", "X3D", "direct", "meter"),
    "multi_x3d": DiscoveryProfile(
        "Produit multifonction X3D", "X3D", "x3d_pped", "multi"
    ),
    "opening_x3d": DiscoveryProfile(
        "Ouvrant / porte / fenêtre X3D", "X3D", "x3d_rm", "opening"
    ),
    "pod_x3d": DiscoveryProfile("Produit POD X3D", "X3D", "x3d_rm", "pod"),
    "remote_x3d": DiscoveryProfile("Télécommande X3D", "X3D", "direct", "remote"),
    "rt2012_measure_x3d": DiscoveryProfile(
        "Mesure RT2012 X3D", "X3D", "x3d_pped", "rt2012_meas"
    ),
    "rt2012_no_outdoor_temp_x3d": DiscoveryProfile(
        "RT2012 sans sonde extérieure X3D", "X3D", "x3d_pped", "rt2012_noOutTemp"
    ),
    "rt2012_x3d": DiscoveryProfile("RT2012 X3D", "X3D", "x3d_pped", "rt2012"),
    "sensor_x3d": DiscoveryProfile("Capteur X3D", "X3D", "direct", "sensor"),
    "shared_thermic_x3d": DiscoveryProfile(
        "Chauffage partagé X3D", "X3D", "x3d_rmloop", "shThermic"
    ),
    "shutter_x3d": DiscoveryProfile("Volet roulant X3D", "X3D", "x3d_rm", "shutter"),
    "shutter_activhome_x3d": DiscoveryProfile(
        "Volet Activ'Home X3D", "X3D", "x3d_rm", "shutterActivHome"
    ),
    "shutter_brushless_x3d": DiscoveryProfile(
        "Volet Brushless X3D", "X3D", "x3d_rm", "shutterBrushless"
    ),
    "shutter_projected_x3d": DiscoveryProfile(
        "Volet projeté X3D", "X3D", "x3d_rm", "shutterProjected"
    ),
    "shutter_profalux_zigbee": DiscoveryProfile(
        "Volet Profalux Zigbee", "ZIGBEE", "PROFALUX", "shutter"
    ),
    "shutter_rmlp_x3d": DiscoveryProfile(
        "Volet RMLP X3D", "X3D", "x3d_rmlp", "shutter"
    ),
    "shutter_stella_zigbee": DiscoveryProfile(
        "Volet Stella Zigbee", "ZIGBEE", "", "shutter"
    ),
    "shutter_zigbee": DiscoveryProfile("Volet roulant Zigbee", "ZIGBEE", "", "shutter"),
    "temperature_x3d": DiscoveryProfile(
        "Sonde de température X3D", "X3D", "direct", "temperature"
    ),
    "thermic_x3d": DiscoveryProfile("Chauffage X3D", "X3D", "x3d_rm", "thermic"),
    "thermic_x2d": DiscoveryProfile("Chauffage X2D", "X3D", "x2d_d", "thermic"),
    "thermic_x3d_es": DiscoveryProfile(
        "Chauffage X3D (émetteur spécifique)", "X3D", "x3d_rm", "thermicES"
    ),
    "thermic_zigbee": DiscoveryProfile("Chauffage Zigbee", "ZIGBEE", "", "thermic"),
    "typass_atl_x3d": DiscoveryProfile("TYPASS ATL X3D", "X3D", "direct", "typassAtl"),
    "typass_saunier_x3d": DiscoveryProfile(
        "TYPASS Saunier X3D", "X3D", "direct", "typassSaunier"
    ),
    "weather_plt": DiscoveryProfile("Station météo", "PltService", "", "weather"),
}


# The official application first asks for a usage, then a product family. Keep
# its initial list of groups intact. A recipe may occur in several categories.
ASSOCIATION_CATALOG: dict[str, tuple[AssociationChoice, ...]] = {
    "Volets": (
        AssociationChoice("Récepteur volet roulant X3D", "shutter_x3d"),
        AssociationChoice("Volet Activ'Home", "shutter_activhome_x3d"),
        AssociationChoice("Volet Brushless", "shutter_brushless_x3d"),
        AssociationChoice("Volet projeté", "shutter_projected_x3d"),
        AssociationChoice("Volet Profalux Zigbee", "shutter_profalux_zigbee"),
        AssociationChoice("Volet Stella Zigbee", "shutter_stella_zigbee"),
        AssociationChoice("Volet roulant Zigbee", "shutter_zigbee"),
    ),
    "Éclairages": (
        AssociationChoice("Récepteur éclairage X3D", "light_x3d"),
        AssociationChoice("Éclairage Zigbee", "light_zigbee"),
    ),
    "Thermique": (
        AssociationChoice("Récepteur chauffage X3D", "thermic_x3d"),
        AssociationChoice("Récepteur chauffage X2D", "thermic_x2d"),
        AssociationChoice("Émetteur chauffage X3D spécifique", "thermic_x3d_es"),
        AssociationChoice("Chaudière Drive", "boiler_drive_x3d"),
        AssociationChoice("Chauffage Zigbee", "thermic_zigbee"),
        AssociationChoice("Chauffage partagé X3D", "shared_thermic_x3d"),
        AssociationChoice("TYPASS ATL", "typass_atl_x3d"),
        AssociationChoice("TYPASS Saunier", "typass_saunier_x3d"),
        AssociationChoice("Aéraulique Zigbee", "aeraulic_zigbee"),
    ),
    "Garage": (
        AssociationChoice("Récepteur portail / garage X3D", "light_x3d"),
        AssociationChoice("Récepteur volet / garage X3D", "shutter_x3d"),
        AssociationChoice("Volet Profalux Zigbee", "shutter_profalux_zigbee"),
    ),
    "Portail": (
        AssociationChoice("Récepteur portail X3D", "light_x3d"),
        AssociationChoice("Produit générique X3D", "generic_x3d"),
    ),
    "Alarme": (
        AssociationChoice("TYXAL / alarme X2D", "alarm_x2d"),
        AssociationChoice("TYXAL+ / alarme X3D", "alarm_x3d"),
        AssociationChoice("Détecteur X3D", "detector_x3d"),
        AssociationChoice("Télécommande / clavier X3D", "remote_x3d"),
    ),
    "Caméras": (AssociationChoice("Aucun profil local documenté", None),),
    "Consommation": (
        AssociationChoice("Compteur ou mesure X3D", "meter_x3d"),
        AssociationChoice("RT2012", "rt2012_x3d"),
        AssociationChoice("RT2012 sans sonde extérieure", "rt2012_no_outdoor_temp_x3d"),
        AssociationChoice("Mesure RT2012", "rt2012_measure_x3d"),
    ),
    "Porte": (
        AssociationChoice("Ouvrant, porte ou fenêtre X3D", "opening_x3d"),
        AssociationChoice("Produit POD X3D", "pod_x3d"),
    ),
    "Fenêtres": (
        AssociationChoice("Ouvrant, porte ou fenêtre X3D", "opening_x3d"),
        AssociationChoice("Produit POD X3D", "pod_x3d"),
    ),
    "Stores": (
        AssociationChoice("Store banne X3D", "awning_x3d"),
        AssociationChoice("Store projeté X3D", "shutter_projected_x3d"),
    ),
    "Prise": (
        AssociationChoice("Prise / équipement électrique Zigbee", "electric_zigbee"),
        AssociationChoice("Récepteur prise X3D", "light_x3d"),
    ),
    "Autres": (
        AssociationChoice("Produit générique X3D", "generic_x3d"),
        AssociationChoice("Produit multifonction X3D", "multi_x3d"),
        AssociationChoice("Produit POD X3D", "pod_x3d"),
        AssociationChoice("Station météo", "weather_plt"),
    ),
    "Télécommandes et claviers": (
        AssociationChoice("Télécommande X3D", "remote_x3d"),
        AssociationChoice("Contrôleur X3D", "controller_x3d"),
    ),
    "Interrupteurs": (
        AssociationChoice("Interrupteur / récepteur éclairage X3D", "light_x3d"),
        AssociationChoice("Éclairage Zigbee", "light_zigbee"),
        AssociationChoice("Contrôleur X3D", "controller_x3d"),
    ),
    "Capteurs": (
        AssociationChoice("Capteur X3D", "sensor_x3d"),
        AssociationChoice("Détecteur X3D", "detector_x3d"),
        AssociationChoice("Sonde de température X3D", "temperature_x3d"),
        AssociationChoice("Station météo", "weather_plt"),
    ),
}


def supports_command(device: Any, command: str) -> bool:
    """Return whether an endpoint advertises a writable START command."""
    metadata = getattr(device, "_metadata", None)
    if not isinstance(metadata, dict):
        return False
    command_metadata = metadata.get(command)
    if not isinstance(command_metadata, dict):
        return False
    permission = str(command_metadata.get("permission", "")).lower()
    values = command_metadata.get("enum_values")
    return (
        "w" in permission and isinstance(values, list) and COMMAND_START_VALUE in values
    )


async def start_command(device: Any, command: str) -> None:
    """Start an association or localisation command advertised by a device."""
    if not supports_command(device, command):
        raise ValueError(f"Device does not support the {command} command")
    endpoint_id = getattr(device, "_endpoint", None)
    if endpoint_id is None:
        raise ValueError("Device has no TYDOM endpoint")
    await device._tydom_client.put_devices_data(  # noqa: SLF001
        device._id,
        endpoint_id,
        command,
        COMMAND_START_VALUE,  # noqa: SLF001
    )


def get_association_choices(category: str) -> tuple[AssociationChoice, ...]:
    """Return the product families available under one displayed category."""
    try:
        return ASSOCIATION_CATALOG[category]
    except KeyError as err:
        raise ValueError(f"Unknown TYDOM association category: {category}") from err


def get_install_payload(
    profile_id: str, network: int | None = None
) -> dict[str, str | int]:
    """Build a validated ``POST /devices/install`` request body."""
    try:
        profile = DISCOVERY_PROFILES[profile_id]
    except KeyError as err:
        raise ValueError(f"Unknown TYDOM discovery profile: {profile_id}") from err
    payload: dict[str, str | int] = {
        "protocol": profile.protocol,
        "type": profile.type,
        "profile": profile.profile,
    }
    if network is not None:
        if network < 0:
            raise ValueError("TYDOM network must be a non-negative integer")
        payload["net"] = network
    elif profile.protocol == "ZIGBEE":
        payload["net"] = 0
    return payload


async def start_product_association(
    tydom_hub, profile_id: str, network: int | None = None
) -> dict[str, str | int]:
    """Start association on one configured TYDOM/Tywell gateway."""
    payload = get_install_payload(profile_id, network)
    await tydom_hub._tydom_client.post_device_install(payload)
    return payload


async def remove_product_association(device) -> None:
    """Remove one already-associated product from its TYDOM gateway."""
    device_id = getattr(device, "_id", None)
    tydom_client = getattr(device, "_tydom_client", None)
    if device_id is None or tydom_client is None:
        raise ValueError("The selected entity does not expose a TYDOM device")
    await tydom_client.delete_device(device_id)


class _GatewayAssociationEntity:
    """Shared Home Assistant device information for gateway controls."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, tydom_hub) -> None:
        self._hub = tydom_hub
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tydom_hub.hub_id)},
            name=tydom_hub._name,
            manufacturer=tydom_hub.manufacturer,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._hub.register_association_control(self)

    async def async_will_remove_from_hass(self) -> None:
        self._hub.unregister_association_control(self)
        await super().async_will_remove_from_hass()


class HAGatewayAssociationCategorySelect(_GatewayAssociationEntity, SelectEntity):
    """Choose the intended usage before choosing a product family."""

    _attr_icon = "mdi:shape-outline"

    def __init__(self, tydom_hub) -> None:
        """Initialise the association-category selector."""
        super().__init__(tydom_hub)
        self._attr_unique_id = f"{tydom_hub.hub_id}_association_category"
        self._attr_name = "Catégorie à associer"

    @property
    def options(self) -> list[str]:
        """Return the product categories from the official workflow."""
        return list(self._hub.association_categories)

    @property
    def current_option(self) -> str:
        """Return the selected product category."""
        return self._hub.association_category

    async def async_select_option(self, option: str) -> None:
        """Select a category and reset the product selection if needed."""
        self._hub.set_association_category(option)


class HAGatewayAssociationProductSelect(_GatewayAssociationEntity, SelectEntity):
    """Choose a product family compatible with the selected category."""

    _attr_icon = "mdi:devices"

    def __init__(self, tydom_hub) -> None:
        """Initialise the product-family selector."""
        super().__init__(tydom_hub)
        self._attr_unique_id = f"{tydom_hub.hub_id}_association_product"
        self._attr_name = "Produit à associer"

    @property
    def options(self) -> list[str]:
        """Return products for the selected category only."""
        return list(self._hub.association_product_labels)

    @property
    def current_option(self) -> str:
        """Return the selected product-family label."""
        return self._hub.association_product_label

    async def async_select_option(self, option: str) -> None:
        """Select the protocol profile represented by an option."""
        self._hub.set_association_product(option)


class HAGatewayStartAssociationButton(_GatewayAssociationEntity, ButtonEntity):
    """Start the generic add-product workflow on the selected gateway."""

    _attr_icon = "mdi:link-plus"

    def __init__(self, tydom_hub) -> None:
        """Initialise the start-association button."""
        super().__init__(tydom_hub)
        self._attr_unique_id = f"{tydom_hub.hub_id}_start_product_association"
        self._attr_name = "Démarrer l'association"

    @property
    def available(self) -> bool:
        """Disable the action if the category has no local install profile."""
        return self._hub.association_product_supported

    async def async_press(self) -> None:
        """Start association using the selected product family."""
        await self._hub.start_selected_product_association()


class Hub:
    """Hub for Delta Dore Tydom."""

    manufacturer = "Delta Dore"

    def handle_event(self, event):
        """Event callback."""
        pass

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        host: str,
        mac: str,
        password: str,
        refresh_interval: str,
        zone_home: str,
        zone_away: str,
        zone_night: str,
        alarmpin: str,
    ) -> None:
        """Init hub."""
        self._host = host
        self._mac = mac
        self._pass = password
        self._refresh_interval = int(refresh_interval) * 60
        self._zone_home = zone_home
        self._zone_away = zone_away
        self._zone_night = zone_night
        self._pin = alarmpin
        self._hass = hass
        self._entry = entry
        self._name = mac
        self._id = "Tydom-" + mac[6:]
        self.devices = {}
        self.ha_devices = {}
        self.add_cover_callback = None
        self.add_sensor_callback = None
        self.add_climate_callback = None
        self.add_light_callback = None
        self.add_lock_callback = None
        self.add_alarm_callback = None
        self.add_update_callback = None
        self.add_weather_callback = None
        self.add_binary_sensor_callback = None
        self.add_scene_callback = None
        self.add_switch_callback = None
        self.add_button_callback = None
        self.add_number_callback = None
        self.add_select_callback = None
        self.add_event_callback = None

        self._tydom_client = TydomClient(
            hass=self._hass,
            id=self._id,
            mac=self._mac,
            host=self._host,
            password=self._pass,
            zone_home=self._zone_home,
            zone_away=self._zone_away,
            zone_night=self._zone_night,
            alarm_pin=self._pin,
            event_callback=self.handle_event,
        )

        self.online = True
        self._reload_button_created = False
        self._association_controls_created = False
        self._association_controls: list = []
        self._association_category = next(iter(ASSOCIATION_CATALOG))
        self._association_profile = get_association_choices(self._association_category)[
            0
        ].profile_id
        self._refresh_energy_buttons_created: set[str] = set()
        self._device_association_buttons_created: set[tuple[str, str]] = set()
        self._remote_battery_entities: dict[str, HARemoteBattery] = {}
        self._interrupter_battery_entities: dict[str, HAInterrupterBattery] = {}
        self._twc_scene_sets: dict[str, dict[str, HAScene]] = {}
        self._twc_cover_entities: dict[str, HATwcShutterCover] = {}
        self._shutting_down = False

        # Polling cache for optimization
        self._polling_cache: dict[
            tuple[str, str], int
        ] = {}  # (device_key, attr_name) -> interval
        self._polling_cache_timestamp = 0
        self._polling_cache_ttl = 300  # 5 minutes
        self._next_poll_due: dict[int, float] = {}  # interval -> monotonic due time

        # Device factory registry for create_ha_device
        self._device_factories: dict[type, Callable] = {
            Tydom: self._create_tydom_device,
            TydomShutter: self._create_shutter_device,
            TydomEnergy: self._create_energy_device,
            TydomSmoke: self._create_smoke_device,
            TydomBoiler: self._create_boiler_device,
            TydomWindow: self._create_window_device,
            TydomDoor: self._create_door_device,
            TydomGate: self._create_gate_device,
            TydomGarage: self._create_garage_device,
            TydomLight: self._create_light_device,
            TydomSwitch: self._create_switch_device,
            TydomInterrupter: self._create_interrupter_device,
            TydomPlug: self._create_switch_device,
            TydomAlarm: self._create_alarm_device,
            TydomWeather: self._create_weather_device,
            TydomWater: self._create_water_device,
            TydomThermo: self._create_thermo_device,
            TydomSun: self._create_sun_device,
            TydomScene: self._create_scene_device,
            TydomGroup: self._create_group_device,
            TydomMoment: self._create_moment_device,
            TydomRemoteControl: self._create_remote_control_device,
            TydomDevice: self._create_generic_device,
        }

    def update_config(self, refresh_interval, zone_home, zone_away, zone_night):
        """Update zone configuration."""
        self._tydom_client.update_config(zone_home, zone_away, zone_night)
        self._refresh_interval = int(refresh_interval) * 60
        self._zone_home = zone_home
        self._zone_away = zone_away
        self._zone_night = zone_night

    @property
    def hub_id(self) -> str:
        """ID for dummy hub."""
        return self._id

    async def connect(self) -> ClientWebSocketResponse:
        """Connect to Tydom."""
        if self._shutting_down:
            raise asyncio.CancelledError()
        connection = await self._tydom_client.async_connect_and_initialise()
        if self._shutting_down:
            await self._tydom_client.async_disconnect()
            raise asyncio.CancelledError()
        return connection

    async def async_shutdown(self) -> None:
        """Stop background work and release the Tydom websocket."""
        if self._shutting_down:
            return
        self._shutting_down = True
        await self._tydom_client.async_disconnect()

    async def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep in short slices so shutdown is picked up quickly."""
        remaining = seconds
        while remaining > 0 and not self._shutting_down:
            await asyncio.sleep(min(1.0, remaining))
            remaining -= 1.0

    @staticmethod
    async def get_tydom_credentials(
        session: ClientSession, email: str, password: str, macaddress: str
    ):
        """Get Tydom credentials."""
        return await TydomClient.async_get_credentials(
            session, email, password, macaddress
        )

    async def test_credentials(self) -> None:
        """Validate credentials."""
        connection = await self._tydom_client.async_connect()
        if hasattr(connection, "close"):
            try:
                await asyncio.wait_for(connection.close(), timeout=3.0)
            except TimeoutError:
                LOGGER.warning(
                    "Timed out closing Tydom websocket after credential test"
                )

    def ready(self) -> bool:
        """Check if we're ready to work."""
        # and self.add_alarm_callback is not None
        is_ready = (
            self.add_cover_callback is not None
            and self.add_sensor_callback is not None
            and self.add_climate_callback is not None
            and self.add_light_callback is not None
            and self.add_lock_callback is not None
            and self.add_update_callback is not None
            and self.add_alarm_callback is not None
            and self.add_weather_callback is not None
            and self.add_scene_callback is not None
            and self.add_switch_callback is not None
            and self.add_button_callback is not None
            and self.add_number_callback is not None
            and self.add_select_callback is not None
            and self.add_event_callback is not None
            and self.add_binary_sensor_callback is not None
        )
        # Créer le bouton de rechargement une fois que les callbacks sont prêts
        if (
            is_ready
            and not self._reload_button_created
            and self.add_button_callback is not None
        ):
            reload_button = HAReloadButton(self, self._hass)
            self.add_button_callback([reload_button])
            self._reload_button_created = True
            LOGGER.debug("Bouton de rechargement créé")
        if (
            is_ready
            and not self._association_controls_created
            and self.add_button_callback is not None
            and self.add_select_callback is not None
        ):
            self.add_select_callback(
                [
                    HAGatewayAssociationCategorySelect(self),
                    HAGatewayAssociationProductSelect(self),
                ]
            )
            self.add_button_callback([HAGatewayStartAssociationButton(self)])
            self._association_controls_created = True
            LOGGER.debug("Gateway product-association controls created")
        return is_ready

    @property
    def association_categories(self) -> tuple[str, ...]:
        """Return the usage categories offered by gateway association."""
        return tuple(ASSOCIATION_CATALOG)

    @property
    def association_category(self) -> str:
        """Return the currently selected association category."""
        return self._association_category

    @property
    def association_product_labels(self) -> tuple[str, ...]:
        """Return product families for the selected category."""
        return tuple(
            choice.label
            for choice in get_association_choices(self._association_category)
        )

    @property
    def association_product_label(self) -> str:
        """Return the label of the currently selected product family."""
        return next(
            choice.label
            for choice in get_association_choices(self._association_category)
            if choice.profile_id == self._association_profile
        )

    @property
    def association_product_supported(self) -> bool:
        """Whether the current choice has a documented local install profile."""
        return self._association_profile is not None

    def register_association_control(self, entity) -> None:
        """Register a gateway control that needs selection-state updates."""
        if entity not in self._association_controls:
            self._association_controls.append(entity)

    def unregister_association_control(self, entity) -> None:
        """Forget a gateway control removed by Home Assistant."""
        if entity in self._association_controls:
            self._association_controls.remove(entity)

    def _notify_association_controls(self) -> None:
        """Update the category/product controls after a selection change."""
        for entity in self._association_controls:
            entity.async_write_ha_state()

    def set_association_category(self, category: str) -> None:
        """Choose a usage category and its first valid product family."""
        choices = get_association_choices(category)
        self._association_category = category
        if not any(
            choice.profile_id == self._association_profile for choice in choices
        ):
            self._association_profile = choices[0].profile_id
        self._notify_association_controls()

    def set_association_product(self, label: str) -> None:
        """Choose one product family from the current category."""
        for choice in get_association_choices(self._association_category):
            if choice.label == label:
                self._association_profile = choice.profile_id
                self._notify_association_controls()
                return
        raise ValueError(
            f"{label!r} is not available for {self._association_category!r}"
        )

    async def start_selected_product_association(self) -> None:
        """Start association using the product selected in the gateway controls."""
        if self._association_profile is None:
            raise ValueError(
                "The selected category has no documented local TYDOM install profile"
            )
        payload = await start_product_association(self, self._association_profile)
        LOGGER.info(
            "Started gateway association for %s on config entry %s",
            payload,
            self._entry.entry_id,
        )

    def _add_discovered_entities(self, entities: list) -> None:
        """Add discovered entities to the platform matching their entity type."""
        binary_sensors = [
            entity for entity in entities if isinstance(entity, BinarySensorEntity)
        ]
        sensors = [
            entity for entity in entities if not isinstance(entity, BinarySensorEntity)
        ]

        if sensors and self.add_sensor_callback is not None:
            self.add_sensor_callback(sensors)
        if binary_sensors and self.add_binary_sensor_callback is not None:
            self.add_binary_sensor_callback(binary_sensors)

    async def setup(self, connection: ClientWebSocketResponse) -> None:
        """Listen to tydom events."""
        # wait for callbacks to become available
        while not self.ready():
            if self._shutting_down:
                return
            await asyncio.sleep(1)
        LOGGER.debug("Listen to tydom events")

        # Validate data consistency after initial setup
        await self._validate_data_consistency()
        while not self._shutting_down:
            devices = await self._tydom_client.consume_messages()
            if self._shutting_down:
                return
            if devices is not None:
                for device in devices:
                    if device.device_id not in self.devices:
                        self.devices[device.device_id] = device
                        STRUCTURED_LOGGER.device_operation(
                            "debug",
                            "create",
                            device.device_id,
                            type=device.device_type,
                            name=device.device_name,
                        )
                        await self.create_ha_device(device)
                    else:
                        # Check for collision: same device_id but different device
                        stored_device = self.devices[device.device_id]
                        if stored_device is not device and (
                            stored_device.device_name != device.device_name
                            or stored_device.device_type != device.device_type
                        ):
                            # Resolve collision: update stored device with new data
                            STRUCTURED_LOGGER.device_operation(
                                "warning",
                                "collision_resolved",
                                device.device_id,
                                stored_name=stored_device.device_name,
                                stored_type=stored_device.device_type,
                                new_name=device.device_name,
                                new_type=device.device_type,
                                action="updating_existing",
                            )

                            # Update stored device attributes to match new device
                            # This ensures consistency and prevents future collisions
                            if hasattr(stored_device, "_name"):
                                stored_device._name = device.device_name
                            if hasattr(stored_device, "_type"):
                                stored_device._type = device.device_type

                            # Also update metadata if available
                            if (
                                hasattr(device, "_metadata")
                                and device._metadata is not None
                            ):
                                if hasattr(stored_device, "_metadata"):
                                    stored_device._metadata = device._metadata

                        LOGGER.debug(
                            "update device %s : %s",
                            device.device_id,
                            self.devices[device.device_id],
                        )
                        await self.update_ha_device(
                            self.devices[device.device_id], device
                        )
                self._refresh_group_members()

    def _refresh_group_members(self) -> None:
        """Resolve group members again after each protocol message batch."""
        for device in self.devices.values():
            if not isinstance(device, TydomGroup):
                continue
            ha_device = getattr(device, "_ha_device", None)
            if ha_device is not None and hasattr(ha_device, "refresh_members"):
                ha_device.refresh_members()

    async def create_ha_device(self, device: TydomDevice) -> None:
        """Create a new HA device using factory pattern.

        This method uses a factory pattern to delegate device-specific creation
        logic to specialized methods. This improves maintainability and reduces
        complexity compared to a large match/case statement.

        Args:
            device: TydomDevice instance to create Home Assistant entity for

        Raises:
            None: Exceptions are caught and logged, but do not propagate

        """
        device_type = type(device)
        factory = self._device_factories.get(device_type)

        if factory is None:
            LOGGER.error(
                "Unsupported device type: %s for device %s",
                device_type.__name__,
                device.device_id,
            )
            return

        try:
            await factory(device)
            self._maybe_create_device_association_buttons(device)
        except Exception as e:
            LOGGER.exception(
                "Error creating HA device for %s (%s): %s",
                device.device_id,
                device_type.__name__,
                e,
            )

    async def _create_tydom_device(self, device: Tydom) -> None:
        """Create Tydom gateway device."""
        LOGGER.debug("Create Tydom gateway %s", device.device_id)
        self.devices[device.device_id] = device
        ha_device = HATydom(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_update_callback is not None:
            self.add_update_callback([ha_device])
        self._add_discovered_entities(ha_device.get_sensors())
        # Le bouton de rechargement est créé dans ready() pour être toujours présent

    async def _create_shutter_device(self, device: TydomShutter) -> None:
        """Create shutter/cover device."""
        LOGGER.debug("Create cover %s", device.device_id)
        ha_device = HACover(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_cover_callback is not None:
            self.add_cover_callback([ha_device])
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_energy_device(self, device: TydomEnergy) -> None:
        """Create energy consumption device."""
        LOGGER.debug("Create conso %s", device.device_id)
        ha_device = HAEnergy(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        # HAEnergy itself carries no device_class/unit/value: it only groups
        # the per-attribute sensors below and must not be added as an entity,
        # or it shows up as a useless "unknown" sensor (e.g. sensor.tywatt_tywatt).
        self._add_discovered_entities(ha_device.get_sensors())
        # The device has no energy* attribute yet at first discovery (they only
        # appear once the first cdata poll response is parsed), so this rarely
        # creates the button here -- update_ha_device() does it once data arrives.
        self._maybe_create_refresh_energy_button(device, ha_device)

    def _maybe_create_refresh_energy_button(
        self, device: TydomEnergy, ha_device: HAEnergy
    ) -> None:
        """Create one on-demand refresh button per real Tywatt device.

        Some TydomEnergy devices only carry outTemperature (e.g. an outdoor
        probe reusing this class), not real Tywatt consumption data -- only
        attach the button to a device that actually exposes one of the polled
        cdata attributes (energyIndex/energyInstant/energyHisto/energyDistrib),
        or it ends up on the wrong HA device.
        """
        has_energy_attrs = any(
            key.startswith("energy") for key in vars(device) if not key.startswith("_")
        )
        device_key = device.device_id
        if (
            has_energy_attrs
            and device_key not in self._refresh_energy_buttons_created
            and self.add_button_callback is not None
        ):
            refresh_energy_button = HARefreshEnergyButton(self, self._hass, ha_device)
            self.add_button_callback([refresh_energy_button])
            self._refresh_energy_buttons_created.add(device_key)
            LOGGER.debug("Created energy refresh button for %s", device_key)

    async def _create_smoke_device(self, device: TydomSmoke) -> None:
        """Create smoke detector device."""
        LOGGER.debug("Create smoke %s", device.device_id)
        ha_device = HASmoke(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities([ha_device, *ha_device.get_sensors()])

    async def _create_boiler_device(self, device: TydomBoiler) -> None:
        """Create boiler/climate device."""
        LOGGER.debug("Create boiler %s", device.device_id)
        ha_device = HaClimate(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_climate_callback is not None:
            self.add_climate_callback([ha_device])
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_window_device(self, device: TydomWindow) -> None:
        """Create window device (cover if motorized, else binary_sensor)."""
        LOGGER.debug("Create window %s", device.device_id)

        # Décision automatique selon les attributs du device
        if any(
            hasattr(device, a) for a in ["position", "positionCmd", "level", "levelCmd"]
        ):
            LOGGER.debug(
                "Window %s has motor control → adding as cover",
                device.device_id,
            )
            ha_device = HaWindow(device, self._hass)
            if self.add_cover_callback:
                self.add_cover_callback([ha_device])
        else:
            LOGGER.debug(
                "Window %s is passive → adding as binary_sensor",
                device.device_id,
            )
            ha_device = HaWindowOpening(device, self._hass)
            if self.add_binary_sensor_callback:
                self.add_binary_sensor_callback([ha_device])

        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_door_device(self, device: TydomDoor) -> None:
        """Create door device (cover if motorized, else binary_sensor)."""
        LOGGER.debug("Create door %s", device.device_id)

        # Décision automatique selon les attributs du device
        # podPosition : attribut utilisé par les portes motorisées KLINE
        # (device_type "belmDoor" / "klineDoor"), en lecture/écriture avec
        # les valeurs OPEN / CLOSE / LOCK.
        if any(
            hasattr(device, a)
            for a in [
                "position",
                "positionCmd",
                "level",
                "levelCmd",
                "podPosition",
            ]
        ):
            LOGGER.debug(
                "Door %s has motor control → adding as cover", device.device_id
            )
            ha_device = HaDoor(device, self._hass)
            if self.add_cover_callback:
                self.add_cover_callback([ha_device])
        else:
            LOGGER.debug(
                "Door %s is passive → adding as binary_sensor", device.device_id
            )
            ha_device = HaDoorOpening(device, self._hass)
            if self.add_binary_sensor_callback:
                self.add_binary_sensor_callback([ha_device])

        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_gate_device(self, device: TydomGate) -> None:
        """Create gate device."""
        LOGGER.debug("Create gate %s", device.device_id)
        if device.is_toggle_only:
            ha_device = HAButton(
                device,
                self._hass,
                "Toggle",
                "toggle",
                icon="mdi:gate",
                primary=True,
            )
            if self.add_button_callback is not None:
                self.add_button_callback([ha_device])
        else:
            ha_device = HaGate(device, self._hass)
            if self.add_cover_callback is not None:
                self.add_cover_callback([ha_device])
        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_garage_device(self, device: TydomGarage) -> None:
        """Create garage device."""
        LOGGER.debug("Create garage %s", device.device_id)
        if device.is_toggle_only:
            ha_device = HAButton(
                device,
                self._hass,
                "Toggle",
                "toggle",
                icon="mdi:garage",
                primary=True,
            )
            if self.add_button_callback is not None:
                self.add_button_callback([ha_device])
        else:
            ha_device = HaGarage(device, self._hass)
            if self.add_cover_callback is not None:
                self.add_cover_callback([ha_device])
        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_light_device(self, device: TydomLight) -> None:
        """Create light device."""
        LOGGER.debug("Create light %s", device.device_id)
        ha_device = HaLight(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_light_callback is not None:
            self.add_light_callback([ha_device])
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_interrupter_device(self, device: TydomInterrupter) -> None:
        """Create a wall-switch event entity and one battery diagnostic."""
        LOGGER.debug("Create wall-switch button %s", device.device_id)
        ha_device = HAInterrupterEvent(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_event_callback is not None:
            self.add_event_callback([ha_device])

        battery = self._interrupter_battery_entities.get(device.physical_device_id)
        if battery is None:
            battery = HAInterrupterBattery(device, self._hass)
            self._interrupter_battery_entities[device.physical_device_id] = battery
            if self.add_binary_sensor_callback is not None:
                self.add_binary_sensor_callback([battery])
        else:
            battery.add_device(device)

    async def _create_switch_device(self, device: TydomPlug | TydomSwitch) -> None:
        """Create a switch device for a controllable binary output."""
        LOGGER.debug("Create switch %s", device.device_id)
        ha_device = HASwitch(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_switch_callback is not None:
            self.add_switch_callback([ha_device])
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_alarm_device(self, device: TydomAlarm) -> None:
        """Create alarm device."""
        LOGGER.debug("Create alarm %s", device.device_id)
        ha_device = HaAlarm(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_alarm_callback is not None:
            self.add_alarm_callback([ha_device])
        if self.add_button_callback is not None:
            self.add_button_callback([HAAlarmAcknowledgeButton(device, self._hass)])
        self._add_discovered_entities(
            [HAAlarmPendingEventsSensor(device, self._hass), *ha_device.get_sensors()]
        )

    async def _create_weather_device(self, device: TydomWeather) -> None:
        """Create weather device."""
        LOGGER.debug("Create weather %s", device.device_id)
        ha_device = HaWeather(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_weather_callback is not None:
            self.add_weather_callback([ha_device])
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_water_device(self, device: TydomWater) -> None:
        """Create water/moisture device."""
        LOGGER.debug("Create moisture %s", device.device_id)
        ha_device = HaMoisture(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities([ha_device, *ha_device.get_sensors()])

    async def _create_thermo_device(self, device: TydomThermo) -> None:
        """Create thermostat device."""
        LOGGER.debug("Create thermo %s", device.device_id)
        ha_device = HaThermo(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities([ha_device, *ha_device.get_sensors()])

    async def _create_sun_device(self, device: TydomSun) -> None:
        """Create a Tysense Sun irradiance sensor."""
        LOGGER.debug("Create Tysense Sun %s", device.device_id)
        ha_device = HaSun(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities([ha_device, *ha_device.get_sensors()])

    async def _create_scene_device(self, device: TydomScene) -> None:
        """Create a normal scene or aggregate TWC commands into one cover."""
        LOGGER.debug("Create scene %s", device.device_id)
        ha_device = HAScene(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        action = ha_device.twc_action
        if action is None:
            if self.add_scene_callback is not None:
                self.add_scene_callback([ha_device])
            return

        zone_key = ha_device._get_zone_from_scene()
        controller_id = ha_device._find_tywell_device(zone_key)
        parent_key = controller_id or f"tywell_control_{zone_key or 'default'}"
        grouping_key = f"{parent_key}:{zone_key or 'default'}"
        scenes = self._twc_scene_sets.setdefault(grouping_key, {})
        scenes[action] = ha_device

        cover = self._twc_cover_entities.get(grouping_key)
        if cover is None:
            cover = HATwcShutterCover(
                grouping_key,
                scenes,
                ha_device,
                self._hass,
                zone_key,
            )
            self._twc_cover_entities[grouping_key] = cover
            self.ha_devices[f"twc_cover_{grouping_key}"] = cover
            if self.add_cover_callback is not None:
                self.add_cover_callback([cover])
            LOGGER.debug(
                "Created Tywell shutter cover %s from scenario %s",
                grouping_key,
                device.device_name,
            )
        else:
            cover.refresh_scenes(ha_device)

    async def _create_group_device(self, device: TydomGroup) -> None:
        """Create a native Home Assistant entity for a controllable group."""
        LOGGER.debug("Create %s group %s", device.group_usage, device.device_id)
        if device.group_usage == "light":
            ha_device = HALightGroup(device, self._hass)
            callback = self.add_light_callback
        elif device.group_usage in {"awning", "shutter"}:
            ha_device = HACoverGroup(device, self._hass)
            callback = self.add_cover_callback
        elif device.group_usage == "plug":
            ha_device = HASwitchGroup(device, self._hass)
            callback = self.add_switch_callback
        else:
            LOGGER.debug(
                "Ignore unsupported group %s (%s)",
                device.device_id,
                device.group_usage,
            )
            return

        self.ha_devices[device.device_id] = ha_device
        if callback is not None:
            callback([ha_device])

    async def _create_moment_device(self, device: TydomMoment) -> None:
        """Create moment device."""
        LOGGER.debug("Create moment %s", device.device_id)
        ha_device = HAMoment(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_switch_callback is not None:
            self.add_switch_callback([ha_device])

    async def _create_remote_control_device(self, device: TydomRemoteControl) -> None:
        """Create an event entity for a remote button and one battery diagnostic."""
        LOGGER.debug("Create remote-control button %s", device.device_id)
        migrate_legacy_remote_endpoint(
            self._hass,
            self._entry.entry_id,
            device.device_id,
        )
        ha_device = HARemoteEvent(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_event_callback is not None:
            self.add_event_callback([ha_device])

        battery = self._remote_battery_entities.get(device.physical_device_id)
        if battery is None:
            battery = HARemoteBattery(device, self._hass)
            self._remote_battery_entities[device.physical_device_id] = battery
            if self.add_binary_sensor_callback is not None:
                self.add_binary_sensor_callback([battery])
        else:
            battery.add_device(device)

    async def _create_generic_device(self, device: TydomDevice) -> None:
        """Create generic sensor device."""
        LOGGER.debug("Create generic sensor %s", device.device_id)
        primary_binary_attribute = next(
            (
                attribute
                for attribute in ("on", "state")
                if hasattr(device, attribute)
                and is_binary_attribute(device, attribute, getattr(device, attribute))
            ),
            None,
        )
        if primary_binary_attribute is not None:
            ha_device = HAGenericBinarySensor(
                device, self._hass, primary_binary_attribute
            )
        else:
            ha_device = HASensor(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities([ha_device, *ha_device.get_sensors()])

        # Try to detect if device should also be a switch
        # Check for on/off capabilities that aren't already handled
        if device.device_type not in ["light", "cover", "alarm"]:
            has_on_off = (
                hasattr(device, "level")
                or hasattr(device, "on")
                or hasattr(device, "state")
            )
            # Check if device has levelCmd or onCmd in metadata (writable)
            has_control = False
            if device._metadata is not None:
                for key in device._metadata:
                    if key.endswith("Cmd") or key in ["level", "on", "state"]:
                        has_control = True
                        break

            if has_on_off and has_control:
                LOGGER.debug(
                    "Device %s has on/off capabilities, creating switch",
                    device.device_id,
                )
                switch_device = HASwitch(device, self._hass)
                if self.add_switch_callback is not None:
                    self.add_switch_callback([switch_device])

    async def update_ha_device(self, stored_device, device):
        """Update HA device values."""
        try:
            await stored_device.update_device(device)
            ha_device = self.ha_devices[device.device_id]

            # Special handling for scenes: invalidate caches and recreate relations
            if isinstance(device, TydomScene) and isinstance(ha_device, HAScene):
                await ha_device.async_device_update(device)

            new_sensors = ha_device.get_sensors()
            if new_sensors:
                # add new sensors
                LOGGER.debug(
                    "Ajout de %d nouveau(x) capteur(s) pour le device %s: %s",
                    len(new_sensors),
                    device.device_id,
                    [s._attr_name for s in new_sensors],
                )
                self._add_discovered_entities(new_sensors)
            if isinstance(ha_device, HAEnergy):
                self._maybe_create_refresh_energy_button(stored_device, ha_device)
            self._maybe_create_device_association_buttons(stored_device)
            # ha_device.publish_updates()
            # ha_device.update()
        except KeyError as e:
            LOGGER.warning(
                "Device %s non trouvé dans ha_devices lors de la mise à jour: %s",
                device.device_id,
                e,
            )
        except Exception:
            LOGGER.exception(
                "Erreur lors de la mise à jour du device %s", device.device_id
            )

    def _maybe_create_device_association_buttons(self, device: TydomDevice) -> None:
        """Expose only association controls advertised by a physical product."""
        if self.add_button_callback is None:
            return

        buttons = []
        for command in (ASSOCIATION_COMMAND, IDENTIFY_COMMAND):
            key = (device.device_id, command)
            if key in self._device_association_buttons_created:
                continue
            if not supports_command(device, command):
                continue
            buttons.append(HADeviceAssociationButton(device, self._hass, command))
            self._device_association_buttons_created.add(key)

        if buttons:
            self.add_button_callback(buttons)

    async def ping(self) -> None:
        """Periodically send pings."""
        while not self._shutting_down:
            await self._tydom_client.ping()
            await self._interruptible_sleep(30)

    async def refresh_all(self) -> None:
        """Periodically refresh all metadata and data.

        It allows new devices to be discovered.
        """
        while not self._shutting_down:
            await self._tydom_client.get_info()
            await self._tydom_client.put_api_mode()
            await self._tydom_client.post_refresh()
            await self._tydom_client.get_configs_file()
            await self._tydom_client.get_groups()
            await self._tydom_client.get_devices_meta()
            await self._tydom_client.get_devices_cmeta()
            await self._tydom_client.get_devices_data()
            await self._tydom_client.get_scenarii()
            await self._tydom_client.get_moments()
            await self._interruptible_sleep(600)

    async def refresh_data_1s(self) -> None:
        """Refresh data for devices in list."""
        while not self._shutting_down:
            await self._tydom_client.poll_devices_data_1s()
            await self._interruptible_sleep(1)

    def _rebuild_polling_cache(self) -> None:
        """Rebuild polling cache efficiently.

        This method scans all devices and their metadata to build a cache
        mapping (device_key, attribute_name) to polling intervals based on
        the validity metadata. The cache is rebuilt periodically to account
        for metadata changes.

        The cache structure: {(device_key, attr_name): interval_seconds}
        - Devices with validity=INFINITE or upToDate are not cached (no polling)
        - Devices with validity=ES_SUPERVISION are cached with 300s interval
        - Devices with validity=SENSOR_SUPERVISION are cached with 60s interval
        - Devices with validity=SYNCHRO_SUPERVISION are cached with 30s interval
        """
        new_cache: dict[tuple[str, str], int] = {}
        for device_key, device in self.devices.items():
            if not hasattr(device, "_metadata") or device._metadata is None:
                continue
            for attr_name, attr_metadata in device._metadata.items():
                if isinstance(attr_metadata, dict):
                    validity = attr_metadata.get("validity")
                    interval = get_polling_interval_for_validity(validity)
                    if interval is not None:
                        new_cache[(device_key, attr_name)] = interval

        # Update cache atomically
        self._polling_cache = new_cache
        LOGGER.debug("Polling cache rebuilt with %d entries", len(self._polling_cache))

    async def refresh_data(self) -> None:
        """Periodically refresh data for devices which don't do push.

        Uses adaptive polling based on validity metadata:
        - INFINITE/upToDate: No polling needed
        - ES_SUPERVISION: Poll every 5 minutes
        - SENSOR_SUPERVISION: Poll every 1 minute
        - SYNCHRO_SUPERVISION: Poll every 30 seconds

        The polling groups are rebuilt every 5 minutes to account for
        metadata changes.
        """
        while not self._shutting_down:
            current_time = time.monotonic()

            # Rebuild cache only if expired
            if current_time - self._polling_cache_timestamp > self._polling_cache_ttl:
                self._rebuild_polling_cache()
                self._polling_cache_timestamp = current_time

            # Group devices by interval from cache
            interval_groups: dict[int, set[str]] = {}
            for (device_key, _attr_name), interval in self._polling_cache.items():
                interval_groups.setdefault(interval, set()).add(device_key)

            active_intervals = set(interval_groups)
            self._next_poll_due = {
                interval: due
                for interval, due in self._next_poll_due.items()
                if interval in active_intervals
            }

            # Poll devices according to their intervals
            if interval_groups:
                # Sort intervals from shortest to longest
                sorted_intervals = sorted(interval_groups.keys())
                shortest_interval = sorted_intervals[0]

                # Poll every interval group whose due time has elapsed, not just
                # the shortest one - otherwise ES_SUPERVISION/SENSOR_SUPERVISION
                # devices are starved forever as soon as any device needs
                # SYNCHRO_SUPERVISION (shortest_interval always wins otherwise).
                for interval, device_keys in interval_groups.items():
                    if current_time < self._next_poll_due.get(interval, 0):
                        continue
                    self._next_poll_due[interval] = current_time + interval
                    for device_key in device_keys:
                        if device_key in self.devices:
                            device = self.devices[device_key]
                            if hasattr(device, "_tydom_client"):
                                try:
                                    await device._tydom_client.poll_device_data(
                                        device._id, device.device_endpoint
                                    )
                                except Exception as e:
                                    LOGGER.warning(
                                        "Error polling device %s: %s", device_key, e
                                    )

                # Sleep for the shortest interval so due longer-interval groups
                # still get checked promptly on the next wake-up.
                await self._interruptible_sleep(shortest_interval)
            else:
                # No devices need validity-based polling, use default refresh interval
                if self._refresh_interval > 0:
                    await self._interruptible_sleep(self._refresh_interval)
                else:
                    await self._interruptible_sleep(60)

    async def refresh_energy_now(self, device_id: str, endpoint_id: str | None) -> None:
        """Poll one Tywatt cdata endpoint immediately, on demand."""
        await self._tydom_client.poll_devices_data_5m(device_id, endpoint_id)

    async def refresh_cdata(self) -> None:
        """Periodically poll the cdata endpoints registered for devices like Tywatt.

        Endpoints such as energyIndex, energyInstant, energyHisto and
        energyDistrib are registered via add_poll_device_url_5m() while parsing
        /devices/cmeta (see MessageHandler.parse_cmeta_data) and must be polled
        on their own schedule. They must NOT be polled only from within
        refresh_data()'s "no validity-based polling needed" branch: as soon as
        any other device exposes validity metadata (the common case), that
        branch never runs and these cdata endpoints (e.g. the Tywatt instant
        consumption sensor) would never be queried.

        Poll once at startup, then follow the refresh interval selected in the
        integration options. The per-device Refresh button remains available
        for an immediate reading between scheduled polls.
        """
        while not self._shutting_down:
            try:
                await self._tydom_client.poll_devices_data_5m()
            except Exception:
                LOGGER.exception("Error polling registered cdata endpoints")
            await self._interruptible_sleep(self._refresh_interval)

    async def reload_devices(self) -> None:
        """Recharger tous les appareils et entités comme au démarrage initial.

        Cette méthode vide tous les appareils existants et les recharges depuis zéro.
        """
        LOGGER.info("Début du rechargement de tous les appareils")

        # Vider les dictionnaires d'appareils
        self.devices.clear()
        self.ha_devices.clear()
        self._remote_battery_entities.clear()
        self._interrupter_battery_entities.clear()
        self._twc_scene_sets.clear()
        self._twc_cover_entities.clear()
        # Réinitialiser le flag pour recréer le bouton après le rechargement
        self._reload_button_created = False
        self._association_controls_created = False
        self._association_controls.clear()
        self._refresh_energy_buttons_created.clear()
        self._device_association_buttons_created.clear()

        # Supprimer toutes les entités existantes via l'Entity Registry
        from homeassistant.helpers import entity_registry as er

        entity_registry = er.async_get(self._hass)
        entities_to_remove = []

        # Parcourir toutes les entités enregistrées pour cette intégration
        for entity_id, entity_entry in entity_registry.entities.items():
            if entity_entry.config_entry_id == self._entry.entry_id:
                entities_to_remove.append(entity_id)

        # Supprimer les entités
        for entity_id in entities_to_remove:
            entity_registry.async_remove(entity_id)

        LOGGER.info(
            "Suppression de %d entité(s) existante(s) et rechargement des appareils",
            len(entities_to_remove),
        )

        # Recharger toutes les métadonnées et données comme au démarrage
        await self._tydom_client.get_info()
        await self._tydom_client.put_api_mode()
        await self._tydom_client.post_refresh()
        await self._tydom_client.get_configs_file()
        await self._tydom_client.get_groups()
        await self._tydom_client.get_devices_meta()
        await self._tydom_client.get_devices_cmeta()
        await self._tydom_client.get_devices_data()
        await self._tydom_client.get_scenarii()
        await self._tydom_client.get_moments()

        # Recréer le bouton de rechargement après le rechargement
        # (le bouton d'actualisation énergie est recréé par _create_energy_device
        # quand le device Tywatt est redécouvert)
        if self.add_button_callback is not None:
            reload_button = HAReloadButton(self, self._hass)
            self.add_button_callback([reload_button])
            LOGGER.debug("Bouton de rechargement recréé après le rechargement")
        if (
            self.add_button_callback is not None
            and self.add_select_callback is not None
        ):
            self.add_select_callback(
                [
                    HAGatewayAssociationCategorySelect(self),
                    HAGatewayAssociationProductSelect(self),
                ]
            )
            self.add_button_callback([HAGatewayStartAssociationButton(self)])
            self._association_controls_created = True

        LOGGER.info(
            "Rechargement terminé, les nouveaux appareils seront découverts automatiquement"
        )

        # Validate data consistency after reload
        await self._validate_data_consistency()

    async def _validate_data_consistency(self) -> None:
        """Validate data consistency: check that devices in groups exist, scenarios reference valid devices."""
        LOGGER.debug("Validating data consistency...")

        issues = []

        # Check groups: verify that all device IDs in groups exist
        for device_id, device in self.devices.items():
            if isinstance(device, TydomGroup):
                for group_device_id in device.device_ids:
                    if group_device_id not in self.devices:
                        # Try to find by various ID formats
                        found = False
                        for _id, _device in self.devices.items():
                            if (
                                _id == group_device_id
                                or str(getattr(_device, "device_id", ""))
                                == group_device_id
                                or str(getattr(_device, "_id", "")) == group_device_id
                            ):
                                found = True
                                break

                        if not found:
                            issues.append(
                                f"Group {device.device_name} ({device_id}) references non-existent device: {group_device_id}"
                            )

        # Check scenarios: verify that grpAct and epAct reference valid devices/groups
        for device_id, device in self.devices.items():
            if isinstance(device, TydomScene):
                # Check grpAct
                grp_act = getattr(device, "grpAct", None)
                if grp_act and isinstance(grp_act, list):
                    from .tydom.MessageHandler import groups_data

                    for grp_action in grp_act:
                        if isinstance(grp_action, dict):
                            grp_id = grp_action.get("id")
                            if grp_id:
                                grp_id_str = str(grp_id)
                                # All groups remain in protocol metadata even
                                # when no Home Assistant control is appropriate.
                                if grp_id_str not in groups_data:
                                    issues.append(
                                        f"Scene {device.device_name} ({device_id}) references non-existent group: {grp_id_str}"
                                    )

                # Check epAct
                ep_act = getattr(device, "epAct", None)
                if ep_act and isinstance(ep_act, list):
                    for ep_action in ep_act:
                        if isinstance(ep_action, dict):
                            ep_id = ep_action.get("id")
                            if ep_id:
                                ep_id_str = str(ep_id)
                                # Check if device/endpoint exists
                                device_found = False
                                for _id, _device in self.devices.items():
                                    if (
                                        _id == ep_id_str
                                        or str(getattr(_device, "device_id", ""))
                                        == ep_id_str
                                        or str(getattr(_device, "_id", "")) == ep_id_str
                                    ):
                                        device_found = True
                                        break

                                if not device_found:
                                    issues.append(
                                        f"Scene {device.device_name} ({device_id}) references non-existent device/endpoint: {ep_id_str}"
                                    )

        # Log issues
        if issues:
            LOGGER.warning(
                "Found %d data consistency issue(s):",
                len(issues),
            )
            for issue in issues:
                LOGGER.warning("  - %s", issue)
        else:
            LOGGER.debug("Data consistency validation passed: no issues found")
