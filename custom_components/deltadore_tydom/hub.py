"""Hub that connects to the Tydom gateway and manages devices."""

from __future__ import annotations

import asyncio
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
)
from .const import LOGGER

# Callback attribute names for platform registration
_CALLBACK_NAMES = (
    "add_cover_callback", "add_sensor_callback", "add_climate_callback",
    "add_light_callback", "add_lock_callback", "add_alarm_callback",
    "add_update_callback", "add_weather_callback", "add_binary_sensor_callback",
    "add_scene_callback", "add_switch_callback", "add_button_callback",
    "add_number_callback", "add_select_callback", "add_event_callback",
)

# Device type → (HA entity class, callback attribute name)
# Order does not matter since we match by exact type()
_DEVICE_HANDLERS: dict[type, tuple[type, str]] = {
    Tydom: (HATydom, "add_update_callback"),
    TydomShutter: (HACover, "add_cover_callback"),
    TydomEnergy: (HAEnergy, "add_sensor_callback"),
    TydomSmoke: (HASmoke, "add_sensor_callback"),
    TydomBoiler: (HaClimate, "add_climate_callback"),
    TydomLight: (HaLight, "add_light_callback"),
    TydomAlarm: (HaAlarm, "add_alarm_callback"),
    TydomWeather: (HaWeather, "add_weather_callback"),
    TydomWater: (HaMoisture, "add_sensor_callback"),
    TydomThermo: (HaThermo, "add_sensor_callback"),
    TydomGate: (HaGate, "add_cover_callback"),
    TydomGarage: (HaGarage, "add_cover_callback"),
    TydomScene: (HAScene, "add_scene_callback"),
}


class Hub:
    """Hub for Delta Dore Tydom."""

    manufacturer = "Delta Dore"

    def handle_event(self, event):
        """Event callback."""

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

        for name in _CALLBACK_NAMES:
            setattr(self, name, None)

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

    def update_config(self, refresh_interval, zone_home, zone_away, zone_night):
        """Update zone configuration."""
        self._tydom_client.update_config(zone_home, zone_away, zone_night)
        self._refresh_interval = int(refresh_interval) * 60
        self._zone_home = zone_home
        self._zone_away = zone_away
        self._zone_night = zone_night

    @property
    def hub_id(self) -> str:
        """Return hub ID."""
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
        """Check if all platform callbacks are registered."""
        return all(getattr(self, name) is not None for name in _CALLBACK_NAMES)

    async def setup(self, connection: ClientWebSocketResponse) -> None:
        """Listen to Tydom events."""
        while not self.ready():
            await asyncio.sleep(1)
        LOGGER.debug("Listen to tydom events")
        while True:
            devices = await self._tydom_client.consume_messages()
            if devices is None:
                continue
            for device in devices:
                if device.device_id not in self.devices:
                    self.devices[device.device_id] = device
                    await self._create_ha_device(device)
                else:
                    stored = self.devices[device.device_id]
                    if stored is not device and (
                        stored.device_name != device.device_name
                        or stored.device_type != device.device_type
                    ):
                        LOGGER.warning(
                            "Collision d'identifiant : device_id=%s "
                            "(existant: %s/%s, nouveau: %s/%s)",
                            device.device_id,
                            stored.device_name, stored.device_type,
                            device.device_name, device.device_type,
                        )
                    await self._update_ha_device(stored, device)

    def _add_callback(self, callback_name: str, entities: list):
        """Invoke a platform callback if registered."""
        cb = getattr(self, callback_name, None)
        if cb is not None:
            cb(entities)

    async def _create_ha_device(self, device):
        """Create a new HA device from a Tydom device."""
        device_type = type(device)

        # ── Standard devices (matched by exact type) ──
        handler = _DEVICE_HANDLERS.get(device_type)
        if handler:
            ha_class, callback_attr = handler
            LOGGER.debug("Create %s %s", device_type.__name__, device.device_id)
            ha_device = ha_class(device, self._hass)
            self.ha_devices[device.device_id] = ha_device
            self._add_callback(callback_attr, [ha_device])
            # All devices except scenes get sensor auto-discovery
            if device_type != TydomScene:
                self._add_callback("add_sensor_callback", ha_device.get_sensors())
            return

        # ── Window / Door: route to cover or binary_sensor ──
        if isinstance(device, (TydomWindow, TydomDoor)):
            type_name = type(device).__name__
            ha_class = HaWindow if isinstance(device, TydomWindow) else HaDoor
            LOGGER.debug("Create %s %s", type_name, device.device_id)
            ha_device = ha_class(device, self._hass)
            self.ha_devices[device.device_id] = ha_device

            has_motor = any(
                hasattr(device, a)
                for a in ("position", "positionCmd", "level", "levelCmd")
            )
            if has_motor:
                LOGGER.debug("%s %s has motor → cover", type_name, device.device_id)
                self._add_callback("add_cover_callback", [ha_device])
            else:
                LOGGER.debug("%s %s passive → binary_sensor", type_name, device.device_id)
                self._add_callback("add_binary_sensor_callback", [ha_device])
            self._add_callback("add_sensor_callback", ha_device.get_sensors())
            return

        # ── Generic TydomDevice fallback ──
        if isinstance(device, TydomDevice):
            LOGGER.debug("Create generic sensor %s", device.device_id)
            ha_device = HASensor(device, self._hass)
            self.ha_devices[device.device_id] = ha_device
            self._add_callback("add_sensor_callback", [ha_device])
            self._add_callback("add_sensor_callback", ha_device.get_sensors())

            # Auto-detect switch capabilities
            if device.device_type not in ("light", "cover", "alarm"):
                has_on_off = any(
                    hasattr(device, a) for a in ("level", "on", "state")
                )
                has_control = device._metadata and any(
                    k.endswith("Cmd") or k in ("level", "on", "state")
                    for k in device._metadata
                )
                if has_on_off and has_control:
                    LOGGER.debug("Device %s → also creating switch", device.device_id)
                    self._add_callback(
                        "add_switch_callback", [HASwitch(device, self._hass)]
                    )
            return

        LOGGER.error(
            "Unsupported device type (%s) %s for %s",
            device_type, device.device_type, device.device_id,
        )

    async def _update_ha_device(self, stored_device, device):
        """Update HA device values."""
        try:
            await stored_device.update_device(device)
            ha_device = self.ha_devices[device.device_id]
            new_sensors = ha_device.get_sensors()
            if new_sensors:
                LOGGER.debug(
                    "Ajout de %d capteur(s) pour %s: %s",
                    len(new_sensors), device.device_id,
                    [s._attr_name for s in new_sensors],
                )
                self._add_callback("add_sensor_callback", new_sensors)
        except KeyError as e:
            LOGGER.warning("Device %s non trouvé dans ha_devices: %s", device.device_id, e)
        except Exception:
            LOGGER.exception("Erreur mise à jour device %s", device.device_id)

    async def ping(self) -> None:
        """Periodically send pings."""
        while True:
            await self._tydom_client.ping()
            await asyncio.sleep(30)

    async def refresh_all(self) -> None:
        """Periodically refresh all metadata and data."""
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
        """Refresh data for polled devices (1s interval)."""
        while True:
            await self._tydom_client.poll_devices_data_1s()
            await asyncio.sleep(1)

    async def refresh_data(self) -> None:
        """Periodically refresh data for non-push devices."""
        while True:
            if self._refresh_interval > 0:
                await self._tydom_client.poll_devices_data_5m()
                await asyncio.sleep(self._refresh_interval)
            else:
                await asyncio.sleep(60)
