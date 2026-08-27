"""Tydom API Client."""

import asyncio
import base64
import json
import os
import re
import socket
import ssl
import time
import traceback
from typing import TYPE_CHECKING, cast
from urllib.parse import quote

import aiohttp
import async_timeout
from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from requests.auth import HTTPDigestAuth
from urllib3 import encode_multipart_formdata

from ..const import (
    LOGGER,
    validate_value_with_metadata,
    TIMEOUT_NORMAL_REQUEST,
    TIMEOUT_LONG_REQUEST,
    TIMEOUT_WEBSOCKET_CONNECT,
    TIMEOUT_WEBSOCKET_RECEIVE,
    TIMEOUT_PING,
    STRUCTURED_LOGGER,
)
from .const import (
    DELTADORE_API_SITES,
    DELTADORE_AUTH_CLIENTID,
    DELTADORE_AUTH_GRANT_TYPE,
    DELTADORE_AUTH_SCOPE,
    DELTADORE_AUTH_URL,
    MEDIATION_URL,
)
from .MessageHandler import MessageHandler
from .tydom_devices import TydomAlarmCommandError

if TYPE_CHECKING:
    from .tydom_devices import TydomDevice


def sanitize_log_message(message: str, password: str | None = None) -> str:
    """Masquer les informations sensibles dans les messages de log."""
    import re

    sanitized = str(message)

    # Masquer le mot de passe s'il est présent
    if password:
        sanitized = sanitized.replace(password, "***")
        sanitized = sanitized.replace(f'"{password}"', '"***"')
        sanitized = sanitized.replace(f"'{password}'", "'***'")

    # Masquer les patterns de mots de passe dans les JSON/strings
    sanitized = re.sub(
        r'"password"\s*:\s*"[^"]*"', '"password":"***"', sanitized, flags=re.IGNORECASE
    )
    sanitized = re.sub(
        r'"pwd"\s*:\s*"[^"]*"', '"pwd":"***"', sanitized, flags=re.IGNORECASE
    )
    sanitized = re.sub(
        r'"access_token"\s*:\s*"[^"]*"',
        '"access_token":"***"',
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r'"token"\s*:\s*"[^"]*"', '"token":"***"', sanitized, flags=re.IGNORECASE
    )

    # Masquer les patterns dans les URLs ou headers
    sanitized = re.sub(
        r'(password|pwd|passwd|token|access_token)\s*[=:]\s*[^\s"\'<>]+',
        r"\1=***",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"Bearer\s+[A-Za-z0-9\-._~+/]+", "Bearer ***", sanitized, flags=re.IGNORECASE
    )

    return sanitized


class TydomClientApiClientError(Exception):
    """Exception to indicate a general API error."""


class TydomClientApiClientCommunicationError(TydomClientApiClientError):
    """Exception to indicate a communication error."""


class TydomClientApiClientAuthenticationError(TydomClientApiClientError):
    """Exception to indicate an authentication error."""


proxy = None

# DEBUG ONLY — replaces websocket with a local trace file
file_mode = False
file_lines = None
file_index = 0
file_name = os.path.join(os.environ.get("HA_CONFIG_DIR", "/config"), "traces.txt")


class TydomClient:
    """Tydom API Client."""

    def __init__(
        self,
        hass,
        id: str,
        mac: str,
        password: str,
        alarm_pin: str | None = None,
        zone_away: str | None = None,
        zone_home: str | None = None,
        zone_night: str | None = None,
        host: str = MEDIATION_URL,
        event_callback=None,
    ) -> None:
        """Initialise client."""
        LOGGER.debug("Initialising TydomClient Class")

        self._hass = hass
        self.id = id
        self._password = password
        self._mac = mac
        self._host = host
        self._zone_home = zone_home
        self._zone_away = zone_away
        self._zone_night = zone_night
        self._alarm_pin = alarm_pin
        self._remote_mode = self._host == MEDIATION_URL
        self._connection: ClientWebSocketResponse | None = None
        self._connection_ready = False
        self._connection_lock = asyncio.Lock()
        self._initialising_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self.event_callback = event_callback
        # Some devices (like Tywatt) need polling
        self.poll_device_urls_1s = []
        self.poll_device_urls_5m = []
        self.current_poll_index = 0
        self.pending_pings = 0

        if self._remote_mode:
            LOGGER.info("Configure remote mode (%s)", self._host)
            self._cmd_prefix = b"\x02"
            self._ping_timeout = TIMEOUT_PING
        else:
            LOGGER.info("Configure local mode (%s)", self._host)
            self._cmd_prefix = b""
            self._ping_timeout = None

        self._message_handler = MessageHandler(
            tydom_client=self, cmd_prefix=self._cmd_prefix
        )

        # Reconnection parameters with exponential backoff
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        self._reconnect_backoff_factor = 2.0
        self.online = True
        self._shutting_down = False

        # Metadata cache with TTL (Time To Live)
        self._metadata_cache: dict[
            str, tuple[float, bool]
        ] = {}  # endpoint -> (timestamp, is_valid)
        self._metadata_cache_ttl = 3600.0  # 1 hour in seconds

    def update_config(self, zone_home: str, zone_away: str, zone_night: str):
        """Update zones configuration."""
        self._zone_home = zone_home
        self._zone_away = zone_away
        self._zone_night = zone_night

    @staticmethod
    async def async_get_credentials(
        session: ClientSession, email: str, password: str, macaddress: str
    ):
        """Get tydom credentials from Delta Dore."""
        if file_mode:
            return "dummyPassword"
        try:
            async with async_timeout.timeout(TIMEOUT_LONG_REQUEST):
                response = await session.request(
                    method="GET", url=DELTADORE_AUTH_URL, proxy=proxy
                )

                LOGGER.debug(
                    "response status for openid-config: %s\nheaders : %s\ncontent : %s",
                    response.status,
                    response.headers,
                    await response.text(),
                )

                json_response = await response.json()
                response.close()
                signin_url = json_response["token_endpoint"]
                LOGGER.info("signin_url : %s", signin_url)

                body, ct_header = encode_multipart_formdata(
                    {
                        "username": f"{email}",
                        "password": f"{password}",
                        "grant_type": DELTADORE_AUTH_GRANT_TYPE,
                        "client_id": DELTADORE_AUTH_CLIENTID,
                        "scope": DELTADORE_AUTH_SCOPE,
                    }
                )

                response = await session.post(
                    url=signin_url,
                    headers={"Content-Type": ct_header},
                    data=body,
                    proxy=proxy,
                )

                response_text = await response.text()
                sanitized_content = sanitize_log_message(response_text, password)
                LOGGER.debug(
                    "response status for signin : %s\nheaders : %s\ncontent : %s",
                    response.status,
                    response.headers,
                    sanitized_content,
                )

                json_response = await response.json()
                response.close()
                access_token = json_response["access_token"]

                response = await session.request(
                    method="GET",
                    url=DELTADORE_API_SITES + macaddress,
                    headers={"Authorization": f"Bearer {access_token}"},
                    proxy=proxy,
                )

                response_text = await response.text()
                # Le contenu peut contenir le mot de passe Tydom, le masquer
                sanitized_content = sanitize_log_message(response_text)
                LOGGER.debug(
                    "response status for https://prod.iotdeltadore.com/sitesmanagement/api/v1/sites?gateway_mac= : %s\nheaders : %s\ncontent : %s",
                    response.status,
                    response.headers,
                    sanitized_content,
                )

                json_response = await response.json()
                response.close()

                if "sites" in json_response and len(json_response["sites"]) > 0:
                    for site in json_response["sites"]:
                        if "gateway" in site and site["gateway"]["mac"] == macaddress:
                            password = json_response["sites"][0]["gateway"]["password"]
                            return password
                raise TydomClientApiClientAuthenticationError(
                    "Tydom credentials not found"
                )
        except TimeoutError as exception:
            raise TydomClientApiClientCommunicationError(
                "Timeout error fetching information",
            ) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            raise TydomClientApiClientCommunicationError(
                "Error fetching information",
            ) from exception
        except Exception as exception:  # pylint: disable=broad-except
            traceback.print_exception(
                type(exception), exception, exception.__traceback__
            )
            raise TydomClientApiClientError(
                "Something really wrong happened!"
            ) from exception

    async def async_connect(self) -> ClientWebSocketResponse:
        """Connect to the Tydom API."""
        global file_lines, file_mode, file_name
        if self._shutting_down:
            raise asyncio.CancelledError()
        self.pending_pings = 0
        if file_mode:
            with open(file_name) as file:
                file_lines = file.readlines()

            # Return a dummy connection for file mode
            # This should not happen in production, but we need to satisfy the type checker
            raise RuntimeError("File mode not supported for async_connect")

        http_headers = {
            "Connection": "Upgrade",
            "Upgrade": "websocket",
            "Host": self._host + ":443",
            "Accept": "*/*",
            "Sec-WebSocket-Key": self.generate_random_key(),
            "Sec-WebSocket-Version": "13",
        }

        # - Wrap slow blocking call flagged by HA
        sslcontext = await asyncio.to_thread(ssl.create_default_context)
        sslcontext.options |= 0x4  # OP_LEGACY_SERVER_CONNECT
        if self._host == MEDIATION_URL:
            # Cloud mode: enforce TLS verification against the public CA chain
            sslcontext.check_hostname = True
            sslcontext.verify_mode = ssl.CERT_REQUIRED
        else:
            # Local mode: Tydom gateway uses a self-signed certificate
            sslcontext.check_hostname = False
            sslcontext.verify_mode = ssl.CERT_NONE

        session = async_create_clientsession(self._hass, False)

        try:
            # Digest handshake can be very slow on busy local gateways (tydom2mqtt
            # applies no timeout to the equivalent HTTP step).
            async with async_timeout.timeout(TIMEOUT_LONG_REQUEST):
                response = await session.request(
                    method="GET",
                    url=f"https://{self._host}:443/mediation/client?mac={self._mac}&appli=1",
                    headers=http_headers,
                    json=None,
                    proxy=proxy,
                    ssl=sslcontext,
                )
                LOGGER.debug(
                    "response status : %s\nheaders : %s\ncontent : %s",
                    response.status,
                    response.headers,
                    await response.text(),
                )

                www_authenticate = response.headers.get("WWW-Authenticate")
                if www_authenticate is None:
                    response.close()
                    raise TydomClientApiClientError(
                        "Could't find WWW-Authenticate header"
                    )

                re_matcher = re.match(
                    '.*nonce="([a-zA-Z0-9+=]+)".*',
                    www_authenticate,
                )
                response.close()

                if re_matcher:
                    pass
                else:
                    raise TydomClientApiClientError("Could't find auth nonce")

                ws_headers = {
                    "Authorization": self.build_digest_headers(re_matcher.group(1))
                }

            connection = await session.ws_connect(
                method="GET",
                url=f"wss://{self._host}:443/mediation/client?mac={self._mac}&appli=1",
                headers=ws_headers,
                autoping=True,
                heartbeat=2.0,
                timeout=TIMEOUT_WEBSOCKET_CONNECT,  # type: ignore[arg-type]
                receive_timeout=TIMEOUT_WEBSOCKET_RECEIVE,
                autoclose=True,
                proxy=proxy,
                ssl=sslcontext,
            )

            return connection

        except TimeoutError as exception:
            raise TydomClientApiClientCommunicationError(
                "Timeout error fetching information",
            ) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            raise TydomClientApiClientCommunicationError(
                "Error fetching information",
            ) from exception
        except Exception as exception:  # pylint: disable=broad-except
            traceback.print_exception(exception)
            raise TydomClientApiClientError(
                "Something really wrong happened!"
            ) from exception

    def begin_shutdown(self) -> None:
        """Signal that the client must stop reconnecting and using the socket."""
        self._shutting_down = True
        self._shutdown_event.set()

    async def _wait_or_shutdown(self, delay: float) -> bool:
        """Wait for a delay and return whether shutdown interrupted the wait."""
        if self._shutting_down:
            return True
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=delay)
        except TimeoutError:
            return False
        return True

    async def _safe_close_connection(
        self, connection: ClientWebSocketResponse | None
    ) -> None:
        """Close a websocket without allowing cleanup errors to escape."""
        if connection is None or connection.closed:
            return
        try:
            await asyncio.wait_for(connection.close(), timeout=3.0)
        except TimeoutError:
            LOGGER.warning("Timed out closing Tydom websocket")
        except Exception:
            LOGGER.exception("Error closing Tydom websocket")

    def _connection_is_usable(self, connection: ClientWebSocketResponse | None) -> bool:
        """Return whether a websocket is the active, initialised connection."""
        return (
            connection is not None
            and connection is self._connection
            and not connection.closed
            and self._connection_ready
        )

    async def _connect_and_initialise_locked(self) -> ClientWebSocketResponse:
        """Create and initialise the sole active websocket while holding the lock."""
        previous = self._connection
        self._connection = None
        self._connection_ready = False
        await self._safe_close_connection(previous)

        candidate: ClientWebSocketResponse | None = None
        initialising_task = asyncio.current_task()
        try:
            candidate = await self.async_connect()
            self._connection = candidate
            self._initialising_task = initialising_task
            await self._initialise_connection(candidate)
        except BaseException:
            if self._connection is candidate:
                self._connection = None
            self._connection_ready = False
            await self._safe_close_connection(candidate)
            raise
        finally:
            if self._initialising_task is initialising_task:
                self._initialising_task = None

        if self._shutting_down:
            if self._connection is candidate:
                self._connection = None
            await self._safe_close_connection(candidate)
            raise asyncio.CancelledError()

        self._connection_ready = True
        self.online = True
        return candidate

    async def async_connect_and_initialise(self) -> ClientWebSocketResponse:
        """Establish the initial managed websocket connection."""
        async with self._connection_lock:
            if self._connection_is_usable(self._connection):
                return self._connection
            return await self._connect_and_initialise_locked()

    async def async_disconnect(self) -> None:
        """Close the active websocket connection, if any."""
        self.begin_shutdown()
        async with self._connection_lock:
            connection = self._connection
            self._connection = None
            self._connection_ready = False
            await self._safe_close_connection(connection)

    async def _initialise_connection(self, connection: ClientWebSocketResponse) -> None:
        """Send initial requests on the active candidate websocket."""
        if self._shutting_down:
            return
        STRUCTURED_LOGGER.connection_event(
            "info",
            "listen_started",
            host=self._host,
            mode="remote" if self._remote_mode else "local",
        )
        if connection is not self._connection:
            raise TydomClientApiClientCommunicationError(
                "Cannot initialise a websocket that is not the active candidate"
            )
        await self.ping()
        if self._shutting_down:
            return
        await self.get_info()
        if self._shutting_down:
            return
        # await self.put_api_mode()
        # await self.get_geoloc()
        # await self.get_local_claim()
        # await self.get_devices_meta()
        # await self.get_areas_meta()
        # await self.get_devices_cmeta()
        # await self.get_areas_cmeta()
        # await self.get_devices_data()
        # await self.get_areas_data()
        # await self.post_refresh()

        # await self.get_info()
        await self.post_refresh()
        await self.get_configs_file()
        await self.get_groups()
        if self._shutting_down:
            return
        await self.get_devices_meta()
        await self.get_devices_cmeta()
        await self.get_devices_data()
        await self.get_areas_data()
        if self._shutting_down:
            return

        await self.get_scenarii()

    async def _reconnect_with_backoff(self) -> bool:
        """Reconnect with exponential backoff strategy.

        This method implements an exponential backoff reconnection strategy
        to avoid overwhelming the server with reconnection attempts. The delay
        between attempts increases exponentially: delay = base_delay * (factor ^ attempt).
        The delay is capped at max_reconnect_delay to prevent excessive wait times.

        The reconnection process:
        1. Calculate delay based on attempt number
        2. Wait for the calculated delay
        3. Attempt to connect and listen
        4. If successful, reset attempts counter and mark as online
        5. If failed, increment attempts and retry (up to max_attempts)

        Raises:
            None: Exceptions are logged but do not propagate. The method
                  will stop after max_reconnect_attempts and mark client as offline.

        """
        if self._shutting_down:
            return False

        async with self._connection_lock:
            # Another reader or writer may have restored the connection while this
            # coroutine was waiting for ownership of the reconnect operation.
            if self._connection_is_usable(self._connection):
                return True

            failed_connection = self._connection
            self._connection = None
            self._connection_ready = False
            await self._safe_close_connection(failed_connection)

            for attempt in range(1, self._max_reconnect_attempts + 1):
                self._reconnect_attempts = attempt
                delay = min(
                    self._reconnect_delay
                    * (self._reconnect_backoff_factor ** (attempt - 1)),
                    self._max_reconnect_delay,
                )
                STRUCTURED_LOGGER.connection_event(
                    "info",
                    "reconnect_attempt",
                    attempt=attempt,
                    max_attempts=self._max_reconnect_attempts,
                    delay_seconds=delay,
                )
                if await self._wait_or_shutdown(delay):
                    return False

                try:
                    await self._connect_and_initialise_locked()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    STRUCTURED_LOGGER.connection_event(
                        "warning",
                        "reconnect_failed",
                        attempt=attempt,
                        max_attempts=self._max_reconnect_attempts,
                        error=str(e),
                    )
                    continue

                self._reconnect_attempts = 0
                STRUCTURED_LOGGER.connection_event(
                    "info",
                    "reconnect_success",
                    attempt=attempt,
                    total_attempts=attempt,
                )
                return True

            LOGGER.error(
                "Impossible de se reconnecter après %d tentatives; "
                "nouvelle tentative dans 60 secondes",
                self._max_reconnect_attempts,
            )
            self.online = False
            self._reconnect_attempts = 0
            await self._wait_or_shutdown(60)
            return False

    async def consume_messages(self) -> list["TydomDevice"] | None:
        """Read and parse incoming messages."""
        global file_lines, file_mode, file_index
        if file_mode:
            if file_lines is not None and len(file_lines) > file_index:
                incoming = (
                    file_lines[file_index].replace("\\r", "\x0d").replace("\\n", "\x0a")
                )
                incoming_bytes_str = incoming.encode("utf-8")
                file_index += 1
                sanitized_msg = sanitize_log_message(
                    incoming_bytes_str.decode("utf-8", errors="replace"), self._password
                )
                LOGGER.info("Incomming message - message : %s", sanitized_msg)
            else:
                await asyncio.sleep(10)
                return None
            await asyncio.sleep(1)
            return await self._message_handler.route_response(incoming_bytes_str)
        try:
            if self._shutting_down:
                return None
            connection = self._connection
            if connection is None or not self._connection_ready:
                await self._reconnect_with_backoff()
                return None
            if connection.closed or self.pending_pings > 5:
                if self._shutting_down:
                    return None
                LOGGER.warning(
                    "Reconnecting Tydom client (reason: %s)",
                    "websocket closed"
                    if connection.closed
                    else f"{self.pending_pings} pending pings",
                )
                if connection is self._connection:
                    self._connection_ready = False
                await self._reconnect_with_backoff()
                return None

            msg = await connection.receive()
            # Masquer les informations sensibles dans les messages entrants
            msg_data_str = (
                msg.data.decode("utf-8", errors="replace")
                if isinstance(msg.data, bytes)
                else str(msg.data)
            )
            sanitized_msg = sanitize_log_message(msg_data_str, self._password)
            LOGGER.info(
                "Incoming message - type : %s - message : %s", msg.type, sanitized_msg
            )

            if (
                msg.type == WSMsgType.CLOSE
                or msg.type == WSMsgType.CLOSED
                or msg.type == WSMsgType.CLOSING
            ):
                LOGGER.debug("Close message type received")
                return None
            elif msg.type == WSMsgType.ERROR:
                LOGGER.debug("Error message type received")
                return None
            elif msg.type == WSMsgType.PING or msg.type == WSMsgType.PONG:
                LOGGER.debug("Ping/Pong message type received")
                return None

            incoming_bytes_str = cast(bytes, msg.data)

            return await self._message_handler.route_response(incoming_bytes_str)

        except asyncio.CancelledError:
            raise
        except Exception:
            # Ne pas logger le message complet pour éviter d'exposer des informations sensibles
            LOGGER.exception("Unable to handle message")
            return None

    def receive_pong(self) -> None:
        """Handle a pong response and keep the pending ping counter non-negative."""
        self.pending_pings = max(0, self.pending_pings - 1)

    def build_digest_headers(self, nonce):
        """Build the headers of Digest Authentication."""
        digest_auth = HTTPDigestAuth(self._mac, self._password)
        chal = {}
        chal["nonce"] = nonce
        chal["realm"] = (
            "ServiceMedia" if self._remote_mode is True else "protected area"
        )
        chal["qop"] = "auth"
        digest_auth._thread_local.chal = chal
        digest_auth._thread_local.last_nonce = nonce
        digest_auth._thread_local.nonce_count = 1
        digest = digest_auth.build_digest_header(
            "GET",
            f"https://{self._host}:443/mediation/client?mac={self._mac}&appli=1",
        )
        return digest

    async def send_bytes(
        self, a_bytes: bytes, max_retries: int = 3, retry_delay: float = 1.0
    ) -> None:
        """Send bytes to connection with intelligent retry mechanism.

        Args:
            a_bytes: Bytes to send
            max_retries: Maximum number of retry attempts
            retry_delay: Initial delay between retries (exponential backoff)

        """
        if file_mode:
            return

        if self._shutting_down:
            raise asyncio.CancelledError()

        last_exception: Exception | None = None
        for attempt in range(max_retries + 1):
            initialising = asyncio.current_task() is self._initialising_task
            connection = self._connection

            if not initialising and not self._connection_is_usable(connection):
                if not await self._reconnect_with_backoff():
                    raise TydomClientApiClientCommunicationError(
                        "No initialised Tydom connection is available"
                    )
                connection = self._connection

            if connection is None or connection.closed:
                raise TydomClientApiClientCommunicationError(
                    "No open Tydom connection is available"
                )

            try:
                await connection.send_bytes(a_bytes)
                if attempt > 0:
                    LOGGER.info(
                        "Successfully sent message after %d retry attempt(s)",
                        attempt,
                    )
                return
            except (aiohttp.ClientConnectionError, ConnectionResetError, OSError) as e:
                last_exception = e

                # Initialisation owns the connection lock. Let its caller close the
                # failed candidate and perform the next backoff attempt rather than
                # recursively trying to acquire the same lock here.
                if initialising:
                    raise TydomClientApiClientCommunicationError(
                        "Connection failed while initialising the Tydom websocket"
                    ) from e

                if connection is self._connection:
                    self._connection_ready = False

                if attempt < max_retries:
                    delay = retry_delay * (2**attempt)  # Exponential backoff
                    LOGGER.warning(
                        "Connection error (attempt %d/%d): %s. Retrying in %.1f seconds...",
                        attempt + 1,
                        max_retries + 1,
                        str(e),
                        delay,
                    )
                    if await self._wait_or_shutdown(delay):
                        raise asyncio.CancelledError()
                else:
                    LOGGER.error(
                        "Cannot send message to Tydom after %d attempts. Connection was lost: %s",
                        max_retries + 1,
                        str(e),
                    )
            except Exception as e:
                if connection.closed:
                    last_exception = e
                    if connection is self._connection:
                        self._connection_ready = False
                    if initialising:
                        raise TydomClientApiClientCommunicationError(
                            "Connection closed while initialising the Tydom websocket"
                        ) from e
                    continue
                # For other exceptions, don't retry
                LOGGER.error(
                    "Unexpected error sending message to Tydom: %s",
                    str(e),
                    exc_info=True,
                )
                raise

        # If we get here, all retries failed
        if last_exception:
            raise TydomClientApiClientCommunicationError(
                f"Failed to send message after {max_retries + 1} attempts"
            ) from last_exception

    async def send_message(self, method, msg):
        """Send Generic message to Tydom."""
        # Transaction ID is currently the current time in ms
        transaction_id = str(time.time_ns())[:13]
        message = (
            method
            + " "
            + msg
            + f" HTTP/1.1\r\nContent-Length: 0\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: {transaction_id}\r\n\r\n"
        )
        a_bytes = self._cmd_prefix + bytes(message, "ascii")
        LOGGER.debug(
            "Sending message to tydom (%s %s)",
            method,
            msg if "pwd" not in msg else "***",
        )
        if not file_mode:
            await self.send_bytes(a_bytes)

    async def send_request(
        self,
        method: str,
        url: str,
        body: dict | bytes | None = None,
        headers: dict | None = None,
    ) -> str:
        """Send request.

        Args:
            method: Request method
            url: Request URL
            body: Request body
            headers: Request headers

        Returns:
            The request transaction ID.

        """
        transaction_id, request = self._message_handler.prepare_request(
            method, url, body, headers
        )
        await self.send_bytes(request)

        return transaction_id

    async def get_reply_to_request(
        self,
        method: str,
        url: str,
        body: dict | bytes | None = None,
        headers: dict | None = None,
        timeout: float = TIMEOUT_NORMAL_REQUEST,
        log_timeout: bool = True,
    ) -> list[dict] | None:
        """Send request and wait for its reply with timeout handling.

        Args:
            method: Request method
            url: Request URL
            body: Request body
            headers: Request headers
            timeout: Timeout in seconds (default: 30.0)
            log_timeout: Log an expected timeout as a warning when true.

        Returns:
            List of reply events or None

        Raises:
            TydomClientApiClientCommunicationError: If timeout or communication error occurs

        """
        event = asyncio.Event()
        # Some official TYXAL configuration endpoints carry the alarm PIN in
        # the query string.  Always redact sensitive query parameters before
        # the URL reaches a log message or an exception.
        safe_url = sanitize_log_message(url)

        transaction_id, request = self._message_handler.prepare_request(
            method, url, body, headers, reply_event=event
        )

        try:
            await self.send_bytes(request)
        except Exception as e:
            LOGGER.error(
                "Failed to send request %s %s: %s",
                method,
                safe_url,
                str(e),
                exc_info=True,
            )
            raise TydomClientApiClientCommunicationError(
                f"Failed to send request {method} {safe_url}: {str(e)}"
            ) from e

        # Wait for the reply with timeout
        try:
            async with async_timeout.timeout(timeout):
                await event.wait()
        except TimeoutError:
            log_method = LOGGER.warning if log_timeout else LOGGER.debug
            log_method(
                "Timeout waiting for reply to %s %s (transaction_id: %s, timeout: %.1fs)",
                method,
                safe_url,
                transaction_id,
                timeout,
            )
            # Remove the pending reply to avoid memory leak
            self._message_handler.remove_reply(transaction_id)
            raise TydomClientApiClientCommunicationError(
                f"Timeout waiting for reply to {method} {safe_url}"
            )

        if error := self._message_handler.get_reply_error(transaction_id):
            raise TydomClientApiClientCommunicationError(
                f"Request {method} {safe_url} failed: {error}"
            )

        reply = self._message_handler.get_reply(transaction_id)

        if reply is None:
            LOGGER.warning(
                "No reply received for %s %s (transaction_id: %s)",
                method,
                safe_url,
                transaction_id,
            )
            return None

        return reply["events"] if reply else None

    # ########################
    # Utils methods
    # ########################

    @staticmethod
    def generate_random_key():
        """Generate 16 bytes random key for Sec-WebSocket-Key and convert it to base64."""
        return str(base64.b64encode(os.urandom(16)))

    # ########################
    # Tydom messages
    # ########################
    async def get_info(self):
        """Ask some information from Tydom."""
        msg_type = "/info"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def post_device_install(self, payload: dict[str, str | int]) -> None:
        """Start the gateway's generic product-association workflow.

        ``/devices/install`` is the endpoint used by the official application
        for TYDOM and Tywell product discovery.  It is deliberately a generic
        request (not a write to an already discovered device).
        """
        required = {"protocol", "type", "profile"}
        missing = required.difference(payload)
        if missing:
            raise ValueError(
                "Product association payload is missing: " + ", ".join(sorted(missing))
            )
        await self.get_reply_to_request("POST", "/devices/install", body=payload)

    async def delete_device(self, device_id: str | int) -> None:
        """Delete one product from the TYDOM gateway inventory."""
        safe_device_id = quote(str(device_id), safe="")
        await self.get_reply_to_request("DELETE", f"/devices/{safe_device_id}")

    async def get_local_claim(self):
        """Ask some information from Tydom."""
        msg_type = "/configs/gateway/local_claim"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def get_geoloc(self):
        """Ask some information from Tydom."""
        msg_type = "/configs/gateway/geoloc"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def put_api_mode(self):
        """Use Tydom API mode."""
        msg_type = "/configs/gateway/api_mode"
        req = "PUT"
        await self.send_message(method=req, msg=msg_type)

    async def post_refresh(self):
        """Refresh (all)."""
        msg_type = "/refresh/all"
        req = "POST"
        await self.send_message(method=req, msg=msg_type)

    async def ping(self):
        """Send a ping (pong should be returned)."""
        msg_type = "/ping"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)
        self.pending_pings += 1

    async def get_devices_meta(self, force_refresh: bool = False):
        """Get all devices metadata.

        This method retrieves metadata for all devices from the Tydom API.
        The metadata includes information about device attributes such as:
        - Type (numeric, boolean, string, etc.)
        - Permissions (read, write, read-write)
        - Validity periods (for polling decisions)
        - Min/max/step values (for numeric attributes)
        - Enum values (for string attributes)

        The results are cached for 1 hour (metadata_cache_ttl) to reduce
        API calls. Use force_refresh=True to bypass the cache.

        Args:
            force_refresh: If True, force refresh even if cache is valid (default: False)

        """
        # Check cache if not forcing refresh
        if not force_refresh:
            current_time = time.time()
            cache_key = "devices_meta"
            if cache_key in self._metadata_cache:
                timestamp, is_valid = self._metadata_cache[cache_key]
                if current_time - timestamp < self._metadata_cache_ttl and is_valid:
                    LOGGER.debug(
                        "Using cached devices metadata (age: %.1fs)",
                        current_time - timestamp,
                    )
                    return

        # Cache expired or force refresh, fetch new metadata
        msg_type = "/devices/meta"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

        # Update cache
        self._metadata_cache["devices_meta"] = (time.time(), True)

    async def get_devices_data(self):
        """Get all devices data."""
        msg_type = "/devices/data"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def poll_devices_data_1s(self):
        """Poll devices data."""
        if self.poll_device_urls_1s:
            url = self.poll_device_urls_1s.pop()
            await self.get_poll_device_data(url)

    async def poll_devices_data_5m(
        self, device_id: str | None = None, endpoint_id: str | None = None
    ) -> None:
        """Poll all registered cdata URLs, or those for one endpoint."""
        urls = self.poll_device_urls_5m
        if device_id is not None and endpoint_id is not None:
            prefix = f"/devices/{device_id}/endpoints/{endpoint_id}/"
            urls = [url for url in urls if url.startswith(prefix)]

        for url in urls:
            try:
                await self.get_poll_device_data(url)
            except Exception:
                LOGGER.exception("Error polling cdata endpoint %s", url)

    async def get_configs_file(self):
        """List the devices to get the endpoint id."""
        msg_type = "/configs/file"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def get_devices_cmeta(self, force_refresh: bool = False):
        """Get metadata configuration to list poll devices (like Tywatt).

        This method retrieves configuration metadata that identifies which
        devices require polling and at what intervals. This is particularly
        important for devices like Tywatt (energy monitoring) that don't send
        push updates and must be polled regularly.

        The results are cached for 1 hour (metadata_cache_ttl) to reduce
        API calls. Use force_refresh=True to bypass the cache.

        Args:
            force_refresh: If True, force refresh even if cache is valid (default: False)

        """
        # Check cache if not forcing refresh
        if not force_refresh:
            current_time = time.time()
            cache_key = "devices_cmeta"
            if cache_key in self._metadata_cache:
                timestamp, is_valid = self._metadata_cache[cache_key]
                if current_time - timestamp < self._metadata_cache_ttl and is_valid:
                    LOGGER.debug(
                        "Using cached devices cmeta (age: %.1fs)",
                        current_time - timestamp,
                    )
                    return

        # Cache expired or force refresh, fetch new metadata
        msg_type = "/devices/cmeta"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

        # Update cache
        self._metadata_cache["devices_cmeta"] = (time.time(), True)

    def invalidate_metadata_cache(self, cache_key: str | None = None):
        """Invalidate metadata cache.

        This method allows manual invalidation of the metadata cache. This is
        useful when you know that metadata has changed and you want to force
        a refresh on the next call to get_devices_meta() or get_devices_cmeta().

        Args:
            cache_key: Specific cache key to invalidate (e.g., "devices_meta", "devices_cmeta").
                      If None, invalidates all caches.

        Examples:
            # Invalidate all caches
            client.invalidate_metadata_cache()

            # Invalidate only devices metadata cache
            client.invalidate_metadata_cache("devices_meta")

        """
        if cache_key is None:
            self._metadata_cache.clear()
            LOGGER.debug("All metadata caches invalidated")
        else:
            if cache_key in self._metadata_cache:
                del self._metadata_cache[cache_key]
                LOGGER.debug("Metadata cache invalidated for: %s", cache_key)

    async def get_areas_meta(self):
        """Get areas metadata."""
        msg_type = "/areas/meta"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def get_areas_cmeta(self):
        """Get areas metadata."""
        msg_type = "/areas/cmeta"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def get_areas_data(self):
        """Get areas metadata."""
        msg_type = "/areas/data"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def get_device_data(self, id):
        """Give order to endpoint."""
        # 10 here is the endpoint = the device (shutter in this case) to open.
        safe_device_id = quote(str(id), safe="")
        str_request = f"GET /devices/{safe_device_id}/endpoints/{safe_device_id}/data HTTP/1.1\r\nContent-Length: 0\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
        a_bytes = self._cmd_prefix + bytes(str_request, "ascii")
        LOGGER.debug("Sending message to tydom (%s)", "GET device data")
        if not file_mode:
            await self.send_bytes(a_bytes)

    async def get_poll_device_data(self, url):
        """Poll a device."""
        msg_type = url
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def poll_device_data(self, device_id, endpoint_id=None):
        """Poll data for a single device.

        The hub passes the protocol device and endpoint ids explicitly.
        Plain device ids and composite "<endpoint_id>_<device_id>" registry
        keys remain supported for compatibility.
        """
        if endpoint_id is None:
            parsed_endpoint, separator, parsed_device = str(device_id).partition("_")
            if separator:
                device_id = parsed_device
                endpoint_id = parsed_endpoint
            else:
                endpoint_id = device_id
        safe_device = quote(str(device_id), safe="")
        safe_endpoint = quote(str(endpoint_id), safe="")
        await self.get_poll_device_data(
            f"/devices/{safe_device}/endpoints/{safe_endpoint}/data"
        )

    def add_poll_device_url_1s(self, url):
        """Add a device for polling."""
        if url not in self.poll_device_urls_1s:
            self.poll_device_urls_1s.append(url)

    def add_poll_device_url_5m(self, url):
        """Add a device for polling."""
        if url not in self.poll_device_urls_5m:
            self.poll_device_urls_5m.append(url)

    async def get_moments(self):
        """Get the moments (programs)."""
        msg_type = "/moments/file"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def suspend_moment(self, moment_id: str | int, suspend_to: int = -1) -> None:
        """Suspend or resume a moment/program.

        Args:
            moment_id: The moment/program ID
            suspend_to: Timestamp until which to suspend (-1 for indefinite, 0 to resume)

        Raises:
            TydomClientApiClientCommunicationError: If the request fails

        """
        # Format du body JSON : {"suspend": {"to": suspend_to}}
        suspend_data = {"suspend": {"to": suspend_to}}
        body = json.dumps(suspend_data)

        path = f"/moments/{moment_id}"
        str_request = (
            f"PUT {path} HTTP/1.1\r\nContent-Length: "
            + str(len(body))
            + "\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
            + body
            + "\r\n\r\n"
        )
        a_bytes = self._cmd_prefix + bytes(str_request, "ascii")

        STRUCTURED_LOGGER.api_request(
            "debug", "PUT", path, moment_id=str(moment_id), suspend_to=suspend_to
        )
        LOGGER.debug(
            "Sending suspend_moment request: moment_id=%s, suspend_to=%s",
            moment_id,
            suspend_to,
        )

        try:
            await self.send_bytes(a_bytes)
            LOGGER.debug(
                "Suspend moment request sent successfully: moment_id=%s, suspend_to=%s",
                moment_id,
                suspend_to,
            )
        except Exception as e:
            LOGGER.error(
                "Failed to send suspend_moment request: moment_id=%s, suspend_to=%s, error=%s",
                moment_id,
                suspend_to,
                e,
                exc_info=True,
            )
            raise TydomClientApiClientCommunicationError(
                f"Failed to suspend moment {moment_id}"
            ) from e

    async def get_scenarii(self):
        """Get the scenarios."""
        msg_type = "/scenarios/file"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def activate_scenario(self, scenario_id: str | int):
        """Activate a scenario.

        Args:
            scenario_id: The scenario ID to activate.

        Raises:
            Exception: If the activation request fails.

        """
        # PUT /scenarios/{id}
        msg_type = f"/scenarios/{scenario_id}"
        req = "PUT"

        LOGGER.debug(
            "Sending scenario activation request: method=%s, path=%s, scenario_id=%s",
            req,
            msg_type,
            scenario_id,
        )

        try:
            await self.send_message(method=req, msg=msg_type)
            LOGGER.debug(
                "Scenario activation request sent: scenario_id=%s",
                scenario_id,
            )
        except Exception as e:
            LOGGER.error(
                "Failed to send scenario activation request: scenario_id=%s, error=%s",
                scenario_id,
                e,
                exc_info=True,
            )
            # Re-raise to allow caller to handle the error
            raise

    async def get_groups(self):
        """Get the groups."""
        msg_type = "/groups/file"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def put_devices_data(
        self,
        device_id,
        endpoint_id,
        name,
        value,
        max_retries: int = 2,
    ):
        """Give order (name + value) to endpoint with retry mechanism.

        Args:
            device_id: Device ID
            endpoint_id: Endpoint ID
            name: Attribute name
            value: Attribute value
            max_retries: Maximum number of retry attempts (default: 2)

        Raises:
            TydomClientApiClientCommunicationError: If all retry attempts fail

        """
        # For shutter, value is the percentage of closing
        body = json.dumps([{"name": name, "value": value}])

        safe_device_id = quote(str(device_id), safe="")
        safe_endpoint_id = quote(str(endpoint_id), safe="")
        # endpoint_id is the endpoint = the device (shutter in this case) to
        # open.
        str_request = (
            f"PUT /devices/{safe_device_id}/endpoints/{safe_endpoint_id}/data HTTP/1.1\r\nContent-Length: "
            + str(len(body))
            + "\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
            + body
            + "\r\n\r\n"
        )
        a_bytes = self._cmd_prefix + bytes(str_request, "ascii")

        # Log the command (masking sensitive data)
        log_value = (
            "***" if "pwd" in name.lower() or "password" in name.lower() else value
        )
        LOGGER.debug(
            "Sending command: device_id=%s, endpoint_id=%s, name=%s, value=%s",
            device_id,
            endpoint_id,
            name,
            log_value,
        )

        # Send with retry mechanism
        try:
            await self.send_bytes(a_bytes, max_retries=max_retries)
        except TydomClientApiClientCommunicationError as e:
            LOGGER.error(
                "Failed to send command after retries: device_id=%s, endpoint_id=%s, name=%s, value=%s, error=%s",
                device_id,
                endpoint_id,
                name,
                log_value,
                str(e),
            )
            raise
        LOGGER.debug("Sending message to tydom (%s)", "PUT device data")
        return 0

    async def put_home_hvac_mode(self, mode: str) -> int:
        """Set the zone-level HVAC direction (STOP / HEATING / COOLING).

        Tydom broadcasts the result to all thermostats via per-device
        authorization updates. Per-thermostat hvacMode writes are ignored.
        """
        body = json.dumps({"mode": mode})
        str_request = (
            "PUT /home/hvac/data HTTP/1.1\r\nContent-Length: "
            + str(len(body))
            + "\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
            + body
            + "\r\n\r\n"
        )
        a_bytes = self._cmd_prefix + bytes(str_request, "ascii")
        LOGGER.debug("Sending message to tydom (PUT home hvac data %s)", mode)
        if not file_mode:
            await self.send_bytes(a_bytes)
        return 0

    async def put_area_data(self, area_id, name, value, max_retries: int = 2) -> int:
        """Set one attribute on an area-backed device."""
        body = json.dumps([{"name": name, "value": value}])
        safe_area_id = quote(str(area_id), safe="")
        path = f"/areas/{safe_area_id}/data"
        str_request = (
            f"PUT {path} HTTP/1.1\r\nContent-Length: "
            + str(len(body))
            + "\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
            + body
            + "\r\n\r\n"
        )
        a_bytes = self._cmd_prefix + bytes(str_request, "ascii")
        LOGGER.debug(
            "Sending area command: area_id=%s, name=%s, value=%s",
            area_id,
            name,
            value,
        )
        if not file_mode:
            await self.send_bytes(a_bytes, max_retries=max_retries)
        return 0

    async def put_devices_data_validated(
        self,
        device_id,
        endpoint_id,
        name,
        value,
        device: "TydomDevice | None" = None,
        max_retries: int = 2,
    ):
        """Give order (name + value) to endpoint with validation and retry mechanism.

        This method validates the value against device metadata before sending
        the command. If validation fails, a ValueError is raised. This helps
        prevent sending invalid commands to devices.

        Validation checks:
        - Type compatibility (numeric, boolean, string)
        - Min/max bounds for numeric values
        - Step alignment for numeric values
        - Enum values for string attributes

        If device is None, validation is skipped and the method behaves like
        put_devices_data().

        Args:
            device_id: Device ID
            endpoint_id: Endpoint ID
            name: Attribute name
            value: Attribute value to validate and send
            device: Optional TydomDevice instance for validation (if None, validation is skipped)
            max_retries: Maximum number of retry attempts (default: 2)

        Returns:
            0 on success

        Raises:
            ValueError: If validation fails (with descriptive error message)
            TydomClientApiClientCommunicationError: If all retry attempts fail

        """
        # Validate value if device is provided
        if device is not None:
            is_valid, error_msg = validate_value_with_metadata(device, name, value)
            if not is_valid:
                LOGGER.error(
                    "Validation failed for device_id=%s, name=%s, value=%s: %s",
                    device_id,
                    name,
                    value,
                    error_msg,
                )
                raise ValueError(error_msg or f"Valeur invalide pour {name}: {value}")

        # If validation passed (or device not provided), send the command
        return await self.put_devices_data(
            device_id=device_id,
            endpoint_id=endpoint_id,
            name=name,
            value=value,
            max_retries=max_retries,
        )

    async def put_alarm_cdata(
        self,
        device_id,
        endpoint_id=None,
        alarm_pin=None,
        value=None,
        zone_id=None,
        legacy_zones=False,
    ):
        """Configure alarm mode."""
        if legacy_zones and zone_id not in (None, ""):
            zones_array = str(zone_id).split(",")
            for zone in zones_array:
                await self._put_alarm_cdata(
                    device_id, endpoint_id, alarm_pin, value, zone, legacy_zones
                )
            return

        # Global legacy commands such as disarm have no zone. They still use
        # alarmCmd and must not be dropped by the legacy zone dispatcher.
        await self._put_alarm_cdata(
            device_id, endpoint_id, alarm_pin, value, zone_id, legacy_zones
        )

    async def _put_alarm_cdata(
        self,
        device_id,
        endpoint_id=None,
        alarm_pin=None,
        value=None,
        zone_id=None,
        legacy_zones=False,
    ):
        """Configure alarm mode."""
        # Credits to @mgcrea on github !
        # AWAY # "PUT /devices/{}/endpoints/{}/cdata?name=alarmCmd HTTP/1.1\r\ncontent-length: 29\r\ncontent-type: application/json; charset=utf-8\r\ntransac-id: request_124\r\n\r\n\r\n{"value":"ON","pwd":{}}\r\n\r\n"
        # HOME "PUT /devices/{}/endpoints/{}/cdata?name=zoneCmd HTTP/1.1\r\ncontent-length: 41\r\ncontent-type: application/json; charset=utf-8\r\ntransac-id: request_46\r\n\r\n\r\n{"value":"ON","pwd":"{}","zones":[1]}\r\n\r\n"
        # DISARM "PUT /devices/{}/endpoints/{}/cdata?name=alarmCmd
        # HTTP/1.1\r\ncontent-length: 30\r\ncontent-type: application/json;
        # charset=utf-8\r\ntransac-id:
        # request_7\r\n\r\n\r\n{"value":"OFF","pwd":"{}"}\r\n\r\n"
        # PUT /devices/{}/endpoints/{}/cdata?name=alarmCmd
        #   HTTP/1.1\nContent-Length: 32\nContent-Type: application/json; charset=UTF-8\nTransac-Id: 1739979111409\nUser-Agent: Jakarta Commons-HttpClient/3.1\nHost: mediation.tydom.com:443
        #   {"pwd":"######","value":"PANIC"}

        # variables:
        # id
        # Cmd
        # value
        # pwd
        # zones
        pin = None
        if alarm_pin is None:
            if self._alarm_pin is None:
                LOGGER.warning("Tydom alarm pin is not set!")
            else:
                pin = self._alarm_pin
        else:
            pin = alarm_pin

        if zone_id is None or zone_id == "":
            cmd = "alarmCmd"
            body = {"value": str(value), "pwd": str(pin)}
        elif legacy_zones:
            cmd = "partCmd"
            body = {"value": str(value), "part": str(zone_id)}
        else:
            cmd = "zoneCmd"
            zones = [
                int(zone.strip()) for zone in str(zone_id).split(",") if zone.strip()
            ]
            body = {"value": str(value), "pwd": str(pin), "zones": zones}

        body_json = json.dumps(body)
        safe_device_id = quote(str(device_id), safe="")
        safe_endpoint_id = quote(str(endpoint_id), safe="")
        safe_cmd = quote(cmd, safe="")
        request = (
            f"PUT /devices/{safe_device_id}/endpoints/{safe_endpoint_id}/cdata"
            f"?name={safe_cmd} HTTP/1.1\r\nContent-Length: {len(body_json)}"
            "\r\nContent-Type: application/json; charset=UTF-8"
            "\r\nTransac-Id: 0\r\n\r\n"
            f"{body_json}\r\n\r\n"
        )
        waiter = self._message_handler.create_alarm_command_waiter(
            str(device_id), str(endpoint_id), cmd
        )
        try:
            if not file_mode:
                await self.send_bytes(self._cmd_prefix + request.encode("ascii"))
            try:
                async with async_timeout.timeout(5):
                    reply = await waiter
            except TimeoutError:
                # Older gateways may execute alarm commands without publishing
                # a command result. Preserve that established fire-and-forget
                # behaviour rather than turning a successful command into an
                # apparent Home Assistant failure.
                LOGGER.debug("No asynchronous result received for %s", cmd)
                return
        finally:
            self._message_handler.remove_alarm_command_waiter(
                str(device_id), str(endpoint_id), cmd, waiter
            )

        result = str(reply.get("values", {}).get("result"))
        if result != "ACK":
            raise TydomAlarmCommandError(cmd, result)

    async def put_ackevents_cdata(self, device_id, endpoint_id=None, alarm_pin=None):
        """Acknowledge alarm events using the command supported by the gateway.

        TYXAL gateways expose two incompatible forms in the field. Some
        advertise ``ackEventCmd`` as authenticated cdata requiring ``pwd``;
        others accept the pin-free ``ACK`` value through the regular data
        endpoint and reject the cdata form. Prefer the authenticated command
        whenever an alarm code is available, then retain the proven data form
        as a compatibility fallback.
        """
        safe_device_id = quote(str(device_id), safe="")
        safe_endpoint_id = quote(str(endpoint_id), safe="")
        pin = alarm_pin or self._alarm_pin

        if pin:
            # TYDOM2 publishes the command outcome asynchronously with the
            # reserved transaction id 0, just like arm commands.  Waiting for
            # a transaction-correlated HTTP reply causes a 30-second timeout.
            body = json.dumps({"pwd": str(pin)})
            request = (
                f"PUT /devices/{safe_device_id}/endpoints/{safe_endpoint_id}/cdata"
                "?name=ackEventCmd HTTP/1.1\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Content-Type: application/json; charset=UTF-8\r\n"
                "Transac-Id: 0\r\n\r\n"
                f"{body}\r\n\r\n"
            )
            waiter = self._message_handler.create_alarm_command_waiter(
                str(device_id), str(endpoint_id), "ackEventCmd"
            )
            try:
                await self.send_bytes(self._cmd_prefix + request.encode("ascii"))
                try:
                    async with async_timeout.timeout(5):
                        reply = await waiter
                except TimeoutError:
                    # Older gateways may not publish a result.  Do not send
                    # the /data fallback: its empty 200 is only transport ACK
                    # and does not prove that the central unit executed it.
                    LOGGER.debug("No asynchronous result received for ackEventCmd")
                    return
            finally:
                self._message_handler.remove_alarm_command_waiter(
                    str(device_id), str(endpoint_id), "ackEventCmd", waiter
                )

            result = str(reply.get("values", {}).get("result"))
            if result != "ACK":
                raise TydomAlarmCommandError("ackEventCmd", result)
            return

        await self.put_devices_data(device_id, endpoint_id, "ackEventCmd", "ACK")

    async def get_historic_cdata(
        self,
        device_id: str,
        endpoint_id: str,
        event_type: str | None = None,
        indexStart: int = 0,
        nbElement: int = 10,
        *,
        timeout: float = TIMEOUT_LONG_REQUEST,
        log_timeout: bool = True,
    ) -> list[dict] | None:
        """Get historical events."""
        # GET /devices/xxxx/endpoints/xxxx/cdata?name=histo&type=ALL&indexStart=0&nbElem=10
        type_ = event_type or "ALL"
        safe_device_id = quote(str(device_id), safe="")
        safe_endpoint_id = quote(str(endpoint_id), safe="")
        safe_type = quote(str(type_), safe="")
        url = f"/devices/{safe_device_id}/endpoints/{safe_endpoint_id}/cdata?name=histo&type={safe_type}&indexStart={indexStart}&nbElem={nbElement}"
        # The box streams the events one message at a time (about 2 seconds
        # apart), so the reply wait needs the long timeout; the default one
        # (10 s) cuts the stream off after a few events.
        return await self.get_reply_to_request(
            "GET", url, timeout=timeout, log_timeout=log_timeout
        )

    @staticmethod
    def _first_cdata_value(messages: list[dict] | None) -> dict | None:
        """Return the first non-sentinel cdata response."""
        if not messages:
            return None
        return next(
            (
                message
                for message in messages
                if isinstance(message, dict) and not message.get("EOR", False)
            ),
            None,
        )

    async def get_alarm_products_cdata(
        self, device_id: str, endpoint_id: str
    ) -> dict[str, dict | None]:
        """Get the TYXAL product inventory and its user-facing labels.

        The documented ``label`` response contains both products and zones.
        Some CS8000 firmware rejects the app's optional ``productInfo`` battery
        enrichment command with HTTP 400, so inventory discovery must not
        depend on it.
        """
        safe_device_id = quote(str(device_id), safe="")
        safe_endpoint_id = quote(str(endpoint_id), safe="")
        base_url = f"/devices/{safe_device_id}/endpoints/{safe_endpoint_id}/cdata"
        headers = {
            "Content-Length": "0",
            "Content-Type": "application/json; charset=UTF-8",
        }
        labels = await self.get_reply_to_request(
            "GET", f"{base_url}?name=label", headers=headers.copy()
        )
        return {
            "productInfo": None,
            "label": self._first_cdata_value(labels),
        }

    async def get_alarm_product_configuration_cdata(
        self,
        device_id: str,
        endpoint_id: str,
        alarm_pin: str,
        product_id: int,
    ) -> dict | None:
        """Get the common configuration of one TYXAL product."""
        safe_device_id = quote(str(device_id), safe="")
        safe_endpoint_id = quote(str(endpoint_id), safe="")
        safe_pin = quote(str(alarm_pin), safe="")
        url = (
            f"/devices/{safe_device_id}/endpoints/{safe_endpoint_id}/cdata"
            f"?name=productConf&pwd={safe_pin}&id={int(product_id)}"
        )
        messages = await self.get_reply_to_request(
            "GET",
            url,
            headers={
                "Content-Length": "0",
                "Content-Type": "application/json; charset=UTF-8",
            },
        )
        return self._first_cdata_value(messages)

    async def put_alarm_product_configuration_cdata(
        self,
        device_id: str,
        endpoint_id: str,
        alarm_pin: str,
        product_id: int,
        *,
        zone: int | None = None,
    ) -> None:
        """Update selected common settings of one TYXAL product."""
        common: dict[str, int] = {}
        if zone is not None:
            common["zone"] = int(zone)
        if not common:
            raise ValueError("At least one product setting must be supplied")

        safe_device_id = quote(str(device_id), safe="")
        safe_endpoint_id = quote(str(endpoint_id), safe="")
        url = (
            f"/devices/{safe_device_id}/endpoints/{safe_endpoint_id}/cdata"
            "?name=productConf"
        )
        await self.get_reply_to_request(
            "PUT",
            url,
            body={
                "pwd": str(alarm_pin),
                "id": int(product_id),
                "common": common,
            },
        )

    async def put_alarm_product_active_cdata(
        self,
        device_id: str,
        endpoint_id: str,
        installer_code: str,
        product_id: int,
        active: bool,
    ) -> None:
        """Activate or deactivate one TYXAL product."""
        safe_device_id = quote(str(device_id), safe="")
        safe_endpoint_id = quote(str(endpoint_id), safe="")
        url = (
            f"/devices/{safe_device_id}/endpoints/{safe_endpoint_id}/cdata"
            "?name=activeProductConf"
        )
        await self.get_reply_to_request(
            "PUT",
            url,
            body={
                "pwd": str(installer_code),
                "id": int(product_id),
                "activeProduct": bool(active),
            },
        )

    async def put_alarm_mode_cdata(
        self,
        device_id: str,
        endpoint_id: str,
        installer_code: str,
        mode: str,
    ) -> None:
        """Set a global TYXAL mode and await the gateway response."""
        if mode not in {"MAINTENANCE", "OFF"}:
            raise ValueError(f"Unsupported TYXAL maintenance mode: {mode}")
        safe_device_id = quote(str(device_id), safe="")
        safe_endpoint_id = quote(str(endpoint_id), safe="")
        url = (
            f"/devices/{safe_device_id}/endpoints/{safe_endpoint_id}/cdata"
            "?name=alarmCmd"
        )
        await self.get_reply_to_request(
            "PUT",
            url,
            body={"pwd": str(installer_code), "value": mode},
        )

    async def put_alarm_remote_control_cdata(
        self,
        device_id: str,
        endpoint_id: str,
        installer_code: str,
        control: str,
    ) -> None:
        """Lock or unlock the TYXAL remote configuration session."""
        if control not in {"lock", "unlock"}:
            raise ValueError(f"Unsupported TYXAL remote control action: {control}")
        safe_device_id = quote(str(device_id), safe="")
        safe_endpoint_id = quote(str(endpoint_id), safe="")
        url = (
            f"/devices/{safe_device_id}/endpoints/{safe_endpoint_id}/cdata"
            "?name=remoteCtrl"
        )
        await self.get_reply_to_request(
            "PUT",
            url,
            body={"pwd": str(installer_code), "control": control},
        )

    async def put_alarm_zone_label_cdata(
        self,
        device_id: str,
        endpoint_id: str,
        alarm_pin: str,
        zone_id: int,
        name: str,
    ) -> None:
        """Rename or clear a TYXAL zone using the official label command."""
        safe_device_id = quote(str(device_id), safe="")
        safe_endpoint_id = quote(str(endpoint_id), safe="")
        url = (
            f"/devices/{safe_device_id}/endpoints/{safe_endpoint_id}/cdata"
            "?name=zoneLabelConf"
        )
        await self.get_reply_to_request(
            "PUT",
            url,
            body={
                "pwd": str(alarm_pin),
                "id": int(zone_id),
                # The Delta Dore app constructs nullable standard-name and
                # number fields, but Gson omits them from the wire payload.
                # Sending the unused standard-name or number fields explicitly
                # as JSON null is rejected by the CS8000. The app keeps an
                # explicitly blank custom name when clearing a label.
                "label": {"nameCustom": name},
            },
        )

    async def update_firmware(self):
        """Update Tydom firmware."""
        msg_type = "/configs/gateway/update"
        req = "PUT"
        await self.send_message(method=req, msg=msg_type)
