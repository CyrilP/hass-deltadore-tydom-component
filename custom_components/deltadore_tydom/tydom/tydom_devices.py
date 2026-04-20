"""Support for Tydom device classes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from ..const import LOGGER

if TYPE_CHECKING:
    from collections.abc import Callable
    from .tydom_client import TydomClient


class TydomDevice:
    """Represents a generic Tydom device."""

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
        self._callbacks: set[Callable[[], None]] = set()
        if data is not None:
            for key, value in data.items():
                setattr(self, key, value)

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
        """Update device values from another device instance."""
        skip = {"_tydom_client", "_callbacks", "_ha_device", "_metadata"}
        for attr, value in device.__dict__.items():
            if attr == "_uid" or (attr[:1] != "_" and attr not in skip):
                setattr(self, attr, value)
        await self.publish_updates()
        if self._ha_device is not None:
            try:
                self._ha_device.async_write_ha_state()
            except Exception:
                LOGGER.exception("update failed")

    async def publish_updates(self) -> None:
        """Call all registered callbacks."""
        for callback in self._callbacks:
            callback()


class Tydom(TydomDevice):
    """Tydom Gateway."""

    async def async_trigger_firmware_update(self) -> None:
        """Trigger firmware update."""
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
        """Tell cover to stop."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "positionCmd", "STOP"
        )

    async def set_position(self, position: int) -> None:
        """Set cover position."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "position", str(position)
        )

    async def slope_open(self) -> None:
        """Tilt open."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "slopeCmd", "DOWN"
        )

    async def slope_close(self) -> None:
        """Tilt close."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "slopeCmd", "UP"
        )

    async def slope_stop(self) -> None:
        """Stop tilt."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "slopeCmd", "STOP"
        )

    async def set_slope_position(self, position: int) -> None:
        """Set tilt position."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "slope", str(position)
        )


class TydomEnergy(TydomDevice):
    """Represents an energy sensor (e.g. TYWATT)."""


class TydomSmoke(TydomDevice):
    """Represents a smoke detector."""


class TydomBoiler(TydomDevice):
    """Represents a Boiler / thermostat."""

    def _meta_has(self, field: str, value: str) -> bool:
        """Check if metadata field contains a value in enum_values."""
        if self._metadata is None:
            return False
        return value in self._metadata.get(field, {}).get("enum_values", [])

    async def set_hvac_mode(self, mode):
        """Set hvac mode (ANTI_FROST/NORMAL/STOP/COOLING)."""
        LOGGER.debug("setting hvac mode to %s", mode)
        put = self._tydom_client.put_devices_data
        put_path = self._tydom_client.put_data
        has_hvac = hasattr(self, "hvacMode")

        if mode == "ANTI_FROST":
            if has_hvac:
                await put(self._id, self._endpoint, "setpoint", None)
                await put(self._id, self._endpoint, "thermicLevel", "STOP")
                await put(self._id, self._endpoint, "hvacMode", "ANTI_FROST")
                await put(self._id, self._endpoint, "antifrostOn", True)
                await put_path("/home/absence", "to", -1)
                await put_path("/events/home/absence", "to", -1)
                await put_path("/events/home/absence", "actions", "in")
            else:
                await put(self._id, self._endpoint, "thermicLevel", "ANTI_FROST")
                await put(self._id, self._endpoint, "comfortMode", "HEATING")

        elif mode == "NORMAL":
            if has_hvac:
                if getattr(self, "hvacMode", None) == "ANTI_FROST":
                    await put_path("/home/absence", "to", 0)
                    await put_path("/events/home/absence", "to", 0)
                    await put_path("/events/home/absence", "actions", "in")
                await put(self._id, self._endpoint, "hvacMode", "NORMAL")
                await put(self._id, self._endpoint, "authorization", "HEATING")
                await self.set_temperature("19.0")
                await put(self._id, self._endpoint, "antifrostOn", False)
            else:
                for level in ("COMFORT", "HEATING"):
                    if self._meta_has("thermicLevel", level):
                        await put(self._id, self._endpoint, "thermicLevel", level)
                        break
                if self._meta_has("comfortMode", "HEATING"):
                    await put(self._id, self._endpoint, "comfortMode", "HEATING")

        elif mode == "STOP":
            if has_hvac:
                for field in ("hvacMode", "authorization", "thermicLevel"):
                    await put(self._id, self._endpoint, field, "STOP")
                await put(self._id, self._endpoint, "setpoint", None)
            else:
                await put(self._id, self._endpoint, "thermicLevel", "STOP")
                await put(self._id, self._endpoint, "comfortMode", "STOP")

        elif mode == "COOLING":
            await put(self._id, self._endpoint, "comfortMode", "COOLING")
        else:
            LOGGER.error("Unknown hvac mode: %s", mode)

    async def set_temperature(self, temperature):
        """Set target temperature."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "setpoint", temperature
        )


class TydomWindow(TydomDevice):
    """Represents a window."""


class TydomDoor(TydomDevice):
    """Represents a door."""


class _TydomToggleCover(TydomDevice):
    """Base for toggle-based covers (gate, garage)."""

    async def open(self) -> None:
        """Open."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "levelCmd", "ON"
        )

    async def close(self) -> None:
        """Close."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "levelCmd", "OFF"
        )

    async def stop(self) -> None:
        """Stop."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "levelCmd", "STOP"
        )

    async def toggle(self) -> None:
        """Toggle."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "levelCmd", "TOGGLE"
        )


class TydomGate(_TydomToggleCover):
    """Represents a gate."""


class TydomGarage(_TydomToggleCover):
    """Represents a garage door."""


class TydomLight(TydomDevice):
    """Represents a light."""

    async def turn_on(self, brightness) -> None:
        """Turn light on."""
        if brightness is None:
            meta = (self._metadata or {}).get("levelCmd", {})
            enums = meta.get("enum_values", [])
            if enums:
                cmd = "ON" if "ON" in enums else "TOGGLE"
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "levelCmd", cmd
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
        """Turn light off."""
        meta = (self._metadata or {}).get("levelCmd", {})
        enums = meta.get("enum_values", [])
        if enums:
            cmd = "OFF" if "OFF" in enums else "TOGGLE"
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "levelCmd", cmd
            )
        else:
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, "level", "0"
            )
        self._tydom_client.add_poll_device_url_1s(
            f"/devices/{self._id}/endpoints/{self._endpoint}/cdata"
        )


class TydomAlarm(TydomDevice):
    """Represents an alarm."""

    def is_legacy_alarm(self) -> bool:
        """Check if alarm is legacy."""
        return hasattr(self, "part1State")

    async def alarm_disarm(self, code) -> None:
        """Disarm alarm."""
        await self._tydom_client.put_alarm_cdata(
            self._id, self._endpoint, code, "OFF", None, self.is_legacy_alarm()
        )

    async def alarm_arm_away(self, code=None) -> None:
        """Arm away."""
        await self._tydom_client.put_alarm_cdata(
            self._id, self._endpoint, code, "ON",
            self._tydom_client._zone_away, self.is_legacy_alarm(),
        )

    async def alarm_arm_home(self, code=None) -> None:
        """Arm home."""
        await self._tydom_client.put_alarm_cdata(
            self._id, self._endpoint, code, "ON",
            self._tydom_client._zone_home, self.is_legacy_alarm(),
        )

    async def alarm_arm_night(self, code=None) -> None:
        """Arm night."""
        await self._tydom_client.put_alarm_cdata(
            self._id, self._endpoint, code, "ON",
            self._tydom_client._zone_night, self.is_legacy_alarm(),
        )

    async def alarm_trigger(self, code=None) -> None:
        """Trigger SOS alarm for 90 seconds."""
        await self._tydom_client.put_alarm_cdata(
            self._id, self._endpoint, code, "PANIC", None, self.is_legacy_alarm()
        )

    async def acknowledge_events(self, code) -> None:
        """Acknowledge alarm events."""
        await self._tydom_client.put_ackevents_cdata(self._id, self._endpoint, code)

    _KEPT_KEYS: ClassVar = {
        "": {"name", "date", "zones", "accessCode", "product"},
        "product": {"nameCustom", "nameStd", "number", "typeLong"},
        "accessCode": {"nameCustom"},
    }

    def _format_alarm_event(self, event: Any, key: str = "") -> Any:
        """Format raw event, keeping only relevant keys."""
        if isinstance(event, dict):
            keys_list = self._KEPT_KEYS.get(key, set(event))
            return {
                k: self._format_alarm_event(v, k)
                for k, v in event.items()
                if k in keys_list
            }
        if isinstance(event, list):
            return [self._format_alarm_event(i, key) for i in event]
        return event

    async def get_events(self, event_type: str | None) -> list[dict[str, Any]]:
        """Get alarm events."""
        if self._endpoint is None:
            LOGGER.error("Cannot get events: endpoint is None for device %s", self._id)
            return []
        events = await self._tydom_client.get_historic_cdata(
            self._id, self._endpoint, event_type
        )
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

    def __init__(self, tydom_client, uid, device_id, name, device_type, endpoint, metadata, data):
        """Initialize with special handling for epAct and grpAct."""
        if data is not None:
            data_copy = data.copy()
            grp_act = data_copy.pop("grpAct", None)
            ep_act = data_copy.pop("epAct", None)
            super().__init__(tydom_client, uid, device_id, name, device_type, endpoint, metadata, data_copy)
            if grp_act is not None:
                self._grp_act = grp_act
            if ep_act is not None:
                self._ep_act = ep_act
        else:
            super().__init__(tydom_client, uid, device_id, name, device_type, endpoint, metadata, data)

    @property
    def grpAct(self):
        """Get grpAct (group actions)."""
        return getattr(self, "_grp_act", None)

    @property
    def epAct(self):
        """Get epAct (endpoint actions)."""
        return getattr(self, "_ep_act", None)

    async def activate(self) -> None:
        """Activate the scene."""
        LOGGER.debug("Activating scene %s", self.device_id)
        scene_id = getattr(self, "scene_id", None) or self._id
        await self._tydom_client.activate_scenario(scene_id)
