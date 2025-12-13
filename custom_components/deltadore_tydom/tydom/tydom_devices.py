"""Support for Tydom classes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from ..const import LOGGER

if TYPE_CHECKING:
    from collections.abc import Callable

    from .tydom_client import TydomClient


class TydomDevice:
    """represents a generic device."""

    _ha_device = None

    def __init__(
        self,
        tydom_client: TydomClient,
        uid: str,
        device_id: str,
        name: str,
        device_type: str,
        endpoint: str | None,
        metadata: dict | None,
        data: dict | None,
    ):
        """Initialize a TydomDevice."""
        self._tydom_client = tydom_client
        self._uid = uid
        self._id = device_id
        self._name = name
        self._type = device_type
        self._endpoint = endpoint
        self._metadata = metadata
        self._callbacks = set()
        if data is not None:
            for key in data:
                if isinstance(data[key], dict):
                    LOGGER.debug("type of %s : %s", key, type(data[key]))
                    LOGGER.debug("%s => %s", key, data[key])
                    setattr(self, key, data[key])
                elif isinstance(data[key], list):
                    LOGGER.debug("type of %s : %s", key, type(data[key]))
                    LOGGER.debug("%s => %s", key, data[key])
                    setattr(self, key, data[key])
                else:
                    setattr(self, key, data[key])

    def register_callback(self, callback: Callable[[], None]) -> None:
        """Register callback, called when state changes."""
        self._callbacks.add(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        """Remove previously registered callback."""
        self._callbacks.discard(callback)

    @property
    def device_id(self) -> str:
        """Return ID for device."""
        return self._uid

    @property
    def device_name(self) -> str:
        """Return name for device."""
        return self._name

    @property
    def device_type(self) -> str:
        """Return type for device."""
        return self._type

    @property
    def device_endpoint(self) -> str | None:
        """Return endpoint for device."""
        return self._endpoint

    async def update_device(self, device):
        """Update the device values from another device."""
        LOGGER.debug("Update device %s", device.device_id)
        for attribute, value in device.__dict__.items():
            # Mettre à jour tous les attributs publics, même s'ils sont None
            # Cela permet de mettre à jour correctement les valeurs qui passent à None
            if attribute == "_uid" or attribute[:1] != "_":
                # Ne pas mettre à jour les attributs internes comme _tydom_client, _callbacks, etc.
                if attribute not in [
                    "_tydom_client",
                    "_callbacks",
                    "_ha_device",
                    "_metadata",
                ]:
                    setattr(self, attribute, value)
        await self.publish_updates()
        if hasattr(self, "_ha_device") and self._ha_device is not None:
            try:
                self._ha_device.async_write_ha_state()
            except Exception:
                LOGGER.exception("update failed")

    async def publish_updates(self) -> None:
        """Schedule call all registered callbacks."""
        for callback in self._callbacks:
            callback()


class Tydom(TydomDevice):
    """Tydom Gateway."""

    async def async_trigger_firmware_update(self) -> None:
        """Trigger firmware update."""
        LOGGER.debug("Installing firmware update...")
        await self._tydom_client.update_firmware()


class TydomShutter(TydomDevice):
    """Represents a shutter."""

    async def down(self) -> None:
        """Tell cover to go down."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "positionCmd", "DOWN"
        )

    async def up(self) -> None:
        """Tell cover to go up."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "positionCmd", "UP"
        )

    async def stop(self) -> None:
        """Tell cover to stop moving."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "positionCmd", "STOP"
        )

    async def set_position(self, position: int) -> None:
        """Set cover to the given position."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "position", str(position)
        )

    # FIXME replace command
    async def slope_open(self) -> None:
        """Tell the cover to tilt open."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "slopeCmd", "DOWN"
        )

    # FIXME replace command
    async def slope_close(self) -> None:
        """Tell the cover to tilt closed."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "slopeCmd", "UP"
        )

    # FIXME replace command
    async def slope_stop(self) -> None:
        """Tell the cover to stop tilt."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "slopeCmd", "STOP"
        )

    # FIXME replace command
    async def set_slope_position(self, position: int) -> None:
        """Set cover to the given position."""
        LOGGER.debug("set roller tilt position (device) to : %s", position)

        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "slope", str(position)
        )


class TydomEnergy(TydomDevice):
    """Represents an energy sensor (for example TYWATT)."""


class TydomSmoke(TydomDevice):
    """Represents an smoke detector sensor."""


class TydomBoiler(TydomDevice):
    """Represents a Boiler."""

    async def set_hvac_mode(self, mode):
        """Set hvac mode (ANTI_FROST/NORMAL/STOP)."""
        LOGGER.debug("setting hvac mode to %s", mode)
        if mode == "ANTI_FROST":
            if hasattr(self, "hvacMode"):
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "setpoint", None
                )
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "thermicLevel", "STOP"
                )
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "hvacMode", "ANTI_FROST"
                )
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "antifrostOn", True
                )
                await self._tydom_client.put_data("/home/absence", "to", -1)
                await self._tydom_client.put_data("/events/home/absence", "to", -1)
                await self._tydom_client.put_data(
                    "/events/home/absence", "actions", "in"
                )
            else:
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "thermicLevel", "ANTI_FROST"
                )
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "comfortMode", "HEATING"
                )
        elif mode == "NORMAL":
            if hasattr(self, "hvacMode"):
                hvac_mode = getattr(self, "hvacMode", None)
                if hvac_mode == "ANTI_FROST":
                    await self._tydom_client.put_data("/home/absence", "to", 0)
                    await self._tydom_client.put_data("/events/home/absence", "to", 0)
                    await self._tydom_client.put_data(
                        "/events/home/absence", "actions", "in"
                    )
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "hvacMode", "NORMAL"
                )
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "authorization", "HEATING"
                )
                await self.set_temperature("19.0")
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "antifrostOn", False
                )
            else:
                if (
                    self._metadata is not None
                    and "thermicLevel" in self._metadata
                    and "enum_values" in self._metadata["thermicLevel"]
                ):
                    if "COMFORT" in self._metadata["thermicLevel"]["enum_values"]:
                        await self._tydom_client.put_devices_data(
                            self._id, self._endpoint, "thermicLevel", "COMFORT"
                        )
                    elif "HEATING" in self._metadata["thermicLevel"]["enum_values"]:
                        await self._tydom_client.put_devices_data(
                            self._id, self._endpoint, "thermicLevel", "HEATING"
                        )

                if (
                    self._metadata is not None
                    and "comfortMode" in self._metadata
                    and "enum_values" in self._metadata["comfortMode"]
                    and "HEATING" in self._metadata["comfortMode"]["enum_values"]
                ):
                    await self._tydom_client.put_devices_data(
                        self._id, self._endpoint, "comfortMode", "HEATING"
                    )

        elif mode == "STOP":
            if hasattr(self, "hvacMode"):
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "hvacMode", "STOP"
                )
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "authorization", "STOP"
                )
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "thermicLevel", "STOP"
                )
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "setpoint", None
                )
            else:
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "thermicLevel", "STOP"
                )
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "comfortMode", "STOP"
                )
        elif mode == "COOLING":
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "comfortMode", "COOLING"
            )
        else:
            LOGGER.error("Unknown hvac mode: %s", mode)

    async def set_temperature(self, temperature):
        """Set target temperature."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "setpoint", temperature
        )

    async def set_area_data(self, name, value):
        """Set data for the linked area."""
        if hasattr(self, 'link_id'):
            LOGGER.debug("setting area data for %s to %s on area %s", name, value, self.link_id)
            await self._tydom_client.put_areas_data(self.link_id, name, value)



class TydomWindow(TydomDevice):
    """represents a window."""


class TydomDoor(TydomDevice):
    """represents a door."""


class TydomGate(TydomDevice):
    """represents a gate."""

    async def open(self) -> None:
        """Tell garage door to open."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "levelCmd", "ON"
        )

    async def close(self) -> None:
        """Tell garage door to close."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "levelCmd", "OFF"
        )

    async def stop(self) -> None:
        """Tell garage door to stop."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "levelCmd", "STOP"
        )

    async def toggle(self) -> None:
        """Tell garage door to stop."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "levelCmd", "TOGGLE"
        )


class TydomGarage(TydomDevice):
    """represents a garage door."""

    async def open(self) -> None:
        """Tell garage door to open."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "levelCmd", "ON"
        )

    async def close(self) -> None:
        """Tell garage door to close."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "levelCmd", "OFF"
        )

    async def stop(self) -> None:
        """Tell garage door to stop."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "levelCmd", "STOP"
        )

    async def toggle(self) -> None:
        """Tell garage door to stop."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "levelCmd", "TOGGLE"
        )


class TydomLight(TydomDevice):
    """represents a light."""

    async def turn_on(self, brightness) -> None:
        """Tell light to turn on."""
        if brightness is None:
            command = "TOGGLE"
            if (
                self._metadata is not None
                and "levelCmd" in self._metadata
                and "enum_values" in self._metadata["levelCmd"]
            ):
                if "ON" in self._metadata["levelCmd"]["enum_values"]:
                    command = "ON"

                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "levelCmd", command
                )
            else:
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "level", "100"
                )

        else:
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "level", str(brightness)
            )
        self._tydom_client.add_poll_device_url_1s(
            f"/devices/{self._id}/endpoints/{self._endpoint}/cdata"
        )

    async def turn_off(self) -> None:
        """Tell light to turn off."""

        command = "TOGGLE"
        if (
            self._metadata is not None
            and "levelCmd" in self._metadata
            and "enum_values" in self._metadata["levelCmd"]
        ):
            if "OFF" in self._metadata["levelCmd"]["enum_values"]:
                command = "OFF"

            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "levelCmd", command
            )
        else:
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "level", "0"
            )

        self._tydom_client.add_poll_device_url_1s(
            f"/devices/{self._id}/endpoints/{self._endpoint}/cdata"
        )


class TydomAlarm(TydomDevice):
    """represents an alarm."""

    def is_legacy_alarm(self) -> bool:
        """Check if alarm is legacy."""
        if hasattr(self, "part1State"):
            return True
        return False

    async def alarm_disarm(self, code) -> None:
        """Disarm alarm."""
        await self._tydom_client.put_alarm_cdata(
            self._id, self._endpoint, code, "OFF", None, self.is_legacy_alarm()
        )
        # self._tydom_client.add_poll_device_url_1s(f"/devices/{self._id}/endpoints/{self._endpoint}/cdata")

    async def alarm_arm_away(self, code=None) -> None:
        """Arm away alarm."""
        await self._tydom_client.put_alarm_cdata(
            self._id,
            self._endpoint,
            code,
            "ON",
            self._tydom_client._zone_away,
            self.is_legacy_alarm(),
        )
        # self._tydom_client.add_poll_device_url_1s(f"/devices/{self._id}/endpoints/{self._endpoint}/cdata")

    async def alarm_arm_home(self, code=None) -> None:
        """Arm home alarm."""
        await self._tydom_client.put_alarm_cdata(
            self._id,
            self._endpoint,
            code,
            "ON",
            self._tydom_client._zone_home,
            self.is_legacy_alarm(),
        )
        # self._tydom_client.add_poll_device_url_1s(f"/devices/{self._id}/endpoints/{self._endpoint}/cdata")

    async def alarm_arm_night(self, code=None) -> None:
        """Arm night alarm."""
        await self._tydom_client.put_alarm_cdata(
            self._id,
            self._endpoint,
            code,
            "ON",
            self._tydom_client._zone_night,
            self.is_legacy_alarm(),
        )

    async def alarm_trigger(self, code=None) -> None:
        """Trigger the alarm.

        This will trigger a SOS alarm for 90 seconds.
        """
        await self._tydom_client.put_alarm_cdata(
            self._id, self._endpoint, code, "PANIC", None, self.is_legacy_alarm()
        )

    async def acknowledge_events(self, code) -> None:
        """Acknowledge alarm events."""
        await self._tydom_client.put_ackevents_cdata(self._id, self._endpoint, code)

    _KEPT_KEYS: ClassVar = {
        "": {"name", "date", "zones", "accessCode", "product"},
        "product": {"nameCustom", "nameStd", "number", "typeLong"},
        "accessCode": {
            "nameCustom",
        },
    }

    def _format_alarm_event(self, event: Any, key: str = "") -> Any:
        """Format raw event."""
        if isinstance(event, dict):
            keys_list = self._KEPT_KEYS.get(key, set(event))
            return {
                k: self._format_alarm_event(v, k)
                for k, v in event.items()
                if k in keys_list
            }
        elif isinstance(event, list):
            return [self._format_alarm_event(i, key) for i in event]
        else:
            return event

    async def get_events(self, event_type: str | None) -> list[dict[str, Any]]:
        """Get alarm events."""
        if self._endpoint is None:
            LOGGER.error("Cannot get events: endpoint is None for device %s", self._id)
            return []
        events = await self._tydom_client.get_historic_cdata(
            self._id, self._endpoint, event_type
        )

        LOGGER.debug("Raw messages: %s", events)
        # Raw message struct: {
        #   "name":"histo",
        #   "parameters":{"type":"<event_type>","nbElem":10,"indexStart":0},
        #   "values":{"step":0,"nbElemTot":1,"index":0,"event":{...}}
        # }
        return [
            self._format_alarm_event(m["values"]["event"])
            for m in (events or [])
            if m.get("values", {}).get("event") is not None
        ]


class TydomWeather(TydomDevice):
    """Represents a weather sensor."""


class TydomWater(TydomDevice):
    """Represents a water leak sensor."""


class TydomThermo(TydomDevice):
    """Represents a thermometer."""


class TydomScene(TydomDevice):
    """Represents a scene/scenario."""

    def __init__(
        self,
        tydom_client: TydomClient,
        uid: str,
        device_id: str,
        name: str,
        device_type: str,
        endpoint: str | None,
        metadata: dict | None,
        data: dict | None,
    ):
        """Initialize a TydomScene with special handling for epAct and grpAct."""
        # Stocker epAct et grpAct comme attributs privés pour éviter l'exposition automatique
        if data is not None:
            # Faire une copie pour ne pas modifier le dictionnaire original
            data_copy = data.copy()
            grp_act = data_copy.pop("grpAct", None)
            ep_act = data_copy.pop("epAct", None)
            super().__init__(
                tydom_client,
                uid,
                device_id,
                name,
                device_type,
                endpoint,
                metadata,
                data_copy,
            )
            # Stocker comme attributs privés (commençant par _)
            if grp_act is not None:
                self._grp_act = grp_act
            if ep_act is not None:
                self._ep_act = ep_act
        else:
            super().__init__(
                tydom_client,
                uid,
                device_id,
                name,
                device_type,
                endpoint,
                metadata,
                data,
            )

    @property
    def grpAct(self):
        """Get grpAct as a property to maintain compatibility."""
        return getattr(self, "_grp_act", None)

    @property
    def epAct(self):
        """Get epAct as a property to maintain compatibility."""
        return getattr(self, "_ep_act", None)

    async def activate(self) -> None:
        """Activate the scene."""
        LOGGER.debug("Activating scene %s", self.device_id)
        # Scenarios are activated via PUT /scenarios/{id}
        scene_id = getattr(self, "scene_id", None) or self._id
        await self._tydom_client.activate_scenario(scene_id)
