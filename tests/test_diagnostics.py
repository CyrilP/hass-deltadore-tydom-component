"""Tests for the TYDOM integration diagnostics dump.

Home Assistant is not a test dependency of this project, so the diagnostics
module is loaded in isolation with the handful of Home Assistant symbols it
imports stubbed into ``sys.modules`` (the same approach as the other helper
tests in this suite).
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
from unittest import TestCase

REDACTED = "**REDACTED**"


def _async_redact_data(data, to_redact):
    """Minimal faithful re-implementation of Home Assistant's redactor."""
    if not isinstance(data, (dict, list)):
        return data
    if isinstance(data, list):
        return [_async_redact_data(item, to_redact) for item in data]
    redacted = dict(data)
    for key, value in redacted.items():
        if value is None or value == "":
            continue
        if key in to_redact:
            redacted[key] = REDACTED
        elif isinstance(value, dict):
            redacted[key] = _async_redact_data(value, to_redact)
        elif isinstance(value, list):
            redacted[key] = [_async_redact_data(item, to_redact) for item in value]
    return redacted


def _module(name: str, **attributes) -> types.ModuleType:
    """Install a minimal module so the diagnostics helper can import it."""
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    sys.modules[name] = module
    return module


# Stub the Home Assistant modules touched at import time.
_module("homeassistant")
helpers = _module("homeassistant.helpers")
helpers.__path__ = []
_module(
    "homeassistant.helpers.redact",
    REDACTED=REDACTED,
    async_redact_data=_async_redact_data,
)
_module("homeassistant.helpers.device_registry", DeviceEntry=object)
_module("homeassistant.config_entries", ConfigEntry=object)
_module("homeassistant.core", HomeAssistant=object)
_module(
    "homeassistant.const",
    CONF_EMAIL="email",
    CONF_HOST="host",
    CONF_MAC="mac",
    CONF_PASSWORD="password",
    CONF_PIN="pin",
)

# Stub the integration package and its const module.
for package_name in ("custom_components", "custom_components.deltadore_tydom"):
    package = _module(package_name)
    package.__path__ = []
_module(
    "custom_components.deltadore_tydom.const",
    DOMAIN="deltadore_tydom",
    CONF_TYDOM_PASSWORD="tydom_password",
)

_root = Path(__file__).parents[1]
_spec = importlib.util.spec_from_file_location(
    "custom_components.deltadore_tydom.diagnostics",
    _root / "custom_components" / "deltadore_tydom" / "diagnostics.py",
)
assert _spec is not None and _spec.loader is not None
diagnostics = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = diagnostics
_spec.loader.exec_module(diagnostics)


class FakeDevice:
    """Minimal stand-in for a parsed TYDOM device."""

    def __init__(
        self,
        uid: str,
        device_id,
        name: str,
        device_type: str,
        endpoint,
        metadata: dict | None,
        data: dict | None = None,
    ) -> None:
        """Mirror TydomDevice's public API and raw data attributes."""
        self._uid = uid
        self._id = device_id
        self._name = name
        self._type = device_type
        self._endpoint = endpoint
        self._metadata = metadata
        # Private attributes must never leak into the dump.
        self._tydom_client = object()
        self._callbacks = set()
        for key, value in (data or {}).items():
            setattr(self, key, value)

    @property
    def device_id(self):
        """Return the device unique id."""
        return self._uid

    @property
    def device_name(self):
        """Return the device name."""
        return self._name

    @property
    def device_type(self):
        """Return the device type."""
        return self._type

    @property
    def device_endpoint(self):
        """Return the device endpoint."""
        return self._endpoint

    @property
    def registry_device_id(self):
        """Return the Home Assistant registry device id."""
        return str(getattr(self, "_registry_device_id", self._uid))


class FakeHub:
    """Minimal stand-in for the integration hub."""

    def __init__(self, devices, *, online=True, remote_mode=False) -> None:
        """Store devices keyed by id and a fake client."""
        self.devices = {device.device_id: device for device in devices}
        self.online = online
        self._tydom_client = types.SimpleNamespace(_remote_mode=remote_mode)


class FakeEntry:
    """Minimal config entry."""

    def __init__(self, data, options=None) -> None:
        """Store entry data and options."""
        self.entry_id = "entry"
        self.title = "Delta Dore TYDOM"
        self.version = 1
        self.data = data
        self.options = options or {}


class FakeDeviceEntry:
    """Minimal device-registry entry."""

    def __init__(self, identifiers) -> None:
        """Store registry identifiers and descriptive fields."""
        self.identifiers = identifiers
        self.name = "PAC"
        self.model = "Tybox Home RF 210"
        self.sw_version = None


def _hass(hub) -> types.SimpleNamespace:
    return types.SimpleNamespace(data={"deltadore_tydom": {"entry": hub}})


def _boiler() -> FakeDevice:
    return FakeDevice(
        uid="1791093691_1791093691",
        device_id=1791093691,
        name="PAC",
        device_type="boiler",
        endpoint=1791093691,
        metadata={"setpoint": {"type": "numeric", "unit": "degC"}},
        data={"setpoint": 19.0, "uid": "10e45248f4d24ef4b60eda55e2434046"},
    )


def _tywatt() -> FakeDevice:
    return FakeDevice(
        uid="55_55",
        device_id=55,
        name="TYWATT",
        device_type="conso",
        endpoint=55,
        metadata={"energyIndex": {"type": "numeric", "unit": "Wh"}},
        data={"energyIndex": 1234, "energyDistrib": [1, 2, 3]},
    )


def _gateway() -> FakeDevice:
    return FakeDevice(
        uid="001A25ABCDEF",
        device_id="001A25ABCDEF",
        name="Tydom",
        device_type="gateway",
        endpoint="001A25ABCDEF",
        metadata=None,
        data={"productName": "TYDOM 1.0"},
    )


class MaskIdentifierTests(TestCase):
    """The gateway MAC is masked while decimal endpoint ids survive."""

    def test_masks_mac_like_identifier(self) -> None:
        """A bare 12-hex gateway MAC is redacted."""
        self.assertEqual(diagnostics._mask_identifier("001A25ABCDEF"), REDACTED)

    def test_keeps_decimal_endpoint_id(self) -> None:
        """Decimal radio ids used to cross-reference endpoints are kept."""
        self.assertEqual(diagnostics._mask_identifier(1791093691), 1791093691)
        self.assertEqual(
            diagnostics._mask_identifier("1791093691_1791093691"),
            "1791093691_1791093691",
        )

    def test_keeps_none(self) -> None:
        """A missing identifier stays None."""
        self.assertIsNone(diagnostics._mask_identifier(None))


class DeviceSnapshotTests(TestCase):
    """A device snapshot exposes cmeta/data but hides serial-like values."""

    def test_exposes_cmetadata_and_data(self) -> None:
        """Expose cmeta and raw data, including TYWATT energy registers."""
        snapshot = diagnostics._device_snapshot(_tywatt())
        self.assertIn("energyIndex", snapshot["cmetadata"])
        self.assertEqual(snapshot["data"]["energyIndex"], 1234)
        self.assertEqual(snapshot["data"]["energyDistrib"], [1, 2, 3])
        self.assertEqual(snapshot["class"], "FakeDevice")

    def test_redacts_hardware_uid(self) -> None:
        """The per-product hardware UID (serial equivalent) is redacted."""
        snapshot = diagnostics._device_snapshot(_boiler())
        self.assertEqual(snapshot["data"]["uid"], REDACTED)

    def test_omits_private_attributes(self) -> None:
        """Private attributes never leak into the data payload."""
        snapshot = diagnostics._device_snapshot(_boiler())
        for leaked in ("_tydom_client", "_callbacks", "_metadata"):
            self.assertNotIn(leaked, snapshot["data"])

    def test_masks_gateway_identifiers(self) -> None:
        """A gateway whose id is its MAC is fully masked."""
        snapshot = diagnostics._device_snapshot(_gateway())
        self.assertEqual(snapshot["device_id"], REDACTED)
        self.assertEqual(snapshot["id"], REDACTED)
        self.assertEqual(snapshot["registry_device_id"], REDACTED)
        self.assertEqual(snapshot["endpoint"], REDACTED)


class ConfigEntryDiagnosticsTests(TestCase):
    """The config-entry dump redacts credentials and lists devices."""

    def test_redacts_config_and_lists_devices(self) -> None:
        """Credentials are redacted and every device is listed."""
        hub = FakeHub([_boiler(), _tywatt()], remote_mode=True)
        entry = FakeEntry(
            {
                "host": "192.168.1.10",
                "mac": "001A25ABCDEF",
                "email": "user@example.com",
                "password": "secret",
                "tydom_password": "localsecret",
                "pin": "1234",
                "refresh_interval": "30",
            }
        )
        result = asyncio.run(
            diagnostics.async_get_config_entry_diagnostics(_hass(hub), entry)
        )
        for key in ("host", "mac", "email", "password", "tydom_password", "pin"):
            self.assertEqual(result["entry"]["data"][key], REDACTED)
        self.assertEqual(result["entry"]["data"]["refresh_interval"], "30")
        self.assertEqual(result["hub"]["device_count"], 2)
        self.assertTrue(result["hub"]["remote_mode"])
        self.assertEqual(len(result["devices"]), 2)

    def test_handles_missing_hub(self) -> None:
        """A not-yet-set-up entry still returns a redacted dump."""
        entry = FakeEntry({"host": "192.168.1.10"})
        hass = types.SimpleNamespace(data={})
        result = asyncio.run(
            diagnostics.async_get_config_entry_diagnostics(hass, entry)
        )
        self.assertIsNone(result["hub"])
        self.assertEqual(result["devices"], [])
        self.assertEqual(result["entry"]["data"]["host"], REDACTED)


class DeviceDiagnosticsTests(TestCase):
    """The per-device dump returns only the targeted TYDOM device."""

    def test_returns_only_matching_device(self) -> None:
        """Only the device matching the registry identifier is dumped."""
        hub = FakeHub([_boiler(), _tywatt()])
        entry = FakeEntry({})
        device_entry = FakeDeviceEntry(
            {("deltadore_tydom", "1791093691_1791093691")}
        )
        result = asyncio.run(
            diagnostics.async_get_device_diagnostics(_hass(hub), entry, device_entry)
        )
        self.assertEqual(len(result["tydom_devices"]), 1)
        self.assertEqual(result["tydom_devices"][0]["name"], "PAC")
        self.assertEqual(result["device"]["model"], "Tybox Home RF 210")

    def test_ignores_foreign_identifiers(self) -> None:
        """Identifiers from another integration match nothing."""
        hub = FakeHub([_boiler()])
        entry = FakeEntry({})
        device_entry = FakeDeviceEntry({("another_domain", "1791093691_1791093691")})
        result = asyncio.run(
            diagnostics.async_get_device_diagnostics(_hass(hub), entry, device_entry)
        )
        self.assertEqual(result["tydom_devices"], [])
