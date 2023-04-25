"""Tydom API Client."""
import os
import logging
import asyncio
import socket
import base64
import async_timeout
import aiohttp

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

        if self._remote_mode:
            logger.info("Configure remote mode (%s)", self._host)
            self._cmd_prefix = "\x02"
            self._ping_timeout = 40
        else:
            logger.info("Configure local mode (%s)", self._host)
            self._cmd_prefix = ""
            self._ping_timeout = None

    async def async_connect(self) -> any:
        """Connect to the Tydom API."""
        http_headers = {
            "Connection": "Upgrade",
            "Upgrade": "websocket",
            "Host": self._host + ":443",
            "Accept": "*/*",
            "Sec-WebSocket-Key": self.generate_random_key(),
            "Sec-WebSocket-Version": "13",
        }

        return await self._api_wrapper(
            method="get",
            url=f"https://{self._host}/mediation/client?mac={self._mac}&appli=1",
            headers=http_headers,
        )

    async def _api_wrapper(
        self,
        method: str,
        url: str,
        data: dict | None = None,
        headers: dict | None = None,
    ) -> any:
        """Get information from the API."""
        try:
            async with async_timeout.timeout(10):
                response = await self._session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                )
                if response.status in (401, 403):
                    raise TydomClientApiClientAuthenticationError(
                        "Invalid credentials",
                    )
                response.raise_for_status()
                return await response.json()

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

    def build_digest_headers(self, nonce):
        """Build the headers of Digest Authentication."""
        digest_auth = HTTPDigestAuth(self._mac, self._password)
        chal = {}
        chal["nonce"] = nonce[2].split("=", 1)[1].split('"')[1]
        chal["realm"] = (
            "ServiceMedia" if self._remote_mode is True else "protected area"
        )
        chal["qop"] = "auth"
        digest_auth._thread_local.chal = chal
        digest_auth._thread_local.last_nonce = nonce
        digest_auth._thread_local.nonce_count = 1
        return digest_auth.build_digest_header(
            "GET",
            "https://{host}:443/mediation/client?mac={mac}&appli=1".format(
                host=self._host, mac=self._mac
            ),
        )

    @staticmethod
    def generate_random_key():
        """Generate 16 bytes random key for Sec-WebSocket-Keyand convert it to base64."""
        return str(base64.b64encode(os.urandom(16)))
