"""Tests for the read-only, response-only TYDOM programme action."""

from enum import Enum
import importlib.util
import json
from pathlib import Path
import sys
import types
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

import voluptuous as vol

_MISSING = object()
_original_modules: dict[str, object] = {}


def _module(name: str, **attributes) -> types.ModuleType:
    """Install only the modules required for an isolated service test."""
    _original_modules.setdefault(name, sys.modules.get(name, _MISSING))
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


class _HomeAssistantError(Exception):
    """Stand-in for errors surfaced by Home Assistant actions."""


class _ServiceValidationError(_HomeAssistantError):
    """Stand-in for invalid action targets."""


class _CommunicationError(Exception):
    """Stand-in for rejected or timed-out gateway requests."""


class _SupportsResponse(Enum):
    """Minimum response capability used by the service."""

    ONLY = "only"


for package_name in (
    "custom_components",
    "custom_components.deltadore_tydom",
    "custom_components.deltadore_tydom.tydom",
    "homeassistant",
):
    package = _module(package_name)
    package.__path__ = []

_module(
    "homeassistant.core",
    HomeAssistant=object,
    ServiceCall=types.SimpleNamespace,
    ServiceResponse=dict,
    SupportsResponse=_SupportsResponse,
    callback=lambda function: function,
)
_module(
    "homeassistant.exceptions",
    HomeAssistantError=_HomeAssistantError,
    ServiceValidationError=_ServiceValidationError,
)
_module("custom_components.deltadore_tydom.const", DOMAIN="deltadore_tydom")
_module(
    "custom_components.deltadore_tydom.tydom.tydom_client",
    TydomClientApiClientCommunicationError=_CommunicationError,
)

root = Path(__file__).parents[1]
module_name = "custom_components.deltadore_tydom.schedule"
spec = importlib.util.spec_from_file_location(
    module_name, root / "custom_components" / "deltadore_tydom" / "schedule.py"
)
assert spec is not None and spec.loader is not None
schedule_module = importlib.util.module_from_spec(spec)
_original_modules.setdefault(module_name, sys.modules.get(module_name, _MISSING))
sys.modules[module_name] = schedule_module
try:
    spec.loader.exec_module(schedule_module)
finally:
    for name, original in _original_modules.items():
        if original is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


class TestScheduleService(IsolatedAsyncioTestCase):
    """Verify selection, safety and response semantics of the action."""

    def setUp(self) -> None:
        """Register a handler with two independently configured gateways."""
        self.first = types.SimpleNamespace(get_moments_file_document=AsyncMock())
        self.second = types.SimpleNamespace(
            get_moments_file_document=AsyncMock(return_value={"mom": []})
        )
        self.hass = types.SimpleNamespace(
            data={
                "deltadore_tydom": {
                    "first": types.SimpleNamespace(_tydom_client=self.first),
                    "second": types.SimpleNamespace(_tydom_client=self.second),
                }
            },
            services=types.SimpleNamespace(async_register=MagicMock()),
        )
        schedule_module.async_register_schedule_service(self.hass)
        registration = self.hass.services.async_register.call_args
        self.handler = registration.args[2]
        self.schema = registration.kwargs["schema"]

    async def _read(self, entry_id: str = "second") -> dict:
        return await self.handler(
            types.SimpleNamespace(data=self.schema({"config_entry_id": entry_id}))
        )

    async def test_requires_a_response_variable(self) -> None:
        """Register only a response-producing get action, never a writer."""
        registration = self.hass.services.async_register.call_args
        self.assertEqual(registration.args[:2], ("deltadore_tydom", "get_schedule"))
        self.assertIs(registration.kwargs["supports_response"], _SupportsResponse.ONLY)
        self.hass.services.async_register.assert_called_once()

    async def test_reads_only_selected_gateway_and_returns_scope(self) -> None:
        """A multi-gateway installation must never silently use the first hub."""
        result = await self._read()
        self.assertEqual(
            result,
            {
                "config_entry_id": "second",
                "scope": "gateway",
                "source": "/moments/file",
                "schedule": {"mom": []},
            },
        )
        self.second.get_moments_file_document.assert_awaited_once_with()
        self.first.get_moments_file_document.assert_not_awaited()

    async def test_preserves_unfiltered_shared_references(self) -> None:
        """Shared actions and unknown fields are not discarded or invented."""
        document = {
            "apiVersion": "1",
            "mom": [{"devId": 12, "epId": 13, "grpAct": [{"id": 14}]}],
            "rdv": [{"id": 15, "rRule": "FREQ=WEEKLY;BYDAY=MO,WE"}],
            "unknown": {"future": True},
        }
        self.second.get_moments_file_document.return_value = document
        result = await self._read()
        self.assertEqual(result["schedule"], document)

    async def test_each_call_reads_fresh_gateway_data(self) -> None:
        """No cached snapshot may hide a subsequent app programme edit."""
        self.second.get_moments_file_document.side_effect = [
            {"mom": []},
            {"mom": [{"id": 16}]},
        ]
        first = await self._read()
        second = await self._read()
        self.assertNotEqual(first["schedule"], second["schedule"])
        self.assertEqual(self.second.get_moments_file_document.await_count, 2)

    async def test_unloaded_entry_is_rejected(self) -> None:
        """An absent or unloaded gateway must not lead to a different target."""
        for data in ({}, {"deltadore_tydom": {"second": object()}}):
            with self.subTest(data=data):
                self.hass.data = data
                with self.assertRaises(_ServiceValidationError):
                    await self._read()
        self.first.get_moments_file_document.assert_not_awaited()
        self.second.get_moments_file_document.assert_not_awaited()

    async def test_schema_rejects_missing_invalid_and_write_fields(self) -> None:
        """Neither an implicit gateway nor an unexpected write payload is accepted."""
        for data in (
            {},
            {"config_entry_id": ""},
            {"config_entry_id": 1},
            {"config_entry_id": "second", "schedule": {"MONDAY": []}},
            {"config_entry_id": "second", "entity_id": "climate.other"},
        ):
            with self.subTest(data=data), self.assertRaises(vol.Invalid):
                self.schema(data)

    async def test_missing_document_is_not_reported_as_an_empty_programme(self) -> None:
        """A 404 is surfaced with a cautious explanation, without fallback writes."""
        self.second.get_moments_file_document.side_effect = _CommunicationError(
            "HTTP 404: Not Found"
        )
        with self.assertRaisesRegex(_HomeAssistantError, "does not prove"):
            await self._read()
        self.second.get_moments_file_document.assert_awaited_once_with()

    async def test_other_rejections_and_timeouts_are_reported(self) -> None:
        """Do not conceal a failed request behind an apparently valid response."""
        for error in ("HTTP 403: Forbidden", "Timeout", "No JSON document"):
            with self.subTest(error=error):
                self.second.get_moments_file_document.side_effect = _CommunicationError(
                    error
                )
                with self.assertRaisesRegex(_HomeAssistantError, error):
                    await self._read()

    async def test_service_translations_cover_the_same_field(self) -> None:
        """Both maintained README languages expose the gateway selector label."""
        for language in ("en", "fr"):
            with self.subTest(language=language):
                translation = json.loads(
                    (
                        root
                        / "custom_components"
                        / "deltadore_tydom"
                        / "translations"
                        / f"{language}.json"
                    ).read_text(encoding="utf-8")
                )["services"]["get_schedule"]
                self.assertEqual(set(translation["fields"]), {"config_entry_id"})
                self.assertTrue(translation["name"])
