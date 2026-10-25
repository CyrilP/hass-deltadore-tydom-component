"""Test general gateway HVAC/absence state and wire commands without HA installed."""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components/deltadore_tydom"
spec = importlib.util.spec_from_file_location(
    "home_climate_under_test", COMPONENT / "home_climate.py"
)
assert spec and spec.loader
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)
HomeClimateState = model.HomeClimateState

# Exercise the actual wire methods without importing HA's client/session stack.
tree = ast.parse((COMPONENT / "tydom/tydom_client.py").read_text(encoding="utf-8"))
client_class = next(
    n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TydomClient"
)
methods = {
    "get_home_climate_data",
    "put_home_absence",
    "put_home_hvac_mode",
    "set_general_climate_mode",
}
wire_tree = ast.Module(
    body=[
        ast.ClassDef(
            name="WireClient",
            bases=[],
            keywords=[],
            body=[
                n
                for n in client_class.body
                if isinstance(n, ast.AsyncFunctionDef) and n.name in methods
            ],
            decorator_list=[],
        )
    ],
    type_ignores=[],
)
namespace = {
    "json": json,
    "HVAC_OPTIONS": model.HVAC_OPTIONS,
    "file_mode": False,
    "LOGGER": Mock(),
}
exec(compile(ast.fix_missing_locations(wire_tree), "wire_client", "exec"), namespace)
WireClient = namespace["WireClient"]


def client(*, cooling=False):
    """Build a real state model with only the network transport mocked."""
    wire = WireClient()
    wire.general_climate = HomeClimateState()
    support = ["STOP", "HEATING", "COOLING"] if cooling else ["STOP", "HEATING"]
    wire.general_climate.update("hvac", {"mode": "HEATING", "support": support})
    wire.general_climate.update("absence", {"to": 0})
    wire._cmd_prefix = b""
    wire._unsupported_optional_paths = set()
    wire.send_bytes = AsyncMock()
    wire.send_message = AsyncMock()
    return wire


def requests(wire):
    """Parse transmitted HTTP requests to assert scope and payload together."""
    result = []
    for call in wire.send_bytes.await_args_list:
        head, body = call.args[0].split(b"\r\n\r\n", 1)
        result.append((head.split(b"\r\n")[0].decode(), json.loads(body)))
    return result


class GeneralClimateStateTests(unittest.TestCase):
    """Keep capability discovery, absence and actual mode independent."""

    def test_supported_modes_differ_between_heating_and_reversible_sites(self):
        """A heating-only gateway must not offer Cooling or a writable Mixed mode."""
        self.assertEqual(client().general_climate.options, ["off", "heat", "away"])
        self.assertEqual(
            client(cooling=True).general_climate.options,
            ["off", "heat", "cool", "away"],
        )

    def test_stop_and_absence_lock_zones_but_heating_does_not(self):
        """A general state cannot be inferred from a local setpoint or activity."""
        state = client().general_climate
        self.assertIsNone(state.lock_reason)
        state.update("hvac", {"mode": "STOP"})
        self.assertEqual((state.lock_reason, state.current_option), ("off", "off"))
        state.update("hvac", {"mode": "HEATING"})
        state.update("absence", {"to": -1})
        self.assertEqual(
            (state.lock_reason, state.current_option, state.mode),
            ("absence", "away", "HEATING"),
        )
        state.update("absence", {"to": 0})
        self.assertEqual(state.current_option, "heat")
        self.assertIsNone(state.lock_reason)

    def test_timed_absence_is_preserved(self):
        """A timed absence is a real Away state and retains its gateway deadline."""
        state = client().general_climate
        state.update("absence", {"to": 12345678})
        self.assertEqual(state.current_option, "away")
        self.assertEqual(state.absence_to, 12345678)

    def test_mixed_is_reported_without_inventing_a_heating_direction(self):
        """The app's unknown/mixed aggregate is retained as a read-only state."""
        state = client(cooling=True).general_climate
        state.update("hvac", {"mode": "UNKNOWN"})
        self.assertEqual(state.current_option, "mixed")
        self.assertIn("mixed", state.options)
        state.update("hvac", {"mode": "COOLING"})
        self.assertEqual(state.current_option, "cool")
        self.assertNotIn("mixed", state.options)

    def test_only_real_changes_notify_and_removal_unsubscribes(self):
        """Duplicate replies must not churn all climate states."""
        state = client().general_climate
        notify = Mock()
        state.add_listener(notify)
        state.update("hvac", {"mode": "HEATING"})
        notify.assert_not_called()
        state.update("hvac", {"mode": "STOP"})
        notify.assert_called_once()
        state.remove_listener(notify)
        state.update("hvac", {"mode": "HEATING"})
        notify.assert_called_once()

    def test_malformed_feedback_retains_known_state(self):
        """Partial or invalid replies cannot clear valid capabilities or absence."""
        state = client().general_climate
        state.update("hvac", {"mode": "invalid", "support": None})
        for value in [None, True, "-1", -2]:
            state.update("absence", {"to": value})
        self.assertEqual(state.current_option, "heat")
        self.assertEqual(state.options, ["off", "heat", "away"])

    def test_general_selector_has_all_ten_translations(self):
        """Every shipped locale can render the selector's supported states."""
        files = list((COMPONENT / "translations").glob("*.json"))
        self.assertEqual(len(files), 10)
        for path in files:
            with self.subTest(locale=path.stem):
                data = json.loads(path.read_text(encoding="utf-8"))
                entry = data["entity"]["select"]["general_climate_mode"]
                self.assertTrue(entry["name"])
                self.assertEqual(
                    set(entry["state"]),
                    {"off", "heat", "cool", "away", "fan_only", "dry", "mixed"},
                )


class GeneralClimateWireTests(unittest.IsolatedAsyncioTestCase):
    """Keep explicit general commands separate from every per-zone endpoint."""

    async def test_off_writes_only_the_general_resource(self):
        """No zone temperatures or modes are rewritten when selecting general Off."""
        wire = client()
        await wire.set_general_climate_mode("off")
        self.assertEqual(
            requests(wire), [("PUT /home/hvac/data HTTP/1.1", {"mode": "STOP"})]
        )
        self.assertEqual(wire.general_climate.current_option, "heat")
        wire.general_climate.update("hvac", {"mode": "STOP"})
        self.assertEqual(wire.general_climate.current_option, "off")

    async def test_absence_preserves_direction_and_uses_official_sentinel(self):
        """General Away changes absence, not the heating/cooling season or setpoints."""
        wire = client(cooling=True)
        wire.general_climate.update("hvac", {"mode": "COOLING"})
        await wire.set_general_climate_mode("away")
        self.assertEqual(requests(wire), [("PUT /home/absence HTTP/1.1", {"to": -1})])
        self.assertEqual(wire.general_climate.mode, "COOLING")

    async def test_leaving_absence_clears_it_before_selecting_supported_cooling(self):
        """An explicit general request can lift Away without leaking zone commands."""
        wire = client(cooling=True)
        wire.general_climate.update("absence", {"to": -1})
        await wire.set_general_climate_mode("cool")
        self.assertEqual(
            requests(wire),
            [
                ("PUT /home/absence HTTP/1.1", {"to": 0}),
                ("PUT /home/hvac/data HTTP/1.1", {"mode": "COOLING"}),
            ],
        )
        self.assertEqual(wire.general_climate.current_option, "away")

    async def test_unsupported_cooling_is_rejected_before_network(self):
        """The Site 2 capability list is authoritative for general choices."""
        wire = client()
        with self.assertRaises(ValueError):
            await wire.set_general_climate_mode("cool")
        wire.send_bytes.assert_not_awaited()

    async def test_mixed_does_not_send_a_command(self):
        """A read-only aggregate must not be turned into a fictitious gateway mode."""
        wire = client(cooling=True)
        wire.general_climate.update("hvac", {"mode": "UNKNOWN"})
        await wire.set_general_climate_mode("mixed")
        wire.send_bytes.assert_not_awaited()

    async def test_optional_absence_endpoint_is_not_retried(self):
        """Respect an explicit unsupported-resource result on older gateways."""
        wire = client()
        wire._unsupported_optional_paths.add("/home/absence")
        await wire.get_home_climate_data()
        wire.send_message.assert_awaited_once_with(method="GET", msg="/home/hvac/data")

    async def test_transport_failure_does_not_invent_general_state(self):
        """Failed sends propagate and leave real feedback untouched."""
        wire = client()
        wire.send_bytes.side_effect = RuntimeError("send failed")
        with self.assertRaises(RuntimeError):
            await wire.set_general_climate_mode("off")
        self.assertEqual(wire.general_climate.current_option, "heat")


class GeneralClimateEntityTests(unittest.IsolatedAsyncioTestCase):
    """Verify actual entity placement, choices and feedback subscriptions."""

    @classmethod
    def setUpClass(cls):
        """Reuse the existing minimal HA adapter to import the actual entity."""
        stub_spec = importlib.util.spec_from_file_location(
            "general_climate_entity_stubs",
            ROOT / "tests/test_climate_filpilote_detection.py",
        )
        assert stub_spec and stub_spec.loader
        stubs = importlib.util.module_from_spec(stub_spec)
        stub_spec.loader.exec_module(stubs)
        cls.stubs = stubs

    def entity(self, *, cooling=False):
        """Attach the real select to a gateway with a mocked wire transport."""
        wire = client(cooling=cooling)
        hub = types.SimpleNamespace(
            hub_id="gateway",
            _name="Gateway",
            manufacturer="Delta Dore",
            online=True,
            _tydom_client=wire,
        )
        entity = self.stubs.entities_module.HAGatewayGeneralClimateSelect(hub)
        entity.async_write_ha_state = Mock()
        return entity, wire, hub

    async def test_control_is_on_gateway_and_is_not_a_configuration_entity(self):
        """A general control belongs in Controls on the gateway, not on a zone."""
        entity, wire, hub = self.entity(cooling=True)
        self.assertEqual(
            entity._attr_device_info["identifiers"], {("deltadore_tydom", "gateway")}
        )
        self.assertEqual(entity._attr_unique_id, "gateway_general_climate_mode")
        self.assertIsNone(entity._attr_entity_category)
        self.assertEqual(entity.options, ["off", "heat", "cool", "away"])
        self.assertTrue(entity.available)
        await entity.async_select_option("cool")
        self.assertEqual(
            requests(wire), [("PUT /home/hvac/data HTTP/1.1", {"mode": "COOLING"})]
        )
        hub.online = False
        self.assertFalse(entity.available)

    async def test_companion_controls_keep_the_canonical_gateway_name(self):
        """Late creation of a companion must not rename the gateway to its MAC."""
        hub = types.SimpleNamespace(
            hub_id="Tydom-ABCDEF",
            _name="001A25ABCDEF",
            manufacturer="Delta Dore",
            register_association_control=Mock(),
        )
        controls = [
            self.stubs.entities_module.HAGatewayGeneralClimateSelect(hub),
            self.stubs.entities_module.HAGatewayAssociationCategorySelect(hub),
            self.stubs.entities_module.HAReloadButton(hub, Mock()),
        ]
        for entity in controls:
            with self.subTest(entity=type(entity).__name__):
                self.assertEqual(entity._attr_device_info["name"], "Tydom-ABCDEF")
                self.assertEqual(
                    entity._attr_device_info["identifiers"],
                    {("deltadore_tydom", "Tydom-ABCDEF")},
                )
                self.assertNotIn("name_by_user", entity._attr_device_info)

    async def test_polling_fallback_is_read_only(self):
        """Refresh legacy firmware without sending any heating command."""
        entity, wire, _ = self.entity()
        await entity.async_update()
        self.assertEqual(wire.send_message.await_count, 2)
        wire.send_bytes.assert_not_awaited()

    async def test_feedback_updates_and_unload_removes_listener(self):
        """The UI updates on real general feedback, then releases its subscription."""
        entity, wire, _ = self.entity()
        base = self.stubs._StubEntity
        with (
            patch.object(base, "async_added_to_hass", new=AsyncMock(), create=True),
            patch.object(
                base, "async_will_remove_from_hass", new=AsyncMock(), create=True
            ),
        ):
            await entity.async_added_to_hass()
            wire.general_climate.update("hvac", {"mode": "STOP"})
            entity.async_write_ha_state.assert_called_once()
            self.assertEqual(entity.current_option, "off")
            await entity.async_will_remove_from_hass()
            wire.general_climate.update("hvac", {"mode": "HEATING"})
            entity.async_write_ha_state.assert_called_once()


if __name__ == "__main__":
    unittest.main()
