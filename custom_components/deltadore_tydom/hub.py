"""A demonstration 'hub' that connects several devices."""

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
)

from .const import LOGGER


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
        alarmpin: str,
    ) -> None:
        """Init hub."""
        self._host = host
        self._mac = mac
        self._pass = password
        self._refresh_interval = int(refresh_interval) * 60
        self._zone_home = zone_home
        self._zone_away = zone_away
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

        self._tydom_client = TydomClient(
            hass=self._hass,
            id=self._id,
            mac=self._mac,
            host=self._host,
            password=self._pass,
            zone_home=self._zone_home,
            zone_away=self._zone_away,
            alarm_pin=self._pin,
            event_callback=self.handle_event,
        )

        self.online = True

    def update_config(self, refresh_interval, zone_home, zone_away):
        """Update zone configuration."""
        self._tydom_client.update_config(zone_home, zone_away)
        self._refresh_interval = int(refresh_interval) * 60
        self._zone_home = zone_home
        self._zone_away = zone_away

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
        return (
            self.add_cover_callback is not None
            and self.add_sensor_callback is not None
            and self.add_climate_callback is not None
            and self.add_light_callback is not None
            and self.add_lock_callback is not None
            and self.add_update_callback is not None
            and self.add_alarm_callback is not None
        )

    async def setup(self, connection: ClientWebSocketResponse) -> None:
        """Listen to tydom events."""
        # wait for callbacks to become available
        while not self.ready():
            await asyncio.sleep(1)
        LOGGER.debug("Listen to tydom events")
        while True:
            devices = await self._tydom_client.consume_messages()
            if devices is not None:
                for device in devices:
                    if device.device_id not in self.devices:
                        self.devices[device.device_id] = device
                        await self.create_ha_device(device)
                    else:
                        LOGGER.debug(
                            "update device %s : %s",
                            device.device_id,
                            self.devices[device.device_id],
                        )
                        await self.update_ha_device(
                            self.devices[device.device_id], device
                        )

    async def create_ha_device(self, device):  # noqa: C901
        """Create a new HA device."""
        match device:
            case Tydom():
                LOGGER.debug("Create Tydom gateway %s", device.device_id)
                self.devices[device.device_id] = device
                ha_device = HATydom(device, self._hass)
                self.ha_devices[device.device_id] = ha_device
                if self.add_update_callback is not None:
                    self.add_update_callback([ha_device])
                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case TydomShutter():
                LOGGER.debug("Create cover %s", device.device_id)
                ha_device = HACover(device, self._hass)
                self.ha_devices[device.device_id] = ha_device
                if self.add_cover_callback is not None:
                    self.add_cover_callback([ha_device])
                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case TydomEnergy():
                LOGGER.debug("Create conso %s", device.device_id)
                ha_device = HAEnergy(device, self._hass)
                self.ha_devices[device.device_id] = ha_device

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback([ha_device])

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())

            case TydomSmoke():
                LOGGER.debug("Create smoke %s", device.device_id)
                ha_device = HASmoke(device, self._hass)
                self.ha_devices[device.device_id] = ha_device
                if self.add_sensor_callback is not None:
                    self.add_sensor_callback([ha_device])

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case TydomBoiler():
                LOGGER.debug("Create boiler %s", device.device_id)
                ha_device = HaClimate(device, self._hass)
                self.ha_devices[device.device_id] = ha_device
                if self.add_climate_callback is not None:
                    self.add_climate_callback([ha_device])

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case TydomWindow():
                LOGGER.debug("Create window %s", device.device_id)
                ha_device = HaWindow(device, self._hass)
                self.ha_devices[device.device_id] = ha_device
                if self.add_cover_callback is not None:
                    self.add_cover_callback([ha_device])

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case TydomDoor():
                LOGGER.debug("Create door %s", device.device_id)
                ha_device = HaDoor(device, self._hass)
                self.ha_devices[device.device_id] = ha_device
                if self.add_cover_callback is not None:
                    self.add_cover_callback([ha_device])

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case TydomGate():
                LOGGER.debug("Create gate %s", device.device_id)
                ha_device = HaGate(device, self._hass)
                self.ha_devices[device.device_id] = ha_device
                if self.add_cover_callback is not None:
                    self.add_cover_callback([ha_device])

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case TydomGarage():
                LOGGER.debug("Create garage %s", device.device_id)
                ha_device = HaGarage(device, self._hass)
                self.ha_devices[device.device_id] = ha_device
                if self.add_cover_callback is not None:
                    self.add_cover_callback([ha_device])

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case TydomLight():
                LOGGER.debug("Create light %s", device.device_id)
                ha_device = HaLight(device, self._hass)
                self.ha_devices[device.device_id] = ha_device
                if self.add_light_callback is not None:
                    self.add_light_callback([ha_device])

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case TydomAlarm():
                LOGGER.debug("Create alarm %s", device.device_id)
                ha_device = HaAlarm(device, self._hass)
                self.ha_devices[device.device_id] = ha_device
                if self.add_alarm_callback is not None:
                    self.add_alarm_callback([ha_device])

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case _:
                LOGGER.error(
                    "unsupported device type (%s) %s for device %s",
                    type(device),
                    device.device_type,
                    device.device_id,
                )
                return

    async def update_ha_device(self, stored_device, device):
        """Update HA device values."""
        try:
            await stored_device.update_device(device)
            ha_device = self.ha_devices[device.device_id]
            new_sensors = ha_device.get_sensors()
            if len(new_sensors) > 0 and self.add_sensor_callback is not None:
                # add new sensors
                self.add_sensor_callback(new_sensors)
            # ha_device.publish_updates()
            # ha_device.update()
        except Exception:
            LOGGER.exception("update failed")

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
            await asyncio.sleep(600)

    async def refresh_data_1s(self) -> None:
        """Refresh data for devices in list."""
        while True:
            await self._tydom_client.poll_devices_data_1s()
            await asyncio.sleep(1)

    async def refresh_data(self) -> None:
        """Periodically refresh data for devices which don't do push."""
        while True:
            if self._refresh_interval > 0:
                await self._tydom_client.poll_devices_data_5m()
                await asyncio.sleep(self._refresh_interval)
            else:
                await asyncio.sleep(60)
