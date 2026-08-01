"""Tests for metadata-driven TYXIA 1137 climate commands."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock


_MISSING = object()
_original_modules: dict[str, object] = {}


def _module(name: str, **attributes) -> types.ModuleType:
    """Install a minimal module needed to load device code in isolation."""
    _original_modules.setdefault(name, sys.modules.get(name, _MISSING))
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    sys.modules[name] = module
    return module


for package_name in (
    "custom_components",
    "custom_components.deltadore_tydom",
    "custom_components.deltadore_tydom.tydom",
):
    package = _module(package_name)
    package.__path__ = []


def _validate_value(device, attribute_name, value, metadata=None):
    """Validate the numeric range needed by these tests."""
    metadata = metadata or device._metadata
    attribute = metadata.get(attribute_name, {}) if metadata else {}
    numeric_value = float(value)
    if "min" in attribute and numeric_value < attribute["min"]:
        return False, "below minimum"
    if "max" in attribute and numeric_value > attribute["max"]:
        return False, "above maximum"
    return True, None


_module(
    "custom_components.deltadore_tydom.const",
    LOGGER=MagicMock(),
    validate_value_with_metadata=_validate_value,
)

devices_path = (
    Path(__file__).parents[1]
    / "custom_components"
    / "deltadore_tydom"
    / "tydom"
    / "tydom_devices.py"
)
devices_spec = importlib.util.spec_from_file_location(
    "custom_components.deltadore_tydom.tydom.tydom_devices", devices_path
)
assert devices_spec is not None and devices_spec.loader is not None
devices_module = importlib.util.module_from_spec(devices_spec)
_original_modules.setdefault(
    devices_spec.name, sys.modules.get(devices_spec.name, _MISSING)
)
sys.modules[devices_spec.name] = devices_module
devices_spec.loader.exec_module(devices_module)

TydomBoiler = devices_module.TydomBoiler

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


def _metadata() -> dict[str, dict]:
    """Return the relevant metadata captured from the issue #355 device."""
    return {
        "authorization": {
            "permission": "r",
            "enum_values": ["STOP", "HEATING"],
        },
        "comfortMode": {
            "permission": "w",
            "enum_values": ["STOP", "HEATING"],
        },
        "heatSetpoint": {
            "permission": "rw",
            "type": "numeric",
            "min": 5.0,
            "max": 30.0,
        },
        "setpoint": {
            "permission": "rw",
            "type": "numeric",
            "min": 5.0,
            "max": 30.0,
        },
        "overrideSetpoint": {
            "permission": "rw",
            "type": "numeric",
            "min": 5.0,
            "max": 30.0,
        },
        "thermicLevel": {
            "permission": "rw",
            "enum_values": ["STOP", "NO_REGUL", "ANTI_FROST"],
        },
    }


def _boiler(
    metadata: dict[str, dict] | None = None,
    data: dict[str, object] | None = None,
) -> tuple[object, AsyncMock]:
    """Create a boiler with a mocked TYDOM client."""
    client = AsyncMock()
    boiler = TydomBoiler(
        client,
        "1715082810_1715082810",
        "1715082810",
        "TYXIA 1137",
        "boiler",
        "1715082810",
        metadata,
        data,
    )
    return boiler, client


class Tyxia1137ControlTests(IsolatedAsyncioTestCase):
    """Validate the command registers exposed by the TYXIA 1137."""

    async def test_stop_uses_writable_comfort_mode(self) -> None:
        """OFF must use comfortMode rather than the live thermicLevel state."""
        boiler, client = _boiler(_metadata(), {"authorization": "HEATING"})

        await boiler.set_hvac_mode("STOP")

        client.put_devices_data.assert_awaited_once_with(
            "1715082810", "1715082810", "comfortMode", "STOP"
        )
        client.put_home_hvac_mode.assert_not_awaited()

    async def test_heat_uses_writable_comfort_mode(self) -> None:
        """HEAT must use the device command paired with authorization."""
        boiler, client = _boiler(_metadata(), {"authorization": "STOP"})

        await boiler.set_hvac_mode("NORMAL")

        client.put_devices_data.assert_awaited_once_with(
            "1715082810", "1715082810", "comfortMode", "HEATING"
        )
        client.put_home_hvac_mode.assert_not_awaited()

    async def test_manual_temperature_uses_override_setpoint(self) -> None:
        """Manual targets must use the writable override register."""
        boiler, client = _boiler(
            _metadata(), {"authorization": "HEATING", "useMode": "MANUAL"}
        )

        await boiler.set_temperature("20.0")

        client.put_devices_data.assert_awaited_once_with(
            "1715082810", "1715082810", "overrideSetpoint", "20.0"
        )

    async def test_active_override_uses_override_setpoint(self) -> None:
        """An active timed override must continue through its override register."""
        boiler, client = _boiler(
            _metadata(), {"authorization": "HEATING", "useMode": "OVERRIDE"}
        )

        await boiler.set_temperature("20.0")

        client.put_devices_data.assert_awaited_once_with(
            "1715082810", "1715082810", "overrideSetpoint", "20.0"
        )

    async def test_scheduled_temperature_keeps_heat_setpoint(self) -> None:
        """Scheduled heating targets must retain the advertised heat register."""
        boiler, client = _boiler(
            _metadata(), {"authorization": "HEATING", "useMode": "SCHED"}
        )

        await boiler.set_temperature("20.0")

        client.put_devices_data.assert_awaited_once_with(
            "1715082810", "1715082810", "heatSetpoint", "20.0"
        )

    async def test_read_only_override_setpoint_falls_back_to_heat_setpoint(
        self,
    ) -> None:
        """A reported-only override register must not be used as a command."""
        metadata = _metadata()
        metadata["overrideSetpoint"]["permission"] = "r"
        boiler, client = _boiler(
            metadata, {"authorization": "HEATING", "useMode": "MANUAL"}
        )

        await boiler.set_temperature("20.0")

        client.put_devices_data.assert_awaited_once_with(
            "1715082810", "1715082810", "heatSetpoint", "20.0"
        )

    async def test_existing_generic_setpoint_path_is_preserved(self) -> None:
        """Devices without zone authorisation must retain generic setpoint."""
        metadata = {
            "setpoint": {
                "permission": "rw",
                "type": "numeric",
                "min": 5.0,
                "max": 30.0,
            }
        }
        boiler, client = _boiler(metadata, {})

        await boiler.set_temperature("20.0")

        client.put_devices_data.assert_awaited_once_with(
            "1715082810", "1715082810", "setpoint", "20.0"
        )

    async def test_read_only_heat_setpoint_is_not_used_as_a_command(self) -> None:
        """A reported-only heatSetpoint must not replace writable setpoint."""
        metadata = _metadata()
        metadata["heatSetpoint"]["permission"] = "r"
        boiler, client = _boiler(metadata, {"authorization": "HEATING"})

        await boiler.set_temperature("20.0")

        client.put_devices_data.assert_awaited_once_with(
            "1715082810", "1715082810", "setpoint", "20.0"
        )

    async def test_existing_zone_fallback_is_preserved(self) -> None:
        """Zones without a writable comfortMode keep their existing route."""
        metadata = _metadata()
        metadata.pop("comfortMode")
        boiler, client = _boiler(metadata, {"authorization": "HEATING"})

        await boiler.set_hvac_mode("STOP")

        client.put_devices_data.assert_awaited_once_with(
            "1715082810", "1715082810", "thermicLevel", "STOP"
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
