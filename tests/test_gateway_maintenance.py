"""Tests for the gateway maintenance features (LED, restart, firmware status).

Payloads are those returned by a TYDOM HOME (firmware 03.24.29).
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
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


class _HomeAssistantError(Exception):
    """Stand-in for homeassistant.exceptions.HomeAssistantError."""

    def __init__(
        self,
        *args,
        translation_domain=None,
        translation_key=None,
        translation_placeholders=None,
    ) -> None:
        super().__init__(*args)
        self.translation_domain = translation_domain
        self.translation_key = translation_key
        self.translation_placeholders = translation_placeholders


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
    "homeassistant.const",
    EntityCategory=SimpleNamespace(CONFIG="config", DIAGNOSTIC="diagnostic"),
)
_module("homeassistant.exceptions", HomeAssistantError=_HomeAssistantError)
_module("homeassistant.helpers.entity", DeviceInfo=dict, Entity=_Entity)

devices_module = _load(
    "custom_components.deltadore_tydom.tydom.tydom_devices",
    COMPONENT / "tydom" / "tydom_devices.py",
)
TydomGatewayCommandError = type("TydomGatewayCommandError", (Exception,), {})
_module(
    "custom_components.deltadore_tydom.tydom.tydom_client",
    TydomGatewayCommandError=TydomGatewayCommandError,
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


class RadioFirmwareStatusTests(TestCase):
    """Radio product firmware status reported by the gateway (read only)."""

    def test_empty_list_from_a_real_gateway(self) -> None:
        """Empty list from a real gateway."""
        gateway = _gateway(gateway_devices_update_status=DEVICES_UPDATE)
        self.assertEqual({}, gateway.device_firmwares)

    def test_install_is_not_offered(self) -> None:
        """Radio firmware deployment waits for a hardware-verified flow."""
        self.assertFalse(hasattr(Tydom, "async_install_device_firmware"))
        self.assertFalse(hasattr(entities_module, "RadioFirmwareUpdate"))


def _gateway_fragment(**data) -> Tydom:
    """Build a gateway fragment as MessageHandler does for one reply."""
    return Tydom(None, "gw", "gw", "gw", "Tydom Gateway", None, None, data)


class UpdateAvailabilityTests(IsolatedAsyncioTestCase):
    """/info and update/status both report updateAvailable: the latest wins."""

    async def _merge(self, stored: Tydom, *fragments: Tydom) -> Tydom:
        stored.publish_updates = AsyncMock()
        for fragment in fragments:
            await stored.update_device(fragment)
        return stored

    async def test_fresh_info_is_not_hidden_by_a_stale_status(self) -> None:
        """A fresh /info offer wins over an older update/status ``false``."""
        gateway = await self._merge(
            _gateway(mainVersionSW="03.24.29", updateAvailable=False),
            _gateway_fragment(gateway_update_status=UPDATE_STATUS),
            _gateway_fragment(updateAvailable=True),
        )
        self.assertTrue(gateway.update_available)

    async def test_fresh_status_is_not_hidden_by_a_stale_info(self) -> None:
        """A fresh update/status offer wins over an older /info ``false``."""
        gateway = await self._merge(
            _gateway(mainVersionSW="03.24.29", updateAvailable=False),
            _gateway_fragment(
                gateway_update_status=dict(UPDATE_STATUS, updateAvailable=True)
            ),
        )
        self.assertTrue(gateway.update_available)

    async def test_a_newer_false_clears_an_older_offer(self) -> None:
        """Once installed, the source reporting last clears the offer."""
        for first, second in (
            (
                _gateway_fragment(updateAvailable=True),
                _gateway_fragment(gateway_update_status=UPDATE_STATUS),
            ),
            (
                _gateway_fragment(
                    gateway_update_status=dict(UPDATE_STATUS, updateAvailable=True)
                ),
                _gateway_fragment(updateAvailable=False),
            ),
        ):
            with self.subTest(first=first.__dict__.keys()):
                gateway = await self._merge(_gateway(), first, second)
                self.assertFalse(gateway.update_available)

    async def test_other_fragments_keep_the_order(self) -> None:
        """An LED or network refresh does not refresh update availability."""
        gateway = await self._merge(
            _gateway(updateAvailable=False),
            _gateway_fragment(
                gateway_update_status=dict(UPDATE_STATUS, updateAvailable=True)
            ),
            _gateway_fragment(gateway_led=LED),
        )
        self.assertTrue(gateway.update_available)

    def test_single_or_no_source(self) -> None:
        """Gateways without update/status keep using /info."""
        self.assertTrue(_gateway(updateAvailable=True).update_available)
        self.assertFalse(_gateway(gateway_update_status=UPDATE_STATUS).update_available)
        self.assertIsNone(_gateway().update_available)


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

    async def test_unapplied_commands_raise_a_home_assistant_error(self) -> None:
        """A command TYDOM rejects or does not apply is reported to the user."""
        gateway = _gateway(gateway_led=LED, gateway_update_status=UPDATE_STATUS)
        error = TydomGatewayCommandError("TYDOM did not apply PUT /x")
        gateway.async_turn_led_on = AsyncMock(side_effect=error)
        gateway.async_turn_led_off = AsyncMock(side_effect=error)
        gateway.async_set_led_color = AsyncMock(side_effect=error)
        gateway.async_set_update_mode = AsyncMock(side_effect=error)
        switch = entities_module.GatewayLedSwitch(gateway)
        colour = entities_module.GatewayLedColorSelect(gateway)
        mode = entities_module.GatewayUpdateModeSelect(gateway)
        for command in (
            switch.async_turn_on,
            switch.async_turn_off,
            lambda: colour.async_select_option("green"),
            lambda: mode.async_select_option("auto"),
        ):
            with self.assertRaises(_HomeAssistantError) as raised:
                await command()
            self.assertEqual("gateway_command_failed", raised.exception.translation_key)
            self.assertEqual(
                {"error": "TYDOM did not apply PUT /x"},
                raised.exception.translation_placeholders,
            )

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
            "RadioFirmwareUpdateAvailableSensor",
        )
    }
    namespace["Tydom"] = Tydom
    # The real path lets coverage credit the lines of hub.py.
    exec(compile(isolated, str(COMPONENT / "hub.py"), "exec"), namespace)
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
        "get_devices_update_status",
        "get_gateway_maintenance_status",
        "get_gateway_network_status",
        "_gateway_request",
        "_put_and_confirm",
        "_send_gateway_command",
        "update_firmware",
    }
    methods = [
        node
        for node in client_class.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name in wanted
    ]
    isolated = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            ast.ClassDef(
                name="Client",
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
        "asyncio": SimpleNamespace(sleep=AsyncMock(), Event=asyncio.Event),
        "async_timeout": SimpleNamespace(timeout=asyncio.timeout),
        "LOGGER": MagicMock(),
        "STRUCTURED_LOGGER": MagicMock(),
        "TydomGatewayCommandError": TydomGatewayCommandError,
        "_GATEWAY_COMMAND_ACK_TIMEOUT": 5.0,
        "_GATEWAY_READ_BACK_TIMEOUT": 10.0,
        "_GATEWAY_READ_BACK_DELAY": 0,
        "_GATEWAY_READ_BACK_ATTEMPTS": 3,
    }
    # The real path lets coverage credit the lines of tydom_client.py.
    exec(
        compile(isolated, str(COMPONENT / "tydom" / "tydom_client.py"), "exec"),
        namespace,
    )
    return namespace["Client"]


LED_OFF = {"color": {"OK": "off", "local": "orange", "error": "red"}, "power": 100}


class ClientRequestTests(IsolatedAsyncioTestCase):
    """Wire format of the new requests (as sent by the official app)."""

    def _client(self, *replies):
        client = _load_client_methods()()
        client._unsupported_optional_paths = set()
        client.send_message = AsyncMock()
        client.real_gateway_request = client._gateway_request
        client._gateway_request = AsyncMock(side_effect=list(replies))
        client.real_send_gateway_command = client._send_gateway_command
        client._send_gateway_command = AsyncMock()
        return client

    def _requests(self, client) -> list[tuple]:
        return [call.args[:3] for call in client._gateway_request.await_args_list]

    async def test_led_is_confirmed_by_a_read_back(self) -> None:
        """The LED PUT succeeds once the gateway reports the new colour."""
        client = self._client([], [LED_OFF])
        await client.put_gateway_led(LED_OFF)
        self.assertEqual(
            [("PUT", "/configs/gateway/led", LED_OFF), ("GET", "/configs/gateway/led")],
            self._requests(client),
        )
        self.assertEqual(
            5.0, client._gateway_request.await_args_list[0].kwargs["timeout"]
        )

    async def test_missing_ack_and_late_state_are_retried(self) -> None:
        """No acknowledgement is tolerated; the state may take a moment."""
        client = self._client(None, None, ["not json", LED], [LED_OFF])
        await client.put_gateway_led(LED_OFF)
        self.assertEqual(4, client._gateway_request.await_count)

    async def test_state_never_applied_is_an_error(self) -> None:
        """The command fails when every read-back shows the old state."""
        client = self._client([], [LED], [LED], [LED])
        with self.assertRaises(TydomGatewayCommandError):
            await client.put_gateway_led(LED_OFF)
        self.assertEqual(4, client._gateway_request.await_count)

    async def test_rejected_put_fails_without_read_back(self) -> None:
        """An HTTP rejection of the PUT is reported at once."""
        client = self._client(TydomGatewayCommandError("HTTP 400"))
        with self.assertRaises(TydomGatewayCommandError):
            await client.put_gateway_led(LED_OFF)
        self.assertEqual(1, client._gateway_request.await_count)

    async def test_update_mode_is_confirmed_on_the_setup_resource(self) -> None:
        """The update mode is sent as {"mode": …} and read back from setup."""
        client = self._client([], [{"mode": "MANUAL"}], [{"mode": "AUTO"}])
        await client.put_gateway_update_setup("AUTO")
        self.assertEqual(
            [
                ("PUT", "/configs/gateway/update/setup", {"mode": "AUTO"}),
                ("GET", "/configs/gateway/update/setup"),
                ("GET", "/configs/gateway/update/setup"),
            ],
            self._requests(client),
        )

    async def test_update_mode_not_applied_is_an_error(self) -> None:
        """The mode change fails when the gateway keeps the old mode."""
        client = self._client(None, *([[{"mode": "MANUAL"}]] * 3))
        with self.assertRaises(TydomGatewayCommandError):
            await client.put_gateway_update_setup("AUTO")

    async def test_firmware_install_reports_a_rejection(self) -> None:
        """Installing waits for TYDOM's answer and reports a refusal."""
        client = self._client(None, TydomGatewayCommandError("HTTP 409"))
        await client.update_firmware()
        self.assertEqual([("PUT", "/configs/gateway/update")], self._requests(client))
        with self.assertRaises(TydomGatewayCommandError):
            await client.update_firmware()

    async def test_reboot_does_not_wait_for_a_reply(self) -> None:
        """Reboot does not wait for a reply."""
        client = self._client()
        await client.reboot_gateway()
        client._send_gateway_command.assert_awaited_once_with(
            "PUT", "/configs/gateway/reboot"
        )
        client._gateway_request.assert_not_awaited()

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

    def _tracked_client(self, *, answer: bool, error: str | None = None):
        client = self._client()
        client._cmd_prefix = b"\x02"
        client.send_bytes = AsyncMock()

        def prepare(method, path, body, headers, reply_event):
            if answer:
                reply_event.set()
            return "7", b"REQ"

        client._message_handler = SimpleNamespace(
            prepare_request=MagicMock(side_effect=prepare),
            get_reply_error=MagicMock(return_value=error),
            get_reply=MagicMock(return_value={"events": [LED]}),
            remove_reply=MagicMock(),
        )
        return client

    async def test_tracked_request_returns_the_reply(self) -> None:
        """A tracked request is prefixed and returns the parsed reply."""
        client = self._tracked_client(answer=True)
        self.assertEqual([LED], await client.real_gateway_request("GET", "/led"))
        client.send_bytes.assert_awaited_once_with(b"\x02REQ")

    async def test_tracked_request_reports_a_rejection(self) -> None:
        """An HTTP error reply raises a gateway command error."""
        client = self._tracked_client(answer=True, error="HTTP 400: Bad Request")
        with self.assertRaisesRegex(TydomGatewayCommandError, "HTTP 400"):
            await client.real_gateway_request("PUT", "/led", {"a": 1})
        client._message_handler.remove_reply.assert_called_once_with("7")

    async def test_tracked_request_without_reply_returns_none(self) -> None:
        """A missing reply is not an error by itself."""
        client = self._tracked_client(answer=False)
        self.assertIsNone(
            await client.real_gateway_request("PUT", "/led", timeout=0.01)
        )
        client._message_handler.remove_reply.assert_called_once_with("7")

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
