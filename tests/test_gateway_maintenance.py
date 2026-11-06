"""Tests for the gateway maintenance features (LED, restart, firmware status).

Payloads are those returned by a TYDOM HOME (firmware 03.24.29).
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import sys
import types
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "deltadore_tydom"

_MISSING = object()
_original_modules: dict[str, object] = {}


def _module(name: str, **attributes) -> types.ModuleType:
    """Install a minimal module, remembering the original for restoration."""
    _original_modules.setdefault(name, sys.modules.get(name, _MISSING))
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    sys.modules[name] = module
    return module


def _load(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    _original_modules.setdefault(name, sys.modules.get(name, _MISSING))
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _Entity:
    """Tiny stand-in for homeassistant.helpers.entity.Entity."""

    async def async_added_to_hass(self) -> None:
        return None

    async def async_will_remove_from_hass(self) -> None:
        return None

    def async_write_ha_state(self) -> None:
        return None


def _entity_base(name: str) -> type:
    return type(name, (), {})


for package_name in (
    "custom_components",
    "custom_components.deltadore_tydom",
    "custom_components.deltadore_tydom.tydom",
):
    _module(package_name).__path__ = []

_module(
    "custom_components.deltadore_tydom.const",
    LOGGER=MagicMock(),
    DOMAIN="deltadore_tydom",
    validate_value_with_metadata=MagicMock(return_value=(True, None)),
)
_named: list[tuple[str, dict | None]] = []
_module(
    "custom_components.deltadore_tydom.entity_names",
    set_entity_name=lambda entity, key, placeholders=None, **_: setattr(
        entity, "_test_name", (key, placeholders)
    ),
)
_module("homeassistant")
_module(
    "homeassistant.components.binary_sensor",
    BinarySensorDeviceClass=SimpleNamespace(
        CONNECTIVITY="connectivity", UPDATE="update"
    ),
    BinarySensorEntity=_entity_base("BinarySensorEntity"),
)
_module(
    "homeassistant.components.button",
    ButtonDeviceClass=SimpleNamespace(RESTART="restart"),
    ButtonEntity=_entity_base("ButtonEntity"),
)
_module("homeassistant.components.select", SelectEntity=_entity_base("SelectEntity"))
_module("homeassistant.components.switch", SwitchEntity=_entity_base("SwitchEntity"))
_module(
    "homeassistant.components.update",
    UpdateDeviceClass=SimpleNamespace(FIRMWARE="firmware"),
    UpdateEntity=_entity_base("UpdateEntity"),
    UpdateEntityFeature=SimpleNamespace(INSTALL=1),
)
_module(
    "homeassistant.const",
    EntityCategory=SimpleNamespace(CONFIG="config", DIAGNOSTIC="diagnostic"),
)
_module("homeassistant.helpers.entity", DeviceInfo=dict, Entity=_Entity)

devices_module = _load(
    "custom_components.deltadore_tydom.tydom.tydom_devices",
    COMPONENT / "tydom" / "tydom_devices.py",
)
handler_module = _load(
    "custom_components.deltadore_tydom.tydom.MessageHandler",
    COMPONENT / "tydom" / "MessageHandler.py",
)
entities_module = _load(
    "custom_components.deltadore_tydom.gateway_entities",
    COMPONENT / "gateway_entities.py",
)

for _name, _original in _original_modules.items():
    if _original is _MISSING:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _original

Tydom = devices_module.Tydom
MessageHandler = handler_module.MessageHandler

# --- Payloads captured on a TYDOM HOME -------------------------------------

LED = {"color": {"OK": "white", "local": "orange", "error": "red"}, "power": 100}
UPDATE_STATUS = {
    "mainId": "6700116",
    "versionHW": "00.00.01",
    "downloadProcess": "idle",
    "checkProcess": "idle",
    "updateAvailable": False,
    "installStatus": "idle",
    "setup": {"mode": "MANUAL"},
    "running": [
        {"target": "recovery", "plan": "25170012", "versionSW": "01.01.06"},
        {"target": "appli", "plan": "25170010", "versionSW": "03.24.29"},
        {"target": "x3d", "plan": "25170020", "versionSW": "01.08.04"},
        {"target": "zigbee", "plan": "25170030", "versionSW": "01.01.00"},
    ],
    "downloaded": [
        {"target": "appli", "plan": "25170010", "versionSW": None},
    ],
    "wish": [
        {"target": "appli", "plan": "25170010", "versionSW": None},
    ],
}
DEVICES_UPDATE = {
    "updateAvailable": False,
    "nbFwFreeSlots": 1,
    "setup": {"mode": "AUTO"},
    "fwList": [],
}
NETWORK = {"ipStatus": "OK", "internetAccessStatus": "OK", "phyModel": "KSZ8081"}


def _gateway(**data) -> Tydom:
    client = SimpleNamespace(
        put_gateway_led=AsyncMock(),
        reboot_gateway=AsyncMock(),
        put_gateway_update_setup=AsyncMock(),
        put_devices_update=AsyncMock(),
        update_firmware=AsyncMock(),
        get_gateway_update_status=AsyncMock(),
    )
    return Tydom(client, "gw", "gw", "gw", "Tydom Gateway", None, None, data)


class GatewayLedTests(IsolatedAsyncioTestCase):
    """Status LED behaviour of the gateway device."""

    def test_reports_the_connected_state_colour(self) -> None:
        """Reports the connected state colour."""
        gateway = _gateway(gateway_led=LED)
        self.assertEqual("white", gateway.led_color)
        self.assertTrue(gateway.led_is_on)

    def test_unknown_until_the_gateway_answers(self) -> None:
        """Unknown until the gateway answers."""
        gateway = _gateway()
        self.assertIsNone(gateway.led_config)
        self.assertIsNone(gateway.led_is_on)
        with self.assertRaises(ValueError):
            gateway.led_document("off")

    async def test_off_only_changes_the_connected_colour(self) -> None:
        """Off only changes the connected colour."""
        gateway = _gateway(gateway_led=LED)
        await gateway.async_turn_led_off()
        gateway._tydom_client.put_gateway_led.assert_awaited_once_with(
            {"color": {"OK": "off", "local": "orange", "error": "red"}, "power": 100}
        )
        self.assertEqual("white", LED["color"]["OK"], "input must not be mutated")

    async def test_on_restores_the_previous_colour(self) -> None:
        """On restores the previous colour."""
        gateway = _gateway(gateway_led={"color": {"OK": "purple"}, "power": 100})
        await gateway.async_turn_led_off()
        gateway.gateway_led = {"color": {"OK": "off"}, "power": 100}
        await gateway.async_turn_led_on()
        sent = gateway._tydom_client.put_gateway_led.await_args.args[0]
        self.assertEqual("purple", sent["color"]["OK"])

    async def test_on_defaults_to_white(self) -> None:
        """On defaults to white."""
        gateway = _gateway(gateway_led={"color": {"OK": "off"}, "power": 100})
        self.assertFalse(gateway.led_is_on)
        await gateway.async_turn_led_on()
        sent = gateway._tydom_client.put_gateway_led.await_args.args[0]
        self.assertEqual("white", sent["color"]["OK"])

    async def test_rejects_unknown_colours(self) -> None:
        """Rejects unknown colours."""
        gateway = _gateway(gateway_led=LED)
        with self.assertRaises(ValueError):
            await gateway.async_set_led_color("rainbow")
        gateway._tydom_client.put_gateway_led.assert_not_awaited()

    async def test_cellular_gateways_use_the_combined_key(self) -> None:
        """Cellular gateways use the combined key."""
        gateway = _gateway(
            gateway_led={"color": {"IpOk LteOk": "white", "error": "red"}, "power": 50}
        )
        await gateway.async_set_led_color("green")
        sent = gateway._tydom_client.put_gateway_led.await_args.args[0]
        self.assertEqual({"IpOk LteOk": "green", "error": "red"}, sent["color"])


class GatewayFirmwareStatusTests(IsolatedAsyncioTestCase):
    """Detailed gateway firmware status."""

    def test_component_versions_and_mode(self) -> None:
        """Component versions and mode."""
        gateway = _gateway(gateway_update_status=UPDATE_STATUS)
        self.assertEqual(
            {
                "recovery": "01.01.06",
                "appli": "03.24.29",
                "x3d": "01.08.04",
                "zigbee": "01.01.00",
            },
            gateway.running_firmware_versions,
        )
        self.assertIsNone(gateway.target_firmware_version)
        self.assertFalse(gateway.update_in_progress)
        self.assertEqual("MANUAL", gateway.update_mode)

    def test_pending_application_version_and_progress(self) -> None:
        """Pending application version and progress."""
        status = dict(
            UPDATE_STATUS,
            updateAvailable=True,
            downloadProcess="running",
            wish=[{"target": "appli", "plan": "25170010", "versionSW": "03.25.01"}],
        )
        gateway = _gateway(gateway_update_status=status)
        self.assertEqual("03.25.01", gateway.target_firmware_version)
        self.assertTrue(gateway.update_in_progress)

    def test_setup_endpoint_overrides_the_status_copy(self) -> None:
        """Setup endpoint overrides the status copy."""
        gateway = _gateway(
            gateway_update_status=UPDATE_STATUS, gateway_update_setup={"mode": "AUTO"}
        )
        self.assertEqual("AUTO", gateway.update_mode)

    async def test_mode_change_is_validated(self) -> None:
        """Mode change is validated."""
        gateway = _gateway(gateway_update_status=UPDATE_STATUS)
        await gateway.async_set_update_mode("AUTO")
        gateway._tydom_client.put_gateway_update_setup.assert_awaited_once_with("AUTO")
        with self.assertRaises(ValueError):
            await gateway.async_set_update_mode("SOMETIMES")

    async def test_install_refreshes_the_status(self) -> None:
        """Install refreshes the status."""
        gateway = _gateway()
        await gateway.async_trigger_firmware_update()
        gateway._tydom_client.update_firmware.assert_awaited_once()
        gateway._tydom_client.get_gateway_update_status.assert_awaited_once()


class RadioFirmwareTests(IsolatedAsyncioTestCase):
    """Radio product firmware deployed by the gateway."""

    FIRMWARE = {
        "fwId": "fw-42",
        "modelId": "TYXIA 5731",
        "running": "01.00.00",
        "wish": "01.02.00",
        "status": "available",
    }

    def test_empty_list_from_a_real_gateway(self) -> None:
        """Empty list from a real gateway."""
        gateway = _gateway(gateway_devices_update_status=DEVICES_UPDATE)
        self.assertEqual({}, gateway.device_firmwares)

    async def test_install_sends_the_official_payload(self) -> None:
        """Install sends the official payload."""
        gateway = _gateway(
            gateway_devices_update_status=dict(DEVICES_UPDATE, fwList=[self.FIRMWARE])
        )
        await gateway.async_install_device_firmware("fw-42")
        gateway._tydom_client.put_devices_update.assert_awaited_once_with(
            [{"fwId": "fw-42", "modelId": "TYXIA 5731"}]
        )

    async def test_unknown_firmware_is_refused(self) -> None:
        """Unknown firmware is refused."""
        gateway = _gateway(gateway_devices_update_status=DEVICES_UPDATE)
        with self.assertRaises(ValueError):
            await gateway.async_install_device_firmware("nope")


class MessageRoutingTests(IsolatedAsyncioTestCase):
    """Maintenance replies are attached to the gateway device."""

    def _handler(self) -> MessageHandler:
        handler = MessageHandler.__new__(MessageHandler)
        handler.tydom_client = SimpleNamespace(id="001A25000000")
        return handler

    async def test_resource_becomes_a_gateway_fragment(self) -> None:
        """Resource becomes a gateway fragment."""
        devices = await self._handler().parse_gateway_resource("gateway_led", LED, "1")
        self.assertEqual(1, len(devices))
        self.assertIsInstance(devices[0], Tydom)
        self.assertEqual("001A25000000", devices[0].device_id)
        self.assertEqual(LED, devices[0].gateway_led)
        self.assertFalse(hasattr(devices[0], "mainVersionSW"))

    async def test_empty_or_html_payloads_are_ignored(self) -> None:
        """Empty or html payloads are ignored."""
        for payload in (None, b"", "<html/>", []):
            with self.subTest(payload=payload):
                self.assertEqual(
                    [],
                    await self._handler().parse_gateway_resource(
                        "gateway_led", payload, "1"
                    ),
                )

    async def test_fragment_update_keeps_info_attributes(self) -> None:
        """Fragment update keeps info attributes."""
        stored = _gateway(mainVersionSW="03.24.29")
        fragment = (
            await self._handler().parse_gateway_resource("gateway_led", LED, "1")
        )[0]
        stored.publish_updates = AsyncMock()
        await stored.update_device(fragment)
        self.assertEqual("03.24.29", stored.mainVersionSW)
        self.assertEqual(LED, stored.gateway_led)


class GatewayEntityTests(IsolatedAsyncioTestCase):
    """Home Assistant entities built on the gateway device."""

    async def test_led_switch(self) -> None:
        """Led switch."""
        gateway = _gateway(gateway_led=LED)
        gateway.async_turn_led_off = AsyncMock()
        switch = entities_module.GatewayLedSwitch(gateway)
        self.assertEqual("gw_gateway_led", switch._attr_unique_id)
        self.assertTrue(switch.available)
        self.assertTrue(switch.is_on)
        await switch.async_turn_off()
        gateway.async_turn_led_off.assert_awaited_once()

    async def test_led_colour_select_maps_lowercase_options(self) -> None:
        """Led colour select maps lowercase options."""
        gateway = _gateway(gateway_led={"color": {"OK": "custom_DD"}, "power": 100})
        gateway.async_set_led_color = AsyncMock()
        select = entities_module.GatewayLedColorSelect(gateway)
        self.assertIn("custom_dd", select._attr_options)
        self.assertNotIn("off", select._attr_options)
        self.assertEqual("custom_dd", select.current_option)
        await select.async_select_option("light_green")
        gateway.async_set_led_color.assert_awaited_once_with("light_green")

    def test_led_entities_unavailable_without_data(self) -> None:
        """Led entities unavailable without data."""
        gateway = _gateway()
        self.assertFalse(entities_module.GatewayLedSwitch(gateway).available)
        self.assertFalse(entities_module.GatewayLedColorSelect(gateway).available)

    def test_connectivity_sensor(self) -> None:
        """Connectivity sensor."""
        gateway = _gateway(gateway_network_status=dict(NETWORK, ipStatus="KO"))
        ip = entities_module.GatewayConnectivitySensor(
            gateway, "ipStatus", "gateway_ip_status"
        )
        internet = entities_module.GatewayConnectivitySensor(
            gateway, "internetAccessStatus", "gateway_internet_status"
        )
        self.assertFalse(ip.is_on)
        self.assertTrue(internet.is_on)

    async def test_update_mode_select(self) -> None:
        """Update mode select."""
        gateway = _gateway(gateway_update_status=UPDATE_STATUS)
        gateway.async_set_update_mode = AsyncMock()
        select = entities_module.GatewayUpdateModeSelect(gateway)
        self.assertEqual(["manual", "auto"], select._attr_options)
        self.assertEqual("manual", select.current_option)
        await select.async_select_option("auto")
        gateway.async_set_update_mode.assert_awaited_once_with("AUTO")

    async def test_radio_firmware_update_entity(self) -> None:
        """Radio firmware update entity."""
        firmware = dict(RadioFirmwareTests.FIRMWARE)
        gateway = _gateway(
            gateway_devices_update_status=dict(DEVICES_UPDATE, fwList=[firmware])
        )
        gateway.async_install_device_firmware = AsyncMock()
        entity = entities_module.RadioFirmwareUpdate(gateway, "fw-42")
        self.assertEqual(("radio_firmware", {"model": "TYXIA 5731"}), entity._test_name)
        self.assertEqual("01.00.00", entity.installed_version)
        self.assertEqual("01.02.00", entity.latest_version)
        self.assertFalse(entity.in_progress)
        await entity.async_install(None, False)
        gateway.async_install_device_firmware.assert_awaited_once_with("fw-42")

        firmware["status"] = "downloading"
        self.assertTrue(entity.in_progress)
        gateway.gateway_devices_update_status = DEVICES_UPDATE
        self.assertFalse(entity.available)

    def test_radio_availability_sensor(self) -> None:
        """Radio availability sensor."""
        gateway = _gateway(gateway_devices_update_status=DEVICES_UPDATE)
        sensor = entities_module.RadioFirmwareUpdateAvailableSensor(gateway)
        self.assertTrue(sensor.available)
        self.assertFalse(sensor.is_on)
        self.assertEqual("AUTO", sensor.extra_state_attributes["mode"])


def _load_hub_methods() -> type:
    """Load the hub's gateway control factory without Home Assistant."""
    source = (COMPONENT / "hub.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    hub_class = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "Hub"
    )
    methods = [
        node
        for node in hub_class.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_add_gateway_control", "_maybe_create_gateway_controls"}
    ]
    isolated = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            ast.ClassDef(
                name="Hub",
                bases=[],
                keywords=[],
                body=methods,
                decorator_list=[],
                type_params=[],
            ),
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(isolated)
    namespace = {
        name: getattr(entities_module, name)
        for name in (
            "GatewayConnectivitySensor",
            "GatewayLedColorSelect",
            "GatewayLedSwitch",
            "GatewayRebootButton",
            "GatewayUpdateModeSelect",
            "RadioFirmwareUpdate",
            "RadioFirmwareUpdateAvailableSensor",
            "gateway_firmware_ids",
        )
    }
    namespace["Tydom"] = Tydom
    exec(compile(isolated, "hub.py", "exec"), namespace)
    return namespace["Hub"]


class HubGatewayControlTests(TestCase):
    """Entities are created once, when their data appears."""

    def _hub(self):
        hub = _load_hub_methods()()
        hub._gateway_controls_created = set()
        hub.add_button_callback = MagicMock()
        hub.add_switch_callback = MagicMock()
        hub.add_select_callback = MagicMock()
        hub.add_binary_sensor_callback = MagicMock()
        hub.add_update_callback = MagicMock()
        return hub

    @staticmethod
    def _created(callback) -> list[str]:
        return [
            type(e).__name__ for call in callback.call_args_list for e in call.args[0]
        ]

    def test_only_restart_before_maintenance_data(self) -> None:
        """Only restart before maintenance data."""
        hub = self._hub()
        hub._maybe_create_gateway_controls(_gateway(mainVersionSW="03.24.29"))
        self.assertEqual(
            ["GatewayRebootButton"], self._created(hub.add_button_callback)
        )
        hub.add_switch_callback.assert_not_called()
        hub.add_select_callback.assert_not_called()
        hub.add_binary_sensor_callback.assert_not_called()

    def test_full_tydom_home_and_idempotence(self) -> None:
        """Full tydom home and idempotence."""
        hub = self._hub()
        gateway = _gateway(
            gateway_led=LED,
            gateway_network_status=NETWORK,
            gateway_update_status=UPDATE_STATUS,
            gateway_devices_update_status=DEVICES_UPDATE,
        )
        hub._maybe_create_gateway_controls(gateway)
        hub._maybe_create_gateway_controls(gateway)
        self.assertEqual(["GatewayLedSwitch"], self._created(hub.add_switch_callback))
        self.assertEqual(
            ["GatewayLedColorSelect", "GatewayUpdateModeSelect"],
            self._created(hub.add_select_callback),
        )
        self.assertEqual(
            [
                "GatewayConnectivitySensor",
                "GatewayConnectivitySensor",
                "RadioFirmwareUpdateAvailableSensor",
            ],
            self._created(hub.add_binary_sensor_callback),
        )
        hub.add_update_callback.assert_not_called()

    def test_new_radio_firmware_creates_one_update_entity(self) -> None:
        """New radio firmware creates one update entity."""
        hub = self._hub()
        gateway = _gateway(gateway_devices_update_status=DEVICES_UPDATE)
        hub._maybe_create_gateway_controls(gateway)
        gateway.gateway_devices_update_status = dict(
            DEVICES_UPDATE, fwList=[RadioFirmwareTests.FIRMWARE]
        )
        hub._maybe_create_gateway_controls(gateway)
        hub._maybe_create_gateway_controls(gateway)
        self.assertEqual(
            ["RadioFirmwareUpdate"], self._created(hub.add_update_callback)
        )

    def test_platform_not_ready_retries_later(self) -> None:
        """Platform not ready retries later."""
        hub = self._hub()
        hub.add_switch_callback = None
        gateway = _gateway(gateway_led=LED)
        hub._maybe_create_gateway_controls(gateway)
        self.assertNotIn("led", hub._gateway_controls_created)
        hub.add_switch_callback = MagicMock()
        hub._maybe_create_gateway_controls(gateway)
        self.assertEqual(["GatewayLedSwitch"], self._created(hub.add_switch_callback))


def _load_client_methods() -> type:
    """Load the new client request helpers without the websocket stack."""
    source = (COMPONENT / "tydom" / "tydom_client.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    client_class = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "TydomClient"
    )
    wanted = {
        "_get_optional",
        "get_gateway_led",
        "put_gateway_led",
        "reboot_gateway",
        "put_gateway_update_setup",
        "get_gateway_update_status",
        "put_devices_update",
        "get_devices_update_status",
        "get_gateway_maintenance_status",
        "get_gateway_network_status",
        "_put_then_read_back",
        "_send_gateway_command",
    }
    methods = [
        node
        for node in client_class.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name in wanted
    ]
    isolated = ast.Module(
        body=[
            ast.ClassDef(
                name="Client",
                bases=[],
                keywords=[],
                body=methods,
                decorator_list=[],
                type_params=[],
            )
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(isolated)
    namespace = {
        "asyncio": SimpleNamespace(sleep=AsyncMock()),
        "json": json,
        "STRUCTURED_LOGGER": MagicMock(),
        "_GATEWAY_READ_BACK_DELAY": 0,
    }
    exec(compile(isolated, "tydom_client.py", "exec"), namespace)
    return namespace["Client"]


class ClientRequestTests(IsolatedAsyncioTestCase):
    """Wire format of the new requests (as sent by the official app)."""

    def _client(self):
        client = _load_client_methods()()
        client._unsupported_optional_paths = set()
        client.send_message = AsyncMock()
        client.send_request = AsyncMock()
        client.get_reply_to_request = AsyncMock()
        client.real_send_gateway_command = client._send_gateway_command
        client._send_gateway_command = AsyncMock()
        return client

    async def test_led_is_written_then_read_back(self) -> None:
        """The LED PUT is not awaited for a reply; the state is read back."""
        client = self._client()
        await client.put_gateway_led(LED)
        client._send_gateway_command.assert_awaited_once_with(
            "PUT", "/configs/gateway/led", body=LED, headers=None
        )
        client.get_reply_to_request.assert_not_awaited()
        client.send_message.assert_awaited_once_with(
            method="GET", msg="/configs/gateway/led"
        )

    async def test_reboot_does_not_wait_for_a_reply(self) -> None:
        """Reboot does not wait for a reply."""
        client = self._client()
        await client.reboot_gateway()
        client._send_gateway_command.assert_awaited_once_with(
            "PUT", "/configs/gateway/reboot"
        )
        client.get_reply_to_request.assert_not_awaited()

    async def test_commands_carry_the_remote_mode_prefix(self) -> None:
        """Requests keep the mediation prefix, unlike prepare_request's output."""
        client = self._client()
        client._cmd_prefix = b"\x02"
        client._message_handler = SimpleNamespace(
            prepare_request=MagicMock(return_value=("1", b"PUT /x HTTP/1.1\r\n\r\n"))
        )
        client.send_bytes = AsyncMock()
        await client.real_send_gateway_command("PUT", "/x", body={"a": 1})
        client._message_handler.prepare_request.assert_called_once_with(
            "PUT", "/x", {"a": 1}, None
        )
        client.send_bytes.assert_awaited_once_with(b"\x02PUT /x HTTP/1.1\r\n\r\n")

    async def test_update_mode_body(self) -> None:
        """The update mode is sent as {"mode": …} and read back."""
        client = self._client()
        await client.put_gateway_update_setup("AUTO")
        client._send_gateway_command.assert_awaited_once_with(
            "PUT", "/configs/gateway/update/setup", body={"mode": "AUTO"}, headers=None
        )
        client.send_message.assert_awaited_once_with(
            method="GET", msg="/configs/gateway/update/status"
        )

    async def test_devices_update_sends_a_json_array(self) -> None:
        """Radio firmware deployment uses a JSON array, then reads back."""
        client = self._client()
        await client.put_devices_update([{"fwId": "fw-42", "modelId": "TYXIA 5731"}])
        method, path = client._send_gateway_command.await_args.args
        kwargs = client._send_gateway_command.await_args.kwargs
        self.assertEqual(("PUT", "/devices/update"), (method, path))
        self.assertEqual(
            [{"fwId": "fw-42", "modelId": "TYXIA 5731"}], json.loads(kwargs["body"])
        )
        self.assertIn("application/json", kwargs["headers"]["Content-Type"])
        client.send_message.assert_awaited_once_with(
            method="GET", msg="/devices/update/status"
        )

    async def test_unsupported_paths_are_skipped(self) -> None:
        """Unsupported paths are skipped."""
        client = self._client()
        client._unsupported_optional_paths = {
            "/configs/gateway/led",
            "/devices/update/status",
        }
        await client.get_gateway_maintenance_status()
        requested = [call.kwargs["msg"] for call in client.send_message.await_args_list]
        self.assertEqual(
            ["/configs/gateway/network/status", "/configs/gateway/update/status"],
            requested,
        )
