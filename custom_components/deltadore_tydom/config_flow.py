"""Config flow for Tydom integration."""

from __future__ import annotations
import traceback
import ipaddress
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import OptionsFlow, ConfigEntry
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant import config_entries, exceptions
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.const import (
    CONF_NAME,
    CONF_HOST,
    CONF_MAC,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PIN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.service_info import dhcp

from .const import (
    DOMAIN,
    LOGGER,
    CONF_TYDOM_PASSWORD,
    CONF_ZONES_AWAY,
    CONF_ZONES_HOME,
    CONF_ZONES_NIGHT,
    CONF_REFRESH_INTERVAL,
    CONF_CONFIG_MODE,
    CONF_CLOUD_MODE,
    CONF_MANUAL_MODE,
)
from . import hub
from .tydom.tydom_client import (
    TydomClientApiClientCommunicationError,
    TydomClientApiClientAuthenticationError,
    TydomClientApiClientError,
)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_MAC): cv.string,
        vol.Required(CONF_EMAIL): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Required(CONF_REFRESH_INTERVAL): cv.string,
        vol.Optional(CONF_ZONES_HOME): cv.string,
        vol.Optional(CONF_ZONES_AWAY): cv.string,
        vol.Optional(CONF_ZONES_NIGHT): cv.string,
        vol.Optional(CONF_PIN): str,
    }
)


def host_valid(host) -> bool:
    """Return True if hostname or IP address is valid."""
    try:
        if ipaddress.ip_address(host).version in (4, 6):
            return True
        return False
    except ValueError:
        disallowed = re.compile(r"[^a-zA-Z\d\-]")
        parts = host.split(".")
        return bool(parts and all(x and not disallowed.search(x) for x in parts))


email_regex = re.compile(
    r"([A-Za-z0-9]+[.-_])*[A-Za-z0-9]+@[A-Za-z0-9-]+(\.[A-Z|a-z]{2,})+"
)
zones_regex = re.compile(r"^$|^[0-8](,[0-8]){0,7}$")


def email_valid(email) -> bool:
    """Return True if email is valid."""
    return re.fullmatch(email_regex, email) is not None


def zones_valid(zones) -> bool:
    """Return True if zone config is valid."""
    return re.fullmatch(zones_regex, zones) is not None


async def validate_input(
    hass: HomeAssistant, cloud: bool, data: dict
) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    # Validate the data can be used to set up a connection.

    LOGGER.debug("validating input: %s", data)
    if not host_valid(data[CONF_HOST]):
        raise InvalidHost

    if len(data[CONF_MAC]) != 12:
        raise InvalidMacAddress

    for zone, error in {
        (CONF_ZONES_HOME, InvalidZoneHome),
        (CONF_ZONES_AWAY, InvalidZoneAway),
        (CONF_ZONES_NIGHT, InvalidZoneNight),
    }:
        if zone in data and not zones_valid(data[zone]):
            raise error

    if cloud:
        if not email_valid(data[CONF_EMAIL]):
            raise InvalidEmail

        if len(data[CONF_PASSWORD]) < 3:
            raise InvalidPassword

        # Convert to string if it's an int (from NumberSelector)
        if isinstance(data[CONF_REFRESH_INTERVAL], int):
            data[CONF_REFRESH_INTERVAL] = str(data[CONF_REFRESH_INTERVAL])

        try:
            int(data[CONF_REFRESH_INTERVAL])
        except (ValueError, TypeError):
            raise InvalidRefreshInterval

        password = await hub.Hub.get_tydom_credentials(
            async_create_clientsession(hass, False),
            data[CONF_EMAIL],
            data[CONF_PASSWORD],
            data[CONF_MAC],
        )
        data[CONF_TYDOM_PASSWORD] = password
    else:
        data[CONF_EMAIL] = ""
        data[CONF_PASSWORD] = ""
        if (
            CONF_TYDOM_PASSWORD not in data
            or len(data.get(CONF_TYDOM_PASSWORD, "")) < 3
        ):
            raise InvalidPassword

        # Convert to string if it's an int (from NumberSelector)
        if isinstance(data[CONF_REFRESH_INTERVAL], int):
            data[CONF_REFRESH_INTERVAL] = str(data[CONF_REFRESH_INTERVAL])

        try:
            int(data[CONF_REFRESH_INTERVAL])
        except (ValueError, TypeError):
            raise InvalidRefreshInterval

    LOGGER.debug("Input is valid.")
    return {
        CONF_HOST: data[CONF_HOST],
        CONF_MAC: data[CONF_MAC],
        CONF_EMAIL: data[CONF_EMAIL],
        CONF_PASSWORD: data[CONF_PASSWORD],
        CONF_REFRESH_INTERVAL: data[CONF_REFRESH_INTERVAL],
        CONF_TYDOM_PASSWORD: data[CONF_TYDOM_PASSWORD],
        CONF_ZONES_HOME: data.get(CONF_ZONES_HOME),
        CONF_ZONES_AWAY: data.get(CONF_ZONES_AWAY),
        CONF_ZONES_NIGHT: data.get(CONF_ZONES_NIGHT),
        CONF_PIN: data.get(CONF_PIN),
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tydom."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        """Initialize config flow."""
        self._discovered_host = None
        self._discovered_mac = None
        self._name_value: str | None = None

    async def async_step_import(self, import_config):
        """Import a config entry from configuration.yaml."""
        return await self.async_step_user(import_config)

    async def async_step_user(self, user_input=None) -> config_entries.FlowResult:
        """Handle the initial step."""
        _errors = {}
        if user_input is not None:
            if user_input.get(CONF_CONFIG_MODE) == CONF_MANUAL_MODE:
                return await self.async_step_user_manual()
            else:
                return await self.async_step_user_cloud()
        else:
            user_input = user_input or {}
            return self.async_show_form(  # type: ignore[return-value]
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_CONFIG_MODE,
                            default=user_input.get(CONF_CONFIG_MODE),
                        ): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    selector.SelectOptionDict(
                                        value=CONF_CLOUD_MODE, label=CONF_CLOUD_MODE
                                    ),
                                    selector.SelectOptionDict(
                                        value=CONF_MANUAL_MODE, label=CONF_MANUAL_MODE
                                    ),
                                ],
                                translation_key=CONF_CONFIG_MODE,
                            ),
                        ),
                    }
                ),
                errors=_errors,
            )

    async def async_step_user_cloud(self, user_input=None) -> config_entries.FlowResult:
        """Handle the cloud connection step."""
        # This goes through the steps to take the user through the setup process.
        # Using this it is possible to update the UI and prompt for additional
        # information. This example provides a single form (built from `DATA_SCHEMA`),
        # and when that has some validated input, it calls `async_create_entry` to
        # actually create the HA config entry. Note the "title" value is returned by
        # `validate_input` above.
        _errors = {}
        default_zone_home = ""
        default_zone_away = ""
        default_zone_night = ""

        if user_input is not None:
            default_zone_home = user_input.get(CONF_ZONES_HOME, None)
            default_zone_away = user_input.get(CONF_ZONES_AWAY, None)
            default_zone_night = user_input.get(CONF_ZONES_NIGHT, None)
            try:
                user_input = await validate_input(self.hass, True, user_input)
                # Ensure it's working as expected

                tydom_hub = hub.Hub(
                    self.hass,
                    None,  # type: ignore[arg-type]
                    user_input[CONF_HOST],
                    user_input[CONF_MAC],
                    user_input[CONF_TYDOM_PASSWORD],
                    "-1",
                    "",
                    "",
                    "",
                    "",
                )
                await tydom_hub.test_credentials()

                await self.async_set_unique_id(user_input[CONF_MAC])
                self._abort_if_unique_id_configured()
            except CannotConnect:
                _errors["base"] = "cannot_connect"
            except InvalidHost:
                # The error string is set here, and should be translated.
                # This example does not currently cover translations, see the
                # comments on `DATA_SCHEMA` for further details.
                # Set the error on the `host` field, not the entire form.
                _errors[CONF_HOST] = "invalid_host"
                LOGGER.error("Invalid host: %s", user_input[CONF_HOST])
            except InvalidMacAddress:
                _errors[CONF_MAC] = "invalid_macaddress"
                LOGGER.error("Invalid MAC: %s", user_input[CONF_MAC])
            except InvalidEmail:
                _errors[CONF_EMAIL] = "invalid_email"
                LOGGER.error("Invalid email: %s", user_input[CONF_EMAIL])
            except InvalidPassword:
                _errors[CONF_PASSWORD] = "invalid_password"
                LOGGER.error("Invalid password")
            except InvalidRefreshInterval:
                _errors[CONF_REFRESH_INTERVAL] = "invalid_refresh_interval"
            except InvalidZoneHome:
                _errors[CONF_ZONES_HOME] = "invalid_zone_config"
                default_zone_home = ""
                LOGGER.error("Invalid Zone HOME: %s", user_input[CONF_ZONES_HOME])
            except InvalidZoneAway:
                _errors[CONF_ZONES_AWAY] = "invalid_zone_config"
                default_zone_away = ""
                LOGGER.error("Invalid Zone AWAY: %s", user_input[CONF_ZONES_AWAY])
            except InvalidZoneNight:
                _errors[CONF_ZONES_NIGHT] = "invalid_zone_config"
                default_zone_night = ""
                LOGGER.error("Invalid Zone NIGHT: %s", user_input[CONF_ZONES_NIGHT])
            except TydomClientApiClientCommunicationError:
                traceback.print_exc()
                _errors["base"] = "communication_error"
                LOGGER.exception("Communication error")
            except TydomClientApiClientAuthenticationError:
                traceback.print_exc()
                _errors["base"] = "authentication_error"
                LOGGER.exception("Authentication error")
            except TydomClientApiClientError:
                traceback.print_exc()
                _errors["base"] = "unknown"
                LOGGER.exception("Unknown error")
            except AbortFlow:
                raise
            except Exception:  # pylint: disable=broad-except
                traceback.print_exc()
                LOGGER.exception("Unexpected exception")
                _errors["base"] = "unknown"
            else:
                LOGGER.warning("adding TYDOM entry")
                await self.async_set_unique_id(user_input[CONF_MAC])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(  # type: ignore[return-value]
                    title="Tydom-" + user_input[CONF_MAC][6:], data=user_input
                )

        user_input = user_input or {}

        return self.async_show_form(  # type: ignore[return-value]
            step_id="user_cloud",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=user_input.get(CONF_HOST)
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Required(
                        CONF_MAC, default=user_input.get(CONF_MAC)
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Required(
                        CONF_EMAIL, default=user_input.get(CONF_EMAIL)
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.EMAIL,
                            autocomplete="username",
                        )
                    ),
                    vol.Required(
                        CONF_PASSWORD, default=user_input.get(CONF_PASSWORD)
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                            autocomplete="current-password",
                        )
                    ),
                    vol.Required(
                        CONF_REFRESH_INTERVAL, default="30"
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=1440,
                            step=1,
                            unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_ZONES_HOME, default=default_zone_home
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Optional(
                        CONF_ZONES_AWAY, default=default_zone_away
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Optional(
                        CONF_ZONES_NIGHT, default=default_zone_night
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Optional(
                        CONF_PIN, default=user_input.get(CONF_PIN, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                            autocomplete="off",
                        )
                    ),
                }
            ),
            errors=_errors,
        )

    async def async_step_user_manual(
        self, user_input=None
    ) -> config_entries.FlowResult:
        """Handle the manual connection step."""
        # This goes through the steps to take the user through the setup process.
        # Using this it is possible to update the UI and prompt for additional
        # information. This example provides a single form (built from `DATA_SCHEMA`),
        # and when that has some validated input, it calls `async_create_entry` to
        # actually create the HA config entry. Note the "title" value is returned by
        # `validate_input` above.
        _errors = {}
        default_zone_home = ""
        default_zone_away = ""
        default_zone_night = ""
        if user_input is not None:
            default_zone_home = user_input.get(CONF_ZONES_HOME, None)
            default_zone_away = user_input.get(CONF_ZONES_AWAY, None)
            default_zone_night = user_input.get(CONF_ZONES_NIGHT, None)
            try:
                user_input = await validate_input(self.hass, False, user_input)
                # Ensure it's working as expected

                tydom_hub = hub.Hub(
                    self.hass,
                    None,  # type: ignore[arg-type]
                    user_input[CONF_HOST],
                    user_input[CONF_MAC],
                    user_input[CONF_TYDOM_PASSWORD],
                    "-1",
                    "",
                    "",
                    "",
                    "",
                )
                await tydom_hub.test_credentials()

                await self.async_set_unique_id(user_input[CONF_MAC])
                self._abort_if_unique_id_configured()
            except CannotConnect:
                _errors["base"] = "cannot_connect"
            except InvalidHost:
                # The error string is set here, and should be translated.
                # This example does not currently cover translations, see the
                # comments on `DATA_SCHEMA` for further details.
                # Set the error on the `host` field, not the entire form.
                _errors[CONF_HOST] = "invalid_host"
                LOGGER.error("Invalid host: %s", user_input[CONF_HOST])
            except InvalidMacAddress:
                _errors[CONF_MAC] = "invalid_macaddress"
                LOGGER.error("Invalid MAC: %s", user_input[CONF_MAC])
            except InvalidPassword:
                _errors[CONF_TYDOM_PASSWORD] = "invalid_password"
                LOGGER.error("Invalid password")
            except InvalidRefreshInterval:
                _errors[CONF_REFRESH_INTERVAL] = "invalid_refresh_interval"
            except InvalidZoneHome:
                _errors[CONF_ZONES_HOME] = "invalid_zone_config"
                default_zone_home = ""
                LOGGER.error("Invalid Zone HOME: %s", user_input[CONF_ZONES_HOME])
            except InvalidZoneAway:
                _errors[CONF_ZONES_AWAY] = "invalid_zone_config"
                default_zone_away = ""
                LOGGER.error("Invalid Zone AWAY: %s", user_input[CONF_ZONES_AWAY])
            except InvalidZoneNight:
                _errors[CONF_ZONES_NIGHT] = "invalid_zone_config"
                default_zone_night = ""
                LOGGER.error("Invalid Zone NIGHT: %s", user_input[CONF_ZONES_NIGHT])
            except TydomClientApiClientCommunicationError:
                traceback.print_exc()
                _errors["base"] = "communication_error"
                LOGGER.exception("Communication error")
            except TydomClientApiClientAuthenticationError:
                traceback.print_exc()
                _errors["base"] = "authentication_error"
                LOGGER.exception("Authentication error")
            except TydomClientApiClientError:
                traceback.print_exc()
                _errors["base"] = "unknown"
                LOGGER.exception("Unknown error")
            except AbortFlow:
                raise
            except Exception:  # pylint: disable=broad-except
                traceback.print_exc()
                LOGGER.exception("Unexpected exception")
                _errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_MAC])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(  # type: ignore[return-value]
                    title="Tydom-" + user_input[CONF_MAC][6:], data=user_input
                )

        user_input = user_input or {}

        return self.async_show_form(  # type: ignore[return-value]
            step_id="user_manual",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=user_input.get(CONF_HOST)
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Required(
                        CONF_MAC, default=user_input.get(CONF_MAC)
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Required(
                        CONF_TYDOM_PASSWORD, default=user_input.get(CONF_TYDOM_PASSWORD)
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                            autocomplete="off",
                        )
                    ),
                    vol.Required(
                        CONF_REFRESH_INTERVAL, default="30"
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=1440,
                            step=1,
                            unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_ZONES_HOME, default=default_zone_home
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Optional(
                        CONF_ZONES_AWAY, default=default_zone_away
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Optional(
                        CONF_ZONES_NIGHT, default=default_zone_night
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Optional(
                        CONF_PIN, default=user_input.get(CONF_PIN, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                            autocomplete="off",
                        )
                    ),
                }
            ),
            errors=_errors,
        )

    @property
    def _name(self) -> str | None:
        return self._name_value or self.context.get(CONF_NAME)

    @_name.setter
    def _name(self, value: str) -> None:
        self._name_value = value

    async def async_step_dhcp(self, discovery_info: dhcp.DhcpServiceInfo):
        """Handle the discovery from dhcp."""
        self._discovered_host = discovery_info.ip
        self._discovered_mac = discovery_info.macaddress.upper()
        self._name = discovery_info.hostname.upper()
        await self.async_set_unique_id(discovery_info.macaddress.upper())
        self._abort_if_unique_id_configured()
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(self, user_input=None):
        """Confirm discovery."""
        _errors = {}
        if user_input is not None:
            if user_input.get(CONF_CONFIG_MODE) == CONF_MANUAL_MODE:
                return await self.async_step_discovery_confirm_manual()
            else:
                return await self.async_step_discovery_confirm_cloud()
        else:
            user_input = user_input or {}
            return self.async_show_form(
                step_id="discovery_confirm",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_CONFIG_MODE,
                            default=user_input.get(CONF_CONFIG_MODE),
                        ): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    selector.SelectOptionDict(
                                        value=CONF_CLOUD_MODE, label=CONF_CLOUD_MODE
                                    ),
                                    selector.SelectOptionDict(
                                        value=CONF_MANUAL_MODE, label=CONF_MANUAL_MODE
                                    ),
                                ],
                                translation_key=CONF_CONFIG_MODE,
                            ),
                        ),
                    }
                ),
                errors=_errors,
            )

    async def async_step_discovery_confirm_manual(self, user_input=None):
        """Confirm discovery manual."""
        _errors = {}
        if user_input is not None:
            try:
                user_input = await validate_input(self.hass, False, user_input)
                # Ensure it's working as expected
                tydom_hub = hub.Hub(
                    self.hass,
                    None,  # type: ignore[arg-type]
                    user_input[CONF_HOST],
                    user_input[CONF_MAC],
                    user_input[CONF_TYDOM_PASSWORD],
                    "-1",
                    "",
                    "",
                    "",
                    "",
                )
                await tydom_hub.test_credentials()

            except CannotConnect:
                _errors["base"] = "cannot_connect"
            except InvalidHost:
                _errors[CONF_HOST] = "invalid_host"
            except InvalidMacAddress:
                _errors[CONF_MAC] = "invalid_macaddress"
                _errors[CONF_TYDOM_PASSWORD] = "invalid_password"
            except InvalidRefreshInterval:
                _errors[CONF_REFRESH_INTERVAL] = "invalid_refresh_interval"
            except InvalidZoneHome:
                _errors[CONF_ZONES_HOME] = "invalid_zone_config"
            except InvalidZoneAway:
                _errors[CONF_ZONES_AWAY] = "invalid_zone_config"
            except InvalidZoneNight:
                _errors[CONF_ZONES_NIGHT] = "invalid_zone_config"
            except TydomClientApiClientCommunicationError:
                traceback.print_exc()
                _errors["base"] = "communication_error"
            except TydomClientApiClientAuthenticationError:
                traceback.print_exc()
                _errors["base"] = "authentication_error"
            except TydomClientApiClientError:
                traceback.print_exc()
                _errors["base"] = "unknown"
            except AbortFlow:
                raise
            except Exception:  # pylint: disable=broad-except
                traceback.print_exc()
                LOGGER.exception("Unexpected exception")
                _errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_MAC])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Tydom-" + user_input[CONF_MAC][6:], data=user_input
                )

        user_input = user_input or {}
        return self.async_show_form(
            step_id="discovery_confirm_manual",
            description_placeholders={"name": self._name or ""},
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST,
                        default=user_input.get(CONF_HOST, self._discovered_host),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Required(
                        CONF_MAC, default=user_input.get(CONF_MAC, self._discovered_mac)
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Required(
                        CONF_TYDOM_PASSWORD, default=user_input.get(CONF_TYDOM_PASSWORD)
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                            autocomplete="off",
                        )
                    ),
                    vol.Required(
                        CONF_REFRESH_INTERVAL,
                        default=user_input.get(CONF_REFRESH_INTERVAL, "30"),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=1440,
                            step=1,
                            unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_ZONES_HOME, default=user_input.get(CONF_ZONES_HOME, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Optional(
                        CONF_ZONES_AWAY, default=user_input.get(CONF_ZONES_AWAY, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Optional(
                        CONF_ZONES_NIGHT, default=user_input.get(CONF_ZONES_NIGHT, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Optional(
                        CONF_PIN, default=user_input.get(CONF_PIN, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                            autocomplete="off",
                        )
                    ),
                }
            ),
        )

    async def async_step_discovery_confirm_cloud(self, user_input=None):
        """Confirm discovery cloud."""
        _errors = {}
        if user_input is not None:
            try:
                user_input = await validate_input(self.hass, True, user_input)
                # Ensure it's working as expected
                tydom_hub = hub.Hub(
                    self.hass,
                    None,  # type: ignore[arg-type]
                    user_input[CONF_HOST],
                    user_input[CONF_MAC],
                    user_input[CONF_TYDOM_PASSWORD],
                    "-1",
                    "",
                    "",
                    "",
                    "",
                )
                await tydom_hub.test_credentials()

            except CannotConnect:
                _errors["base"] = "cannot_connect"
            except InvalidHost:
                _errors[CONF_HOST] = "invalid_host"
            except InvalidMacAddress:
                _errors[CONF_MAC] = "invalid_macaddress"
            except InvalidEmail:
                _errors[CONF_EMAIL] = "invalid_email"
            except InvalidPassword:
                _errors[CONF_PASSWORD] = "invalid_password"
            except InvalidRefreshInterval:
                _errors[CONF_REFRESH_INTERVAL] = "invalid_refresh_interval"
            except InvalidZoneHome:
                _errors[CONF_ZONES_HOME] = "invalid_zone_config"
            except InvalidZoneAway:
                _errors[CONF_ZONES_AWAY] = "invalid_zone_config"
            except InvalidZoneNight:
                _errors[CONF_ZONES_NIGHT] = "invalid_zone_config"
            except TydomClientApiClientCommunicationError:
                traceback.print_exc()
                _errors["base"] = "communication_error"
            except TydomClientApiClientAuthenticationError:
                traceback.print_exc()
                _errors["base"] = "authentication_error"
            except TydomClientApiClientError:
                traceback.print_exc()
                _errors["base"] = "unknown"
            except AbortFlow:
                raise
            except Exception:  # pylint: disable=broad-except
                traceback.print_exc()
                LOGGER.exception("Unexpected exception")
                _errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_MAC])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Tydom-" + user_input[CONF_MAC][6:], data=user_input
                )

        user_input = user_input or {}
        return self.async_show_form(
            step_id="discovery_confirm_cloud",
            description_placeholders={"name": self._name or ""},
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST,
                        default=user_input.get(CONF_HOST, self._discovered_host),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Required(
                        CONF_MAC, default=user_input.get(CONF_MAC, self._discovered_mac)
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Required(
                        CONF_EMAIL, default=user_input.get(CONF_EMAIL)
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.EMAIL,
                            autocomplete="username",
                        )
                    ),
                    vol.Required(
                        CONF_PASSWORD, default=user_input.get(CONF_PASSWORD)
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                            autocomplete="current-password",
                        )
                    ),
                    vol.Required(
                        CONF_REFRESH_INTERVAL,
                        default=user_input.get(CONF_REFRESH_INTERVAL, "30"),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=1440,
                            step=1,
                            unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_ZONES_HOME, default=user_input.get(CONF_ZONES_HOME, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Optional(
                        CONF_ZONES_AWAY, default=user_input.get(CONF_ZONES_AWAY, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Optional(
                        CONF_ZONES_NIGHT, default=user_input.get(CONF_ZONES_NIGHT, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Optional(
                        CONF_PIN, default=user_input.get(CONF_PIN, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                            autocomplete="off",
                        )
                    ),
                }
            ),
        )

    async def async_step_reauth(self, user_input=None):
        """Handle reauth upon an API authentication error."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Handle reauth confirmation."""
        errors = {}
        existing_entry = self._get_reauth_entry()
        if existing_entry is None:
            return self.async_abort(reason="reauth_entry_not_found")

        if user_input is not None:
            try:
                # Determine if cloud or manual mode
                cloud_mode = (
                    CONF_EMAIL in existing_entry.data
                    and existing_entry.data[CONF_EMAIL]
                )

                if cloud_mode:
                    # Cloud mode reauth
                    data = {
                        CONF_HOST: user_input.get(
                            CONF_HOST, existing_entry.data[CONF_HOST]
                        ),
                        CONF_MAC: existing_entry.data[CONF_MAC],
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_REFRESH_INTERVAL: existing_entry.data.get(
                            CONF_REFRESH_INTERVAL, "30"
                        ),
                        CONF_ZONES_HOME: existing_entry.data.get(CONF_ZONES_HOME, ""),
                        CONF_ZONES_AWAY: existing_entry.data.get(CONF_ZONES_AWAY, ""),
                        CONF_ZONES_NIGHT: existing_entry.data.get(CONF_ZONES_NIGHT, ""),
                        CONF_PIN: existing_entry.data.get(CONF_PIN, ""),
                    }
                    validated_data = await validate_input(self.hass, True, data)
                else:
                    # Manual mode reauth
                    data = {
                        CONF_HOST: user_input.get(
                            CONF_HOST, existing_entry.data[CONF_HOST]
                        ),
                        CONF_MAC: existing_entry.data[CONF_MAC],
                        CONF_TYDOM_PASSWORD: user_input[CONF_TYDOM_PASSWORD],
                        CONF_REFRESH_INTERVAL: existing_entry.data.get(
                            CONF_REFRESH_INTERVAL, "30"
                        ),
                        CONF_ZONES_HOME: existing_entry.data.get(CONF_ZONES_HOME, ""),
                        CONF_ZONES_AWAY: existing_entry.data.get(CONF_ZONES_AWAY, ""),
                        CONF_ZONES_NIGHT: existing_entry.data.get(CONF_ZONES_NIGHT, ""),
                        CONF_PIN: existing_entry.data.get(CONF_PIN, ""),
                    }
                    validated_data = await validate_input(self.hass, False, data)

                # Test credentials
                tydom_hub = hub.Hub(
                    self.hass,
                    None,  # type: ignore[arg-type]
                    validated_data[CONF_HOST],
                    validated_data[CONF_MAC],
                    validated_data[CONF_TYDOM_PASSWORD],
                    "-1",
                    "",
                    "",
                    "",
                    "",
                )
                await tydom_hub.test_credentials()

                # Update entry
                self.hass.config_entries.async_update_entry(
                    existing_entry, data=validated_data
                )
                await self.hass.config_entries.async_reload(existing_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

            except TydomClientApiClientAuthenticationError:
                errors["base"] = "authentication_error"
                LOGGER.exception("Authentication error during reauth")
            except TydomClientApiClientCommunicationError:
                errors["base"] = "communication_error"
                LOGGER.exception("Communication error during reauth")
            except InvalidPassword:
                if cloud_mode:
                    errors[CONF_PASSWORD] = "invalid_password"
                else:
                    errors[CONF_TYDOM_PASSWORD] = "invalid_password"
            except InvalidHost:
                errors[CONF_HOST] = "invalid_host"
            except Exception:
                errors["base"] = "unknown"
                LOGGER.exception("Unexpected error during reauth")

        # Show form
        if cloud_mode:
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_EMAIL, default=existing_entry.data.get(CONF_EMAIL, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.EMAIL,
                            autocomplete="username",
                        )
                    ),
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                            autocomplete="current-password",
                        )
                    ),
                    vol.Optional(
                        CONF_HOST, default=existing_entry.data.get(CONF_HOST, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                }
            )
        else:
            schema = vol.Schema(
                {
                    vol.Required(CONF_TYDOM_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                            autocomplete="off",
                        )
                    ),
                    vol.Optional(
                        CONF_HOST, default=existing_entry.data.get(CONF_HOST, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                }
            )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={"name": existing_entry.title},
        )

    def _get_reauth_entry(self) -> ConfigEntry | None:
        """Get the entry being re-authenticated."""
        if "entry_id" not in self.context:
            return None
        entry_id = self.context["entry_id"]
        return self.hass.config_entries.async_get_entry(entry_id)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Option flow to configure zones at any time."""

    @property
    def config_entry(self):
        """Config entry."""
        return self.hass.config_entries.async_get_entry(self.handler)

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage the options."""
        _errors = {}
        if self.config_entry is None:
            return self.async_abort(reason="config_entry_not_found")

        default_zone_home = ""
        default_zone_away = ""
        default_zone_night = ""
        default_refresh_interval = "30"
        if CONF_ZONES_HOME in self.config_entry.data:
            default_zone_home = self.config_entry.data[CONF_ZONES_HOME]

        if CONF_ZONES_AWAY in self.config_entry.data:
            default_zone_away = self.config_entry.data[CONF_ZONES_AWAY]

        if CONF_ZONES_NIGHT in self.config_entry.data:
            default_zone_night = self.config_entry.data[CONF_ZONES_NIGHT]

        if CONF_REFRESH_INTERVAL in self.config_entry.data:
            default_refresh_interval = self.config_entry.data[CONF_REFRESH_INTERVAL]

        if user_input is not None:
            default_zone_home = user_input.get(CONF_ZONES_HOME, "")
            default_zone_away = user_input.get(CONF_ZONES_AWAY, "")
            default_zone_night = user_input.get(CONF_ZONES_NIGHT, "")
            default_refresh_interval = user_input.get(CONF_REFRESH_INTERVAL, "30")

            try:
                # Validate zones
                if CONF_ZONES_HOME in user_input and user_input[CONF_ZONES_HOME]:
                    if not zones_valid(user_input[CONF_ZONES_HOME]):
                        raise InvalidZoneHome

                if CONF_ZONES_AWAY in user_input and user_input[CONF_ZONES_AWAY]:
                    if not zones_valid(user_input[CONF_ZONES_AWAY]):
                        raise InvalidZoneAway

                if CONF_ZONES_NIGHT in user_input and user_input[CONF_ZONES_NIGHT]:
                    if not zones_valid(user_input[CONF_ZONES_NIGHT]):
                        raise InvalidZoneNight

                # Validate refresh interval
                # Convert to string if it's an int (from NumberSelector)
                if isinstance(user_input[CONF_REFRESH_INTERVAL], int):
                    user_input[CONF_REFRESH_INTERVAL] = str(
                        user_input[CONF_REFRESH_INTERVAL]
                    )
                    default_refresh_interval = user_input[CONF_REFRESH_INTERVAL]

                try:
                    interval = int(user_input[CONF_REFRESH_INTERVAL])
                    if interval < 0:
                        raise InvalidRefreshInterval
                except (ValueError, TypeError):
                    raise InvalidRefreshInterval

                if self.config_entry is None:
                    return self.async_abort(reason="config_entry_not_found")

                # Prepare updated data
                updated_data = self.config_entry.data.copy()
                updated_data[CONF_ZONES_HOME] = default_zone_home
                updated_data[CONF_ZONES_AWAY] = default_zone_away
                updated_data[CONF_ZONES_NIGHT] = default_zone_night
                updated_data[CONF_REFRESH_INTERVAL] = default_refresh_interval

                # Update entry
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=updated_data,
                    options=self.config_entry.options,
                )
                return self.async_create_entry(title="", data={})

            except InvalidRefreshInterval:
                _errors[CONF_REFRESH_INTERVAL] = "invalid_refresh_interval"
                LOGGER.warning(
                    "Invalid refresh interval: %s",
                    user_input.get(CONF_REFRESH_INTERVAL),
                )
            except InvalidZoneHome:
                _errors[CONF_ZONES_HOME] = "invalid_zone_config"
                default_zone_home = ""
                LOGGER.warning("Invalid Zone HOME: %s", user_input.get(CONF_ZONES_HOME))
            except InvalidZoneAway:
                _errors[CONF_ZONES_AWAY] = "invalid_zone_config"
                default_zone_away = ""
                LOGGER.warning("Invalid Zone AWAY: %s", user_input.get(CONF_ZONES_AWAY))
            except InvalidZoneNight:
                _errors[CONF_ZONES_NIGHT] = "invalid_zone_config"
                default_zone_night = ""
                LOGGER.warning(
                    "Invalid Zone NIGHT: %s", user_input.get(CONF_ZONES_NIGHT)
                )
            except Exception:
                _errors["base"] = "unknown"
                LOGGER.exception("Unexpected error in options flow")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_REFRESH_INTERVAL,
                        description={"suggested_value": default_refresh_interval},
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=1440,
                            step=1,
                            unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_ZONES_HOME,
                        description={"suggested_value": default_zone_home},
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Optional(
                        CONF_ZONES_AWAY,
                        description={"suggested_value": default_zone_away},
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                    vol.Optional(
                        CONF_ZONES_NIGHT,
                        description={"suggested_value": default_zone_night},
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        )
                    ),
                }
            ),
            errors=_errors,
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""


class InvalidMacAddress(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid Mac address."""


class InvalidEmail(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid Email."""


class InvalidPassword(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid Password."""


class InvalidZoneHome(exceptions.HomeAssistantError):
    """Error to indicate the Zones Home config is not valid."""


class InvalidZoneAway(exceptions.HomeAssistantError):
    """Error to indicate the Zones Away config is not valid."""


class InvalidZoneNight(exceptions.HomeAssistantError):
    """Error to indicate the Zones Night config is not valid."""


class InvalidRefreshInterval(exceptions.HomeAssistantError):
    """Error to indicate the refresh interval is not valid."""
