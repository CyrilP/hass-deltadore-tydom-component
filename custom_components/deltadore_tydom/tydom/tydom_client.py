"""Tydom API Client."""

import asyncio
import base64
import os
import re
import socket
import ssl
import time
import traceback
from typing import TYPE_CHECKING, cast

import aiohttp
import async_timeout
from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from requests.auth import HTTPDigestAuth
from urllib3 import encode_multipart_formdata

from ..const import (
    LOGGER,
    validate_value_with_metadata,
    TIMEOUT_QUICK_REQUEST,
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

if TYPE_CHECKING:
    from .tydom_devices import TydomDevice


class TydomClientApiClientError(Exception):
    """Exception to indicate a general API error."""


class TydomClientApiClientCommunicationError(TydomClientApiClientError):
    """Exception to indicate a communication error."""


class TydomClientApiClientAuthenticationError(TydomClientApiClientError):
    """Exception to indicate an authentication error."""


proxy = None

# For debugging with traces
file_mode = False
file_lines = None
file_index = 0
file_name = "/config/traces.txt"


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
        """Initialize client."""
        LOGGER.debug("Initializing TydomClient Class")

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
        self._connection = None
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
            async with async_timeout.timeout(TIMEOUT_QUICK_REQUEST):
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

                LOGGER.debug(
                    "response status for signin : %s\nheaders : %s\ncontent : %s",
                    response.status,
                    response.headers,
                    await response.text(),
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

                LOGGER.debug(
                    "response status for https://prod.iotdeltadore.com/sitesmanagement/api/v1/sites?gateway_mac= : %s\nheaders : %s\ncontent : %s",
                    response.status,
                    response.headers,
                    await response.text(),
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
        self.pending_pings = 0
        if file_mode:
            file = open(file_name)
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

        # configuration needed for local mode
        # - Wrap slow blocking call flagged by HA
        sslcontext = await asyncio.to_thread(ssl.create_default_context)
        sslcontext.options |= 0x4  # OP_LEGACY_SERVER_CONNECT
        sslcontext.check_hostname = False
        sslcontext.verify_mode = ssl.CERT_NONE

        session = async_create_clientsession(self._hass, False)

        try:
            # Use TIMEOUT_WEBSOCKET_CONNECT instead of TIMEOUT_QUICK_REQUEST because
            # the initial GET request is part of the WebSocket connection process:
            # it obtains the digest challenge, calculates authentication, and establishes
            # the WebSocket connection. This can take longer, especially on first connection
            # or with network latency.
            async with async_timeout.timeout(TIMEOUT_WEBSOCKET_CONNECT):
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

                http_headers = {}
                http_headers["Authorization"] = self.build_digest_headers(
                    re_matcher.group(1)
                )

                connection = await session.ws_connect(
                    method="GET",
                    url=f"wss://{self._host}:443/mediation/client?mac={self._mac}&appli=1",
                    headers=http_headers,
                    autoping=True,
                    heartbeat=2.0,
                    timeout=aiohttp.ClientTimeout(total=TIMEOUT_WEBSOCKET_CONNECT),
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

    async def listen_tydom(self, connection: ClientWebSocketResponse):
        """Listen for Tydom messages."""
        STRUCTURED_LOGGER.connection_event(
            "info",
            "listen_started",
            host=self._host,
            mode="remote" if self._remote_mode else "local",
        )
        self._connection = connection
        await self.ping()
        await self.get_info()
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
        await self.get_groups()
        await self.post_refresh()
        await self.get_configs_file()
        await self.get_devices_meta()
        await self.get_devices_cmeta()
        await self.get_devices_data()

        await self.get_scenarii()

    async def _reconnect_with_backoff(self) -> None:
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
        while self._reconnect_attempts < self._max_reconnect_attempts:
            delay = min(
                self._reconnect_delay
                * (self._reconnect_backoff_factor**self._reconnect_attempts),
                self._max_reconnect_delay,
            )
            STRUCTURED_LOGGER.connection_event(
                "info",
                "reconnect_attempt",
                attempt=self._reconnect_attempts + 1,
                max_attempts=self._max_reconnect_attempts,
                delay_seconds=delay,
            )
            await asyncio.sleep(delay)

            try:
                self._connection = await self.async_connect()
                await self.listen_tydom(self._connection)
                self._reconnect_attempts = 0
                self.online = True
                STRUCTURED_LOGGER.connection_event(
                    "info",
                    "reconnect_success",
                    attempt=self._reconnect_attempts + 1,
                    total_attempts=self._reconnect_attempts + 1,
                )
                return
            except Exception as e:
                self._reconnect_attempts += 1
                STRUCTURED_LOGGER.connection_event(
                    "warning",
                    "reconnect_failed",
                    attempt=self._reconnect_attempts,
                    max_attempts=self._max_reconnect_attempts,
                    error=str(e),
                )

        LOGGER.error(
            "Impossible de se reconnecter après %d tentatives",
            self._max_reconnect_attempts,
        )
        # Notifier Home Assistant de la perte de connexion
        self.online = False

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
                LOGGER.info("Incomming message - message : %s", incoming_bytes_str)
            else:
                await asyncio.sleep(10)
                return None
            await asyncio.sleep(1)
            return await self._message_handler.route_response(incoming_bytes_str)
        try:
            if self._connection is None:
                return None
            if self._connection.closed or self.pending_pings > 5:
                await self._connection.close()
                await self._reconnect_with_backoff()
                return None

            if self._connection is None:
                return None
            msg = await self._connection.receive()
            LOGGER.info(
                "Incoming message - type : %s - message : %s", msg.type, msg.data
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

        except Exception:
            LOGGER.exception("Unable to handle message")
            return None

    def receive_pong(self):
        """Received a pong message, decrease pending ping counts."""
        self.pending_pings -= 1

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
    ):
        """Send bytes to connection with intelligent retry mechanism.

        Args:
            a_bytes: Bytes to send
            max_retries: Maximum number of retry attempts
            retry_delay: Initial delay between retries (exponential backoff)

        """
        if file_mode:
            return

        if self._connection is None:
            LOGGER.warning(
                "Cannot send message to Tydom because no connection has been established yet."
            )
            return

        last_exception = None
        for attempt in range(max_retries + 1):
            try:
                await self._connection.send_bytes(a_bytes)
                if attempt > 0:
                    LOGGER.info(
                        "Successfully sent message after %d retry attempt(s)",
                        attempt,
                    )
                return
            except (ConnectionResetError, ConnectionError, OSError) as e:
                last_exception = e
                if attempt < max_retries:
                    delay = retry_delay * (2**attempt)  # Exponential backoff
                    LOGGER.warning(
                        "Connection error (attempt %d/%d): %s. Retrying in %.1f seconds...",
                        attempt + 1,
                        max_retries + 1,
                        str(e),
                        delay,
                    )
                    try:
                        # Try to reconnect
                        self._connection = await self.async_connect()
                        await asyncio.sleep(delay)
                    except Exception as reconnect_error:
                        LOGGER.error(
                            "Failed to reconnect (attempt %d/%d): %s",
                            attempt + 1,
                            max_retries + 1,
                            reconnect_error,
                        )
                        if attempt < max_retries:
                            await asyncio.sleep(delay)
                else:
                    LOGGER.error(
                        "Cannot send message to Tydom after %d attempts. Connection was lost: %s",
                        max_retries + 1,
                        str(e),
                    )
            except Exception as e:
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
    ) -> list[dict] | None:
        """Send request and wait for its reply with timeout handling.

        Args:
            method: Request method
            url: Request URL
            body: Request body
            headers: Request headers
            timeout: Timeout in seconds (default: 10.0)

        Returns:
            List of reply events or None

        Raises:
            TydomClientApiClientCommunicationError: If timeout or communication error occurs

        """
        event = asyncio.Event()

        transaction_id, request = self._message_handler.prepare_request(
            method, url, body, headers, reply_event=event
        )

        try:
            await self.send_bytes(request)
        except Exception as e:
            LOGGER.error(
                "Failed to send request %s %s: %s",
                method,
                url,
                str(e),
                exc_info=True,
            )
            raise TydomClientApiClientCommunicationError(
                f"Failed to send request {method} {url}: {str(e)}"
            ) from e

        # Wait for the reply with timeout
        try:
            async with async_timeout.timeout(timeout):
                await event.wait()
        except TimeoutError:
            LOGGER.warning(
                "Timeout waiting for reply to %s %s (transaction_id: %s, timeout: %.1fs)",
                method,
                url,
                transaction_id,
                timeout,
            )
            # Remove the pending reply to avoid memory leak
            self._message_handler.remove_reply(transaction_id)
            raise TydomClientApiClientCommunicationError(
                f"Timeout waiting for reply to {method} {url}"
            )

        reply = self._message_handler.get_reply(transaction_id)

        if reply is None:
            LOGGER.warning(
                "No reply received for %s %s (transaction_id: %s)",
                method,
                url,
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

    async def poll_devices_data_5m(self):
        """Poll devices data."""
        for url in self.poll_device_urls_5m:
            await self.get_poll_device_data(url)

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
        device_id = str(id)
        str_request = f"GET /devices/{device_id}/endpoints/{device_id}/data HTTP/1.1\r\nContent-Length: 0\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
        a_bytes = self._cmd_prefix + bytes(str_request, "ascii")
        LOGGER.debug("Sending message to tydom (%s %s)", "GET device data", str_request)
        if not file_mode:
            await self.send_bytes(a_bytes)

    async def get_poll_device_data(self, url):
        """Poll a device."""
        msg_type = url
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

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
        import json

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

        STRUCTURED_LOGGER.api_call(
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

    async def put_data(self, path, name, value):
        """Give order (name + value) to path."""
        body: str
        if value is None:
            body = '{"' + name + '":"null}'
        elif isinstance(value, bool | int):
            body = '{"' + name + '":"' + str(value).lower() + "}"
        else:
            body = '{"' + name + '":"' + value + '"}'

        str_request = (
            f"PUT {path} HTTP/1.1\r\nContent-Length: "
            + str(len(body))
            + "\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
            + body
            + "\r\n\r\n"
        )
        a_bytes = self._cmd_prefix + bytes(str_request, "ascii")
        LOGGER.debug("Sending message to tydom (%s %s)", "PUT data", body)
        if not file_mode:
            await self.send_bytes(a_bytes)
        return 0

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
        body: str
        if value is None:
            body = '[{"name":"' + name + '","value":null}]'
        elif isinstance(value, bool):
            body = '[{"name":"' + name + '","value":' + str(value).lower() + "}]"
        else:
            body = '[{"name":"' + name + '","value":"' + value + '"}]'

        # endpoint_id is the endpoint = the device (shutter in this case) to
        # open.
        str_request = (
            f"PUT /devices/{device_id}/endpoints/{endpoint_id}/data HTTP/1.1\r\nContent-Length: "
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
        LOGGER.debug("Sending message to tydom (%s %s)", "PUT device data", body)
        if not file_mode:
            await self.send_bytes(a_bytes)

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
        if legacy_zones:
            if zone_id is not None:
                zones_array = zone_id.split(",")
                for zone in zones_array:
                    await self._put_alarm_cdata(
                        device_id, endpoint_id, alarm_pin, value, zone, legacy_zones
                    )
        else:
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

        try:
            if zone_id is None or zone_id == "":
                cmd = "alarmCmd"
                body = '{"value":"' + str(value) + '","pwd":"' + str(pin) + '"}'
            else:
                if legacy_zones:
                    cmd = "partCmd"
                    body = (
                        '{"value":"' + str(value) + ', "part":"' + str(zone_id) + '"}'
                    )
                else:
                    cmd = "zoneCmd"
                    body = (
                        '{"value":"'
                        + str(value)
                        + '","pwd":"'
                        + str(pin)
                        + '","zones":"['
                        + str(zone_id)
                        + ']"}'
                    )

            str_request = (
                f"PUT /devices/{device_id}/endpoints/{endpoint_id}/cdata?name={cmd} HTTP/1.1\r\nContent-Length: "
                + str(len(body))
                + "\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
                + body
                + "\r\n\r\n"
            )

            a_bytes = self._cmd_prefix + bytes(str_request, "ascii")
            LOGGER.debug("Sending message to tydom (%s %s)", "PUT cdata", body)

            try:
                if not file_mode:
                    await self.send_bytes(a_bytes)
                    return 0
            except BaseException:
                LOGGER.error("put_alarm_cdata ERROR !", exc_info=True)
                LOGGER.error(a_bytes)
        except BaseException:
            LOGGER.error("put_alarm_cdata ERROR !", exc_info=True)

    async def put_ackevents_cdata(self, device_id, endpoint_id=None, alarm_pin=None):
        """Acknowledge the alarm events."""
        # PUT /devices/xxxx/endpoints/xxxx/cdata?name=ackEventCmd HTTP/1.1 {"pwd":"xxxxxx"}
        pwd = alarm_pin or self._alarm_pin
        if pwd is None:
            LOGGER.warning("Tydom alarm pin is not set!")
        await self.put_data(
            f"/devices/{device_id}/endpoints/{endpoint_id}/cdata?name=ackEventCmd",
            "pwd",
            str(pwd),
        )

    async def get_historic_cdata(
        self,
        device_id: str,
        endpoint_id: str,
        event_type: str | None = None,
        indexStart: int = 0,
        nbElement: int = 10,
    ) -> list[dict] | None:
        """Get historical events."""
        # GET /devices/xxxx/endpoints/xxxx/cdata?name=histo&type=ALL&indexStart=0&nbElem=10
        type_ = event_type or "ALL"
        url = f"/devices/{device_id}/endpoints/{endpoint_id}/cdata?name=histo&type={type_}&indexStart={indexStart}&nbElem={nbElement}"
        timeout = TIMEOUT_LONG_REQUEST  # Wait maximum for long operations like historical data
        async with asyncio.timeout(timeout):
            return await self.get_reply_to_request("GET", url)

    async def update_firmware(self):
        """Update Tydom firmware."""
        msg_type = "/configs/gateway/update"
        req = "PUT"
        await self.send_message(method=req, msg=msg_type)
