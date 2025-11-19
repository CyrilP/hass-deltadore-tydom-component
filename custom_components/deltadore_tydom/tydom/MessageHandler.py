"""Tydom message parsing."""

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass
from functools import partial
from http.client import HTTPMessage, LineTooLong
from http.client import HTTPResponse as CoreHTTPResponse
from io import BytesIO
from typing import TYPE_CHECKING, TypedDict, cast

from ..const import LOGGER
from .tydom_devices import (
    Tydom,
    TydomAlarm,
    TydomBoiler,
    TydomDevice,
    TydomDoor,
    TydomEnergy,
    TydomGarage,
    TydomGate,
    TydomLight,
    TydomShutter,
    TydomSmoke,
    TydomWindow,
    TydomWeather,
    TydomWater,
    TydomThermo,
    TydomSwitch,
    TydomRemote,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from .tydom_client import TydomClient

_MAX_REPLIES_SIZE = 5
"""Maximal number of replies to keep track of."""

# Device dict for parsing
device_name = {}
device_endpoint = {}
device_type = {}
device_metadata = {}


class Reply(TypedDict):
    """cdata request reply."""

    transaction_id: str
    """Transaction ID."""
    events: list[dict]
    """Raw reply events."""
    done: bool
    """Whether all reply events have been received or not."""


class MessageHandler:
    """Handle incoming Tydom messages."""

    def __init__(self, tydom_client: "TydomClient", cmd_prefix: bytes) -> None:
        """Initialize MessageHandler."""
        self.tydom_client = tydom_client
        self.cmd_prefix = cmd_prefix
        self._cdata_replies: list[Reply] = []
        self._end_reply_events: dict[str, asyncio.Event] = {}

    def get_reply(self, transaction_id: str) -> Reply | None:
        """
        Get the reply to a request.

        If the reply is incomplete, this will return None.

        Args:
            transaction_id: The transaction ID of the request.

        Returns:
            The reply or None if no reply found.

        """
        reply = None

        for r in self._cdata_replies:
            if r["transaction_id"] == transaction_id:
                reply = r
                break

        if reply is not None:
            if reply["done"]:
                self._cdata_replies.remove(reply)
            else:
                LOGGER.debug(
                    "Try to get partial reply to request %s: %s",
                    transaction_id,
                    reply["events"],
                )
                reply = None

        return reply

    async def route_response(self, bytes_str: bytes) -> list["TydomDevice"] | None:
        """
        Identify message type and dispatch the result.

        Args:
            bytes_str: Incoming message

        """
        if bytes_str is None:
            return None

        incoming = None
        stripped_msg = bytes_str.strip(self.cmd_prefix)

        try:
            if stripped_msg.startswith(b"HTTP/"):
                parsed_message = _parse_response(stripped_msg)
                # Find Uri-Origin in header if available
                uri_origin = parsed_message.headers.get("Uri-Origin", "")

            else:
                parsed_message = parse_request(stripped_msg)
                uri_origin = parsed_message.path
            transaction_id = parsed_message.headers.get("Transac-Id")

            try:
                return await self.parse_response(
                    parsed_message.body,
                    uri_origin,
                    parsed_message.headers.get("content-type"),
                    transaction_id=transaction_id if transaction_id else None,
                )
            except BaseException as e:
                LOGGER.error(
                    "Error when parsing tydom message (%s)", bytes_str, exc_info=e
                )
            return None

        except Exception as ex:
            LOGGER.error(
                "Technical error when parsing tydom message (%s) : %s",
                bytes_str,
                ex,
                exc_info=ex,
            )
            LOGGER.debug("Incoming payload (%s)", incoming)
            raise Exception("Something really wrong happened!") from ex

    def prepare_request(
        self,
        method: str,
        url: str,
        body: dict | bytes | None = None,
        headers: dict | None = None,
        reply_event: asyncio.Event | None = None,
    ) -> tuple[str, bytes]:
        """
        Create request bytes message.

        If body is a dictionary, it should be json serializable.

        Args:
            method: HTTP method
            url: HTTP target URL
            body: [optional] Request body
            headers: [optional] Request headers
            reply_event: [optional] Event to wait for the reply completion

        Returns:
            Tuple (request transaction ID, request bytes message)

        """
        headers = headers or {}
        # Transaction ID is the current time in ms
        transaction_id = headers.get("Transac-Id", str(time.time_ns())[:13])
        headers["Transac-Id"] = transaction_id
        if body:
            if isinstance(body, dict):
                body = json.dumps(body).encode("ascii")
                headers["Content-Type"] = "application/json; charset=UTF-8"
            content_length = headers.get("Content-Length", str(len(body)))
            headers["Content-Length"] = content_length

        request = bytes(f"{method} {url} HTTP/1.1\r\n", "ascii")
        if len(headers):
            for k, v in headers.items():
                request += bytes(f"{k}: {v}\r\n", "ascii")

        if body:
            request += b"\r\n"
            request += cast(bytes, body) + b"\r\n"

        request += b"\r\n"

        if reply_event:
            self._end_reply_events[transaction_id] = reply_event

        return (transaction_id, request)

    async def parse_response(
        self,
        data: bytes | None,
        uri_origin: str,
        content_type: str | None,
        transaction_id: str | None,
    ) -> list[TydomDevice] | None:
        """
        Parse response.

        Args:
            data: Response body
            uri_origin: Response URL
            content_type: Response content type (can't be trusted)
            transaction_id: Response transaction ID

        Returns:
            List of Tydom devices if applicable.

        """

        async def no_op(message_type: str, *args):
            LOGGER.debug("%s response", message_type)

        async def event_message(*args):
            LOGGER.debug("Event message, refreshing...")
            await self.tydom_client.get_devices_data()

        async def ping_message(*args):
            self.tydom_client.receive_pong()

        MSG_MAPPING = {
            "/configs/file": MessageHandler.parse_config_data,
            "/configs/gateway/api_mode": partial(no_op, "msg_api_mode"),
            "/devices/cdata": self.parse_devices_cdata,
            "/devices/cmeta": self.parse_cmeta_data,
            "/devices/install": partial(no_op, "msg_pairing"),
            "/devices/meta": self.parse_devices_metadata,
            "/events": event_message,
            "/groups/file": partial(no_op, "msg_groups"),
            "/info": self.parse_msg_info,
            "/ping": ping_message,
            "/refresh/all": partial(no_op, "msg_refresh_all"),
            "/scenarios/file": partial(no_op, "msg_scenarios"),
        }

        parsed = data
        msg_type: (
            Callable[
                [bytes | dict | None, str | None], Awaitable[list[TydomDevice] | None]
            ]
            | None
        ) = None

        if data:
            if content_type == "application/json":
                # Content-Type is not reliable; it is use with text/html for example
                with contextlib.suppress(json.decoder.JSONDecodeError):
                    parsed = json.loads(data)
            elif content_type == "text/html":
                msg_type = partial(no_op, "msg_html")

        if msg_type is None:
            msg_type = MSG_MAPPING.get(uri_origin)

            if msg_type is None and data:
                first = data[:40]
                if b"doctype" in first:  # Content-Type header is not respected
                    msg_type = partial(no_op, "msg_html")
                elif b"id" in first:
                    msg_type = self.parse_devices_data

        if msg_type is None:
            LOGGER.warning("Unknown message type received %s: %s", uri_origin, data)
        else:
            LOGGER.debug("Message received from %s", uri_origin)
            try:
                return await msg_type(parsed, transaction_id)
            except Exception as e:
                LOGGER.error("Error on parsing tydom response (%s)", data, exc_info=e)
        LOGGER.debug("Incoming data parsed with success")

    async def parse_devices_metadata(self, parsed, transaction_id):
        """Parse metadata."""
        LOGGER.debug("metadata : %s", parsed)
        for device in parsed:
            id = device["id"]
            for endpoint in device["endpoints"]:
                id_endpoint = endpoint["id"]
                device_unique_id = str(id_endpoint) + "_" + str(id)
                device_metadata[device_unique_id] = {}
                for metadata in endpoint["metadata"]:
                    metadata_name = metadata["name"]
                    device_metadata[device_unique_id][metadata_name] = {}
                    for meta in metadata:
                        if meta == "name":
                            continue
                        device_metadata[device_unique_id][metadata_name][meta] = (
                            metadata[meta]
                        )
        return []

    async def parse_msg_info(self, parsed, transaction_id):
        """Parse message info."""
        LOGGER.debug("parse_msg_info : %s", parsed)

        return [
            Tydom(
                self.tydom_client,
                self.tydom_client.id,
                self.tydom_client.id,
                self.tydom_client.id,
                "Tydom Gateway",
                None,
                None,
                parsed,
            )
        ]

    @staticmethod
    async def get_device(
        tydom_client, last_usage, uid, device_id, name, endpoint=None, data=None
    ) -> TydomDevice | None:
        """Get device class from its last usage."""

        # FIXME voir: class CoverDeviceClass(StrEnum):
        # Refer to the cover dev docs for device class descriptions
        # AWNING = "awning"
        # BLIND = "blind"
        # CURTAIN = "curtain"
        # DAMPER = "damper"
        # DOOR = "door"
        # GARAGE = "garage"
        # GATE = "gate"
        # SHADE = "shade"
        # SHUTTER = "shutter"
        # WINDOW = "window"
        match last_usage:
            case "shutter" | "klineShutter" | "awning" | "swingShutter":
                return TydomShutter(
                    tydom_client, uid, device_id, name, last_usage, endpoint, None, data
                )
            case (
                "window"
                | "windowFrench"
                | "windowSliding"
                | "klineWindowFrench"
                | "klineWindowSliding"
            ):
                return TydomWindow(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata[uid],
                    data,
                )
            case "belmDoor" | "klineDoor":
                return TydomDoor(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata[uid],
                    data,
                )
            case "garage_door":
                return TydomGarage(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata[uid],
                    data,
                )
            case "gate":
                return TydomGate(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata[uid],
                    data,
                )
            case "light":
                return TydomLight(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata[uid],
                    data,
                )
            case "conso":
                return TydomEnergy(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata[uid],
                    data,
                )
            case "sensorDFR":
                return TydomSmoke(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata[uid],
                    data,
                )
            case "boiler" | "sh_hvac" | "electric" | "aeraulic":
                return TydomBoiler(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata[uid],
                    data,
                )
            case "alarm":
                return TydomAlarm(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata[uid],
                    data,
                )
            case "weather":
                return TydomWeather(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata[uid],
                    data,
                )
            case "sensorDF":
                return TydomWater(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata[uid],
                    data,
                )
            case "sensorThermo":
                return TydomThermo(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata[uid],
                    data,
                )
            case "plug":
                return TydomSwitch(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata[uid],
                    data,
                )
            case "remoteControl":
                return TydomRemote(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata[uid],
                    data,
                )
            case _:
                # TODO generic sensor ?
                LOGGER.warn(
                    "Unknown usage : %s for device_id %s, uid %s",
                    last_usage,
                    device_id,
                    uid,
                )
                return

    @staticmethod
    async def parse_config_data(parsed, transaction_id):
        """Parse config data."""
        LOGGER.debug("parse_config_data : %s", parsed)
        for i in parsed["endpoints"]:
            device_unique_id = str(i["id_endpoint"]) + "_" + str(i["id_device"])

            LOGGER.debug(
                "config_data device parsed : %s - %s", device_unique_id, i["name"]
            )

            device_name[device_unique_id] = i["name"]
            device_type[device_unique_id] = i["last_usage"] or "unknown"
            device_endpoint[device_unique_id] = i["id_endpoint"]

            if i["last_usage"] == "alarm":
                device_name[device_unique_id] = "Tyxal Alarm"

        LOGGER.debug("Configuration updated")
        return []

    async def parse_cmeta_data(self, parsed, transaction_id):
        """Parse cmeta data."""
        LOGGER.debug("parse_cmeta_data : %s", parsed)
        for i in parsed:
            for endpoint in i["endpoints"]:
                if len(endpoint["cmetadata"]) > 0:
                    for elem in endpoint["cmetadata"]:
                        if elem["name"] == "energyIndex":
                            for params in elem["parameters"]:
                                if params["name"] == "dest":
                                    for dest in params["enum_values"]:
                                        url = (
                                            "/devices/"
                                            + str(i["id"])
                                            + "/endpoints/"
                                            + str(endpoint["id"])
                                            + "/cdata?name="
                                            + elem["name"]
                                            + "&dest="
                                            + dest
                                            + "&reset=false"
                                        )
                                        self.tydom_client.add_poll_device_url_5m(url)
                                        LOGGER.debug("Add poll device : %s", url)
                        elif elem["name"] == "energyInstant":
                            for params in elem["parameters"]:
                                if params["name"] == "unit":
                                    for unit in params["enum_values"]:
                                        url = (
                                            "/devices/"
                                            + str(i["id"])
                                            + "/endpoints/"
                                            + str(endpoint["id"])
                                            + "/cdata?name="
                                            + elem["name"]
                                            + "&unit="
                                            + unit
                                            + "&reset=false"
                                        )
                                        self.tydom_client.add_poll_device_url_5m(url)
                                        LOGGER.debug("Add poll device : " + url)
                        elif elem["name"] == "energyHisto":
                            for params in elem["parameters"]:
                                if params["name"] == "dest":
                                    for dest in params["enum_values"]:
                                        url = (
                                            "/devices/"
                                            + str(i["id"])
                                            + "/endpoints/"
                                            + str(endpoint["id"])
                                            + "/cdata?name="
                                            + elem["name"]
                                            + "&period=YEAR&periodOffset=0&dest="
                                            + dest
                                        )
                                        self.tydom_client.add_poll_device_url_5m(url)
                                        LOGGER.debug("Add poll device : " + url)
                        elif elem["name"] == "energyDistrib":
                            for params in elem["parameters"]:
                                if params["name"] == "src":
                                    for src in params["enum_values"]:
                                        url = (
                                            "/devices/"
                                            + str(i["id"])
                                            + "/endpoints/"
                                            + str(endpoint["id"])
                                            + "/cdata?name="
                                            + elem["name"]
                                            + "&period=YEAR&periodOffset=0&src="
                                            + src
                                        )
                                        self.tydom_client.add_poll_device_url_5m(url)
                                        LOGGER.debug("Add poll device : " + url)

        LOGGER.debug("Metadata configuration updated")

    async def parse_devices_data(self, parsed, transaction_id):
        """Parse device data."""
        LOGGER.debug("parse_devices_data : %s", parsed)
        devices = []

        for i in parsed:
            if "endpoints" in i:
                for endpoint in i["endpoints"]:
                    if (
                        endpoint["error"] == 0
                        and "data" in endpoint
                        and len(endpoint["data"]) > 0
                    ):
                        try:
                            device_id = i["id"]
                            endpoint_id = endpoint["id"]
                            unique_id = str(endpoint_id) + "_" + str(device_id)
                            name_of_id = self.get_name_from_id(unique_id)
                            type_of_id = self.get_type_from_id(unique_id)

                            data = {}

                            for elem in endpoint["data"]:
                                element_name = elem["name"]
                                element_value = elem["value"]
                                element_validity = elem["validity"]

                                if element_validity == "upToDate":
                                    data[element_name] = element_value

                            # Create the device
                            device = await MessageHandler.get_device(
                                self.tydom_client,
                                type_of_id,
                                unique_id,
                                device_id,
                                name_of_id,
                                endpoint_id,
                                data,
                            )
                            if device is not None:
                                devices.append(device)
                                LOGGER.info(
                                    "Device update (id=%s, endpoint=%s, name=%s, type=%s)",
                                    device_id,
                                    endpoint_id,
                                    name_of_id,
                                    type_of_id,
                                )
                        except Exception:
                            LOGGER.exception("msg_data error in parsing !")
            else:
                LOGGER.warning("Unsupported message received: %s", parsed)
        return devices

    async def parse_devices_cdata(self, parsed, transaction_id: str | None = None):
        """Parse devices cdata."""
        LOGGER.debug("parse_devices_cdata : %s", parsed)
        devices = []

        for i in parsed:
            for endpoint in i["endpoints"]:
                if endpoint["error"] == 0 and len(endpoint["cdata"]) > 0:
                    try:
                        device_id = i["id"]
                        endpoint_id = endpoint["id"]
                        unique_id = str(endpoint_id) + "_" + str(device_id)
                        name_of_id = self.get_name_from_id(unique_id)
                        type_of_id = self.get_type_from_id(unique_id)

                        data = {}

                        for elem in endpoint["cdata"]:
                            if type_of_id == "conso":
                                element_name = None
                                if "parameters" in elem and elem["parameters"].get(
                                    "dest"
                                ):
                                    element_name = (
                                        elem["name"] + "_" + elem["parameters"]["dest"]
                                    )
                                    element_value = elem["values"]["counter"]
                                    data[element_name] = element_value
                                elif "parameters" in elem and elem["parameters"].get(
                                    "period"
                                ):
                                    for key in elem["values"]:
                                        if key.isupper():
                                            element_name = elem["name"] + "_" + key
                                            data[element_name] = elem["values"][key]
                                else:
                                    continue

                                # Create the device
                                device = await MessageHandler.get_device(
                                    self.tydom_client,
                                    type_of_id,
                                    unique_id,
                                    device_id,
                                    name_of_id,
                                    endpoint_id,
                                    data,
                                )

                                if device is not None:
                                    devices.append(device)
                                    LOGGER.debug(
                                        "Device update (id=%s, endpoint=%s, name=%s, type=%s)",
                                        device_id,
                                        endpoint_id,
                                        name_of_id,
                                        type_of_id,
                                    )

                            elif type_of_id == "alarm" and transaction_id is not None:
                                reply = None
                                for r in self._cdata_replies:
                                    if r["transaction_id"] == transaction_id:
                                        reply = r
                                        break
                                if reply is None:
                                    reply = Reply(
                                        transaction_id=transaction_id,
                                        events=[],
                                        done=False,
                                    )
                                    self._cdata_replies.insert(0, reply)
                                    # Limit the number of tracked replies
                                    if len(self._cdata_replies) > _MAX_REPLIES_SIZE:
                                        reply = self._cdata_replies.pop()
                                        LOGGER.warning(
                                            "Forget uncomplete request with transaction ID '%s'.",
                                            reply["transaction_id"],
                                        )
                                        self._end_reply_events.pop(
                                            reply["transaction_id"], None
                                        )

                                if elem.get("EOR", False):
                                    LOGGER.debug(
                                        "End of reply for request '%s'.", transaction_id
                                    )
                                    reply["done"] = True
                                    # Set the end reply event and forget about it
                                    if (
                                        event := self._end_reply_events.pop(
                                            transaction_id, None
                                        )
                                    ) is not None:
                                        event.set()
                                else:
                                    LOGGER.debug(
                                        "Catching new reply for request '%s'.",
                                        transaction_id,
                                    )
                                    reply["events"].append(elem)
                            else:
                                LOGGER.debug(
                                    "Ignore cdata message targetting '%s' (%s).",
                                    name_of_id,
                                    type_of_id,
                                )
                    except Exception as e:
                        LOGGER.exception("Error when parsing msg_cdata", exc_info=e)
        return devices

    # FUNCTIONS

    def get_type_from_id(self, id):
        """Get device type from id."""
        device_type_detected = ""
        if id in device_type:
            device_type_detected = device_type[id]
        else:
            LOGGER.warning("Unknown device type (%s)", id)
        return device_type_detected

    # Get pretty name for a device id
    def get_name_from_id(self, id):
        """Get device name from id."""
        name = ""
        if id in device_name:
            name = device_name[id]
        else:
            for deviceid in device_name:
                LOGGER.error("- device %s -> %s", deviceid, device_name[deviceid])
            LOGGER.warning("Unknown device name (%s)", id)
        return name


class BytesIOSocket:
    """BytesIOSocket."""

    def __init__(self, content):
        """Initialize a BytesIOSocket."""
        self.handle = BytesIO(content)

    def makefile(self, mode):
        """Get handle."""
        return self.handle


@dataclass(frozen=True)
class HTTPResponse:
    """HTTPResponse."""

    status: int
    headers: HTTPMessage
    body: bytes | None


def _parse_response(raw_message: bytes) -> HTTPResponse:
    sock = BytesIOSocket(raw_message)
    response = CoreHTTPResponse(sock)
    response.begin()

    return HTTPResponse(
        status=response.status, headers=response.headers, body=response.read()
    )


_MAXLINE = 65536


class _FakeHTTPRequest(CoreHTTPResponse):
    def _read_status(self):
        # This is the only line that is different for a request vs a response
        # so we fake it.
        line = str(self.fp.readline(_MAXLINE + 1), "iso-8859-1")
        if len(line) > _MAXLINE:
            raise LineTooLong("status line")
        if self.debuglevel > 0:
            print("reply:", repr(line))  # noqa: T201
        if not line:
            raise ValueError("No request line")

        words = line.rstrip("\r\n").split()

        version = words[-1]

        if not version.startswith("HTTP/"):
            self._close_conn()
            raise ValueError(line)

        command, path = words[:2]
        self.method = command
        self.path = path

        # Return fake status and reason to keep parsing the message
        return version, 200, ""


@dataclass(frozen=True)
class HTTPRequest:
    """HTTPRequest."""

    method: str
    path: str
    headers: HTTPMessage
    body: bytes | None


def parse_request(raw_request: bytes) -> HTTPRequest:
    """
    Parse a HTTP request sent through the websocket.

    Args:
        raw_request: Websocket message

    Returns:
        The parsed request.

    """
    sock = BytesIOSocket(raw_request)
    request = _FakeHTTPRequest(sock)
    request.begin()

    return HTTPRequest(
        method=request.method,
        path=request.path,
        headers=request.headers,
        body=request.read(),
    )
