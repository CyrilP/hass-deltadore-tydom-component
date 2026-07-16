"""Constants for deltadore_tydom integration."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

# This is the internal name of the integration, it should also match the directory
# name for the integration.
DOMAIN = "deltadore_tydom"
NAME = "Delta Dore TYDOM"

CONF_TYDOM_PASSWORD = "tydom_password"
CONF_REFRESH_INTERVAL = "refresh_interval"
CONF_ZONES_HOME = "zones_home"
CONF_ZONES_AWAY = "zones_away"
CONF_ZONES_NIGHT = "zones_night"
CONF_CONFIG_MODE = "config_mode"

CONF_CLOUD_MODE = "tydom_cloud_account"
CONF_MANUAL_MODE = "tydom_credentials"

# Mapping des unités Tydom vers les unités Home Assistant
TYDOM_UNIT_TO_HA_UNIT = {
    "degC": "°C",
    "degF": "°F",
    "%": "%",
    "W/m2": "W/m²",
    "Wh/m2": "Wh/m²",
    "W": "W",
    "Wh": "Wh",
    "kW": "kW",
    "kWh": "kWh",
    "V": "V",
    "A": "A",
    "boolean": None,  # Pas d'unité pour les booléens
    "NA": None,  # Pas d'unité
    "": None,  # Pas d'unité
}


def validate_value_with_metadata(
    device,
    attribute_name: str,
    value: float | int | str,
    metadata: dict | None = None,
) -> tuple[bool, str | None]:
    """
    Validate a value according to device metadata.

    Args:
        device: Device Tydom avec _metadata
        attribute_name: Nom de l'attribut à valider
        value: Valeur à valider
        metadata: Métadonnées à utiliser (si None, utilise device._metadata)

    Returns:
        Tuple (is_valid, error_message)
        - is_valid: True si la valeur est valide
        - error_message: Message d'erreur si invalide, None sinon

    """
    if metadata is None:
        if not hasattr(device, "_metadata") or device._metadata is None:
            return True, None  # Pas de métadonnées, on accepte
        metadata = device._metadata

    # Vérification de type pour le type checker
    if metadata is None:
        return True, None  # Pas de métadonnées, on accepte

    if attribute_name not in metadata:
        return True, None  # Pas de métadonnées pour cet attribut, on accepte

    attr_metadata = metadata[attribute_name]

    # Vérifier le type
    if "type" in attr_metadata:
        expected_type = attr_metadata["type"]
        if expected_type == "numeric":
            try:
                numeric_value = float(value)
            except (ValueError, TypeError):
                return False, f"La valeur doit être numérique pour {attribute_name}"
            value = numeric_value
        elif expected_type == "boolean":
            if not isinstance(value, bool):
                return False, f"La valeur doit être booléenne pour {attribute_name}"
        elif expected_type == "string":
            if not isinstance(value, str):
                return False, f"La valeur doit être une chaîne pour {attribute_name}"

    # Vérifier min/max pour les valeurs numériques
    if isinstance(value, (int, float)):
        if "min" in attr_metadata:
            min_val = attr_metadata["min"]
            try:
                if float(value) < float(min_val):
                    return (
                        False,
                        f"La valeur {value} est inférieure au minimum {min_val} pour {attribute_name}",
                    )
            except (ValueError, TypeError):
                pass

        if "max" in attr_metadata:
            max_val = attr_metadata["max"]
            try:
                if float(value) > float(max_val):
                    return (
                        False,
                        f"La valeur {value} est supérieure au maximum {max_val} pour {attribute_name}",
                    )
            except (ValueError, TypeError):
                pass

        # Vérifier step si disponible
        if "step" in attr_metadata:
            step = attr_metadata["step"]
            try:
                step_val = float(step)
                if step_val > 0:
                    # Vérifier que la valeur est un multiple du step
                    remainder = (
                        float(value) - (attr_metadata.get("min", 0))
                    ) % step_val
                    if (
                        remainder > 0.0001
                    ):  # Tolérance pour les erreurs de virgule flottante
                        return (
                            False,
                            f"La valeur {value} n'est pas un multiple du step {step_val} pour {attribute_name}",
                        )
            except (ValueError, TypeError):
                pass

    # Vérifier enum_values pour les strings
    if isinstance(value, str) and "enum_values" in attr_metadata:
        enum_values = attr_metadata["enum_values"]
        if value not in enum_values:
            return (
                False,
                f"La valeur '{value}' n'est pas dans les valeurs autorisées {enum_values} pour {attribute_name}",
            )

    return True, None


# Fan speed helpers for Naviclim (X3D) reversible air-conditioning zones.
#
# These HVAC zones expose two dedicated fan-speed registers (verified on a live
# Naviclim Atlantic, see tools/traces-naviclim-atlantic.txt):
#   speed:        numeric, permission rw, min 1, max 3, step 1  -> manual speeds
#   speedString:  string,  permission rw, enum_values ["AUTO"]  -> automatic
# When automatic is active the device reports speedString="AUTO" and speed=null;
# in manual mode it reports the numeric speed (1..3). We map this onto the Home
# Assistant fan_mode feature as ["auto", "1", "2", "3"].
#
# Kept here (HA-free module) so the mapping can be unit-tested in isolation and
# reused by the climate entity.
NAVICLIM_FAN_AUTO_ENUM = "AUTO"


def get_naviclim_fan_modes(metadata: dict | None, auto_value: str = "auto") -> list[str]:
    """Build the list of Home Assistant fan modes from Naviclim metadata.

    Args:
        metadata: The device ``_metadata`` dict (keyed by register name).
        auto_value: The HA fan-mode string used for automatic speed
            (defaults to "auto", matching ``homeassistant`` FAN_AUTO).

    Returns:
        Fan modes ordered auto first, then the numeric speeds, e.g.
        ``["auto", "1", "2", "3"]``. Empty list when the device exposes no
        usable fan-speed register (i.e. it is not a Naviclim-style AC).

    """
    modes: list[str] = []
    if not isinstance(metadata, dict):
        return modes

    speed_string_meta = metadata.get("speedString")
    if (
        isinstance(speed_string_meta, dict)
        and NAVICLIM_FAN_AUTO_ENUM in speed_string_meta.get("enum_values", [])
    ):
        modes.append(auto_value)

    speed_meta = metadata.get("speed")
    if isinstance(speed_meta, dict) and speed_meta.get("type") == "numeric":
        try:
            speed_min = int(float(speed_meta.get("min", 1)))
            speed_max = int(float(speed_meta.get("max", 3)))
        except (ValueError, TypeError):
            speed_min, speed_max = 1, 3
        if speed_max >= speed_min:
            modes.extend(str(i) for i in range(speed_min, speed_max + 1))

    return modes


def get_naviclim_fan_mode(
    speed: float | int | None,
    speed_string: str | None,
    fan_modes: list[str],
    auto_value: str = "auto",
) -> str | None:
    """Resolve the current HA fan mode from Naviclim register values.

    ``speed_string == "AUTO"`` means automatic (``speed`` is then null);
    otherwise the numeric ``speed`` (1..3) is the active manual speed.

    Args:
        speed: Current value of the numeric ``speed`` register (or None).
        speed_string: Current value of the ``speedString`` register (or None).
        fan_modes: The supported fan modes (from :func:`get_naviclim_fan_modes`).
        auto_value: The HA fan-mode string used for automatic speed.

    Returns:
        The active fan mode string, or None when fan control is unsupported.

    """
    if not fan_modes:
        return None

    if speed_string == NAVICLIM_FAN_AUTO_ENUM and auto_value in fan_modes:
        return auto_value

    if speed is not None:
        try:
            speed_str = str(int(float(speed)))
        except (ValueError, TypeError):
            speed_str = None
        if speed_str is not None and speed_str in fan_modes:
            return speed_str

    # speed is null / unrecognised: prefer auto when the device supports it,
    # otherwise report the first available speed so HA always has a value.
    if auto_value in fan_modes:
        return auto_value
    return fan_modes[0]


# Mapping des valeurs validity vers les intervalles de polling (en secondes)
VALIDITY_POLLING_INTERVALS = {
    "INFINITE": None,  # Pas de polling nécessaire
    "ES_SUPERVISION": 300,  # 5 minutes
    "SENSOR_SUPERVISION": 60,  # 1 minute
    "SYNCHRO_SUPERVISION": 30,  # 30 secondes
    "upToDate": None,  # Pas de polling nécessaire
}


def get_polling_interval_for_validity(validity: str | None) -> int | None:
    """
    Retourne l'intervalle de polling en secondes selon la valeur validity.

    Args:
        validity: Valeur de validity depuis les métadonnées

    Returns:
        Intervalle en secondes ou None si pas de polling nécessaire

    """
    if validity is None:
        return None

    validity_upper = str(validity).upper()
    return VALIDITY_POLLING_INTERVALS.get(validity_upper, None)


# Timeout constants (in seconds) for different operation types
TIMEOUT_QUICK_REQUEST = 15.0  # Fast operations like simple GET requests
TIMEOUT_NORMAL_REQUEST = 30.0  # Standard request/reply over the websocket
TIMEOUT_LONG_REQUEST = 60.0  # Cloud credential fetch, digest handshake, historical data
TIMEOUT_WEBSOCKET_CONNECT = 30.0  # WebSocket upgrade (after digest handshake)
TIMEOUT_WEBSOCKET_RECEIVE = 20.0  # Per-message websocket receive timeout
TIMEOUT_PING = 40.0  # Ping timeout for remote mode


class StructuredLogger:
    """Helper class for structured logging with context."""

    def __init__(self, logger: Logger):
        """Initialize structured logger.

        Args:
            logger: Base logger instance

        """
        self._logger = logger

    def device_operation(
        self, level: str, operation: str, device_id: str, **kwargs
    ) -> None:
        """Log device operation with structured context.

        Args:
            level: Log level (debug, info, warning, error)
            operation: Operation name (e.g., "create", "update", "delete")
            device_id: Device identifier
            **kwargs: Additional context fields

        """
        context = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        message = f"Device operation: {operation} | device_id={device_id}"
        if context:
            message += f" | {context}"

        log_method = getattr(self._logger, level.lower(), self._logger.debug)
        log_method(message)

    def connection_event(self, level: str, event: str, **kwargs) -> None:
        """Log connection event with structured context.

        Args:
            level: Log level (debug, info, warning, error)
            event: Event name (e.g., "connect", "disconnect", "reconnect")
            **kwargs: Additional context fields

        """
        context = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        message = f"Connection event: {event}"
        if context:
            message += f" | {context}"

        log_method = getattr(self._logger, level.lower(), self._logger.debug)
        log_method(message)

    def api_request(self, level: str, method: str, url: str, **kwargs) -> None:
        """Log API request with structured context.

        Args:
            level: Log level (debug, info, warning, error)
            method: HTTP method (GET, POST, PUT, etc.)
            url: Request URL
            **kwargs: Additional context fields (status_code, duration, etc.)

        """
        context = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        message = f"API request: {method} {url}"
        if context:
            message += f" | {context}"

        log_method = getattr(self._logger, level.lower(), self._logger.debug)
        log_method(message)


# Create structured logger instance
STRUCTURED_LOGGER = StructuredLogger(LOGGER)
