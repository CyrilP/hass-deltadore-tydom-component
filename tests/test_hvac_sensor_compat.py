"""Test the real hub climate factory without a Home Assistant installation."""

import ast
import asyncio
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

from test_device_models import (
    MessageHandler,
    _rothelec_hvac_metadata,
    devices_module,
    handler_module,
)


class FakeSensor:
    """Minimal generic sensor preserving its source and registered attributes."""

    def __init__(self, device, hass, *, set_primary=True):
        """Record the existing generic sensor state."""
        self._device = device
        self._set_primary = set_primary
        self._registered_sensors = ["temperature", "localMode"]


class FakeClimate:
    """Stand-in exposing the fields used by the real hub factory."""

    def __init__(self, device, hass):
        """Record a new climate entity."""
        self._device = device
        self._registered_sensors = []

    def get_sensors(self):
        """Return one new diagnostic for the factory."""
        return ["new-climate-diagnostic"]


def _factory():
    path = Path(__file__).parents[1] / "custom_components/deltadore_tydom/hub.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hub = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Hub"
    )
    method = next(
        node
        for node in hub.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_create_boiler_device"
    )
    setup = next(
        node
        for node in hub.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "setup"
    )
    # The isolated runtime does not need Home Assistant type annotations.
    method.args.args[1].annotation = None
    setup.args.args[1].annotation = None
    module = ast.Module(
        body=[
            ast.ClassDef(
                name="HubFactory",
                bases=[],
                keywords=[],
                body=[method, setup],
                decorator_list=[],
            )
        ],
        type_ignores=[],
    )
    namespace = {
        "LOGGER": MagicMock(),
        "STRUCTURED_LOGGER": MagicMock(),
        "asyncio": asyncio,
        "TydomDevice": devices_module.TydomDevice,
        "TydomBoiler": devices_module.TydomBoiler,
        "HASensor": FakeSensor,
        "HaClimate": FakeClimate,
    }
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace["HubFactory"]


class HubHvacCompatibilityTests(IsolatedAsyncioTestCase):
    """Only the new hvac profile preserves its prior generic primary sensor."""

    def setUp(self):
        """Provide callbacks and registry state for the factory."""
        self.hub = _factory()()
        self.hub._hass = None
        self.hub.ha_devices = {}
        self.hub.add_climate_callback = MagicMock()
        self.hub.add_button_callback = None
        self.hub._add_discovered_entities = MagicMock()

    async def test_new_hvac_climate_keeps_legacy_sensor(self):
        """First discovery retains the existing generic sensor identity."""
        device = MagicMock(device_id="20_10", device_type="hvac", is_area_trv=False)
        await self.hub._create_boiler_device(device)
        climate = self.hub.ha_devices[device.device_id]
        self.hub.add_climate_callback.assert_called_once_with([climate])
        sensors = self.hub._add_discovered_entities.call_args.args[0]
        self.assertIsInstance(sensors[0], FakeSensor)
        self.assertFalse(sensors[0]._set_primary)
        self.assertIs(sensors[0]._device, device)
        self.assertEqual(sensors[1:], ["new-climate-diagnostic"])

    async def test_late_promotion_reuses_existing_entities(self):
        """Late promotion avoids registering a second copy of sensors."""
        device = MagicMock(device_id="20_10", device_type="hvac", is_area_trv=False)
        previous = FakeSensor(device, None)
        self.hub.ha_devices[device.device_id] = previous
        await self.hub._create_boiler_device(device)
        climate = self.hub.ha_devices[device.device_id]
        self.assertFalse(previous._set_primary)
        self.assertEqual(climate._registered_sensors, ["temperature", "localMode"])
        self.hub._add_discovered_entities.assert_called_once_with(
            ["new-climate-diagnostic"]
        )

    async def test_actual_hub_setup_promotes_without_losing_existing_sensor(self):
        """Run the real listener and factory for a metadata-late radiator."""
        uid = "20_10"
        handler_module.device_metadata.clear()
        client = MagicMock()
        previous = await MessageHandler.get_device(
            client, "hvac", uid, "10", "Radiator", "20", {"temperature": 16.96}
        )
        handler_module.device_metadata[uid] = _rothelec_hvac_metadata()
        incoming = await MessageHandler.get_device(
            client, "hvac", uid, "10", "Radiator", "20", {"localMode": "NORMAL"}
        )
        old_sensor = FakeSensor(previous, None)
        self.hub.ha_devices[uid] = old_sensor
        self.hub.devices = {uid: previous}
        self.hub._shutting_down = False
        self.hub.ready = lambda: True
        self.hub._validate_data_consistency = AsyncMock()
        self.hub._refresh_group_members = MagicMock()
        self.hub.create_ha_device = self.hub._create_boiler_device
        self.hub._tydom_client = MagicMock()

        async def consume():
            if self.hub.devices[uid] is previous:
                return [incoming]
            self.hub._shutting_down = True
            return None

        self.hub._tydom_client.consume_messages = consume
        await self.hub.setup(None)
        self.assertIs(self.hub.devices[uid], incoming)
        self.assertIs(self.hub.ha_devices[uid]._device, incoming)
        self.assertFalse(old_sensor._set_primary)
        self.assertEqual(incoming.temperature, 16.96)
        self.assertEqual(old_sensor._device.localMode, "NORMAL")
        self.hub._add_discovered_entities.assert_called_once_with(
            ["new-climate-diagnostic"]
        )

    async def test_typass_climate_does_not_gain_generic_primary(self):
        """Existing boiler devices retain their established entity set."""
        device = MagicMock(device_id="20_10", device_type="boiler", is_area_trv=False)
        await self.hub._create_boiler_device(device)
        self.hub._add_discovered_entities.assert_called_once_with(
            ["new-climate-diagnostic"]
        )
