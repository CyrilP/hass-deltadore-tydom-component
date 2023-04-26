"""Tydom API Client."""
import os
import logging
import asyncio
import socket
import base64
import re
import async_timeout
import aiohttp

from aiohttp import ClientWebSocketResponse
from .MessageHandler import MessageHandler

from requests.auth import HTTPDigestAuth

logger = logging.getLogger(__name__)


class TydomClientApiClientError(Exception):
    """Exception to indicate a general API error."""


class TydomClientApiClientCommunicationError(TydomClientApiClientError):
    """Exception to indicate a communication error."""


class TydomClientApiClientAuthenticationError(TydomClientApiClientError):
    """Exception to indicate an authentication error."""


class TydomClient:
    """Tydom API Client."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        mac: str,
        password: str,
        alarm_pin: str = None,
        host: str = "mediation.tydom.com",
    ) -> None:
        logger.debug("Initializing TydomClient Class")

        self._session = session
        self._password = password
        self._mac = mac
        self._host = host
        self._alarm_pin = alarm_pin
        self._remote_mode = self._host == "mediation.tydom.com"
        self._connection = None

        # Some devices (like Tywatt) need polling
        self.poll_device_urls = []
        self.current_poll_index = 0

        if self._remote_mode:
            logger.info("Configure remote mode (%s)", self._host)
            self._cmd_prefix = "\x02"
            self._ping_timeout = 40
        else:
            logger.info("Configure local mode (%s)", self._host)
            self._cmd_prefix = ""
            self._ping_timeout = None

    async def async_connect(self) -> ClientWebSocketResponse:
        """Connect to the Tydom API."""
        http_headers = {
            "Connection": "Upgrade",
            "Upgrade": "websocket",
            "Host": self._host + ":443",
            "Accept": "*/*",
            "Sec-WebSocket-Key": self.generate_random_key(),
            "Sec-WebSocket-Version": "13",
        }

        try:
            async with async_timeout.timeout(10):
                response = await self._session.request(
                    method="GET",
                    url=f"https://{self._host}:443/mediation/client?mac={self._mac}&appli=1",
                    headers=http_headers,
                    json=None,
                )
                logger.info("response status : %s", response.status)
                logger.info("response content : %s", await response.text())
                logger.info("response headers : %s", response.headers)

                re_matcher = re.match(
                    '.*nonce="([a-zA-Z0-9+=]+)".*',
                    response.headers.get("WWW-Authenticate"),
                )
                if re_matcher:
                    logger.info("nonce : %s", re_matcher.group(1))
                else:
                    raise TydomClientApiClientError("Could't find auth nonce")

                http_headers = {}
                http_headers["Authorization"] = self.build_digest_headers(
                    re_matcher.group(1)
                )

                logger.info("new request headers : %s", http_headers)

                connection = await self._session.ws_connect(
                    method="GET",
                    url=f"wss://{self._host}:443/mediation/client?mac={self._mac}&appli=1",
                    headers=http_headers,
                    autoclose=False,
                    autoping=True,
                    timeout=100,
                    heartbeat=10,
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
            raise TydomClientApiClientError(
                "Something really wrong happened!"
            ) from exception

    async def listen_tydom(self, connection: ClientWebSocketResponse):
        """Listen for Tydom messages"""
        logger.info("Listen for Tydom messages")
        self._connection = connection
        await self.get_info()
        await self.post_refresh()
        await self.get_configs_file()
        await self.get_devices_cmeta()
        await self.get_devices_data()

        while True:
            try:
                if self._connection.closed:
                    self._connection = await self.async_connect()
                incoming_bytes_str = await self._connection.receive_bytes()
                # logger.info(incoming_bytes_str.type)
                logger.info(incoming_bytes_str)

                message_handler = MessageHandler(
                    incoming_bytes=incoming_bytes_str,
                    tydom_client=self,
                    cmd_prefix=self._cmd_prefix,
                )
                await message_handler.incoming_triage()
                #                message_handler = MessageHandler(
                #                    incoming_bytes=incoming_bytes_str,
                #                    tydom_client=tydom_client,
                #                    mqtt_client=mqtt_client,
                #                )
                # await message_handler.incoming_triage()
            except Exception as e:
                logger.warning("Unable to handle message: %s", e)

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

    async def send_message(self, method, msg):
        """Send Generic message to Tydom"""
        message = (
            self._cmd_prefix
            + method
            + " "
            + msg
            + " HTTP/1.1\r\nContent-Length: 0\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
        )
        a_bytes = bytes(message, "ascii")
        logger.debug(
            "Sending message to tydom (%s %s)",
            method,
            msg if "pwd" not in msg else "***",
        )

        if self._connection is not None:
            await self._connection.send_bytes(a_bytes)
        else:
            logger.warning(
                "Cannot send message to Tydom because no connection has been established yet"
            )

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
        """Ask some information from Tydom"""
        msg_type = "/info"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    # Refresh (all)
    async def post_refresh(self):
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

    # Send a ping (pong should be returned)
    async def ping(self):
        msg_type = "/ping"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)
        logger.debug("Ping")

    async def get_devices_meta(self):
        """Get all devices metadata"""
        msg_type = "/devices/meta"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def get_devices_data(self):
        """Get all devices data"""
        msg_type = "/devices/data"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)
        # Get poll devices data
        for url in self.poll_device_urls:
            await self.get_poll_device_data(url)

    async def get_configs_file(self):
        """List the device to get the endpoint id"""
        msg_type = "/configs/file"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    # Get metadata configuration to list poll devices (like Tywatt)
    async def get_devices_cmeta(self):
        msg_type = "/devices/cmeta"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def get_data(self):
        await self.get_configs_file()
        await self.get_devices_cmeta()
        await self.get_devices_data()

    # Give order to endpoint
    async def get_device_data(self, id):
        # 10 here is the endpoint = the device (shutter in this case) to open.
        device_id = str(id)
        str_request = (
            self._cmd_prefix
            + f"GET /devices/{device_id}/endpoints/{device_id}/data HTTP/1.1\r\nContent-Length: 0\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
        )
        a_bytes = bytes(str_request, "ascii")
        await self._connection.send(a_bytes)

    async def get_poll_device_data(self, url):
        msg_type = url
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    # Get the moments (programs)
    async def get_moments(self):
        msg_type = "/moments/file"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    # Get the scenarios
    async def get_scenarii(self):
        msg_type = "/scenarios/file"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    # Give order (name + value) to endpoint
    async def put_devices_data(self, device_id, endpoint_id, name, value):
        # For shutter, value is the percentage of closing
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
        logger.debug("Sending message to tydom (%s %s)", "PUT data", body)
        await self._connection.send(a_bytes)
        return 0

    async def put_alarm_cdata(self, device_id, alarm_id=None, value=None, zone_id=None):
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

        if self._alarm_pin is None:
            logger.warning("Tydom alarm pin is not set!")

        try:
            if zone_id is None:
                cmd = "alarmCmd"
                body = (
                    '{"value":"'
                    + str(value)
                    + '","pwd":"'
                    + str(self._alarm_pin)
                    + '"}'
                )
            else:
                cmd = "zoneCmd"
                body = (
                    '{"value":"'
                    + str(value)
                    + '","pwd":"'
                    + str(self._alarm_pin)
                    + '","zones":"['
                    + str(zone_id)
                    + ']"}'
                )

            str_request = (
                self._cmd_prefix
                + "PUT /devices/{device}/endpoints/{alarm}/cdata?name={cmd} HTTP/1.1\r\nContent-Length: ".format(
                    device=str(device_id), alarm=str(alarm_id), cmd=str(cmd)
                )
                + str(len(body))
                + "\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
                + body
                + "\r\n\r\n"
            )

            a_bytes = bytes(str_request, "ascii")
            logger.debug("Sending message to tydom (%s %s)", "PUT cdata", body)

            try:
                await self._connection.send(a_bytes)
                return 0
            except BaseException:
                logger.error("put_alarm_cdata ERROR !", exc_info=True)
                logger.error(a_bytes)
        except BaseException:
            logger.error("put_alarm_cdata ERROR !", exc_info=True)

    def add_poll_device_url(self, url):
        self.poll_device_urls.append(url)
