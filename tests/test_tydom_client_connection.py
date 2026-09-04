"""Tests for serialised Tydom websocket connection ownership."""

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, call, patch

_MISSING = object()
_original_modules: dict[str, object] = {}


def _module(name: str, **attributes) -> types.ModuleType:
    """Install a minimal module required to load the client in isolation."""
    _original_modules.setdefault(name, sys.modules.get(name, _MISSING))
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    sys.modules[name] = module
    return module


class _ClientConnectionError(Exception):
    """Stand-in for aiohttp.ClientConnectionError."""


class _WSServerHandshakeError(Exception):
    """Stand-in for aiohttp.WSServerHandshakeError."""


class _WebSocketResponse:
    """Stand-in used only to evaluate runtime annotations."""


class _AlarmCommandError(Exception):
    """Stand-in retaining the command result inspected by the tests."""

    def __init__(self, command: str, result: str) -> None:
        """Store the simulated command result."""
        self.command = command
        self.result = result


for package_name in (
    "custom_components",
    "custom_components.deltadore_tydom",
    "custom_components.deltadore_tydom.tydom",
):
    package = _module(package_name)
    package.__path__ = []

aiohttp = _module(
    "aiohttp",
    ClientError=Exception,
    ClientConnectionError=_ClientConnectionError,
    WSServerHandshakeError=_WSServerHandshakeError,
    ClientSession=object,
    ClientWebSocketResponse=_WebSocketResponse,
    WSMsgType=MagicMock(),
)
_module("async_timeout", timeout=MagicMock())
_module("homeassistant")
_module("homeassistant.helpers")
_module("homeassistant.helpers.aiohttp_client", async_create_clientsession=MagicMock())
_module("requests")
_module("requests.auth", HTTPDigestAuth=MagicMock())
_module("urllib3", encode_multipart_formdata=MagicMock())

logger = MagicMock()
structured_logger = MagicMock()
_module(
    "custom_components.deltadore_tydom.const",
    LOGGER=logger,
    STRUCTURED_LOGGER=structured_logger,
    validate_value_with_metadata=MagicMock(),
    TIMEOUT_NORMAL_REQUEST=30.0,
    TIMEOUT_LONG_REQUEST=60.0,
    TIMEOUT_WEBSOCKET_CONNECT=30.0,
    TIMEOUT_WEBSOCKET_RECEIVE=20.0,
    TIMEOUT_PING=40.0,
)
_module(
    "custom_components.deltadore_tydom.tydom.const",
    DELTADORE_API_SITES="",
    DELTADORE_AUTH_CLIENTID="",
    DELTADORE_AUTH_GRANT_TYPE="",
    DELTADORE_AUTH_SCOPE="",
    DELTADORE_AUTH_URL="",
    MEDIATION_URL="mediation.tydom.com",
)
_module(
    "custom_components.deltadore_tydom.tydom.MessageHandler",
    MessageHandler=MagicMock(),
)
_module(
    "custom_components.deltadore_tydom.tydom.tydom_devices",
    TydomAlarmCommandError=_AlarmCommandError,
)

module_name = "custom_components.deltadore_tydom.tydom.tydom_client"
client_path = (
    Path(__file__).parents[1]
    / "custom_components"
    / "deltadore_tydom"
    / "tydom"
    / "tydom_client.py"
)
spec = importlib.util.spec_from_file_location(module_name, client_path)
assert spec is not None and spec.loader is not None
client_module = importlib.util.module_from_spec(spec)
_original_modules.setdefault(module_name, sys.modules.get(module_name, _MISSING))
sys.modules[module_name] = client_module
spec.loader.exec_module(client_module)
TydomClient = client_module.TydomClient
TydomClientApiClientCommunicationError = (
    client_module.TydomClientApiClientCommunicationError
)
TydomAlarmCommandError = client_module.TydomAlarmCommandError
sanitize_log_message = client_module.sanitize_log_message
parse_digest_challenge = client_module._parse_digest_challenge

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


def _websocket() -> MagicMock:
    """Return a minimal open websocket mock."""
    connection = MagicMock()
    connection.closed = False

    async def close() -> None:
        connection.closed = True

    connection.close = AsyncMock(side_effect=close)
    connection.send_bytes = AsyncMock()
    return connection


class TestManagedConnection(IsolatedAsyncioTestCase):
    """Exercise connection candidate cleanup and reconnect serialisation."""

    def _client(self) -> TydomClient:
        return TydomClient(None, "test", "001122334455", "password", host="local")

    def test_cloud_credentials_select_the_matching_gateway(self) -> None:
        """Credential lookup must not use another gateway from the same account."""
        password = TydomClient._gateway_password_from_sites(
            [
                {"gateway": {"mac": "AABBCCDDEEFF", "password": "first"}},
                {"gateway": {"mac": "001122334455", "password": "requested"}},
            ],
            "001122334455",
        )

        self.assertEqual(password, "requested")

    def test_cloud_credentials_match_gateway_mac_without_case_sensitivity(self) -> None:
        """The API's MAC casing must not prevent a matching gateway lookup."""
        password = TydomClient._gateway_password_from_sites(
            [{"gateway": {"mac": "001A2B3C4D5E", "password": "requested"}}],
            "001a2b3c4d5e",
        )

        self.assertEqual(password, "requested")

    def test_cloud_credentials_normalize_gateway_mac_separators(self) -> None:
        """Cloud responses may format a MAC address with colon separators."""
        password = TydomClient._gateway_password_from_sites(
            [{"gateway": {"mac": "00:1A:2B:3C:4D:5E", "password": "requested"}}],
            "001a2b3c4d5e",
        )

        self.assertEqual(password, "requested")

    def test_digest_authentication_normalizes_the_mac_username(self) -> None:
        """Digest must use the gateway's canonical uppercase MAC username."""
        digest_auth = MagicMock()
        digest_auth.build_digest_header.return_value = "Digest response"
        client = TydomClient(
            None,
            "test",
            "001a2505f4b1",
            "gateway-password",
            host="mediation.tydom.com",
        )

        with patch.object(
            client_module, "HTTPDigestAuth", return_value=digest_auth
        ) as digest_auth_class:
            client.build_digest_headers(
                'Digest realm="ServiceMedia", nonce="nonce", qop="auth"'
            )

        self.assertEqual(client._mac, "001A2505F4B1")
        digest_auth_class.assert_called_once_with("001A2505F4B1", "gateway-password")
        digest_auth.build_digest_header.assert_called_once_with(
            "GET",
            "https://mediation.tydom.com:443/mediation/client?mac=001A2505F4B1&appli=1",
        )

    def test_digest_challenge_retains_all_server_parameters(self) -> None:
        """The mediation server may require parameters beyond its nonce."""
        challenge = parse_digest_challenge(
            'Digest realm="ServiceMedia", nonce="abc/123==", '
            'qop="auth", algorithm="MD5", opaque="gateway-token"'
        )

        self.assertEqual(
            challenge,
            {
                "realm": "ServiceMedia",
                "nonce": "abc/123==",
                "qop": "auth",
                "algorithm": "MD5",
                "opaque": "gateway-token",
            },
        )

    def test_digest_header_uses_complete_server_challenge(self) -> None:
        """Digest signing must retain every parameter sent by mediation."""
        digest_auth = MagicMock()
        digest_auth.build_digest_header.return_value = "Digest response"
        client = TydomClient(
            None,
            "test",
            "001A2505F4B1",
            "gateway-password",
            host="mediation.tydom.com",
        )
        header = (
            'Digest realm="ServiceMedia", nonce="nonce", qop="auth", '
            'algorithm="MD5", opaque="opaque"'
        )

        with patch.object(client_module, "HTTPDigestAuth", return_value=digest_auth):
            authorization = client.build_digest_headers(header)

        self.assertEqual(authorization, "Digest response")
        self.assertEqual(digest_auth._thread_local.chal, parse_digest_challenge(header))
        digest_auth.build_digest_header.assert_called_once_with(
            "GET",
            "https://mediation.tydom.com:443/mediation/client?mac=001A2505F4B1&appli=1",
        )

    async def test_legacy_alarm_disarm_uses_global_alarm_command(self) -> None:
        """A zone-capable legacy alarm must not drop a global disarm."""
        client = self._client()
        client._put_alarm_cdata = AsyncMock()

        await client.put_alarm_cdata(
            "20",
            "10",
            "123456",
            "OFF",
            None,
            legacy_zones=True,
        )

        client._put_alarm_cdata.assert_awaited_once_with(
            "20",
            "10",
            "123456",
            "OFF",
            None,
            True,
        )

    async def test_set_local_gateway_password_uses_gateway_endpoint(self) -> None:
        """The local password update uses the generic gateway endpoint."""
        client = self._client()
        client.get_reply_to_request = AsyncMock(return_value=[])

        await client.async_set_local_gateway_password("NewPassword1")

        client.get_reply_to_request.assert_awaited_once_with(
            "PUT",
            "/configs/gateway/password",
            body={"password": "NewPassword1"},
        )
        self.assertEqual(client._password, "NewPassword1")

    async def test_set_local_gateway_password_keeps_previous_password_on_failure(
        self,
    ) -> None:
        """A rejected update must not poison the next Digest authentication."""
        client = self._client()
        client.get_reply_to_request = AsyncMock(
            side_effect=TydomClientApiClientCommunicationError("rejected")
        )

        with self.assertRaises(TydomClientApiClientCommunicationError):
            await client.async_set_local_gateway_password("NewPassword1")

        self.assertEqual(client._password, "password")

    async def test_set_local_gateway_password_rejects_cloud_mediation(self) -> None:
        """The password-changing API must remain a direct local operation."""
        client = TydomClient(
            None,
            "test",
            "001122334455",
            "password",
            host="mediation.tydom.com",
        )

        with self.assertRaisesRegex(
            client_module.TydomClientApiClientError, "direct local connection"
        ):
            await client.async_set_local_gateway_password("NewPassword1")

    async def test_legacy_alarm_zone_commands_are_still_split(self) -> None:
        """Legacy arm commands must continue to address each configured part."""
        client = self._client()
        client._put_alarm_cdata = AsyncMock()

        await client.put_alarm_cdata(
            "20",
            "10",
            "123456",
            "ON",
            "1,3",
            legacy_zones=True,
        )

        self.assertEqual(
            client._put_alarm_cdata.await_args_list,
            [
                call("20", "10", "123456", "ON", "1", True),
                call("20", "10", "123456", "ON", "3", True),
            ],
        )

    async def test_alarm_command_waits_for_acknowledged_result(self) -> None:
        """Alarm commands must correlate their Transac-Id 0 cdata result."""
        client = self._client()
        waiter = asyncio.get_running_loop().create_future()
        waiter.set_result(
            {"name": "alarmCmd", "values": {"result": "ACK", "authent": "USER"}}
        )
        client._message_handler.create_alarm_command_waiter.return_value = waiter
        client.send_bytes = AsyncMock()

        await client._put_alarm_cdata("20", "10", "123456", "ON")

        request = client.send_bytes.await_args.args[0].decode("ascii")
        self.assertIn("PUT /devices/20/endpoints/10/cdata?name=alarmCmd", request)
        self.assertIn("Transac-Id: 0", request)
        self.assertIn('{"value": "ON", "pwd": "123456"}', request)

    async def test_denied_zone_alarm_command_raises(self) -> None:
        """A gateway DENIED result must reach the Home Assistant action."""
        client = self._client()
        waiter = asyncio.get_running_loop().create_future()
        waiter.set_result(
            {"name": "zoneCmd", "values": {"result": "DENIED", "authent": "USER"}}
        )
        client._message_handler.create_alarm_command_waiter.return_value = waiter
        client.send_bytes = AsyncMock()

        with self.assertRaises(TydomAlarmCommandError) as context:
            await client._put_alarm_cdata("20", "10", "123456", "ON", "1,3")

        self.assertEqual(context.exception.command, "zoneCmd")
        self.assertEqual(context.exception.result, "DENIED")
        request = client.send_bytes.await_args.args[0].decode("ascii")
        self.assertIn("PUT /devices/20/endpoints/10/cdata?name=zoneCmd", request)
        self.assertIn("Transac-Id: 0", request)
        self.assertIn('"zones": [1, 3]', request)

    async def test_alarm_inventory_uses_supported_label_command(self) -> None:
        """Inventory must not depend on optional unsupported productInfo data."""
        client = self._client()
        client.get_reply_to_request = AsyncMock(
            return_value=[{"name": "label", "values": {"products": [], "zones": []}}]
        )

        result = await client.get_alarm_products_cdata("20", "10")

        self.assertIsNone(result["productInfo"])
        self.assertEqual(result["label"]["name"], "label")
        self.assertEqual(
            client.get_reply_to_request.await_args_list,
            [
                call(
                    "GET",
                    "/devices/20/endpoints/10/cdata?name=label",
                    headers={
                        "Content-Length": "0",
                        "Content-Type": "application/json; charset=UTF-8",
                    },
                ),
            ],
        )

    async def test_rejected_tracked_request_raises_protocol_error(self) -> None:
        """A gateway rejection must not be returned as an empty success."""
        client = self._client()

        def prepare_request(_method, _url, _body, _headers, reply_event):
            reply_event.set()
            return "request-1", b"request"

        client._message_handler.prepare_request = MagicMock(side_effect=prepare_request)
        client._message_handler.get_reply_error = MagicMock(
            return_value="HTTP 403: The data is not writable"
        )
        client.send_bytes = AsyncMock()

        with self.assertRaisesRegex(TydomClientApiClientCommunicationError, "HTTP 403"):
            await client.get_reply_to_request(
                "GET", "/cdata?name=productConf&pwd=123456"
            )

    async def test_alarm_product_configuration_uses_encoded_pin(self) -> None:
        """The read command must follow the official query-string protocol."""
        client = self._client()
        client.get_reply_to_request = AsyncMock(
            return_value=[{"name": "productConf", "values": {"id": 4}}]
        )

        result = await client.get_alarm_product_configuration_cdata(
            "20", "10", "12&34", 4
        )

        self.assertEqual(result["values"]["id"], 4)
        client.get_reply_to_request.assert_awaited_once_with(
            "GET",
            "/devices/20/endpoints/10/cdata?name=productConf&pwd=12%2634&id=4",
            headers={
                "Content-Length": "0",
                "Content-Type": "application/json; charset=UTF-8",
            },
        )
        self.assertNotIn("12&34", sanitize_log_message("?pwd=12&34"))

    async def test_alarm_product_zone_update_sends_only_requested_field(self) -> None:
        """A zone update must not overwrite unrelated product settings."""
        client = self._client()
        client.get_reply_to_request = AsyncMock(return_value=[])

        await client.put_alarm_product_configuration_cdata(
            "20", "10", "123456", 4, zone=3
        )

        client.get_reply_to_request.assert_awaited_once_with(
            "PUT",
            "/devices/20/endpoints/10/cdata?name=productConf",
            body={
                "pwd": "123456",
                "id": 4,
                "common": {"zone": 3},
            },
        )

    async def test_alarm_product_activation_uses_dedicated_command(self) -> None:
        """Activation must use activeProductConf instead of productConf."""
        client = self._client()
        client.get_reply_to_request = AsyncMock(return_value=[])

        await client.put_alarm_product_active_cdata("20", "10", "123456", 4, False)

        client.get_reply_to_request.assert_awaited_once_with(
            "PUT",
            "/devices/20/endpoints/10/cdata?name=activeProductConf",
            body={"pwd": "123456", "id": 4, "activeProduct": False},
        )

    async def test_alarm_maintenance_commands_await_gateway_reply(self) -> None:
        """Entering and leaving maintenance must use global alarmCmd writes."""
        client = self._client()
        client.get_reply_to_request = AsyncMock(return_value=[])

        await client.put_alarm_mode_cdata("20", "10", "123456", "MAINTENANCE")
        await client.put_alarm_mode_cdata("20", "10", "123456", "OFF")

        self.assertEqual(
            client.get_reply_to_request.await_args_list,
            [
                call(
                    "PUT",
                    "/devices/20/endpoints/10/cdata?name=alarmCmd",
                    body={"pwd": "123456", "value": "MAINTENANCE"},
                ),
                call(
                    "PUT",
                    "/devices/20/endpoints/10/cdata?name=alarmCmd",
                    body={"pwd": "123456", "value": "OFF"},
                ),
            ],
        )

    async def test_alarm_acknowledgement_prefers_authenticated_cdata(self) -> None:
        """A configured code uses the asynchronous TYXAL command result."""
        client = self._client()
        waiter = asyncio.get_running_loop().create_future()
        waiter.set_result({"name": "ackEventCmd", "values": {"result": "ACK"}})
        client._message_handler.create_alarm_command_waiter.return_value = waiter
        client.send_bytes = AsyncMock()
        client.put_devices_data = AsyncMock()

        await client.put_ackevents_cdata("20", "10", "123456")

        request = client.send_bytes.await_args.args[0].decode("ascii")
        self.assertIn("PUT /devices/20/endpoints/10/cdata?name=ackEventCmd", request)
        self.assertIn("Transac-Id: 0", request)
        self.assertIn('{"pwd": "123456"}', request)
        client.put_devices_data.assert_not_awaited()

    async def test_alarm_acknowledgement_rejects_denied_result(self) -> None:
        """A negative asynchronous result must reach the service caller."""
        client = self._client()
        waiter = asyncio.get_running_loop().create_future()
        waiter.set_result({"name": "ackEventCmd", "values": {"result": "DENIED"}})
        client._message_handler.create_alarm_command_waiter.return_value = waiter
        client.send_bytes = AsyncMock()

        with self.assertRaises(TydomAlarmCommandError):
            await client.put_ackevents_cdata("20", "10", "123456")

    async def test_alarm_remote_configuration_lock_uses_official_command(self) -> None:
        """Remote TYXAL configuration must be explicitly locked and unlocked."""
        client = self._client()
        client.get_reply_to_request = AsyncMock(return_value=[])

        await client.put_alarm_remote_control_cdata("20", "10", "123456", "lock")
        await client.put_alarm_remote_control_cdata("20", "10", "123456", "unlock")

        self.assertEqual(
            client.get_reply_to_request.await_args_list,
            [
                call(
                    "PUT",
                    "/devices/20/endpoints/10/cdata?name=remoteCtrl",
                    body={"pwd": "123456", "control": "lock"},
                ),
                call(
                    "PUT",
                    "/devices/20/endpoints/10/cdata?name=remoteCtrl",
                    body={"pwd": "123456", "control": "unlock"},
                ),
            ],
        )

    async def test_alarm_zone_rename_uses_custom_label_command(self) -> None:
        """Zone renaming must use the official zoneLabelConf payload."""
        client = self._client()
        client.get_reply_to_request = AsyncMock(return_value=[])

        await client.put_alarm_zone_label_cdata("20", "10", "123456", 2, "Outbuildings")

        client.get_reply_to_request.assert_awaited_once_with(
            "PUT",
            "/devices/20/endpoints/10/cdata?name=zoneLabelConf",
            body={
                "pwd": "123456",
                "id": 2,
                "label": {"nameCustom": "Outbuildings"},
            },
        )

    async def test_alarm_zone_empty_name_clears_label(self) -> None:
        """An empty name must remain explicit in the app's reset payload."""
        client = self._client()
        client.get_reply_to_request = AsyncMock(return_value=[])

        await client.put_alarm_zone_label_cdata("20", "10", "123456", 4, "")

        client.get_reply_to_request.assert_awaited_once_with(
            "PUT",
            "/devices/20/endpoints/10/cdata?name=zoneLabelConf",
            body={"pwd": "123456", "id": 4, "label": {"nameCustom": ""}},
        )

    async def test_failed_initialisation_closes_candidate(self) -> None:
        """A socket that fails initialisation must never remain active."""
        client = self._client()
        candidate = _websocket()
        client.async_connect = AsyncMock(return_value=candidate)
        client._initialise_connection = AsyncMock(
            side_effect=RuntimeError("init failed")
        )

        with self.assertRaisesRegex(RuntimeError, "init failed"):
            await client.async_connect_and_initialise()

        candidate.close.assert_awaited_once()
        self.assertIsNone(client._connection)
        self.assertFalse(client._connection_ready)

    async def test_concurrent_initialisation_opens_one_socket(self) -> None:
        """Concurrent callers must share one initialised connection."""
        client = self._client()
        candidate = _websocket()
        initialisation_started = asyncio.Event()
        finish_initialisation = asyncio.Event()

        async def initialise(connection) -> None:
            self.assertIs(connection, candidate)
            initialisation_started.set()
            await finish_initialisation.wait()

        client.async_connect = AsyncMock(return_value=candidate)
        client._initialise_connection = AsyncMock(side_effect=initialise)

        first = asyncio.create_task(client.async_connect_and_initialise())
        await initialisation_started.wait()
        second = asyncio.create_task(client.async_connect_and_initialise())
        await asyncio.sleep(0)
        finish_initialisation.set()

        first_result, second_result = await asyncio.gather(first, second)

        self.assertIs(first_result, candidate)
        self.assertIs(second_result, candidate)
        client.async_connect.assert_awaited_once()
        self.assertTrue(client._connection_ready)

    async def test_cancelled_initialisation_closes_candidate(self) -> None:
        """Cancellation during initialisation must also close the candidate."""
        client = self._client()
        candidate = _websocket()
        initialisation_started = asyncio.Event()

        async def initialise(_connection) -> None:
            initialisation_started.set()
            await asyncio.Event().wait()

        client.async_connect = AsyncMock(return_value=candidate)
        client._initialise_connection = AsyncMock(side_effect=initialise)

        initialisation = asyncio.create_task(client.async_connect_and_initialise())
        await initialisation_started.wait()
        initialisation.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await initialisation

        candidate.close.assert_awaited_once()
        self.assertIsNone(client._connection)
        self.assertFalse(client._connection_ready)

    async def test_each_failed_reconnect_candidate_is_closed(self) -> None:
        """Every failed backoff attempt must clean up its candidate socket."""
        client = self._client()
        candidates = [_websocket(), _websocket()]
        client._max_reconnect_attempts = len(candidates)
        client._reconnect_delay = 0
        client._max_reconnect_delay = 0
        client.async_connect = AsyncMock(side_effect=candidates)
        client._initialise_connection = AsyncMock(
            side_effect=RuntimeError("init failed")
        )
        client._wait_or_shutdown = AsyncMock(return_value=False)

        self.assertFalse(await client._reconnect_with_backoff())

        for candidate in candidates:
            candidate.close.assert_awaited_once()
        self.assertIsNone(client._connection)
        self.assertFalse(client._connection_ready)

    async def test_concurrent_reconnects_share_one_connection(self) -> None:
        """Concurrent reconnect callers must create one replacement socket."""
        client = self._client()
        candidate = _websocket()
        reconnect_started = asyncio.Event()
        finish_reconnect = asyncio.Event()

        async def connect():
            reconnect_started.set()
            await finish_reconnect.wait()
            return candidate

        client.async_connect = AsyncMock(side_effect=connect)
        client._initialise_connection = AsyncMock()
        client._wait_or_shutdown = AsyncMock(return_value=False)

        first = asyncio.create_task(client._reconnect_with_backoff())
        await reconnect_started.wait()
        second = asyncio.create_task(client._reconnect_with_backoff())
        await asyncio.sleep(0)
        finish_reconnect.set()

        first_result, second_result = await asyncio.gather(first, second)

        self.assertTrue(first_result)
        self.assertTrue(second_result)
        client.async_connect.assert_awaited_once()
        self.assertIs(client._connection, candidate)
        self.assertTrue(client._connection_ready)

    async def test_writer_uses_managed_reconnect_after_send_failure(self) -> None:
        """A writer must not create or assign a replacement socket itself."""
        client = self._client()
        failed = _websocket()
        replacement = _websocket()
        failed.send_bytes = AsyncMock(side_effect=ConnectionResetError("lost"))
        client._connection = failed
        client._connection_ready = True

        async def reconnect() -> bool:
            client._connection = replacement
            client._connection_ready = True
            return True

        client._reconnect_with_backoff = AsyncMock(side_effect=reconnect)
        client._wait_or_shutdown = AsyncMock(return_value=False)

        await client.send_bytes(b"request", max_retries=1, retry_delay=0)

        client._reconnect_with_backoff.assert_awaited_once()
        replacement.send_bytes.assert_awaited_once_with(b"request")


class TestDevicePolling(IsolatedAsyncioTestCase):
    """Exercise adaptive polling URL construction."""

    def _client(self) -> TydomClient:
        return TydomClient(None, "test", "001122334455", "password", host="local")

    async def test_explicit_protocol_ids_use_correct_url_positions(self) -> None:
        """Canonical device and endpoint ids must retain their URL positions."""
        client = self._client()
        client.get_poll_device_data = AsyncMock()

        await client.poll_device_data(8, 0)

        client.get_poll_device_data.assert_awaited_once_with(
            "/devices/8/endpoints/0/data"
        )

    async def test_composite_key_uses_endpoint_then_device_order(self) -> None:
        """A legacy registry-key call must use endpoint-then-device order."""
        client = self._client()
        client.get_poll_device_data = AsyncMock()

        await client.poll_device_data("3_42")

        client.get_poll_device_data.assert_awaited_once_with(
            "/devices/42/endpoints/3/data"
        )

    async def test_plain_device_id_uses_same_endpoint_id(self) -> None:
        """A plain device id must retain the legacy device endpoint form."""
        client = self._client()
        client.get_poll_device_data = AsyncMock()

        await client.poll_device_data("8")

        client.get_poll_device_data.assert_awaited_once_with(
            "/devices/8/endpoints/8/data"
        )

    async def test_cdata_poll_can_target_one_energy_endpoint(self) -> None:
        """An entity refresh button must poll only its own TYWATT endpoint."""
        client = self._client()
        client.get_poll_device_data = AsyncMock()
        client.poll_device_urls_5m = [
            "/devices/10/endpoints/20/cdata?name=energyInstant&unit=ELEC_A",
            "/devices/11/endpoints/21/cdata?name=energyInstant&unit=ELEC_A",
        ]

        await client.poll_devices_data_5m("10", "20")

        client.get_poll_device_data.assert_awaited_once_with(
            "/devices/10/endpoints/20/cdata?name=energyInstant&unit=ELEC_A"
        )

    async def test_cdata_poll_continues_after_one_endpoint_fails(self) -> None:
        """One rejected cdata request must not prevent later URLs from polling."""
        client = self._client()
        first_url = "/devices/10/endpoints/20/cdata?name=energyIndex"
        second_url = "/devices/11/endpoints/21/cdata?name=energyIndex"
        client.poll_device_urls_5m = [first_url, second_url]
        client.get_poll_device_data = AsyncMock(
            side_effect=[RuntimeError("rejected"), None]
        )

        await client.poll_devices_data_5m()

        self.assertEqual(
            client.get_poll_device_data.await_args_list,
            [call(first_url), call(second_url)],
        )
