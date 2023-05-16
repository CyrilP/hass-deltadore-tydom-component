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
from .tydom.tydom_devices import TydomBaseEntity
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
        self._id = "Tydom-" + mac
        self.device_info = TydomBaseEntity(None, None, None, None, None, None, None, None, None, None, None, False)
        self.devices = {}
        self.ha_devices = {}
        self.add_cover_callback = None
        self.add_sensor_callback = None
        self.add_climate_callback = None
        self.add_light_callback = None
        self.add_lock_callback = None

        self._tydom_client = TydomClient(
            hass=self._hass,
            mac=self._mac,
            host=self._host,
            password=self._pass,
            alarm_pin=self._pin,
            event_callback=self.handle_event
        )

        self.rollers = [
        #    Roller(f"{self._id}_1", f"{self._name} 1", self),
        #    Roller(f"{self._id}_2", f"{self._name} 2", self),
        #    Roller(f"{self._id}_3", f"{self._name} 3", self),
        ]
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
                    logger.info("*** device %s", device)
                    if isinstance(device, TydomBaseEntity):
                        await self.device_info.update_device(device)
                    else:
                        logger.error("*** publish_updates for device : %s", device)
                        if device.device_id not in self.devices:
                            self.devices[device.device_id] = device
                            await self.create_ha_device(device)
                        else:
                            logger.warn("update device %s : %s", device.device_id, self.devices[device.device_id])
                            await self.update_ha_device(self.devices[device.device_id], device)

    async def create_ha_device(self, device):
        """Create a new HA device"""
        logger.warn("device type %s", device.device_type)
        match device:
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
                ha_device = HAEnergy(device)
                self.ha_devices[device.device_id] = ha_device
                if self.add_sensor_callback is not None:
                    self.add_sensor_callback([ha_device])

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
                logger.error("unsupported device type (%s) %s for device %s", type(device), device.device_type, device.device_id)
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


class Roller:
    """Dummy roller (device for HA) for Hello World example."""

    def __init__(self, rollerid: str, name: str, hub: Hub) -> None:
        """Init dummy roller."""
        self._id = rollerid
        self.hub = hub
        self.name = name
        self._callbacks = set()
        self._loop = asyncio.get_event_loop()
        self._target_position = 100
        self._current_position = 100
        # Reports if the roller is moving up or down.
        # >0 is up, <0 is down. This very much just for demonstration.
        self.moving = 0

        # Some static information about this device
        self.firmware_version = f"0.0.{random.randint(1, 9)}"
        self.model = "Test Device"

    @property
    def roller_id(self) -> str:
        """Return ID for roller."""
        return self._id

    @property
    def position(self):
        """Return position for roller."""
        logger.error("get roller position")
        return self._current_position

    async def set_position(self, position: int) -> None:
        """
        Set dummy cover to the given position.
        State is announced a random number of seconds later.
        """
        logger.error("set roller position")
        self._target_position = position

        # Update the moving status, and broadcast the update
        self.moving = position - 50
        await self.publish_updates()

        self._loop.create_task(self.delayed_update())

    async def delayed_update(self) -> None:
        """Publish updates, with a random delay to emulate interaction with device."""
        logger.error("delayed_update")
        await asyncio.sleep(random.randint(1, 10))
        self.moving = 0
        await self.publish_updates()

    def register_callback(self, callback: Callable[[], None]) -> None:
        """Register callback, called when Roller changes state."""
        logger.error("register_callback %s", callback)
        self._callbacks.add(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        """Remove previously registered callback."""
        logger.error("remove_callback")
        self._callbacks.discard(callback)

    # In a real implementation, this library would call it's call backs when it was
    # notified of any state changeds for the relevant device.
    async def publish_updates(self) -> None:
        """Schedule call all registered callbacks."""
        logger.error("publish_updates")
        self._current_position = self._target_position
        for callback in self._callbacks:
            callback()

    @property
    def online(self) -> float:
        """Roller is online."""
        logger.error("online")
        # The dummy roller is offline about 10% of the time. Returns True if online,
        # False if offline.
        return random.random() > 0.1

    @property
    def battery_level(self) -> int:
        """Battery level as a percentage."""
        logger.error("battery_level")
        return random.randint(0, 100)

    @property
    def battery_voltage(self) -> float:
        """Return a random voltage roughly that of a 12v battery."""
        logger.error("battery_voltage")
        return round(random.random() * 3 + 10, 2)

    @property
    def illuminance(self) -> int:
        """Return a sample illuminance in lux."""
        logger.error("illuminance")
        return random.randint(0, 500)
