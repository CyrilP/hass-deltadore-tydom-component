"""Support for Tydom classes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

from ..const import LOGGER, validate_value_with_metadata

if TYPE_CHECKING:
    from .tydom_client import TydomClient


_CONFIRMED_TUTORIAL_MODELS = {
    "25_tymoov": "TYMOOV",
    "35_se2000": "Tysense Thermo",
    "4_dvi_kline": "DVI K-Line",
    "6_pod_kline": "POD K-Line",
    "7_dvi_kline_fenetre_coul_battant": "DVI K-Line",
    "8_dvi_kline_fenetre_coul": "DVI K-Line",
    "8_tyxia6610": "TYXIA 6610",
    "sensor_dfr": "DFR TYXAL+",
    "smart_plug_dd": "Delta Dore Easy Plug",
    "split_takao_type_1": "Atlantic Naviclim 875311",
    "split_takao_type_2": "Atlantic Naviclim 875311",
    "tysense_sun": "Tysense Sun",
    "tywatt_serie1000": "TYWATT 1000",
    "tywell_control": "Tywell Control",
    "tywell_control_2050": "Tywell 2050",
    "volet_roulant_wellcom": "Well'com roller shutter",
}

_TUTORIAL_PREFIX_MODELS = {
    "rcu_tyxia1410": "TYXIA 1410",
    "switch_tyxia2600": "TYXIA 2600",
    "tl2000": "TL 2000 Tyxal+",
}


def is_binary_tyxia_receiver_profile(metadata: dict[str, Any] | None) -> bool:
    """Return whether metadata identifies a fixed-output TYXIA receiver."""
    if not isinstance(metadata, dict):
        return False

    level = metadata.get("level")
    level_cmd = metadata.get("levelCmd")
    if not isinstance(level, dict) or not isinstance(level_cmd, dict):
        return False

    commands = level_cmd.get("enum_values")
    if not isinstance(commands, list) or not {"ON", "OFF"}.issubset(commands):
        return False

    try:
        return (
            float(level.get("min")) == 0
            and float(level.get("max")) == 100
            and float(level.get("step")) == 100
        )
    except (TypeError, ValueError):
        return False


def is_tymoov_profile(data: dict[str, Any] | None) -> bool:
    """Return whether firmware descriptors identify the TYMOOV range."""
    if not isinstance(data, dict):
        return False
    return (
        data.get("softPlan0") == "24.28.00.20"
        and data.get("softPlan2") == "24.28.00.31"
        and data.get("softPlan3") == "22.10.00.30"
    )


def is_trv_1_profile(data: dict[str, Any] | None) -> bool:
    """Return whether issue #259's firmware descriptors identify a TRV 1.0."""
    if not isinstance(data, dict):
        return False
    return (
        data.get("softPlan0") == "24.22.00.14"
        and data.get("softPlan1") == "24.22.00.30"
        and data.get("softPlan2") == "24.22.00.20"
    )


def is_tyxia_dimmer_profile(metadata: dict[str, Any] | None) -> bool:
    """Return whether metadata identifies a variable-output TYXIA receiver."""
    if not isinstance(metadata, dict):
        return False

    level = metadata.get("level")
    level_cmd = metadata.get("levelCmd")
    if not isinstance(level, dict) or not isinstance(level_cmd, dict):
        return False

    commands = level_cmd.get("enum_values")
    if not isinstance(commands, list):
        return False

    try:
        return (
            float(level.get("min")) == 0
            and float(level.get("max")) == 100
            and float(level.get("step")) == 1
            and {"ON", "OFF", "STOP", "ON_SLOW", "OFF_SLOW"}.issubset(commands)
        )
    except (TypeError, ValueError):
        return False


def is_tybox_1137_profile(metadata: dict[str, Any] | None) -> bool:
    """Return whether issue #355's metadata identifies a TYBOX 1137."""
    if not isinstance(metadata, dict):
        return False

    required_attributes = {
        "authorization",
        "heatSetpoint",
        "overrideSetpoint",
        "overrideThermicLevel",
        "useMode",
        "antiSeizurePeriod",
        "invertOutput",
    }
    if not required_attributes.issubset(metadata):
        return False

    use_mode = metadata.get("useMode")
    authorization = metadata.get("authorization")
    if not isinstance(use_mode, dict) or not isinstance(authorization, dict):
        return False

    use_modes = use_mode.get("enum_values")
    authorizations = authorization.get("enum_values")
    return (
        isinstance(use_modes, list)
        and {"SCHED", "OVERRIDE", "MANUAL"}.issubset(use_modes)
        and isinstance(authorizations, list)
        and {"STOP", "HEATING"}.issubset(authorizations)
    )


def resolve_device_model(
    tutorial_id: str | None,
    usage: str,
    metadata: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> str | None:
    """Return the most specific model justified by TYDOM descriptors.

    Only descriptors proven to identify an exact product or an explicitly
    named product range are accepted. Broad capability profiles retain Home
    Assistant's existing fallback instead of being presented as device models.
    """
    tutorial = str(tutorial_id or "").strip().casefold()
    if not tutorial:
        if usage == "shutter" and is_tymoov_profile(data):
            return "TYMOOV"
        if usage == "sh_hvac" and is_trv_1_profile(data):
            return "TRV 1.0"
        if usage in {"boiler", "hvac"} and is_tybox_1137_profile(metadata):
            return "TYBOX 1137"
        return None

    for prefix, model in _TUTORIAL_PREFIX_MODELS.items():
        if tutorial.startswith(prefix):
            return model

    if tutorial == "7_tyxia_serie4000":
        if usage in {"garage_door", "gate"}:
            return "TYXIA 4620"
        return None

    if tutorial == "9_tyxia_modulaire_serie4900":
        if is_tyxia_dimmer_profile(metadata):
            return "TYXIA 4940"
        if is_binary_tyxia_receiver_profile(metadata):
            return "TYXIA 4910"
        return None

    return _CONFIRMED_TUTORIAL_MODELS.get(tutorial)


class DeviceCallback(Protocol):
    """Protocol for device callbacks that can be called without arguments."""

    def __call__(self) -> None:
        """Call the callback."""


# Import TydomGroup at the end to avoid circular import


class TydomDevice:
    """represents a generic device."""

    _ha_device: Any = None

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
        self._callbacks: set[DeviceCallback] = set()
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

    def register_callback(self, callback: DeviceCallback) -> None:
        """Register callback, called when state changes."""
        self._callbacks.add(callback)

    def remove_callback(self, callback: DeviceCallback) -> None:
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

    @property
    def registry_device_id(self) -> str:
        """Return the physical device identifier used by Home Assistant."""
        return str(getattr(self, "_registry_device_id", self._uid))

    @property
    def registry_device_name(self) -> str:
        """Return the physical device name used by Home Assistant."""
        return str(getattr(self, "_registry_device_name", self._name))

    def group_with_registry_device(self, device_id: str, device_name: str) -> None:
        """Group this protocol endpoint with another physical HA device."""
        self._registry_device_id = str(device_id)
        self._registry_device_name = str(device_name)

    @property
    def battery_level_attributes(self) -> set[str]:
        """Return battery values owned by this physical endpoint.

        ``battLevel`` on a ``re2020ControlPassive`` or direct
        ``re2020ControlBoiler`` is the battery level of the Tywell Control wall
        unit itself. It must not be inferred from, or applied to, an ordinary
        boiler/Tybox/TY-PASS endpoint, shutter, weather source, or other entity
        grouped with that HA device.
        """
        if self._type in {
            "re2020ControlPassive",
            "re2020ControlBoiler",
        } and hasattr(self, "battLevel"):
            return {"battLevel"}
        return set()

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

    async def publish_updates(self) -> None:
        """Schedule call all registered callbacks."""
        for callback in self._callbacks:
            try:
                callback()
            except Exception:
                LOGGER.exception("Device callback failed for %s", self.device_id)


class Tydom(TydomDevice):
    """Tydom Gateway."""

    async def async_trigger_firmware_update(self) -> None:
        """Trigger firmware update."""
        LOGGER.debug("Installing firmware update...")
        await self._tydom_client.update_firmware()


class TydomShutter(TydomDevice):
    """Represents a shutter."""

    @property
    def is_awning(self) -> bool:
        """Return whether Delta Dore identifies this cover as an awning."""
        return self._type == "awning"

    def position_from_tydom(self, position: int) -> int:
        """Translate a Delta Dore position into Home Assistant semantics."""
        return 100 - position if self.is_awning else position

    def position_to_tydom(self, position: int) -> int:
        """Translate a Home Assistant position into Delta Dore semantics."""
        return 100 - position if self.is_awning else position

    async def open(self) -> None:
        """Open the cover using semantics appropriate to its usage."""
        if self.is_awning:
            await self.down()
        else:
            await self.up()

    async def close(self) -> None:
        """Close the cover using semantics appropriate to its usage."""
        if self.is_awning:
            await self.up()
        else:
            await self.down()

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
        # Validate value with metadata
        is_valid, error_msg = validate_value_with_metadata(self, "position", position)
        if not is_valid:
            from homeassistant.exceptions import HomeAssistantError

            raise HomeAssistantError(error_msg or f"Valeur invalide: {position}")

        # Delta Dore reports an awning at 100 when it is retracted, whereas
        # Home Assistant cover semantics use 0 for closed and 100 for open.
        native_position = self.position_to_tydom(position)
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "position", str(native_position)
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

        # Validate value with metadata
        is_valid, error_msg = validate_value_with_metadata(self, "slope", position)
        if not is_valid:
            from homeassistant.exceptions import HomeAssistantError

            raise HomeAssistantError(error_msg or f"Valeur invalide: {position}")

        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "slope", str(position)
        )


class TydomEnergy(TydomDevice):
    """Represents an energy sensor (for example TYWATT)."""


class TydomSmoke(TydomDevice):
    """Represents an smoke detector sensor."""


class TydomRemoteControl(TydomDevice):
    """Represent one button endpoint of a physical remote control."""

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
        remote_info: dict | None = None,
    ) -> None:
        """Initialise a remote-control button endpoint."""
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
        info = remote_info or {}
        self._physical_device_id = str(info.get("physical_device_id", device_id))
        self._remote_name = str(
            info.get("name", f"Remote control {self._physical_device_id}")
        )
        self._remote_model = str(info.get("model", "Delta Dore remote control"))
        self._button_number = info.get("button_number")
        self._configured_action = str(info.get("configured_action", "TOGGLE"))
        self._event_sequence = 0

    @property
    def physical_device_id(self) -> str:
        """Return the identifier shared by every button on the remote."""
        return self._physical_device_id

    @property
    def remote_name(self) -> str:
        """Return the configured name of the physical remote."""
        return self._remote_name

    @property
    def remote_model(self) -> str:
        """Return the remote-control model inferred from TYDOM configuration."""
        return self._remote_model

    @property
    def button_number(self) -> int | None:
        """Return the physical button number represented by this endpoint."""
        return self._button_number

    @property
    def event_sequence(self) -> int:
        """Return a monotonically increasing sequence for fresh button actions."""
        return self._event_sequence

    async def update_device(self, device) -> None:
        """Record fresh remote actions before publishing the endpoint update."""
        action = getattr(device, "action", None)
        if action is not None and action != "IDLE":
            self._event_sequence += 1
        await super().update_device(device)


class TydomBoiler(TydomDevice):
    """Represents a Boiler."""

    @property
    def is_derived_area_climate(self) -> bool:
        """Return whether this climate proxies a passive controller's area."""
        return self.device_id.endswith("_area_climate")

    @property
    def source_device_id(self) -> str:
        """Return the physical device identifier represented by this climate."""
        if self.is_derived_area_climate:
            return self.device_id.removesuffix("_area_climate")
        return self.device_id

    def area_setpoint_attribute(self) -> str:
        """Return the setpoint register advertised for the current area mode."""
        authorization = getattr(self, "authorization", None)
        if authorization == "COOLING":
            candidates = ("coolSetpoint", "setpoint", "heatSetpoint")
        elif authorization == "HEATING":
            candidates = ("heatSetpoint", "setpoint", "coolSetpoint")
        else:
            candidates = ("setpoint", "heatSetpoint", "coolSetpoint")

        metadata = self._metadata or {}
        return next(
            (
                attribute
                for attribute in candidates
                if hasattr(self, attribute) or attribute in metadata
            ),
            "setpoint",
        )

    def area_temperature_limits(self) -> tuple[float | None, float | None]:
        """Return live area limits, falling back to controller metadata."""
        if not hasattr(self, "area_id"):
            return (None, None)

        authorization = getattr(self, "authorization", None)
        if authorization == "COOLING":
            live_names = (
                ("minCoolSetpoint", "minSetpoint"),
                ("maxCoolSetpoint", "maxSetpoint"),
            )
            metadata_names = ("coolSetpoint", "setpoint")
        elif authorization == "HEATING":
            live_names = (
                ("minHeatSetpoint", "minSetpoint"),
                ("maxHeatSetpoint", "maxSetpoint"),
            )
            metadata_names = ("heatSetpoint", "setpoint")
        else:
            live_names = (
                ("minSetpoint", "minHeatSetpoint", "minCoolSetpoint"),
                ("maxSetpoint", "maxHeatSetpoint", "maxCoolSetpoint"),
            )
            metadata_names = ("setpoint", "heatSetpoint", "coolSetpoint")

        limits: list[float | None] = []
        metadata = self._metadata or {}
        for attribute_names, bound in zip(live_names, ("min", "max"), strict=True):
            live_value = next(
                (
                    getattr(self, attribute_name)
                    for attribute_name in attribute_names
                    if getattr(self, attribute_name, None) is not None
                ),
                None,
            )
            if live_value is not None:
                limits.append(float(live_value))
                continue

            metadata_value = next(
                (
                    metadata[attribute_name].get(bound)
                    for attribute_name in metadata_names
                    if metadata.get(attribute_name, {}).get(bound) is not None
                ),
                None,
            )
            limits.append(float(metadata_value) if metadata_value is not None else None)

        return (limits[0], limits[1])

    def area_temperature_step(self) -> float | None:
        """Return the target-temperature step advertised for this area."""
        if not hasattr(self, "area_id"):
            return None

        authorization = getattr(self, "authorization", None)
        if authorization == "COOLING":
            metadata_names = ("coolSetpoint", "setpoint")
        elif authorization == "HEATING":
            metadata_names = ("heatSetpoint", "setpoint")
        else:
            metadata_names = ("setpoint", "heatSetpoint", "coolSetpoint")

        metadata = self._metadata or {}
        step = next(
            (
                metadata[attribute_name].get("step")
                for attribute_name in metadata_names
                if metadata.get(attribute_name, {}).get("step") is not None
            ),
            None,
        )
        return float(step) if step is not None else None

    def area_hvac_modes(self) -> set[str]:
        """Return the HVAC modes advertised by an area-backed thermostat."""
        if not hasattr(self, "area_id"):
            return set()

        # A linked thermal receiver always provides stop and heating. Cooling is
        # exposed only when TYDOM reports it in metadata or live state.
        modes = {"STOP", "HEATING"}
        metadata = self._metadata or {}
        for attribute in ("authorization", "comfortMode", "hvacMode", "thermicLevel"):
            attribute_metadata = metadata.get(attribute, {})
            if isinstance(attribute_metadata, dict):
                modes.update(attribute_metadata.get("enum_values", []))

            value = getattr(self, attribute, None)
            if isinstance(value, str):
                modes.add(value)

        return modes

    def _uses_zone_authorization(self) -> bool:
        """Return True when heat/cool is driven by zone authorization."""
        return (
            self._metadata is not None and "authorization" in self._metadata
        ) or hasattr(self, "authorization")

    def _is_writable(self, name: str) -> bool:
        """Return whether metadata advertises a writable register."""
        if self._metadata is None:
            return False
        register = self._metadata.get(name)
        return isinstance(register, dict) and "w" in register.get("permission", "")

    def _supports_command_value(self, name: str, value: str) -> bool:
        """Return whether metadata advertises a writable command value."""
        command = (self._metadata or {}).get(name)
        return (
            self._is_writable(name)
            and isinstance(command, dict)
            and value in command.get("enum_values", [])
        )

    def _temperature_command_name(self) -> str:
        """Select the writable setpoint register for the current HVAC direction."""
        if self._uses_zone_authorization():
            if getattr(self, "authorization", None) == "COOLING" and self._is_writable(
                "coolSetpoint"
            ):
                return "coolSetpoint"
            if getattr(self, "useMode", None) in {
                "MANUAL",
                "OVERRIDE",
            } and self._is_writable("overrideSetpoint"):
                return "overrideSetpoint"
            if self._is_writable("heatSetpoint"):
                return "heatSetpoint"
        return "setpoint"

    async def set_hvac_mode(self, mode):
        """Set hvac mode (ANTI_FROST/NORMAL/STOP)."""
        LOGGER.debug("setting hvac mode to %s", mode)
        # Mode changes must not clear or replace the setpoint. TYDOM retains
        # the user's last setpoint and restores it when heating resumes.
        if hasattr(self, "area_id"):
            area_modes = {
                "NORMAL": "HEATING",
                "HEATING": "HEATING",
                "COOLING": "COOLING",
                "STOP": "STOP",
            }
            area_mode = area_modes.get(mode)
            if area_mode is None:
                LOGGER.error("Unknown area HVAC mode: %s", mode)
                return
            await self._tydom_client.put_area_data(
                self.area_id, "authorization", area_mode
            )
            return

        if self._uses_zone_authorization():
            command_mode = "HEATING" if mode == "NORMAL" else mode
            if self._supports_command_value("comfortMode", command_mode):
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "comfortMode", command_mode
                )
                return

            if mode == "STOP":
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "thermicLevel", "STOP"
                )
            elif mode == "COOLING":
                await self._tydom_client.put_home_hvac_mode("COOLING")
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "thermicLevel", ""
                )
            elif mode in ("NORMAL", "HEATING"):
                await self._tydom_client.put_home_hvac_mode("HEATING")
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "thermicLevel", ""
                )
            elif mode == "ANTI_FROST":
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "thermicLevel", "ANTI_FROST"
                )
            else:
                LOGGER.error("Unknown hvac mode: %s", mode)
            return

        if mode == "ANTI_FROST":
            if hasattr(self, "hvacMode"):
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "thermicLevel", "STOP"
                )
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "hvacMode", "ANTI_FROST"
                )
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "antifrostOn", True
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
                await self._tydom_client.put_devices_data(
                    self._id, self._endpoint, "hvacMode", "NORMAL"
                )
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
                    self._id, self._endpoint, "antifrostOn", True
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
        setpoint_attribute = (
            self.area_setpoint_attribute()
            if hasattr(self, "area_id")
            else self._temperature_command_name()
        )
        # Validate value with metadata
        is_valid, error_msg = validate_value_with_metadata(
            self, setpoint_attribute, temperature
        )
        if not is_valid:
            from homeassistant.exceptions import HomeAssistantError

            raise HomeAssistantError(
                error_msg or f"Température invalide: {temperature}"
            )

        if hasattr(self, "area_id"):
            await self._tydom_client.put_area_data(
                self.area_id, setpoint_attribute, temperature
            )
        else:
            await self._tydom_client.put_devices_data(
                self._id, self._endpoint, setpoint_attribute, temperature
            )

    async def set_thermic_level(self, level):
        """Set the pilot-wire order directly (fil-pilote zones)."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "thermicLevel", level
        )

    async def set_fan_speed(self, speed) -> None:
        """Set a manual fan speed on a Naviclim (X3D) HVAC zone.

        Writes the numeric ``speed`` register (1..3 on a Naviclim). The value is
        validated against the device metadata first so an out-of-range speed is
        rejected before it reaches the Tydom box.
        """
        is_valid, error_msg = validate_value_with_metadata(self, "speed", speed)
        if not is_valid:
            from homeassistant.exceptions import HomeAssistantError

            raise HomeAssistantError(
                error_msg or f"Vitesse de ventilation invalide: {speed}"
            )

        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "speed", speed
        )

    async def set_fan_auto(self) -> None:
        """Set automatic fan speed on a Naviclim (X3D) HVAC zone.

        Writes ``speedString`` = ``"AUTO"``; the box then drives the fan speed
        automatically and reports the numeric ``speed`` register as null.
        """
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "speedString", "AUTO"
        )


class TydomWindow(TydomDevice):
    """represents a window."""


class TydomInterrupter(TydomDevice):
    """Represent one button endpoint of a physical wall switch."""

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
        interrupter_info: dict | None = None,
    ) -> None:
        """Initialise a wall-switch button endpoint."""
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
        info = interrupter_info or {}
        self._physical_device_id = str(info.get("physical_device_id", device_id))
        self._interrupter_name = str(
            info.get("name", f"Wall switch {self._physical_device_id}")
        )
        self._interrupter_model = str(info.get("model", "Delta Dore wall switch"))
        self._button = info.get("button")
        self._configured_action = str(info.get("configured_action", "TOGGLE"))
        self._event_sequence = 0

    @property
    def physical_device_id(self) -> str:
        """Return the identifier shared by both wall-switch buttons."""
        return self._physical_device_id

    @property
    def interrupter_name(self) -> str:
        """Return the configured name of the physical wall switch."""
        return self._interrupter_name

    @property
    def interrupter_model(self) -> str:
        """Return the wall-switch model inferred from TYDOM configuration."""
        return self._interrupter_model

    @property
    def button(self) -> str | None:
        """Return the physical button represented by this endpoint."""
        return self._button

    @property
    def event_sequence(self) -> int:
        """Return a monotonically increasing sequence for fresh button actions."""
        return self._event_sequence

    async def update_device(self, device) -> None:
        """Record fresh switch actions before publishing the endpoint update."""
        action = getattr(device, "action", None)
        if action is not None and action != "IDLE":
            self._event_sequence += 1
        await super().update_device(device)


class TydomDoor(TydomDevice):
    """represents a door."""

    async def open(self) -> None:
        """Tell door to open."""
        await self._tydom_client.put_devices_data_validated(
            self._id, self._endpoint, "podPosition", "OPEN", device=self
        )

    async def close(self) -> None:
        """Tell door to close (unlocked)."""
        await self._tydom_client.put_devices_data_validated(
            self._id, self._endpoint, "podPosition", "CLOSE", device=self
        )

    async def lock(self) -> None:
        """Tell door to close and lock (KLINE doors only, no unlock)."""
        await self._tydom_client.put_devices_data_validated(
            self._id, self._endpoint, "podPosition", "LOCK", device=self
        )


@dataclass(frozen=True)
class TydomCoverCapabilities:
    """Commands and feedback exposed by a level-command cover receiver."""

    open: bool
    close: bool
    stop: bool
    toggle: bool
    set_position: bool


class TydomLevelCommandCover(TydomDevice):
    """Cover controlled through the Tydom levelCmd register."""

    @property
    def level_commands(self) -> frozenset[str]:
        """Return commands explicitly advertised by the gateway."""
        if not isinstance(self._metadata, dict):
            return frozenset()
        level_command = self._metadata.get("levelCmd")
        if not isinstance(level_command, dict):
            return frozenset()
        enum_values = level_command.get("enum_values")
        if not isinstance(enum_values, (list, tuple, set)):
            return frozenset()
        return frozenset(str(value) for value in enum_values)

    @property
    def cover_capabilities(self) -> TydomCoverCapabilities:
        """Return cover capabilities derived from gateway metadata."""
        commands = self.level_commands
        has_command_metadata = bool(commands)

        level_metadata = (
            self._metadata.get("level", {}) if isinstance(self._metadata, dict) else {}
        )
        permission = (
            str(level_metadata.get("permission", ""))
            if isinstance(level_metadata, dict)
            else ""
        )

        return TydomCoverCapabilities(
            # Preserve the historical open-only fallback when old gateways do
            # not describe levelCmd at all.
            open=not has_command_metadata or "ON" in commands,
            close="OFF" in commands,
            stop="STOP" in commands,
            toggle="TOGGLE" in commands,
            set_position=hasattr(self, "level") and "w" in permission.lower(),
        )

    @property
    def is_toggle_only(self) -> bool:
        """Return whether the receiver only offers a stateless movement pulse."""
        commands = self.level_commands
        return "TOGGLE" in commands and not commands.intersection({"ON", "OFF", "STOP"})

    def _command_for(self, preferred: str) -> str:
        """Return a command only when the receiver explicitly advertises it."""
        commands = self.level_commands
        if not commands or preferred in commands:
            return preferred
        raise ValueError(f"Device {self.device_id} does not support {preferred}")

    async def _send_level_command(self, command: str) -> None:
        """Send a capability-checked level command."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "levelCmd", command
        )

    async def open(self) -> None:
        """Open the cover when a directional command is available."""
        await self._send_level_command(self._command_for("ON"))

    async def close(self) -> None:
        """Close the cover when a directional command is available."""
        await self._send_level_command(self._command_for("OFF"))

    async def stop(self) -> None:
        """Stop the cover when the receiver advertises STOP."""
        await self._send_level_command(self._command_for("STOP"))

    async def toggle(self) -> None:
        """Pulse the receiver without deriving direction from cover state."""
        await self._send_level_command(self._command_for("TOGGLE"))


class TydomGate(TydomLevelCommandCover):
    """represents a gate."""


class TydomGarage(TydomLevelCommandCover):
    """represents a garage door."""

    async def set_level(self, level: int) -> None:
        """Set garage door to the given level."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "level", str(level)
        )


class TydomLight(TydomDevice):
    """represents a light."""

    @property
    def supports_brightness(self) -> bool:
        """Return whether level metadata exposes intermediate light levels."""
        if not isinstance(self._metadata, dict):
            return False

        level_metadata = self._metadata.get("level")
        if not isinstance(level_metadata, dict):
            return False

        try:
            minimum = float(level_metadata.get("min", 0))
            maximum = float(level_metadata.get("max", 100))
            step = float(level_metadata["step"])
        except (KeyError, TypeError, ValueError):
            # Preserve brightness support for gateways that advertise level
            # without complete numeric constraints.
            return True

        return step > 0 and maximum - minimum > step

    async def turn_on(self, brightness) -> None:
        """Turn on the light with specified brightness."""
        # Validate brightness value with metadata
        if brightness is not None:
            is_valid, error_msg = validate_value_with_metadata(
                self, "level", brightness
            )
            if not is_valid:
                from homeassistant.exceptions import HomeAssistantError

                raise HomeAssistantError(
                    error_msg or f"Luminosité invalide: {brightness}"
                )
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
            f"/devices/{self._id}/endpoints/{self._endpoint}/data"
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
            f"/devices/{self._id}/endpoints/{self._endpoint}/data"
        )


class TydomAlarm(TydomDevice):
    """represents an alarm."""

    def __init__(self, *args, **kwargs) -> None:
        """Initialise an alarm and its dashboard event cache."""
        super().__init__(*args, **kwargs)
        self._pending_events: list[dict[str, Any]] | None = None

    @property
    def pending_events(self) -> list[dict[str, Any]] | None:
        """Return the most recently fetched unacknowledged events."""
        return self._pending_events

    def clear_pending_events(self) -> None:
        """Clear the local event cache after acknowledgement or a clear state."""
        self._pending_events = []

    def is_legacy_alarm(self) -> bool:
        """Check if alarm is legacy."""
        if hasattr(self, "part1State"):
            return True
        return False

    def get_alarm_mode_from_zones(self) -> str | None:
        """Identify the configured alarm mode from the active zones."""

        def parse_zones(value) -> set[int]:
            if not value:
                return set()

            return {int(zone.strip()) for zone in str(value).split(",") if zone.strip()}

        active_zones = {
            zone
            for zone in range(1, 9)
            if getattr(self, f"part{zone}State", "OFF") == "ON"
            or getattr(self, f"zone{zone}State", "OFF") == "ON"
        }

        configured_modes = (
            ("night", parse_zones(self._tydom_client._zone_night)),
            ("home", parse_zones(self._tydom_client._zone_home)),
            ("away", parse_zones(self._tydom_client._zone_away)),
        )

        for mode, configured_zones in configured_modes:
            if configured_zones and configured_zones == active_zones:
                return mode

        return None

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

    async def acknowledge_events(self, code=None) -> None:
        """Acknowledge alarm events and refresh the authoritative event list."""
        await self._tydom_client.put_ackevents_cdata(self._id, self._endpoint, code)
        await self.get_events("UNACKED_EVENTS")

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
        formatted_events = [
            self._format_alarm_event(m["values"]["event"])
            for m in (events or [])
            if m.get("values", {}).get("event") is not None
        ]
        if event_type == "UNACKED_EVENTS":
            self._pending_events = formatted_events
            await self.publish_updates()
        return formatted_events

    def _require_endpoint(self) -> str:
        """Return the alarm endpoint or fail before building a request."""
        if self._endpoint is None:
            raise ValueError(f"Alarm device {self._id} has no endpoint")
        return self._endpoint

    async def get_alarm_products(self) -> dict[str, list[dict[str, Any]]]:
        """Return the TYXAL product inventory and configured zones."""
        messages = await self._tydom_client.get_alarm_products_cdata(
            self._id, self._require_endpoint()
        )
        label_values = (messages.get("label") or {}).get("values") or {}
        info_values = (messages.get("productInfo") or {}).get("values") or {}

        technical_products = {
            product.get("id"): product
            for product in info_values.get("products", [])
            if isinstance(product, dict) and product.get("id") is not None
        }
        products = []
        for product in label_values.get("products", []):
            if not isinstance(product, dict) or product.get("id") is None:
                continue
            technical = technical_products.get(product["id"], {})
            products.append(
                {
                    key: value
                    for key, value in {
                        "id": product["id"],
                        "name_custom": product.get("nameCustom"),
                        "name_standard": product.get("nameStd"),
                        "number": product.get("number"),
                        "type_short": product.get("typeShort"),
                        "type_long": product.get("typeLong"),
                        "zone": product.get("zone"),
                        "uuid": technical.get("uuid"),
                        "battery_level": technical.get("batteryLevel"),
                    }.items()
                    if value is not None
                }
            )

        zones = [
            {
                key: value
                for key, value in {
                    "id": zone.get("id"),
                    "name_custom": zone.get("nameCustom"),
                    "name_standard": zone.get("nameStd"),
                    "number": zone.get("number"),
                }.items()
                if value is not None
            }
            for zone in label_values.get("zones", [])
            if isinstance(zone, dict) and zone.get("id") is not None
        ]
        return {"zones": zones, "products": products}

    async def get_alarm_product_configuration(
        self, code: str, product_id: int
    ) -> dict[str, Any]:
        """Return only the safe, common settings of one TYXAL product."""
        message = await self._tydom_client.get_alarm_product_configuration_cdata(
            self._id, self._require_endpoint(), code, product_id
        )
        if message is None:
            raise ValueError("The CS8000 returned no product configuration")
        values = message.get("values") or {}
        common = values.get("common") or {}
        response: dict[str, Any] = {"id": values.get("id", product_id)}
        if common.get("inactive") is not None:
            response["active"] = not common["inactive"]
        if common.get("zone") is not None:
            response["zone"] = common["zone"]
        if common.get("autoProtectActive") is not None:
            response["auto_protect_active"] = common["autoProtectActive"]
        return response

    async def configure_alarm_product(
        self,
        code: str,
        product_id: int,
        *,
        active: bool | None = None,
        zone: int | None = None,
    ) -> None:
        """Enable, disable or reassign one TYXAL product."""
        endpoint = self._require_endpoint()
        if active is not None:
            await self._tydom_client.put_alarm_product_active_cdata(
                self._id, endpoint, code, product_id, active
            )
        if zone is not None:
            await self._tydom_client.put_alarm_product_configuration_cdata(
                self._id, endpoint, code, product_id, zone=zone
            )

    async def enter_alarm_maintenance(self, code: str) -> None:
        """Put the TYXAL central unit into maintenance mode."""
        endpoint = self._require_endpoint()
        await self._tydom_client.put_alarm_remote_control_cdata(
            self._id, endpoint, code, "lock"
        )
        try:
            await self._tydom_client.put_alarm_mode_cdata(
                self._id, endpoint, code, "MAINTENANCE"
            )
        except Exception:
            await self._tydom_client.put_alarm_remote_control_cdata(
                self._id, endpoint, code, "unlock"
            )
            raise

    async def exit_alarm_maintenance(self, code: str) -> None:
        """Take the TYXAL central unit out of maintenance mode."""
        endpoint = self._require_endpoint()
        try:
            await self._tydom_client.put_alarm_mode_cdata(
                self._id, endpoint, code, "OFF"
            )
        finally:
            await self._tydom_client.put_alarm_remote_control_cdata(
                self._id, endpoint, code, "unlock"
            )

    async def rename_alarm_zone(self, code: str, zone_id: int, name: str) -> None:
        """Rename one TYXAL zone."""
        await self._tydom_client.put_alarm_zone_label_cdata(
            self._id, self._require_endpoint(), code, zone_id, name
        )


class TydomWeather(TydomDevice):
    """Represents a weather sensor."""


class TydomWater(TydomDevice):
    """Represents a water leak sensor."""


class TydomThermo(TydomDevice):
    """Represents a thermometer."""


class TydomSun(TydomDevice):
    """Represents a Tysense Sun irradiance sensor."""


class TydomPlug(TydomDevice):
    """Represents a generic third-party smart plug (e.g. Zigbee Philips Hue plug).

    These devices report their state via a ``plugCmd`` attribute (ON/OFF)
    instead of the more common ``on``/``level``/``state`` attributes used by
    native Delta Dore devices, so they need dedicated handling.
    """

    @property
    def on(self) -> bool:
        """Return True if the plug is currently on."""
        return getattr(self, "plugCmd", None) == "ON"

    async def turn_on(self) -> None:
        """Turn the plug on."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "plugCmd", "ON"
        )

    async def turn_off(self) -> None:
        """Turn the plug off."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "plugCmd", "OFF"
        )


class TydomSwitch(TydomDevice):
    """Represent a binary TYXIA output configured under the 'others' usage."""

    @property
    def productName(self) -> str:
        """Return the model inferred from the binary series-4900 profile."""
        return getattr(self, "_product_name", "TYXIA 4910")

    @productName.setter
    def productName(self, value: str) -> None:
        """Retain a model explicitly supplied by TYDOM."""
        self._product_name = value

    async def turn_on(self) -> None:
        """Turn the binary output on."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "levelCmd", "ON"
        )
        self._schedule_state_refresh()

    async def turn_off(self) -> None:
        """Turn the binary output off."""
        await self._tydom_client.put_devices_data(
            self._id, self._endpoint, "levelCmd", "OFF"
        )
        self._schedule_state_refresh()

    def _schedule_state_refresh(self) -> None:
        """Poll the regular data endpoint after a command."""
        self._tydom_client.add_poll_device_url_1s(
            f"/devices/{self._id}/endpoints/{self._endpoint}/data"
        )


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
        """Activate the scene.

        Raises:
            Exception: If activation fails, with detailed error information.

        """
        scene_id = getattr(self, "scene_id", None) or self._id
        scene_name = getattr(self, "device_name", "Unknown")

        LOGGER.info(
            "Activating scene: id=%s, name=%s, device_id=%s",
            scene_id,
            scene_name,
            self.device_id,
        )

        try:
            # Scenarios are activated via PUT /scenarios/{id}
            await self._tydom_client.activate_scenario(scene_id)
            LOGGER.debug(
                "Scene activation request sent successfully: id=%s, name=%s",
                scene_id,
                scene_name,
            )
        except Exception as e:
            LOGGER.error(
                "Failed to activate scene: id=%s, name=%s, device_id=%s, error=%s",
                scene_id,
                scene_name,
                self.device_id,
                e,
                exc_info=True,
            )
            # Re-raise to allow Home Assistant to handle the error
            raise


class TydomGroup(TydomDevice):
    """Represents a Tydom group."""

    def __init__(
        self,
        tydom_client: TydomClient,
        group_id: str,
        name: str,
        device_ids: list[str],
        usage: str | None = None,
    ):
        """Initialize a TydomGroup."""
        super().__init__(
            tydom_client=tydom_client,
            uid=group_id,
            device_id=group_id,
            name=name,
            device_type="group",
            endpoint=None,
            metadata=None,
            data=None,
        )
        self.group_id = group_id
        self.device_ids = device_ids
        self.group_usage = usage  # Store usage for translation key
        # Note: device_name is already set by parent class TydomDevice via the 'name' parameter

    @property
    def device_id(self) -> str:
        """Return the group ID as device_id."""
        return self.group_id

    async def activate_scenario(self, scenario_id: str) -> None:
        """Activate a scenario on this group.

        Args:
            scenario_id: The scenario ID to activate

        Raises:
            Exception: If the activation request fails

        """
        LOGGER.debug("Activating scenario %s on group %s", scenario_id, self.group_id)
        try:
            # Use the same activate_scenario method from tydom_client
            # Scenarios are global, so we can activate them directly
            await self._tydom_client.activate_scenario(scenario_id)
            LOGGER.debug(
                "Scenario %s activated on group %s", scenario_id, self.group_id
            )
        except Exception as e:
            LOGGER.error(
                "Failed to activate scenario %s on group %s: %s",
                scenario_id,
                self.group_id,
                e,
                exc_info=True,
            )
            raise


class TydomMoment(TydomDevice):
    """Represents a Tydom moment/program."""

    def __init__(
        self,
        tydom_client: TydomClient,
        moment_id: str,
        name: str,
        moment_data: dict,
    ):
        """Initialize a TydomMoment.

        Args:
            tydom_client: Tydom client instance
            moment_id: Moment ID
            name: Moment name
            moment_data: Moment data dict from /moments/file

        """
        super().__init__(
            tydom_client=tydom_client,
            uid=moment_id,
            device_id=moment_id,
            name=name,
            device_type="moment",
            endpoint=None,
            metadata=None,
            data=moment_data,
        )
        self.moment_id = moment_id
        self.device_name = name
        self.moment_data = moment_data
        # Extract suspend info
        self.suspend = moment_data.get("suspend", {})
        self.suspend_to = (
            self.suspend.get("to", -1) if isinstance(self.suspend, dict) else -1
        )

    @property
    def device_id(self) -> str:
        """Return the moment ID as device_id."""
        return self.moment_id

    @property
    def is_suspended(self) -> bool:
        """Check if the moment is suspended."""
        # If suspend_to is -1, it means suspended indefinitely
        # If suspend_to is a timestamp, it means suspended until that time
        return self.suspend_to != 0

    async def suspend_moment(self, suspend: bool, suspend_to: int = -1) -> None:
        """Suspend or resume a moment.

        Args:
            suspend: True to suspend, False to resume
            suspend_to: Timestamp until which to suspend (-1 for indefinite)

        Raises:
            TydomClientApiClientCommunicationError: If the request fails

        """
        # Calculer suspend_to : 0 pour reprendre, -1 ou timestamp pour suspendre
        if not suspend:
            suspend_to = 0

        LOGGER.debug(
            "Suspending moment %s: suspend=%s, suspend_to=%s",
            self.moment_id,
            suspend,
            suspend_to,
        )

        try:
            await self._tydom_client.suspend_moment(self.moment_id, suspend_to)
            # Mettre à jour l'état local après succès
            self.suspend_to = suspend_to
            if hasattr(self, "suspend"):
                self.suspend = {"to": suspend_to}
            LOGGER.debug(
                "Moment %s state updated: suspend_to=%s",
                self.moment_id,
                suspend_to,
            )
        except Exception as e:
            LOGGER.error(
                "Failed to suspend moment %s: %s",
                self.moment_id,
                e,
                exc_info=True,
            )
            raise
