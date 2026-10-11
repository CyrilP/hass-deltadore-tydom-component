"""Read-only access to the gateway's shared TYDOM programming document."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import DOMAIN
from .tydom.tydom_client import TydomClientApiClientCommunicationError


@callback
def async_register_schedule_service(hass: HomeAssistant) -> None:
    """Register the response-only gateway programme action."""

    async def async_get_schedule(call: ServiceCall) -> ServiceResponse:
        """Return a fresh, unfiltered snapshot from the selected gateway."""
        entry_id = call.data["config_entry_id"]
        hub = hass.data.get(DOMAIN, {}).get(entry_id)
        client = getattr(hub, "_tydom_client", None)
        if client is None:
            raise ServiceValidationError(
                "Select a loaded Delta Dore Tydom integration entry"
            )

        try:
            document = await client.get_moments_file_document()
        except TydomClientApiClientCommunicationError as err:
            if "HTTP 404" in str(err):
                raise HomeAssistantError(
                    "The gateway returned HTTP 404 for /moments/file. Its "
                    "programming document is not available through this route. "
                    "This does not prove that the thermostat has no programme; "
                    "check its programming screen in the TYDOM app and include "
                    "the error when reporting the result."
                ) from err
            raise HomeAssistantError(f"Cannot read the TYDOM programme: {err}") from err

        return {
            "config_entry_id": entry_id,
            "scope": "gateway",
            "source": "/moments/file",
            "schedule": document,
        }

    hass.services.async_register(
        DOMAIN,
        "get_schedule",
        async_get_schedule,
        schema=vol.Schema(
            {vol.Required("config_entry_id"): vol.All(str, vol.Length(min=1))}
        ),
        supports_response=SupportsResponse.ONLY,
    )
