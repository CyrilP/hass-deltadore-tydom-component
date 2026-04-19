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


# ─── Helpers ───────────────────────────────────────────────────────────────────

_TEXT = selector.TextSelectorType.TEXT
_EMAIL = selector.TextSelectorType.EMAIL
_PWD = selector.TextSelectorType.PASSWORD

email_regex = re.compile(
    r"([A-Za-z0-9]+[.-_])*[A-Za-z0-9]+@[A-Za-z0-9-]+(\.[A-Z|a-z]{2,})+"
)
zones_regex = re.compile(r"^$|^[0-8](,[0-8]){0,7}$")


def _text(type_=_TEXT, autocomplete="off"):
    """Create a TextSelector shorthand."""
    return selector.TextSelector(
        selector.TextSelectorConfig(type=type_, autocomplete=autocomplete)
    )


def _refresh_selector():
    """Create the refresh interval NumberSelector."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=1, max=1440, step=1,
            unit_of_measurement="minutes",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _config_mode_schema(user_input=None):
    """Schema for choosing cloud vs manual mode."""
    return vol.Schema({
        vol.Required(
            CONF_CONFIG_MODE,
            default=(user_input or {}).get(CONF_CONFIG_MODE),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(value=CONF_CLOUD_MODE, label=CONF_CLOUD_MODE),
                    selector.SelectOptionDict(value=CONF_MANUAL_MODE, label=CONF_MANUAL_MODE),
                ],
                translation_key=CONF_CONFIG_MODE,
            ),
        ),
    })


def _build_schema(
    cloud: bool,
    user_input: dict | None = None,
    discovered_host: str | None = None,
    discovered_mac: str | None = None,
):
    """Build form schema for cloud or manual setup."""
    ui = user_input or {}
    fields: dict = {
        vol.Required(CONF_HOST, default=ui.get(CONF_HOST, discovered_host)): _text(),
        vol.Required(CONF_MAC, default=ui.get(CONF_MAC, discovered_mac)): _text(),
    }
    if cloud:
        fields[vol.Required(CONF_EMAIL, default=ui.get(CONF_EMAIL))] = _text(_EMAIL, "username")
        fields[vol.Required(CONF_PASSWORD, default=ui.get(CONF_PASSWORD))] = _text(_PWD, "current-password")
    else:
        fields[vol.Required(CONF_TYDOM_PASSWORD, default=ui.get(CONF_TYDOM_PASSWORD))] = _text(_PWD)

    fields[vol.Required(CONF_REFRESH_INTERVAL, default=ui.get(CONF_REFRESH_INTERVAL, "30"))] = _refresh_selector()

    for zone_key in (CONF_ZONES_HOME, CONF_ZONES_AWAY, CONF_ZONES_NIGHT):
        fields[vol.Optional(zone_key, default=ui.get(zone_key, ""))] = _text()
    fields[vol.Optional(CONF_PIN, default=ui.get(CONF_PIN, ""))] = _text(_PWD)

    return vol.Schema(fields)


def host_valid(host) -> bool:
    """Return True if hostname or IP address is valid."""
    try:
        return ipaddress.ip_address(host).version in (4, 6)
    except ValueError:
        disallowed = re.compile(r"[^a-zA-Z\d\-]")
        parts = host.split(".")
        return bool(parts and all(x and not disallowed.search(x) for x in parts))


def email_valid(email) -> bool:
    """Return True if email is valid."""
    return re.fullmatch(email_regex, email) is not None


def zones_valid(zones) -> bool:
    """Return True if zone config is valid."""
    return re.fullmatch(zones_regex, zones) is not None


# ─── Validation ────────────────────────────────────────────────────────────────

# Zone field → exception class
_ZONE_ERRORS = [
    (CONF_ZONES_HOME, InvalidZoneHome := type("InvalidZoneHome", (exceptions.HomeAssistantError,), {})),
    (CONF_ZONES_AWAY, InvalidZoneAway := type("InvalidZoneAway", (exceptions.HomeAssistantError,), {})),
    (CONF_ZONES_NIGHT, InvalidZoneNight := type("InvalidZoneNight", (exceptions.HomeAssistantError,), {})),
]


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


class InvalidRefreshInterval(exceptions.HomeAssistantError):
    """Error to indicate the refresh interval is not valid."""


# Error type → (field_key, error_string) mapping for _handle_errors
_ERROR_MAP: list[tuple[type, str, str]] = [
    (CannotConnect, "base", "cannot_connect"),
    (InvalidHost, CONF_HOST, "invalid_host"),
    (InvalidMacAddress, CONF_MAC, "invalid_macaddress"),
    (InvalidEmail, CONF_EMAIL, "invalid_email"),
    (InvalidRefreshInterval, CONF_REFRESH_INTERVAL, "invalid_refresh_interval"),
    (InvalidZoneHome, CONF_ZONES_HOME, "invalid_zone_config"),
    (InvalidZoneAway, CONF_ZONES_AWAY, "invalid_zone_config"),
    (InvalidZoneNight, CONF_ZONES_NIGHT, "invalid_zone_config"),
    (TydomClientApiClientCommunicationError, "base", "communication_error"),
    (TydomClientApiClientAuthenticationError, "base", "authentication_error"),
    (TydomClientApiClientError, "base", "unknown"),
]


def _handle_errors(exc: Exception, errors: dict, cloud: bool = True) -> None:
    """Map a validation exception to a field error."""
    if isinstance(exc, InvalidPassword):
        errors[CONF_PASSWORD if cloud else CONF_TYDOM_PASSWORD] = "invalid_password"
        return
    for exc_type, field, msg in _ERROR_MAP:
        if isinstance(exc, exc_type):
            errors[field] = msg
            if isinstance(exc, (TydomClientApiClientCommunicationError,
                                TydomClientApiClientAuthenticationError,
                                TydomClientApiClientError)):
                traceback.print_exc()
                LOGGER.exception(msg)
            return
    traceback.print_exc()
    LOGGER.exception("Unexpected exception")
    errors["base"] = "unknown"


async def validate_input(
    hass: HomeAssistant, cloud: bool, data: dict
) -> dict[str, Any]:
    """Validate user input and return cleaned data."""
    if not host_valid(data[CONF_HOST]):
        raise InvalidHost
    if len(data[CONF_MAC]) != 12:
        raise InvalidMacAddress

    for zone_key, error_cls in _ZONE_ERRORS:
        if zone_key in data and not zones_valid(data[zone_key]):
            raise error_cls

    # Normalize refresh interval
    if isinstance(data.get(CONF_REFRESH_INTERVAL), int):
        data[CONF_REFRESH_INTERVAL] = str(data[CONF_REFRESH_INTERVAL])
    try:
        int(data[CONF_REFRESH_INTERVAL])
    except (ValueError, TypeError):
        raise InvalidRefreshInterval

    if cloud:
        if not email_valid(data[CONF_EMAIL]):
            raise InvalidEmail
        if len(data[CONF_PASSWORD]) < 3:
            raise InvalidPassword
        password = await hub.Hub.get_tydom_credentials(
            async_create_clientsession(hass, False),
            data[CONF_EMAIL], data[CONF_PASSWORD], data[CONF_MAC],
        )
        data[CONF_TYDOM_PASSWORD] = password
    else:
        data[CONF_EMAIL] = ""
        data[CONF_PASSWORD] = ""
        if len(data.get(CONF_TYDOM_PASSWORD, "")) < 3:
            raise InvalidPassword

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


async def _test_hub(hass, data) -> None:
    """Create a temporary hub and test credentials."""
    tydom_hub = hub.Hub(
        hass, None, data[CONF_HOST], data[CONF_MAC],
        data[CONF_TYDOM_PASSWORD], "-1", "", "", "", "",
    )
    await tydom_hub.test_credentials()


# ─── Config Flow ───────────────────────────────────────────────────────────────


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
        """Handle the initial step: choose cloud or manual."""
        if user_input is not None:
            if user_input.get(CONF_CONFIG_MODE) == CONF_MANUAL_MODE:
                return await self._async_step_setup(False, step_id="user_manual")
            return await self._async_step_setup(True, step_id="user_cloud")
        return self.async_show_form(
            step_id="user", data_schema=_config_mode_schema(user_input), errors={},
        )

    async def async_step_user_cloud(self, user_input=None) -> config_entries.FlowResult:
        """Handle cloud setup step."""
        return await self._async_step_setup(True, user_input, step_id="user_cloud")

    async def async_step_user_manual(self, user_input=None) -> config_entries.FlowResult:
        """Handle manual setup step."""
        return await self._async_step_setup(False, user_input, step_id="user_manual")

    async def _async_step_setup(
        self,
        cloud: bool,
        user_input: dict | None = None,
        step_id: str = "user",
        discovered_host: str | None = None,
        discovered_mac: str | None = None,
        description_placeholders: dict | None = None,
    ) -> config_entries.FlowResult:
        """Shared logic for cloud/manual setup (initial or discovery)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                validated = await validate_input(self.hass, cloud, user_input)
                await _test_hub(self.hass, validated)
                await self.async_set_unique_id(validated[CONF_MAC])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Tydom-" + validated[CONF_MAC][6:], data=validated
                )
            except AbortFlow:
                raise
            except Exception as exc:
                _handle_errors(exc, errors, cloud)

        schema = _build_schema(
            cloud, user_input,
            discovered_host=discovered_host or self._discovered_host,
            discovered_mac=discovered_mac or self._discovered_mac,
        )
        return self.async_show_form(
            step_id=step_id, data_schema=schema, errors=errors,
            description_placeholders=description_placeholders,
        )

    # ── DHCP discovery ──

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
        """Confirm discovery: choose cloud or manual."""
        if user_input is not None:
            if user_input.get(CONF_CONFIG_MODE) == CONF_MANUAL_MODE:
                return await self.async_step_discovery_confirm_manual()
            return await self.async_step_discovery_confirm_cloud()
        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=_config_mode_schema(user_input),
            errors={},
        )

    async def async_step_discovery_confirm_manual(self, user_input=None):
        """Confirm discovery with manual credentials."""
        return await self._async_step_setup(
            False, user_input,
            step_id="discovery_confirm_manual",
            description_placeholders={"name": self._name or ""},
        )

    async def async_step_discovery_confirm_cloud(self, user_input=None):
        """Confirm discovery with cloud credentials."""
        return await self._async_step_setup(
            True, user_input,
            step_id="discovery_confirm_cloud",
            description_placeholders={"name": self._name or ""},
        )

    # ── Reauth ──

    async def async_step_reauth(self, user_input=None):
        """Handle reauth upon an API authentication error."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Handle reauth confirmation."""
        errors = {}
        existing_entry = self._get_reauth_entry()
        if existing_entry is None:
            return self.async_abort(reason="reauth_entry_not_found")

        cloud_mode = bool(existing_entry.data.get(CONF_EMAIL))

        if user_input is not None:
            try:
                data = {
                    CONF_HOST: user_input.get(CONF_HOST, existing_entry.data[CONF_HOST]),
                    CONF_MAC: existing_entry.data[CONF_MAC],
                    CONF_REFRESH_INTERVAL: existing_entry.data.get(CONF_REFRESH_INTERVAL, "30"),
                    CONF_ZONES_HOME: existing_entry.data.get(CONF_ZONES_HOME, ""),
                    CONF_ZONES_AWAY: existing_entry.data.get(CONF_ZONES_AWAY, ""),
                    CONF_ZONES_NIGHT: existing_entry.data.get(CONF_ZONES_NIGHT, ""),
                    CONF_PIN: existing_entry.data.get(CONF_PIN, ""),
                }
                if cloud_mode:
                    data[CONF_EMAIL] = user_input[CONF_EMAIL]
                    data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
                else:
                    data[CONF_TYDOM_PASSWORD] = user_input[CONF_TYDOM_PASSWORD]

                validated = await validate_input(self.hass, cloud_mode, data)
                await _test_hub(self.hass, validated)

                self.hass.config_entries.async_update_entry(
                    existing_entry, data=validated
                )
                await self.hass.config_entries.async_reload(existing_entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            except Exception as exc:
                _handle_errors(exc, errors, cloud_mode)

        # Build reauth schema
        if cloud_mode:
            schema = vol.Schema({
                vol.Required(CONF_EMAIL, default=existing_entry.data.get(CONF_EMAIL, "")): _text(_EMAIL, "username"),
                vol.Required(CONF_PASSWORD): _text(_PWD, "current-password"),
                vol.Optional(CONF_HOST, default=existing_entry.data.get(CONF_HOST, "")): _text(),
            })
        else:
            schema = vol.Schema({
                vol.Required(CONF_TYDOM_PASSWORD): _text(_PWD),
                vol.Optional(CONF_HOST, default=existing_entry.data.get(CONF_HOST, "")): _text(),
            })

        return self.async_show_form(
            step_id="reauth_confirm", data_schema=schema, errors=errors,
            description_placeholders={"name": existing_entry.title},
        )

    def _get_reauth_entry(self) -> ConfigEntry | None:
        """Get the entry being re-authenticated."""
        entry_id = self.context.get("entry_id")
        return self.hass.config_entries.async_get_entry(entry_id) if entry_id else None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler()


# ─── Options Flow ──────────────────────────────────────────────────────────────


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Option flow to configure zones at any time."""

    @property
    def config_entry(self):
        """Config entry."""
        return self.hass.config_entries.async_get_entry(self.handler)

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage the options."""
        errors: dict[str, str] = {}
        if self.config_entry is None:
            return self.async_abort(reason="config_entry_not_found")

        # Defaults from current config
        defaults = {
            CONF_ZONES_HOME: self.config_entry.data.get(CONF_ZONES_HOME, ""),
            CONF_ZONES_AWAY: self.config_entry.data.get(CONF_ZONES_AWAY, ""),
            CONF_ZONES_NIGHT: self.config_entry.data.get(CONF_ZONES_NIGHT, ""),
            CONF_REFRESH_INTERVAL: self.config_entry.data.get(CONF_REFRESH_INTERVAL, "30"),
        }

        if user_input is not None:
            defaults.update(user_input)
            try:
                # Validate zones
                for zone_key, error_cls in _ZONE_ERRORS:
                    if user_input.get(zone_key) and not zones_valid(user_input[zone_key]):
                        raise error_cls

                # Normalize refresh interval
                if isinstance(user_input.get(CONF_REFRESH_INTERVAL), int):
                    user_input[CONF_REFRESH_INTERVAL] = str(user_input[CONF_REFRESH_INTERVAL])
                    defaults[CONF_REFRESH_INTERVAL] = user_input[CONF_REFRESH_INTERVAL]

                interval = int(user_input[CONF_REFRESH_INTERVAL])
                if interval < 0:
                    raise InvalidRefreshInterval

                updated_data = self.config_entry.data.copy()
                for key in (CONF_ZONES_HOME, CONF_ZONES_AWAY, CONF_ZONES_NIGHT, CONF_REFRESH_INTERVAL):
                    updated_data[key] = defaults[key]

                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=updated_data, options=self.config_entry.options,
                )
                return self.async_create_entry(title="", data={})

            except (ValueError, TypeError):
                errors[CONF_REFRESH_INTERVAL] = "invalid_refresh_interval"
            except InvalidRefreshInterval:
                errors[CONF_REFRESH_INTERVAL] = "invalid_refresh_interval"
            except InvalidZoneHome:
                errors[CONF_ZONES_HOME] = "invalid_zone_config"
                defaults[CONF_ZONES_HOME] = ""
            except InvalidZoneAway:
                errors[CONF_ZONES_AWAY] = "invalid_zone_config"
                defaults[CONF_ZONES_AWAY] = ""
            except InvalidZoneNight:
                errors[CONF_ZONES_NIGHT] = "invalid_zone_config"
                defaults[CONF_ZONES_NIGHT] = ""
            except Exception:
                errors["base"] = "unknown"
                LOGGER.exception("Unexpected error in options flow")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_REFRESH_INTERVAL,
                    description={"suggested_value": defaults[CONF_REFRESH_INTERVAL]},
                ): _refresh_selector(),
                vol.Optional(
                    CONF_ZONES_HOME,
                    description={"suggested_value": defaults[CONF_ZONES_HOME]},
                ): _text(),
                vol.Optional(
                    CONF_ZONES_AWAY,
                    description={"suggested_value": defaults[CONF_ZONES_AWAY]},
                ): _text(),
                vol.Optional(
                    CONF_ZONES_NIGHT,
                    description={"suggested_value": defaults[CONF_ZONES_NIGHT]},
                ): _text(),
            }),
            errors=errors,
        )
