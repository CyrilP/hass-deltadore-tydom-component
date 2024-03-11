"""Tydom API Client."""
import os
import asyncio
import socket
import base64
import re
import async_timeout
import aiohttp
import ssl
import traceback

from typing import cast
from urllib3 import encode_multipart_formdata
from aiohttp import ClientWebSocketResponse, ClientSession, WSMsgType
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import (
    MEDIATION_URL,
    DELTADORE_AUTH_URL,
    DELTADORE_AUTH_GRANT_TYPE,
    DELTADORE_AUTH_CLIENTID,
    DELTADORE_AUTH_SCOPE,
    DELTADORE_API_SITES)
from .MessageHandler import MessageHandler

from requests.auth import HTTPDigestAuth

from ..const import LOGGER

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
        alarm_pin: str = None,
        zone_away: str = None,
        zone_home: str = None,
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
        self._alarm_pin = alarm_pin
        self._remote_mode = self._host == MEDIATION_URL
        self._connection = None
        self.event_callback = event_callback
        # Some devices (like Tywatt) need polling
        self.poll_device_urls = []
        self.current_poll_index = 0

        if self._remote_mode:
            LOGGER.info("Configure remote mode (%s)", self._host)
            self._cmd_prefix = "\x02"
            self._ping_timeout = 40
        else:
            LOGGER.info("Configure local mode (%s)", self._host)
            self._cmd_prefix = ""
            self._ping_timeout = None

        self._message_handler = MessageHandler(
            tydom_client=self, cmd_prefix=self._cmd_prefix
        )

    def update_config(self, zone_home, zone_away):
        self._zone_home = zone_home
        self._zone_away = zone_away

    @staticmethod
    async def async_get_credentials(
        session: ClientSession, email: str, password: str, macaddress: str
    ):
        """Get tydom credentials from Delta Dore."""
        if file_mode:
            return "dummyPassword"
        try:
            async with async_timeout.timeout(10):
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
        except asyncio.TimeoutError as exception:
            raise TydomClientApiClientCommunicationError(
                "Timeout error fetching information",
            ) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            raise TydomClientApiClientCommunicationError(
                "Error fetching information",
            ) from exception
        except Exception as exception:  # pylint: disable=broad-except
            traceback.print_exception
            raise TydomClientApiClientError(
                "Something really wrong happened!"
            ) from exception

    async def async_connect(self) -> ClientWebSocketResponse:
        """Connect to the Tydom API."""
        global file_lines, file_mode, file_name
        if file_mode:
            file = open(file_name)
            file_lines = file.readlines()

            return None

        http_headers = {
            "Connection": "Upgrade",
            "Upgrade": "websocket",
            "Host": self._host + ":443",
            "Accept": "*/*",
            "Sec-WebSocket-Key": self.generate_random_key(),
            "Sec-WebSocket-Version": "13",
        }

        # configuration needed for local mode
        sslcontext = ssl.create_default_context()
        sslcontext.options |= 0x4  # OP_LEGACY_SERVER_CONNECT
        sslcontext.check_hostname = False
        sslcontext.verify_mode = ssl.CERT_NONE

        session = async_create_clientsession(self._hass, False)

        try:
            async with async_timeout.timeout(10):
                response = await session.request(
                    method="GET",
                    url=f"https://{self._host}:443/mediation/client?mac={self._mac}&appli=1",
                    headers=http_headers,
                    json=None,
                    proxy=proxy,
                    ssl_context=sslcontext,
                )
                LOGGER.debug(
                    "response status : %s\nheaders : %s\ncontent : %s",
                    response.status,
                    response.headers,
                    await response.text(),
                )

                re_matcher = re.match(
                    '.*nonce="([a-zA-Z0-9+=]+)".*',
                    response.headers.get("WWW-Authenticate"),
                )
                response.close()

                if re_matcher:
                    LOGGER.info("nonce : %s", re_matcher.group(1))
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
                    heartbeat=2,
                    proxy=proxy,
                    ssl_context=sslcontext,
                )

                return connection

        except asyncio.TimeoutError as exception:
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
        LOGGER.info("Listen for Tydom messages")
        self._connection = connection
        await self.ping()
        await self.get_info()
        await self.put_api_mode()
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

    async def consume_messages(self):
        """Read and parse incomming messages."""
        global file_lines, file_mode, file_index
        if file_mode:
            if (len(file_lines) > file_index):
                incoming = file_lines[file_index].replace("\\r", '\x0d').replace("\\n", "\x0a")
                incoming_bytes_str = incoming.encode("utf-8")
                file_index += 1
                LOGGER.info("Incomming message - message : %s", incoming_bytes_str)
            else:
                await asyncio.sleep(10)
                return None
            await asyncio.sleep(1)
            return await self._message_handler.incoming_triage(incoming_bytes_str)
        try:
            if self._connection.closed:
                await self._connection.close()
                await asyncio.sleep(10)
                await self.listen_tydom(await self.async_connect())

            msg = await self._connection.receive()
            LOGGER.info(
                "Incomming message - type : %s - message : %s", msg.type, msg.data
            )

            if msg.type == WSMsgType.CLOSE or msg.type == WSMsgType.CLOSED or msg.type == WSMsgType.CLOSING:
                LOGGER.debug("Close message type received")
                return None
            elif msg.type == WSMsgType.ERROR:
                LOGGER.debug("Error message type received")
                return None
            elif msg.type == WSMsgType.PING or msg.type == WSMsgType.PONG:
                LOGGER.debug("Ping/Pong message type received")
                return None

            incoming_bytes_str = cast(bytes, msg.data)

            return await self._message_handler.incoming_triage(incoming_bytes_str)

        except Exception:
            LOGGER.exception("Unable to handle message")
            return None

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

    async def send_bytes(self, a_bytes : bytes):
        """Send bytes to connection, retry if it fails."""
        if self._connection is not None:
            try:
                await self._connection.send_bytes(a_bytes)
            except ConnectionResetError:
                # Failed, retrying...
                try:
                    self._connection = await self.async_connect()
                    await self._connection.send_bytes(a_bytes)
                except ConnectionResetError:
                    LOGGER.warning(
                        "Cannot send message to Tydom. Connection was lost."
            )
        else:
            LOGGER.warning(
                "Cannot send message to Tydom because no connection has been established yet."
            )

    async def send_message(self, method, msg):
        """Send Generic message to Tydom."""
        message = (
            self._cmd_prefix
            + method
            + " "
            + msg
            + " HTTP/1.1\r\nContent-Length: 0\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
        )
        a_bytes = bytes(message, "ascii")
        LOGGER.debug(
            "Sending message to tydom (%s %s)",
            method,
            msg if "pwd" not in msg else "***",
        )
        if not file_mode:
            await self.send_bytes(a_bytes)


    # ########################
    # Utils methods
    # ########################

    @staticmethod
    def generate_random_key():
        """Generate 16 bytes random key for Sec-WebSocket-Keyand convert it to base64."""
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
        # Get poll device data
        nb_poll_devices = len(self.poll_device_urls)
        if self.current_poll_index < nb_poll_devices - 1:
            self.current_poll_index = self.current_poll_index + 1
        else:
            self.current_poll_index = 0
        if nb_poll_devices > 0:
            await self.get_poll_device_data(
                self.poll_device_urls[self.current_poll_index]
            )

    async def ping(self):
        """Send a ping (pong should be returned)."""
        msg_type = "/ping"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)
        LOGGER.debug("Ping")

    async def get_devices_meta(self):
        """Get all devices metadata."""
        msg_type = "/devices/meta"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def get_devices_data(self):
        """Get all devices data."""
        msg_type = "/devices/data"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)
        # Get poll devices data
        for url in self.poll_device_urls:
            await self.get_poll_device_data(url)

    async def get_configs_file(self):
        """List the devices to get the endpoint id."""
        msg_type = "/configs/file"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def get_devices_cmeta(self):
        """Get metadata configuration to list poll devices (like Tywatt)."""
        msg_type = "/devices/cmeta"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

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
        str_request = (
            self._cmd_prefix
            + f"GET /devices/{device_id}/endpoints/{device_id}/data HTTP/1.1\r\nContent-Length: 0\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
        )
        a_bytes = bytes(str_request, "ascii")
        await self._connection.send(a_bytes)

    async def get_poll_device_data(self, url):
        """Poll a device (probably unused)."""
        LOGGER.error("poll device data %s", url)
        msg_type = url
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    def add_poll_device_url(self, url):
        """Add a device for polling (probably unused)."""
        self.poll_device_urls.append(url)

    async def get_moments(self):
        """Get the moments (programs)."""
        msg_type = "/moments/file"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def get_scenarii(self):
        """Get the scenarios."""
        msg_type = "/scenarios/file"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

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
        elif isinstance(value, bool) or isinstance(value, int):
            body = '{"' + name + '":"' + str(value).lower() + '}'
        else:
            body = '{"' + name + '":"' + value + '"}'

        str_request = (
            self._cmd_prefix
            + f"PUT {path} HTTP/1.1\r\nContent-Length: "
            + str(len(body))
            + "\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
            + body
            + "\r\n\r\n"
        )
        a_bytes = bytes(str_request, "ascii")
        LOGGER.debug("Sending message to tydom (%s %s)", "PUT data", body)
        await self.send_bytes(a_bytes)
        return 0

    async def put_devices_data(self, device_id, endpoint_id, name, value):
        """Give order (name + value) to endpoint."""
        # For shutter, value is the percentage of closing
        body: str
        if value is None:
            body = '[{"name":"' + name + '","value":null}]'
        elif isinstance(value, bool):
            body = '[{"name":"' + name + '","value":' + str(value).lower() + '}]'
        else:
            body = '[{"name":"' + name + '","value":"' + value + '"}]'

        # endpoint_id is the endpoint = the device (shutter in this case) to
        # open.
        str_request = (
            self._cmd_prefix
            + f"PUT /devices/{device_id}/endpoints/{endpoint_id}/data HTTP/1.1\r\nContent-Length: "
            + str(len(body))
            + "\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
            + body
            + "\r\n\r\n"
        )
        a_bytes = bytes(str_request, "ascii")
        await self.send_bytes(a_bytes)
        LOGGER.debug("Sending message to tydom (%s %s)", "PUT data", body)
        return 0

    async def put_alarm_cdata(self, device_id, endpoint_id=None, alarm_pin=None, value=None, zone_id=None, legacy_zones=False):
        if legacy_zones:
            if zone_id is not None:
                zones_array = zone_id.split(",")
                for zone in zones_array:
                    await self._put_alarm_cdata(device_id, endpoint_id, alarm_pin, value, zone, legacy_zones)
        else:
            await self._put_alarm_cdata(device_id, endpoint_id, alarm_pin, value, zone_id, legacy_zones)


    async def _put_alarm_cdata(self, device_id, endpoint_id=None, alarm_pin=None, value=None, zone_id=None, legacy_zones=False):
        """Configure alarm mode."""
        # Credits to @mgcrea on github !
        # AWAY # "PUT /devices/{}/endpoints/{}/cdata?name=alarmCmd HTTP/1.1\r\ncontent-length: 29\r\ncontent-type: application/json; charset=utf-8\r\ntransac-id: request_124\r\n\r\n\r\n{"value":"ON","pwd":{}}\r\n\r\n"
        # HOME "PUT /devices/{}/endpoints/{}/cdata?name=zoneCmd HTTP/1.1\r\ncontent-length: 41\r\ncontent-type: application/json; charset=utf-8\r\ntransac-id: request_46\r\n\r\n\r\n{"value":"ON","pwd":"{}","zones":[1]}\r\n\r\n"
        # DISARM "PUT /devices/{}/endpoints/{}/cdata?name=alarmCmd
        # HTTP/1.1\r\ncontent-length: 30\r\ncontent-type: application/json;
        # charset=utf-8\r\ntransac-id:
        # request_7\r\n\r\n\r\n{"value":"OFF","pwd":"{}"}\r\n\r\n"

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
                body = (
                    '{"value":"'
                    + str(value)
                    + '","pwd":"'
                    + str(pin)
                    + '"}'
                )
            else:
                if legacy_zones:
                    cmd = "partCmd"
                    body = (
                        '{"value":"'
                        + str(value)
                        + ', "part":"['
                        + str(zone_id)
                        + ']"}'
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
                self._cmd_prefix
                + "PUT /devices/{device}/endpoints/{alarm}/cdata?name={cmd} HTTP/1.1\r\nContent-Length: ".format(
                    device=str(device_id), alarm=str(endpoint_id), cmd=str(cmd)
                )
                + str(len(body))
                + "\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
                + body
                + "\r\n\r\n"
            )

            a_bytes = bytes(str_request, "ascii")
            LOGGER.debug("Sending message to tydom (%s %s)", "PUT cdata", body)

            try:
                if not file_mode:
                    await self._connection.send(a_bytes)
                    return 0
            except BaseException:
                LOGGER.error("put_alarm_cdata ERROR !", exc_info=True)
                LOGGER.error(a_bytes)
        except BaseException:
            LOGGER.error("put_alarm_cdata ERROR !", exc_info=True)

    async def update_firmware(self):
        """Update Tydom firmware."""
        msg_type = "/configs/gateway/update"
        req = "PUT"
        await self.send_message(method=req, msg=msg_type)
