"""Config flow for Tydom integration."""
from __future__ import annotations
import traceback
import logging
from typing import Any

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant import config_entries, exceptions
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PASSWORD, CONF_PIN
from homeassistant.core import HomeAssistant
from homeassistant.components import dhcp

from .const import DOMAIN  # pylint:disable=unused-import
from .hub import Hub

_LOGGER = logging.getLogger(__name__)

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
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_MAC): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_PIN): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect.
    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    # Validate the data can be used to set up a connection.

    # This is a simple example to show an error in the UI for a short hostname
    # The exceptions are defined at the end of this file, and are used in the
    # `async_step_user` method below.
    if CONF_HOST not in data:
        raise InvalidHost

    if len(data[CONF_HOST]) < 3:
        raise InvalidHost

    if len(data[CONF_MAC]) < 3:
        raise InvalidMacAddress

    if len(data[CONF_PASSWORD]) < 3:
        raise InvalidPassword

    pin = None
    if CONF_PIN in data:
        pin = data[CONF_PIN]

    hub = Hub(hass, data[CONF_HOST], data[CONF_MAC], data[CONF_PASSWORD], pin)
    # The dummy hub provides a `test_connection` method to ensure it's working
    # as expected
    result = hub.test_connection()
    if not result:
        # If there is an error, raise an exception to notify HA that there was a
        # problem. The UI will also show there was a problem
        raise CannotConnect

    # If your PyPI package is not built with async, pass your methods
    # to the executor:
    # await hass.async_add_executor_job(
    #     your_validate_func, data["username"], data["password"]
    # )

    # If you cannot connect:
    # throw CannotConnect
    # If the authentication is wrong:
    # InvalidAuth

    # Return info that you want to store in the config entry.
    # "Title" is what is displayed to the user for this hub device
    # It is stored internally in HA as part of the device config.
    # See `async_step_user` below for how this is used
    return {"title": data[CONF_MAC]}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hello World."""

    VERSION = 1

    # Pick one of the available connection classes in homeassistant/config_entries.py
    # This tells HA if it should be asking for updates, or it'll be notified of updates
    # automatically. This example uses PUSH, as the dummy hub will notify HA of
    # changes.
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        self._discovered_host = None
        self._discovered_mac = None

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        # This goes through the steps to take the user through the setup process.
        # Using this it is possible to update the UI and prompt for additional
        # information. This example provides a single form (built from `DATA_SCHEMA`),
        # and when that has some validated input, it calls `async_create_entry` to
        # actually create the HA config entry. Note the "title" value is returned by
        # `validate_input` above.
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                await self.async_set_unique_id(user_input[CONF_MAC])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidHost:
                # The error string is set here, and should be translated.
                # This example does not currently cover translations, see the
                # comments on `DATA_SCHEMA` for further details.
                # Set the error on the `host` field, not the entire form.
                errors[CONF_HOST] = "cannot_connect"
            except InvalidMacAddress:
                errors[CONF_MAC] = "cannot_connect"
            except InvalidPassword:
                errors[CONF_PASSWORD] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                traceback.print_exc()
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        user_input = user_input or {}
        # If there is no user input or there were errors, show the form again, including any errors that were found with the input.
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
            errors=errors,
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


class InvalidPassword(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid Password."""
