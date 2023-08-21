"""Tydom API Client."""
import os
import logging
import asyncio
import socket
import base64
import re
import async_timeout
import aiohttp
import traceback

from typing import cast
from urllib3 import encode_multipart_formdata
from aiohttp import ClientWebSocketResponse, ClientSession
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import *
from .MessageHandler import MessageHandler

from requests.auth import HTTPDigestAuth

logger = logging.getLogger(__name__)


class TydomClientApiClientError(Exception):
    """Exception to indicate a general API error."""


class TydomClientApiClientCommunicationError(TydomClientApiClientError):
    """Exception to indicate a communication error."""


class TydomClientApiClientAuthenticationError(TydomClientApiClientError):
    """Exception to indicate an authentication error."""


proxy = None


class TydomClient:
    """Tydom API Client."""

    def __init__(
        self,
        hass,
        mac: str,
        password: str,
        alarm_pin: str = None,
        host: str = MEDIATION_URL,
        event_callback=None,
    ) -> None:
        logger.debug("Initializing TydomClient Class")

        self._hass = hass
        self._password = password
        self._mac = mac
        self._host = host
        self._alarm_pin = alarm_pin
        self._remote_mode = self._host == MEDIATION_URL
        self._connection = None
        self.event_callback = event_callback
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

        self._message_handler = MessageHandler(
            tydom_client=self, cmd_prefix=self._cmd_prefix
        )

    @staticmethod
    async def async_get_credentials(
        session: ClientSession, email: str, password: str, macaddress: str
    ):
        """get tydom credentials from Delta Dore"""
        try:
            async with async_timeout.timeout(10):
                response = await session.request(
                    method="GET", url=DELTADORE_AUTH_URL, proxy=proxy
                )

                logger.debug(
                    "response status for openid-config: %s\nheaders : %s\ncontent : %s",
                    response.status,
                    response.headers,
                    await response.text(),
                )

                json_response = await response.json()
                response.close()
                signin_url = json_response["token_endpoint"]
                logger.info("signin_url : %s", signin_url)

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

                logger.debug(
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

                logger.debug(
                    "response status for https://prod.iotdeltadore.com/sitesmanagement/api/v1/sites?gateway_mac= : %s\nheaders : %s\ncontent : %s",
                    response.status,
                    response.headers,
                    await response.text(),
                )

                json_response = await response.json()
                response.close()

                await session.close()
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
        http_headers = {
            "Connection": "Upgrade",
            "Upgrade": "websocket",
            "Host": self._host + ":443",
            "Accept": "*/*",
            "Sec-WebSocket-Key": self.generate_random_key(),
            "Sec-WebSocket-Version": "13",
        }

        session = async_create_clientsession(self._hass, False)

        try:
            async with async_timeout.timeout(10):
                response = await session.request(
                    method="GET",
                    url=f"https://{self._host}:443/mediation/client?mac={self._mac}&appli=1",
                    headers=http_headers,
                    json=None,
                    proxy=proxy,
                )
                logger.debug(
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
                    logger.info("nonce : %s", re_matcher.group(1))
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
        """Listen for Tydom messages"""
        logger.info("Listen for Tydom messages")
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
        await self.post_refresh()
        await self.get_configs_file()
        await self.get_devices_meta()
        await self.get_devices_cmeta()
        await self.get_devices_data()

    async def consume_messages(self):
        """Read and parse incomming messages"""
        try:
            if self._connection.closed:
                await self._connection.close()
                await asyncio.sleep(10)
                self.listen_tydom(await self.async_connect())
                # self._connection = await self.async_connect()

            msg = await self._connection.receive()
            logger.info(
                "Incomming message - type : %s - message : %s", msg.type, msg.data
            )
            incoming_bytes_str = cast(bytes, msg.data)

            return await self._message_handler.incoming_triage(incoming_bytes_str)

        except Exception as e:
            logger.warning("Unable to handle message: %s", e)
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

    async def get_local_claim(self):
        """Ask some information from Tydom"""
        msg_type = "/configs/gateway/local_claim"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def get_geoloc(self):
        """Ask some information from Tydom"""
        msg_type = "/configs/gateway/geoloc"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def put_api_mode(self):
        """Use Tydom API mode ?"""
        msg_type = "/configs/gateway/api_mode"
        req = "PUT"
        await self.send_message(method=req, msg=msg_type)

    async def post_refresh(self):
        """Refresh (all)"""
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
        """Send a ping (pong should be returned)"""
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
        """List the devices to get the endpoint id"""
        msg_type = "/configs/file"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def get_devices_cmeta(self):
        """Get metadata configuration to list poll devices (like Tywatt)"""
        msg_type = "/devices/cmeta"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def get_areas_meta(self):
        """Get areas metadata"""
        msg_type = "/areas/meta"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def get_areas_cmeta(self):
        """Get areas metadata"""
        msg_type = "/areas/cmeta"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def get_areas_data(self):
        """Get areas metadata"""
        msg_type = "/areas/data"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def get_device_data(self, id):
        """Give order to endpoint"""
        # 10 here is the endpoint = the device (shutter in this case) to open.
        device_id = str(id)
        str_request = (
            self._cmd_prefix
            + f"GET /devices/{device_id}/endpoints/{device_id}/data HTTP/1.1\r\nContent-Length: 0\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
        )
        a_bytes = bytes(str_request, "ascii")
        await self._connection.send(a_bytes)

    async def get_poll_device_data(self, url):
        logger.error("poll device data %s", url)
        msg_type = url
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    def add_poll_device_url(self, url):
        self.poll_device_urls.append(url)

    async def get_moments(self):
        """Get the moments (programs)"""
        msg_type = "/moments/file"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def get_scenarii(self):
        """Get the scenarios"""
        msg_type = "/scenarios/file"
        req = "GET"
        await self.send_message(method=req, msg=msg_type)

    async def put_devices_data(self, device_id, endpoint_id, name, value):
        """Give order (name + value) to endpoint"""
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
        # self._connection.send_bytes
        # self._connection.send_json
        # self._connection.send_str
        # await self._connection.send(a_bytes)
        await self._connection.send_bytes(a_bytes)
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

    async def update_firmware(self):
        """Update Tydom firmware"""
        msg_type = "/configs/gateway/update"
        req = "PUT"
        await self.send_message(method=req, msg=msg_type)
