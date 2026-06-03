"""A demonstration 'hub' that connects several devices."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from aiohttp import ClientWebSocketResponse, ClientSession

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    TydomAlarm,
    TydomWeather,
    TydomWater,
    TydomThermo,
    TydomDevice,
    TydomScene,
    TydomGroup,
    TydomMoment,
)
from .ha_entities import (
    HATydom,
    HACover,
    HAEnergy,
    HASmoke,
    HaClimate,
    HaWindow,
    HaDoor,
    HaGate,
    HaGarage,
    HaLight,
    HaAlarm,
    HaWeather,
    HaMoisture,
    HaThermo,
    HASensor,
    HAScene,
    HASwitch,
    HAReloadButton,
    HAGroup,
    HAMoment,
)

from .const import LOGGER, get_polling_interval_for_validity, STRUCTURED_LOGGER


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

        # Polling cache for optimization
        self._polling_cache: dict[
            tuple[str, str], int
        ] = {}  # (device_id, attr_name) -> interval
        self._polling_cache_timestamp = 0
        self._polling_cache_ttl = 300  # 5 minutes

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
            TydomAlarm: self._create_alarm_device,
            TydomWeather: self._create_weather_device,
            TydomWater: self._create_water_device,
            TydomThermo: self._create_thermo_device,
            TydomScene: self._create_scene_device,
            TydomGroup: self._create_group_device,
            TydomMoment: self._create_moment_device,
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
        connection = await self._tydom_client.async_connect()
        await self._tydom_client.listen_tydom(connection)
        return connection

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
            await connection.close()

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
        return is_ready

    async def setup(self, connection: ClientWebSocketResponse) -> None:
        """Listen to tydom events."""
        # wait for callbacks to become available
        while not self.ready():
            await asyncio.sleep(1)
        LOGGER.debug("Listen to tydom events")

        # Validate data consistency after initial setup
        await self._validate_data_consistency()
        while True:
            devices = await self._tydom_client.consume_messages()
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
        if self.add_sensor_callback is not None:
            self.add_sensor_callback(ha_device.get_sensors())
        # Le bouton de rechargement est créé dans ready() pour être toujours présent

    async def _create_shutter_device(self, device: TydomShutter) -> None:
        """Create shutter/cover device."""
        LOGGER.debug("Create cover %s", device.device_id)
        ha_device = HACover(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_cover_callback is not None:
            self.add_cover_callback([ha_device])
        if self.add_sensor_callback is not None:
            self.add_sensor_callback(ha_device.get_sensors())

    async def _create_energy_device(self, device: TydomEnergy) -> None:
        """Create energy consumption device."""
        LOGGER.debug("Create conso %s", device.device_id)
        ha_device = HAEnergy(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_sensor_callback is not None:
            self.add_sensor_callback([ha_device])
            self.add_sensor_callback(ha_device.get_sensors())

    async def _create_smoke_device(self, device: TydomSmoke) -> None:
        """Create smoke detector device."""
        LOGGER.debug("Create smoke %s", device.device_id)
        ha_device = HASmoke(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_sensor_callback is not None:
            self.add_sensor_callback([ha_device])
            self.add_sensor_callback(ha_device.get_sensors())

    async def _create_boiler_device(self, device: TydomBoiler) -> None:
        """Create boiler/climate device."""
        LOGGER.debug("Create boiler %s", device.device_id)
        ha_device = HaClimate(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_climate_callback is not None:
            self.add_climate_callback([ha_device])
        if self.add_sensor_callback is not None:
            self.add_sensor_callback(ha_device.get_sensors())

    async def _create_window_device(self, device: TydomWindow) -> None:
        """Create window device (cover or binary_sensor)."""
        LOGGER.debug("Create window %s", device.device_id)
        ha_device = HaWindow(device, self._hass)
        self.ha_devices[device.device_id] = ha_device

        # Décision automatique selon les attributs du device
        if any(
            hasattr(device, a) for a in ["position", "positionCmd", "level", "levelCmd"]
        ):
            LOGGER.debug(
                "Window %s has motor control → adding as cover",
                device.device_id,
            )
            if self.add_cover_callback:
                self.add_cover_callback([ha_device])
        else:
            LOGGER.debug(
                "Window %s is passive → adding as binary_sensor",
                device.device_id,
            )
            if self.add_binary_sensor_callback:
                self.add_binary_sensor_callback([ha_device])

        if self.add_sensor_callback:
            self.add_sensor_callback(ha_device.get_sensors())

    async def _create_door_device(self, device: TydomDoor) -> None:
        """Create door device (cover or binary_sensor)."""
        LOGGER.debug("Create door %s", device.device_id)
        ha_device = HaDoor(device, self._hass)
        self.ha_devices[device.device_id] = ha_device

        # Décision automatique selon les attributs du device
        if any(
            hasattr(device, a) for a in ["position", "positionCmd", "level", "levelCmd"]
        ):
            LOGGER.debug(
                "Door %s has motor control → adding as cover", device.device_id
            )
            if self.add_cover_callback:
                self.add_cover_callback([ha_device])
        else:
            LOGGER.debug(
                "Door %s is passive → adding as binary_sensor", device.device_id
            )
            if self.add_binary_sensor_callback:
                self.add_binary_sensor_callback([ha_device])

        if self.add_sensor_callback:
            self.add_sensor_callback(ha_device.get_sensors())

    async def _create_gate_device(self, device: TydomGate) -> None:
        """Create gate device."""
        LOGGER.debug("Create gate %s", device.device_id)
        ha_device = HaGate(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_cover_callback is not None:
            self.add_cover_callback([ha_device])
        if self.add_sensor_callback is not None:
            self.add_sensor_callback(ha_device.get_sensors())

    async def _create_garage_device(self, device: TydomGarage) -> None:
        """Create garage device."""
        LOGGER.debug("Create garage %s", device.device_id)
        ha_device = HaGarage(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_cover_callback is not None:
            self.add_cover_callback([ha_device])
        if self.add_sensor_callback is not None:
            self.add_sensor_callback(ha_device.get_sensors())

    async def _create_light_device(self, device: TydomLight) -> None:
        """Create light device."""
        LOGGER.debug("Create light %s", device.device_id)
        ha_device = HaLight(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_light_callback is not None:
            self.add_light_callback([ha_device])
        if self.add_sensor_callback is not None:
            self.add_sensor_callback(ha_device.get_sensors())

    async def _create_alarm_device(self, device: TydomAlarm) -> None:
        """Create alarm device."""
        LOGGER.debug("Create alarm %s", device.device_id)
        ha_device = HaAlarm(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_alarm_callback is not None:
            self.add_alarm_callback([ha_device])
        if self.add_sensor_callback is not None:
            self.add_sensor_callback(ha_device.get_sensors())

    async def _create_weather_device(self, device: TydomWeather) -> None:
        """Create weather device."""
        LOGGER.debug("Create weather %s", device.device_id)
        ha_device = HaWeather(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_weather_callback is not None:
            self.add_weather_callback([ha_device])
        if self.add_sensor_callback is not None:
            self.add_sensor_callback(ha_device.get_sensors())

    async def _create_water_device(self, device: TydomWater) -> None:
        """Create water/moisture device."""
        LOGGER.debug("Create moisture %s", device.device_id)
        ha_device = HaMoisture(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_sensor_callback is not None:
            self.add_sensor_callback([ha_device])
            self.add_sensor_callback(ha_device.get_sensors())

    async def _create_thermo_device(self, device: TydomThermo) -> None:
        """Create thermostat device."""
        LOGGER.debug("Create thermo %s", device.device_id)
        ha_device = HaThermo(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_sensor_callback is not None:
            self.add_sensor_callback([ha_device])
            self.add_sensor_callback(ha_device.get_sensors())

    async def _create_scene_device(self, device: TydomScene) -> None:
        """Create scene device."""
        LOGGER.debug("Create scene %s", device.device_id)
        ha_device = HAScene(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_scene_callback is not None:
            self.add_scene_callback([ha_device])

    async def _create_group_device(self, device: TydomGroup) -> None:
        """Create group device."""
        LOGGER.debug("Create group %s", device.device_id)
        ha_device = HAGroup(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_button_callback is not None:
            self.add_button_callback([ha_device])

    async def _create_moment_device(self, device: TydomMoment) -> None:
        """Create moment device."""
        LOGGER.debug("Create moment %s", device.device_id)
        ha_device = HAMoment(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_switch_callback is not None:
            self.add_switch_callback([ha_device])

    async def _create_generic_device(self, device: TydomDevice) -> None:
        """Create generic sensor device."""
        LOGGER.debug("Create generic sensor %s", device.device_id)
        ha_device = HASensor(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_sensor_callback is not None:
            self.add_sensor_callback([ha_device])
            self.add_sensor_callback(ha_device.get_sensors())

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
            if len(new_sensors) > 0 and self.add_sensor_callback is not None:
                # add new sensors
                LOGGER.debug(
                    "Ajout de %d nouveau(x) capteur(s) pour le device %s: %s",
                    len(new_sensors),
                    device.device_id,
                    [s._attr_name for s in new_sensors],
                )
                self.add_sensor_callback(new_sensors)
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

    async def ping(self) -> None:
        """Periodically send pings."""
        while True:
            await self._tydom_client.ping()
            await asyncio.sleep(30)

    async def refresh_all(self) -> None:
        """Periodically refresh all metadata and data.

        It allows new devices to be discovered.
        """
        while True:
            await self._tydom_client.get_info()
            await self._tydom_client.put_api_mode()
            await self._tydom_client.get_groups()
            await self._tydom_client.post_refresh()
            await self._tydom_client.get_configs_file()
            await self._tydom_client.get_devices_meta()
            await self._tydom_client.get_devices_cmeta()
            await self._tydom_client.get_devices_data()
            await self._tydom_client.get_scenarii()
            await self._tydom_client.get_moments()
            await asyncio.sleep(600)

    async def refresh_data_1s(self) -> None:
        """Refresh data for devices in list."""
        while True:
            await self._tydom_client.poll_devices_data_1s()
            await asyncio.sleep(1)

    def _rebuild_polling_cache(self) -> None:
        """Rebuild polling cache efficiently.

        This method scans all devices and their metadata to build a cache
        mapping (device_id, attribute_name) to polling intervals based on
        the validity metadata. The cache is rebuilt periodically to account
        for metadata changes.

        The cache structure: {(device_id, attr_name): interval_seconds}
        - Devices with validity=INFINITE or upToDate are not cached (no polling)
        - Devices with validity=ES_SUPERVISION are cached with 300s interval
        - Devices with validity=SENSOR_SUPERVISION are cached with 60s interval
        - Devices with validity=SYNCHRO_SUPERVISION are cached with 30s interval
        """
        new_cache: dict[tuple[str, str], int] = {}
        for device_id, device in self.devices.items():
            if not hasattr(device, "_metadata") or device._metadata is None:
                continue
            for attr_name, attr_metadata in device._metadata.items():
                if isinstance(attr_metadata, dict):
                    validity = attr_metadata.get("validity")
                    interval = get_polling_interval_for_validity(validity)
                    if interval is not None:
                        new_cache[(device_id, attr_name)] = interval

        # Update cache atomically
        self._polling_cache = new_cache
        LOGGER.debug("Polling cache rebuilt with %d entries", len(self._polling_cache))

    def _rebuild_polling_cache(self) -> None:
        """Rebuild polling cache efficiently.

        This method scans all devices and their metadata to build a cache
        mapping (device_id, attribute_name) to polling intervals based on
        the validity metadata. The cache is rebuilt periodically to account
        for metadata changes.

        The cache structure: {(device_id, attr_name): interval_seconds}
        - Devices with validity=INFINITE or upToDate are not cached (no polling)
        - Devices with validity=ES_SUPERVISION are cached with 300s interval
        - Devices with validity=SENSOR_SUPERVISION are cached with 60s interval
        - Devices with validity=SYNCHRO_SUPERVISION are cached with 30s interval
        """
        new_cache: dict[tuple[str, str], int] = {}
        for device_id, device in self.devices.items():
            if not hasattr(device, "_metadata") or device._metadata is None:
                continue
            for attr_name, attr_metadata in device._metadata.items():
                if isinstance(attr_metadata, dict):
                    validity = attr_metadata.get("validity")
                    interval = get_polling_interval_for_validity(validity)
                    if interval is not None:
                        new_cache[(device_id, attr_name)] = interval

        # Update cache atomically
        self._polling_cache = new_cache

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
        while True:
            current_time = time.time()

            # Rebuild cache only if expired
            if current_time - self._polling_cache_timestamp > self._polling_cache_ttl:
                self._rebuild_polling_cache()
                self._polling_cache_timestamp = current_time

            # Group devices by interval from cache
            interval_groups: dict[int, list[tuple[str, str]]] = {}
            for (device_id, attr_name), interval in self._polling_cache.items():
                if interval not in interval_groups:
                    interval_groups[interval] = []
                interval_groups[interval].append((device_id, attr_name))

            # Poll devices according to their intervals
            if interval_groups:
                # Sort intervals from shortest to longest
                sorted_intervals = sorted(interval_groups.keys())
                shortest_interval = sorted_intervals[0]

                # Poll devices that need the shortest interval
                for device_id, _attr_name in interval_groups[shortest_interval]:
                    if device_id in self.devices:
                        device = self.devices[device_id]
                        if hasattr(device, "_tydom_client"):
                            try:
                                await device._tydom_client.poll_device_data(device_id)
                            except Exception as e:
                                LOGGER.warning(
                                    "Error polling device %s: %s", device_id, e
                                )

                # Sleep for the shortest interval
                await asyncio.sleep(shortest_interval)
            else:
                # No devices need polling, use default refresh interval
                if self._refresh_interval > 0:
                    await self._tydom_client.poll_devices_data_5m()
                    await asyncio.sleep(self._refresh_interval)
                else:
                    await asyncio.sleep(60)

    async def reload_devices(self) -> None:
        """Recharger tous les appareils et entités comme au démarrage initial.

        Cette méthode vide tous les appareils existants et les recharges depuis zéro.
        """
        LOGGER.info("Début du rechargement de tous les appareils")

        # Vider les dictionnaires d'appareils
        self.devices.clear()
        self.ha_devices.clear()
        # Réinitialiser le flag pour recréer le bouton après le rechargement
        self._reload_button_created = False

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
        await self._tydom_client.get_groups()
        await self._tydom_client.post_refresh()
        await self._tydom_client.get_configs_file()
        await self._tydom_client.get_devices_meta()
        await self._tydom_client.get_devices_cmeta()
        await self._tydom_client.get_devices_data()
        await self._tydom_client.get_scenarii()
        await self._tydom_client.get_moments()

        # Recréer le bouton de rechargement après le rechargement
        if self.add_button_callback is not None:
            reload_button = HAReloadButton(self, self._hass)
            self.add_button_callback([reload_button])
            LOGGER.debug("Bouton de rechargement recréé après le rechargement")

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
                    for grp_action in grp_act:
                        if isinstance(grp_action, dict):
                            grp_id = grp_action.get("id")
                            if grp_id:
                                grp_id_str = str(grp_id)
                                # Check if group exists
                                group_found = False
                                for _id, _device in self.devices.items():
                                    if (
                                        isinstance(_device, TydomGroup)
                                        and _device.group_id == grp_id_str
                                    ):
                                        group_found = True
                                        break

                                if not group_found:
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
