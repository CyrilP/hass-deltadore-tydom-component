"""Tests for serialised Tydom websocket connection ownership."""

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, call

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


class _WebSocketResponse:
    """Stand-in used only to evaluate runtime annotations."""


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
