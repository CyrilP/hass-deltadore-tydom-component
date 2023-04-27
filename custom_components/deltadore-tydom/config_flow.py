"""Config flow for Tydom integration."""
from __future__ import annotations
import traceback
import ipaddress
import re
from typing import Any

import voluptuous as vol


from homeassistant.helpers.aiohttp_client import async_create_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant import config_entries, exceptions
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_EMAIL, CONF_PASSWORD, CONF_PIN
from homeassistant.core import HomeAssistant
from homeassistant.components import dhcp

from .const import DOMAIN, LOGGER
from . import hub
from .tydom.tydom_client import (
    TydomClientApiClientCommunicationError,
    TydomClientApiClientAuthenticationError,
    TydomClientApiClientError,
)

# This is the schema that used to display the UI to the user. This simple
# schema has a single required host field, but it could include a number of fields
# such as username, password etc. See other components in the HA core code for
# further examples.
# Note the input displayed to the user will be translated. See the
# translations/<lang>.json file and strings.json. See here for further information:
# https://developers.home-assistant.io/docs/config_entries_config_flow_handler/#translations
# At the time of writing I found the translations created by the scaffold didn't
# quite work as documented and always gave me the "Lokalise key references" string
# (in square brackets), rather than the actual translated value. I did not attempt to
# figure this out or look further into it.

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_MAC): cv.string,
        vol.Required(CONF_EMAIL): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_PIN): str,
    }
)


def host_valid(host) -> bool:
    """Return True if hostname or IP address is valid"""
    try:
        if ipaddress.ip_address(host).version == (4 or 6):
            return True
    except ValueError:
        disallowed = re.compile(r"[^a-zA-Z\d\-]")
        return all(x and not disallowed.search(x) for x in host.split("."))


regex = re.compile(r"([A-Za-z0-9]+[.-_])*[A-Za-z0-9]+@[A-Za-z0-9-]+(\.[A-Z|a-z]{2,})+")


def email_valid(email) -> bool:
    """Return True if email is valid"""
    return re.fullmatch(regex, email)


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect.
    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    # Validate the data can be used to set up a connection.

    # This is a simple example to show an error in the UI for a short hostname
    # The exceptions are defined at the end of this file, and are used in the
    # `async_step_user` method below.

    if not host_valid(data[CONF_HOST]):
        raise InvalidHost

    if len(data[CONF_MAC]) != 12:
        raise InvalidMacAddress

    if not email_valid(data[CONF_EMAIL]):
        raise InvalidEmail

    if len(data[CONF_PASSWORD]) < 3:
        raise InvalidPassword

    password = await hub.Hub.get_tydom_credentials(
        async_create_clientsession(hass, False),
        data[CONF_EMAIL],
        data[CONF_PASSWORD],
        data[CONF_MAC],
    )
    data[CONF_PASSWORD] = password

    pin = None
    if CONF_PIN in data:
        pin = data[CONF_PIN]

    return {
        CONF_HOST: data[CONF_HOST],
        CONF_MAC: data[CONF_MAC],
        CONF_PASSWORD: data[CONF_PASSWORD],
        CONF_PIN: pin,
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tydom."""

    VERSION = 1

    # Pick one of the available connection classes in homeassistant/config_entries.py
    # This tells HA if it should be asking for updates, or it'll be notified of updates
    # automatically. This example uses PUSH, as the dummy hub will notify HA of
    # changes.
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        self._discovered_host = None
        self._discovered_mac = None

    async def async_step_import(self, import_config):
        """Import a config entry from configuration.yaml."""
        return await self.async_step_user(import_config)

    async def async_step_user(self, user_input=None) -> config_entries.FlowResult:
        """Handle the initial step."""
        # This goes through the steps to take the user through the setup process.
        # Using this it is possible to update the UI and prompt for additional
        # information. This example provides a single form (built from `DATA_SCHEMA`),
        # and when that has some validated input, it calls `async_create_entry` to
        # actually create the HA config entry. Note the "title" value is returned by
        # `validate_input` above.
        _errors = {}
        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)
                # Ensure it's working as expected

                tydom_hub = hub.Hub(
                    self.hass,
                    user_input[CONF_HOST],
                    user_input[CONF_MAC],
                    user_input[CONF_PASSWORD],
                    None,
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
            except InvalidMacAddress:
                _errors[CONF_MAC] = "invalid_macaddress"
            except InvalidEmail:
                _errors[CONF_MAC] = "invalid_email"
            except InvalidPassword:
                _errors[CONF_PASSWORD] = "invalid_password"
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
                return self.async_create_entry(
                    title="Tydom-" + user_input[CONF_MAC], data=user_input
                )

        user_input = user_input or {}
        # If there is no user input or there were errors, show the form again, including any errors that were found with the input.
        return self.async_show_form(
            step_id="user",
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
                    vol.Optional(CONF_PIN): str,
                }
            ),
            errors=_errors,
        )

    async def async_step_dhcp(self, discovery_info: dhcp.DhcpServiceInfo):
        """Handle the discovery from dhcp."""
        self._discovered_host = discovery_info.ip
        self._discovered_mac = discovery_info.macaddress
        return await self._async_handle_discovery()

    async def _async_handle_discovery(self):
        self.context[CONF_HOST] = self._discovered_host
        self.context[CONF_MAC] = self._discovered_mac
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(self, user_input=None):
        """Confirm discovery."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=user_input.get(CONF_HOST, "")): str,
                    vol.Required(CONF_MAC, default=user_input.get(CONF_MAC, "")): str,
                    vol.Required(
                        CONF_PASSWORD, default=user_input.get(CONF_PASSWORD, "")
                    ): str,
                    vol.Optional(CONF_PIN, default=user_input.get(CONF_PIN, "")): str,
                }
            ),
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
