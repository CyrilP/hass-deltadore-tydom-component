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
TIMEOUT_QUICK_REQUEST = 5.0  # Fast operations like simple GET requests
TIMEOUT_NORMAL_REQUEST = 10.0  # Standard operations like PUT, POST
TIMEOUT_LONG_REQUEST = 30.0  # Long operations like historical data, firmware updates
TIMEOUT_WEBSOCKET_CONNECT = 10.0  # WebSocket connection timeout
TIMEOUT_WEBSOCKET_RECEIVE = 5.0  # WebSocket receive timeout
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
