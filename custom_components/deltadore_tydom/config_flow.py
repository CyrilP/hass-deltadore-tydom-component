"""Config flow for Tydom integration."""

from __future__ import annotations
import traceback
import ipaddress
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import OptionsFlow
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant import config_entries, exceptions
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
        if ipaddress.ip_address(host).version == (4 or 6):
            return True
    except ValueError:
        disallowed = re.compile(r"[^a-zA-Z\d\-]")
        return all(x and not disallowed.search(x) for x in host.split("."))


email_regex = re.compile(
    r"([A-Za-z0-9]+[.-_])*[A-Za-z0-9]+@[A-Za-z0-9-]+(\.[A-Z|a-z]{2,})+"
)
zones_regex = re.compile(r"^$|^[0-8](,[0-8]){0,7}$")


def email_valid(email) -> bool:
    """Return True if email is valid."""
    return re.fullmatch(email_regex, email)


def zones_valid(zones) -> bool:
    """Return True if zone config is valid."""
    return re.fullmatch(zones_regex, zones)


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

        try:
            int(data[CONF_REFRESH_INTERVAL])
        except ValueError:
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
        if len(data[CONF_TYDOM_PASSWORD]) < 3:
            raise InvalidPassword

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
            return self.async_show_form(
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
            user_input.get(CONF_PIN, "")
            default_zone_home = user_input.get(CONF_ZONES_HOME, None)
            default_zone_away = user_input.get(CONF_ZONES_AWAY, None)
            default_zone_night = user_input.get(CONF_ZONES_NIGHT, None)
            try:
                user_input = await validate_input(self.hass, True, user_input)
                # Ensure it's working as expected

                tydom_hub = hub.Hub(
                    self.hass,
                    None,
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

            except Exception:  # pylint: disable=broad-except
                traceback.print_exc()
                LOGGER.exception("Unexpected exception")
                _errors["base"] = "unknown"
            else:
                LOGGER.warn("adding TYDOM entry")
                await self.async_set_unique_id(user_input[CONF_MAC])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Tydom-" + user_input[CONF_MAC][6:], data=user_input
                )

        user_input = user_input or {}

        return self.async_show_form(
            step_id="user_cloud",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=user_input.get(CONF_HOST)
                    ): cv.string,
                    vol.Required(CONF_MAC, default=user_input.get(CONF_MAC)): cv.string,
                    vol.Required(
                        CONF_EMAIL, default=user_input.get(CONF_EMAIL)
                    ): cv.string,
                    vol.Required(
                        CONF_PASSWORD, default=user_input.get(CONF_PASSWORD)
                    ): cv.string,
                    vol.Required(CONF_REFRESH_INTERVAL, default="30"): cv.string,
                    vol.Optional(CONF_ZONES_HOME, default=default_zone_home): str,
                    vol.Optional(CONF_ZONES_AWAY, default=default_zone_away): str,
                    vol.Optional(CONF_ZONES_NIGHT, default=default_zone_night): str,
                    vol.Optional(CONF_PIN, default=user_input.get(CONF_PIN, "")): str,
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
            user_input.get(CONF_PIN, "")
            default_zone_home = user_input.get(CONF_ZONES_HOME, None)
            default_zone_away = user_input.get(CONF_ZONES_AWAY, None)
            default_zone_night = user_input.get(CONF_ZONES_NIGHT, None)
            try:
                user_input = await validate_input(self.hass, False, user_input)
                # Ensure it's working as expected

                tydom_hub = hub.Hub(
                    self.hass,
                    None,
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
            step_id="user_manual",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=user_input.get(CONF_HOST)
                    ): cv.string,
                    vol.Required(CONF_MAC, default=user_input.get(CONF_MAC)): cv.string,
                    vol.Required(
                        CONF_TYDOM_PASSWORD, default=user_input.get(CONF_TYDOM_PASSWORD)
                    ): cv.string,
                    vol.Required(CONF_REFRESH_INTERVAL, default="30"): cv.string,
                    vol.Optional(CONF_ZONES_HOME, default=default_zone_home): str,
                    vol.Optional(CONF_ZONES_AWAY, default=default_zone_away): str,
                    vol.Optional(CONF_ZONES_NIGHT, default=default_zone_night): str,
                    vol.Optional(CONF_PIN, default=user_input.get(CONF_PIN, "")): str,
                }
            ),
            errors=_errors,
        )

    @property
    def _name(self) -> str | None:
        return self.context.get(CONF_NAME)

    @_name.setter
    def _name(self, value: str) -> None:
        self.context[CONF_NAME] = value
        self.context["title_placeholders"] = {"name": self._name}

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
                    None,
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
            description_placeholders={"name": self._name},
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST,
                        default=user_input.get(CONF_HOST, self._discovered_host),
                    ): str,
                    vol.Required(
                        CONF_MAC, default=user_input.get(CONF_MAC, self._discovered_mac)
                    ): str,
                    vol.Required(
                        CONF_TYDOM_PASSWORD, default=user_input.get(CONF_TYDOM_PASSWORD)
                    ): cv.string,
                    vol.Required(
                        CONF_REFRESH_INTERVAL,
                        default=user_input.get(CONF_REFRESH_INTERVAL, "30"),
                    ): str,
                    vol.Optional(
                        CONF_ZONES_HOME, default=user_input.get(CONF_ZONES_HOME, "")
                    ): str,
                    vol.Optional(
                        CONF_ZONES_AWAY, default=user_input.get(CONF_ZONES_AWAY, "")
                    ): str,
                    vol.Optional(
                        CONF_ZONES_NIGHT, default=user_input.get(CONF_ZONES_NIGHT, "")
                    ): str,
                    vol.Optional(CONF_PIN, default=user_input.get(CONF_PIN, "")): str,
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
                    None,
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
            description_placeholders={"name": self._name},
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST,
                        default=user_input.get(CONF_HOST, self._discovered_host),
                    ): str,
                    vol.Required(
                        CONF_MAC, default=user_input.get(CONF_MAC, self._discovered_mac)
                    ): str,
                    vol.Required(
                        CONF_EMAIL, default=user_input.get(CONF_EMAIL)
                    ): cv.string,
                    vol.Required(
                        CONF_PASSWORD, default=user_input.get(CONF_PASSWORD)
                    ): cv.string,
                    vol.Required(
                        CONF_REFRESH_INTERVAL,
                        default=user_input.get(CONF_REFRESH_INTERVAL, "30"),
                    ): str,
                    vol.Optional(
                        CONF_ZONES_HOME, default=user_input.get(CONF_ZONES_HOME, "")
                    ): str,
                    vol.Optional(
                        CONF_ZONES_AWAY, default=user_input.get(CONF_ZONES_AWAY, "")
                    ): str,
                    vol.Optional(
                        CONF_ZONES_NIGHT, default=user_input.get(CONF_ZONES_NIGHT, "")
                    ): str,
                    vol.Optional(CONF_PIN, default=user_input.get(CONF_PIN, "")): str,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Option flow to configure zones at any time."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage the options."""
        _errors = {}
        default_zone_home = ""
        default_zone_away = ""
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
                if CONF_ZONES_HOME in user_input and not zones_valid(
                    user_input[CONF_ZONES_HOME]
                ):
                    raise InvalidZoneHome

                if CONF_ZONES_AWAY in user_input and not zones_valid(
                    user_input[CONF_ZONES_AWAY]
                ):
                    raise InvalidZoneAway

                if CONF_ZONES_NIGHT in user_input and not zones_valid(
                    user_input[CONF_ZONES_NIGHT]
                ):
                    raise InvalidZoneNight

                try:
                    int(user_input[CONF_REFRESH_INTERVAL])
                except ValueError:
                    raise InvalidRefreshInterval

                user_input[CONF_HOST] = self.config_entry.data[CONF_HOST]
                user_input[CONF_MAC] = self.config_entry.data[CONF_MAC]
                user_input[CONF_EMAIL] = self.config_entry.data[CONF_EMAIL]
                user_input[CONF_PASSWORD] = self.config_entry.data[CONF_PASSWORD]
                user_input[CONF_TYDOM_PASSWORD] = self.config_entry.data[
                    CONF_TYDOM_PASSWORD
                ]
                user_input[CONF_PIN] = self.config_entry.data[CONF_PIN]
                user_input[CONF_ZONES_HOME] = default_zone_home
                user_input[CONF_ZONES_AWAY] = default_zone_away
                user_input[CONF_ZONES_NIGHT] = default_zone_night

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=user_input,
                    options=self.config_entry.options,
                )
                return self.async_create_entry(title="", data={})

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

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_REFRESH_INTERVAL,
                        description={"suggested_value": default_refresh_interval},
                    ): str,
                    vol.Optional(
                        CONF_ZONES_HOME,
                        description={"suggested_value": default_zone_home},
                    ): str,
                    vol.Optional(
                        CONF_ZONES_AWAY,
                        description={"suggested_value": default_zone_away},
                    ): str,
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
