"""A demonstration 'hub' that connects several devices."""
from __future__ import annotations

# In a real implementation, this would be in an external library that's on PyPI.
# The PyPI package needs to be included in the `requirements` section of manifest.json
# See https://developers.home-assistant.io/docs/creating_integration_manifest
# for more information.
# This dummy hub always returns 3 rollers.
import asyncio
import random
import logging
import time
from typing import Callable
from aiohttp import ClientWebSocketResponse, ClientSession

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from .tydom.tydom_client import TydomClient
from .tydom.tydom_devices import Tydom
from .ha_entities import *

logger = logging.getLogger(__name__)


class Hub:
    """Hub for Delta Dore Tydom."""

    manufacturer = "Delta Dore"

    def handle_event(self, event):
        """Event callback"""
        pass

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        mac: str,
        password: str,
        alarmpin: str,
    ) -> None:
        """Init hub."""
        self._host = host
        self._mac = mac
        self._pass = password
        self._pin = alarmpin
        self._hass = hass
        self._name = mac
        self._id = "Tydom-" + mac[6:]
        self.device_info = Tydom(None, None, None, None, None, None, None)
        self.devices = {}
        self.ha_devices = {}
        self.add_cover_callback = None
        self.add_sensor_callback = None
        self.add_climate_callback = None
        self.add_light_callback = None
        self.add_lock_callback = None
        self.add_light_callback = None

        self._tydom_client = TydomClient(
            hass=self._hass,
            id=self._id,
            mac=self._mac,
            host=self._host,
            password=self._pass,
            alarm_pin=self._pin,
            event_callback=self.handle_event,
        )

        self.online = True

    @property
    def hub_id(self) -> str:
        """ID for dummy hub."""
        return self._id

    async def connect(self) -> ClientWebSocketResponse:
        """Connect to Tydom"""
        connection = await self._tydom_client.async_connect()
        await self._tydom_client.listen_tydom(connection)
        return connection

    @staticmethod
    async def get_tydom_credentials(
        session: ClientSession, email: str, password: str, macaddress: str
    ):
        """Get Tydom credentials"""
        return await TydomClient.async_get_credentials(
            session, email, password, macaddress
        )

    async def test_credentials(self) -> None:
        """Validate credentials."""
        connection = await self.connect()
        await connection.close()

    async def setup(self, connection: ClientWebSocketResponse) -> None:
        """Listen to tydom events."""
        logger.info("Listen to tydom events")
        while True:
            devices = await self._tydom_client.consume_messages()
            if devices is not None:
                for device in devices:
                    if device.device_id not in self.devices:
                        self.devices[device.device_id] = device
                        await self.create_ha_device(device)
                    else:
                        logger.warn(
                            "update device %s : %s",
                            device.device_id,
                            self.devices[device.device_id],
                        )
                        await self.update_ha_device(
                            self.devices[device.device_id], device
                        )

    async def create_ha_device(self, device):
        """Create a new HA device"""
        logger.warn("device type %s", device.device_type)
        match device:
            case Tydom(): 

                logger.info("Create Tydom gateway %s", device.device_id)
                self.devices[device.device_id] = self.device_info
                await self.device_info.update_device(device)
                ha_device = HATydom(self.device_info, self._hass)
                
                self.ha_devices[self.device_info.device_id] = ha_device
                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case TydomShutter():
                logger.warn("Create cover %s", device.device_id)
                ha_device = HACover(device)
                self.ha_devices[device.device_id] = ha_device
                if self.add_cover_callback is not None:
                    self.add_cover_callback([ha_device])
                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case TydomEnergy():
                logger.warn("Create conso %s", device.device_id)
                ha_device = HAEnergy(device, self._hass)
                self.ha_devices[device.device_id] = ha_device

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())

            case TydomSmoke():
                logger.warn("Create smoke %s", device.device_id)
                ha_device = HASmoke(device)
                self.ha_devices[device.device_id] = ha_device
                if self.add_sensor_callback is not None:
                    self.add_sensor_callback([ha_device])

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case TydomBoiler():
                logger.warn("Create boiler %s", device.device_id)
                ha_device = HaClimate(device)
                self.ha_devices[device.device_id] = ha_device
                if self.add_climate_callback is not None:
                    self.add_climate_callback([ha_device])

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case TydomWindow():
                logger.warn("Create window %s", device.device_id)
                ha_device = HaWindow(device)
                self.ha_devices[device.device_id] = ha_device
                if self.add_cover_callback is not None:
                    self.add_cover_callback([ha_device])

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case TydomDoor():
                logger.warn("Create door %s", device.device_id)
                ha_device = HaDoor(device)
                self.ha_devices[device.device_id] = ha_device
                if self.add_cover_callback is not None:
                    self.add_cover_callback([ha_device])

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case TydomGate():
                logger.warn("Create gate %s", device.device_id)
                ha_device = HaGate(device)
                self.ha_devices[device.device_id] = ha_device
                if self.add_cover_callback is not None:
                    self.add_cover_callback([ha_device])

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case TydomGarage():
                logger.warn("Create garage %s", device.device_id)
                ha_device = HaGarage(device)
                self.ha_devices[device.device_id] = ha_device
                if self.add_cover_callback is not None:
                    self.add_cover_callback([ha_device])

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case TydomLight():
                logger.warn("Create light %s", device.device_id)
                ha_device = HaLight(device)
                self.ha_devices[device.device_id] = ha_device
                if self.add_light_callback is not None:
                    self.add_light_callback([ha_device])

                if self.add_sensor_callback is not None:
                    self.add_sensor_callback(ha_device.get_sensors())
            case _:
                logger.error(
                    "unsupported device type (%s) %s for device %s",
                    type(device),
                    device.device_type,
                    device.device_id,
                )
                return

    async def update_ha_device(self, stored_device, device):
        """Update HA device values"""
        await stored_device.update_device(device)
        ha_device = self.ha_devices[device.device_id]
        new_sensors = ha_device.get_sensors()
        if len(new_sensors) > 0 and self.add_sensor_callback is not None:
            # add new sensors
            self.add_sensor_callback(new_sensors)

    async def ping(self) -> None:
        """Periodically send pings"""
        logger.info("Sending ping")
        while True:
            await self._tydom_client.ping()
            await asyncio.sleep(10)

    async def async_trigger_firmware_update(self) -> None:
        """Trigger firmware update"""
        logger.info("Installing firmware update...")
        self._tydom_client.update_firmware()
