"""Tydom message parsing."""

import asyncio
import contextlib
import json
import re
import time
from dataclasses import dataclass
from functools import partial
from http.client import HTTPMessage, LineTooLong
from http.client import HTTPResponse as CoreHTTPResponse
from io import BytesIO
from typing import TYPE_CHECKING, Any, TypedDict, cast

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
    TydomGroup,
    TydomInterrupter,
    TydomLight,
    TydomSwitch,
    TydomPlug,
    TydomRemoteControl,
    TydomShutter,
    TydomSmoke,
    TydomWindow,
    TydomWeather,
    TydomWater,
    TydomThermo,
    TydomSun,
    TydomScene,
    is_binary_tyxia_receiver_profile,
    resolve_device_model,
)


def _sanitize_uri(uri: str) -> str:
    """Redact credentials carried by legacy TYDOM query parameters."""
    return re.sub(
        r"([?&](?:password|pwd|passwd|token|access_token)=)[^&\s]*",
        r"\1***",
        uri,
        flags=re.IGNORECASE,
    )


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from .tydom_client import TydomClient

_MAX_REPLIES_SIZE = 5
"""Maximal number of replies to keep track of."""

_HISTO_END_INDEX = 255
"""Index value (0xFF) of the sentinel element closing an histo reply stream.

Some firmwares never send an EOR flag; they mark the end of the enumeration
with a last element carrying index 255 and invalid event data instead.
"""

_ENERGY_INSTANT_DIVISORS = {
    "ELEC_A": 100,
    "ELEC_W": 1,
}
"""Divisors used by TYDOM for supported instantaneous measurements."""


def _parse_energy_cdata_element(element: Any) -> dict[str, int | float]:
    """Extract sensor values from one successful energy cdata element."""
    if not isinstance(element, dict) or element.get("status", "OK") != "OK":
        return {}

    name = element.get("name")
    parameters = element.get("parameters")
    values = element.get("values")
    if not isinstance(parameters, dict) or not isinstance(values, dict):
        return {}

    if name == "energyIndex":
        destination = parameters.get("dest")
        counter = values.get("counter")
        if (
            not isinstance(destination, str)
            or destination.startswith("TEMP_")
            or not isinstance(counter, (int, float))
            or isinstance(counter, bool)
        ):
            return {}
        return {f"{name}_{destination}": counter}

    if name == "energyInstant":
        unit = parameters.get("unit")
        measure = values.get("measure")
        if (
            not isinstance(unit, str)
            or unit not in _ENERGY_INSTANT_DIVISORS
            or not isinstance(measure, (int, float))
            or isinstance(measure, bool)
        ):
            return {}
        return {f"{name}_{unit}": measure / _ENERGY_INSTANT_DIVISORS[unit]}

    if name in {"energyDistrib", "energyHisto"}:
        return {
            f"{name}_{key}": value
            for key, value in values.items()
            if isinstance(key, str)
            and key.isupper()
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        }

    return {}


_EMPTY_CDATA_EOR_GRACE = 0.1
"""Seconds to wait for TYXAL data sent just after an early empty EOR."""


def _is_tyxia_4910_other(uid: str) -> bool:
    """Identify a binary TYXIA 4910 configured under the TYDOM 'others' usage."""
    if str(device_tutorial_id.get(uid, "")).lower() != "9_tyxia_modulaire_serie4900":
        return False
    return is_binary_tyxia_receiver_profile(device_metadata.get(uid))


# Device dict for parsing
device_name = {}
device_endpoint = {}
device_type = {}
device_metadata = {}
device_tutorial_id = {}
interrupter_endpoint_config = {}
interrupter_info = {}
scenario_metadata = {}  # Store scenario metadata from /configs/file
groups_metadata = {}  # Store group metadata from /configs/file: {group_id: {"usage": "light", "name": "TOTAL"}}
groups_data = {}  # Store groups data: {group_id: {"devices": [device_ids], "name": group_name}}
endpoint_config = {}  # Store endpoint-specific configuration from /configs/file
remote_control_info = {}  # Store physical remote and button details by endpoint UID

SUPPORTED_CONTROL_GROUP_USAGES = {"awning", "light", "plug", "shutter"}
TOTAL_GROUP_NAMES = {
    "awning": "All awnings",
    "light": "All lights",
    "plug": "All plugs",
    "shutter": "All shutters",
}


def _remote_control_model(tutorial_id: str) -> str:
    """Return a friendly model name from a TYDOM tutorial identifier."""
    return (
        resolve_device_model(tutorial_id, "remoteControl")
        or "Delta Dore remote control"
    )


def _infer_separately_paired_tyxia_2600() -> None:
    """Identify the two endpoint records of a separately paired TYXIA 2600."""
    configs_by_device: dict[str, list[tuple[str, dict]]] = {}
    for unique_id, config in endpoint_config.items():
        if config.get("usage") == "interrupter":
            configs_by_device.setdefault(str(config["device_id"]), []).append(
                (unique_id, config)
            )

    for endpoint_items in configs_by_device.values():
        if len(endpoint_items) != 2:
            continue
        configs = [config for _, config in endpoint_items]
        if any(config.get("tutorial_id") for config in configs):
            continue

        names = [str(config.get("name", "")) for config in configs]
        has_numbered_switch = any(
            re.fullmatch(r"Interrupteur\s+\d+", name, flags=re.IGNORECASE)
            for name in names
        )
        has_common_button = any(
            re.fullmatch(r"CG_DD_COMMON_BUTTON[AB]", name, flags=re.IGNORECASE)
            for name in names
        )
        if not (has_numbered_switch and has_common_button):
            continue

        for unique_id, config in endpoint_items:
            config["tutorial_id"] = "switch_tyxia2600"
            device_tutorial_id[unique_id] = "switch_tyxia2600"


def _refresh_remote_control_info() -> None:
    """Combine endpoint configuration with related-endpoint group metadata."""
    remote_control_info.clear()

    for unique_id, config in endpoint_config.items():
        if config.get("usage") != "remoteControl":
            continue

        physical_device_id = str(config["device_id"])
        group_id = None
        group_name = f"Remote control {physical_device_id}"
        group_tutorial_id = ""

        for candidate_id, group in groups_data.items():
            group_metadata = groups_metadata.get(candidate_id, {})
            group_usage = group.get("usage") or group_metadata.get("usage")
            if group_usage != "remoteControl":
                continue
            if physical_device_id in group.get("devices", []):
                group_id = candidate_id
                group_name = (
                    group_metadata.get("name") or group.get("name") or group_name
                )
                group_tutorial_id = str(group_metadata.get("tutorial_id", ""))
                break

        endpoint_tutorial_id = str(config.get("tutorial_id", ""))
        tutorial_id = group_tutorial_id or endpoint_tutorial_id
        remote_control_info[unique_id] = {
            "physical_device_id": physical_device_id,
            "group_id": group_id,
            "name": group_name,
            "model": _remote_control_model(tutorial_id),
            "button_number": config.get("button_number"),
            "configured_action": config.get("configured_action", "TOGGLE"),
        }


@dataclass(frozen=True)
class AreaDeviceReference:
    """Identify the device endpoint whose state is backed by an area."""

    uid: str
    device_id: str
    endpoint_id: str


_AREA_CONTROL_ATTRIBUTES = {
    "authorization",
    "setpoint",
    "heatSetpoint",
    "coolSetpoint",
}

_TYWELL_CONTROL_SENSOR_ATTRIBUTES = {
    "hygroIn",
    "isReference",
    "shutterCmd",
    "synchroRadio",
}


def _is_physical_tywell_control_endpoint(
    uid: str, metadata: dict | None, data: dict | None
) -> bool:
    """Return whether an unlinked endpoint exposes physical Tywell controls.

    Some installations advertise the wall controller itself as
    ``re2020ControlBoiler`` without linking it to an area. Prefer Delta Dore's
    explicit tutorial identifier, then fall back to controller-only
    capabilities when configuration metadata is incomplete. Orphaned thermal
    proxies must not create misleading climate entities.
    """
    if str(device_tutorial_id.get(uid, "")).casefold() == "tywell_control":
        return True

    attributes = set(metadata or {}) | set(data or {})
    return bool(attributes & _TYWELL_CONTROL_SENSOR_ATTRIBUTES)


def _area_metadata_score(metadata: dict) -> int:
    """Measure how much writable HVAC information metadata contains."""
    return sum(attribute in metadata for attribute in _AREA_CONTROL_ATTRIBUTES)


def _area_control_metadata(parsed: list[dict]) -> dict[str, dict]:
    """Return the strongest writable HVAC metadata found for each area."""
    controls: dict[str, tuple[int, dict]] = {}
    for raw_device in parsed:
        device_id = raw_device.get("id")
        for endpoint in raw_device.get("endpoints", []):
            endpoint_id = endpoint.get("id")
            link = endpoint.get("link")
            if (
                device_id is None
                or endpoint_id is None
                or not isinstance(link, dict)
                or link.get("type") != "area"
                or link.get("id") is None
            ):
                continue

            uid = f"{endpoint_id}_{device_id}"
            metadata = device_metadata.get(uid, {})
            score = _area_metadata_score(metadata)
            area_id = str(link["id"])
            if score > controls.get(area_id, (-1, {}))[0]:
                controls[area_id] = (score, metadata)

    return {area_id: metadata for area_id, (_, metadata) in controls.items()}


class Reply(TypedDict):
    """cdata request reply."""

    transaction_id: str
    """Transaction ID."""
    events: list[dict]
    """Raw reply events."""
    done: bool
    """Whether all reply events have been received or not."""


def _interrupter_model(tutorial_id: str) -> str:
    """Return a friendly wall-switch model from its tutorial identifier."""
    if tutorial_id.startswith("switch_tyxia2600"):
        return "TYXIA 2600"
    return "Delta Dore wall switch"


def _is_ungrouped_tyxia_2600(endpoint_configs: list[dict]) -> bool:
    """Recognise a TYXIA 2600 whose two outputs were paired separately."""
    if len(endpoint_configs) != 2:
        return False

    names = [str(config.get("name", "")) for config in endpoint_configs]
    return any(
        re.fullmatch(r"Interrupteur\s+\d+", name, flags=re.IGNORECASE) for name in names
    ) and any(
        re.fullmatch(r"CG_DD_COMMON_BUTTON[AB]", name, flags=re.IGNORECASE)
        for name in names
    )


def _refresh_interrupter_info() -> None:
    """Combine button endpoint configuration with its physical device group."""
    interrupter_info.clear()

    configs_by_device: dict[str, list[tuple[str, dict]]] = {}
    for unique_id, config in interrupter_endpoint_config.items():
        configs_by_device.setdefault(str(config["device_id"]), []).append(
            (unique_id, config)
        )

    for physical_device_id, endpoint_items in configs_by_device.items():
        endpoint_configs = [config for _, config in endpoint_items]
        group_id = None
        friendly_names = [
            str(config.get("name", ""))
            for config in endpoint_configs
            if config.get("name")
            and not re.fullmatch(
                r"CG_DD_COMMON_BUTTON[A-Z0-9]+",
                str(config["name"]),
                flags=re.IGNORECASE,
            )
        ]
        group_name = friendly_names[0] if friendly_names else "Wall switch"
        group_tutorial_id = ""

        for candidate_id, group in groups_data.items():
            group_metadata = groups_metadata.get(candidate_id, {})
            group_usage = group.get("usage") or group_metadata.get("usage")
            if group_usage != "interrupter":
                continue
            if physical_device_id in group.get("devices", []):
                group_id = candidate_id
                group_name = (
                    group_metadata.get("name") or group.get("name") or group_name
                )
                group_tutorial_id = str(group_metadata.get("tutorial_id", ""))
                break

        if not group_tutorial_id and _is_ungrouped_tyxia_2600(endpoint_configs):
            group_tutorial_id = "switch_tyxia2600"

        assigned_buttons = {
            str(config["button"])
            for config in endpoint_configs
            if config.get("button") in {"A", "B"}
        }
        missing_buttons = {"A", "B"} - assigned_buttons
        missing_configs = [
            config for config in endpoint_configs if config.get("button") is None
        ]
        if (
            len(endpoint_configs) == 2
            and len(missing_configs) == 1
            and len(missing_buttons) == 1
        ):
            missing_configs[0]["button"] = missing_buttons.pop()

        for unique_id, config in endpoint_items:
            endpoint_tutorial_id = str(config.get("tutorial_id", ""))
            button = config.get("button")
            if button is not None:
                device_name[unique_id] = f"Button {button}"
            interrupter_info[unique_id] = {
                "physical_device_id": physical_device_id,
                "group_id": group_id,
                "name": group_name,
                "model": _interrupter_model(group_tutorial_id or endpoint_tutorial_id),
                "button": button,
                "configured_action": config.get("configured_action", "TOGGLE"),
            }


class MessageHandler:
    """Handle incoming Tydom messages."""

    def __init__(self, tydom_client: "TydomClient", cmd_prefix: bytes) -> None:
        """Initialize MessageHandler."""
        self.tydom_client = tydom_client
        self.cmd_prefix = cmd_prefix
        self._cdata_replies: list[Reply] = []
        self._end_reply_events: dict[str, asyncio.Event] = {}
        self._reply_errors: dict[str, str] = {}
        self._area_devices: dict[str, dict[str, AreaDeviceReference]] = {}
        self._area_data: dict[str, dict[str, Any]] = {}
        self._area_metadata: dict[str, dict] = {}

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

    def remove_reply(self, transaction_id: str) -> None:
        """
        Remove a pending reply to prevent memory leaks.

        This should be called when a request times out or fails.

        Args:
            transaction_id: The transaction ID of the request to remove.

        """
        # Remove from cdata_replies
        for reply in self._cdata_replies[:]:
            if reply["transaction_id"] == transaction_id:
                self._cdata_replies.remove(reply)
                break

        # Remove from end_reply_events
        self._end_reply_events.pop(transaction_id, None)
        LOGGER.debug("Removed pending reply for transaction_id: %s", transaction_id)

    def get_reply_error(self, transaction_id: str) -> str | None:
        """Return and forget a protocol error for one pending request."""
        return self._reply_errors.pop(transaction_id, None)

    def _complete_empty_cdata_reply(self, transaction_id: str) -> None:
        """Complete an EOR-only reply unless late TYXAL data completed it first."""
        if event := self._end_reply_events.pop(transaction_id, None):
            event.set()

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
            status = None
            if stripped_msg.startswith(b"HTTP/"):
                parsed_message = _parse_response(stripped_msg)
                # Find Uri-Origin in header if available
                uri_origin = parsed_message.headers.get("Uri-Origin", "")
                status = parsed_message.status

            else:
                parsed_message = parse_request(stripped_msg)
                uri_origin = parsed_message.path
            transaction_id = parsed_message.headers.get("Transac-Id")

            if status is not None and status >= 400:
                # The box rejected the request; surface the error body (an
                # HTML page naming the cause) instead of dropping it in the
                # html no-op, and resolve any pending reply right away
                # instead of letting it time out.
                LOGGER.warning(
                    "Request '%s' (%s) rejected with HTTP status %s: %s",
                    transaction_id,
                    _sanitize_uri(uri_origin),
                    status,
                    (parsed_message.body or b"")[:500],
                )
                if transaction_id and transaction_id in self._end_reply_events:
                    detail = (parsed_message.body or b"").decode(
                        "utf-8", errors="replace"
                    )
                    self._reply_errors[transaction_id] = (
                        f"HTTP {status}: {re.sub(r'<[^>]+>', ' ', detail).strip()}"
                    )
                    event = self._end_reply_events.get(transaction_id)
                    self.remove_reply(transaction_id)
                    if event is not None:
                        event.set()
                return None

            if status is not None and not parsed_message.body:
                # Successful GET/PUT requests can be acknowledged with an empty
                # body while the updated state arrives in a separate push. This
                # also happens for requests using the gateway's reserved
                # transaction id "0", which are not tracked as pending replies.
                # A ping is itself completed by this empty 200 response, so it
                # must still reach the liveness bookkeeping even though there is
                # no body to parse.
                if uri_origin == "/ping":
                    self.tydom_client.receive_pong()
                LOGGER.debug(
                    "Empty acknowledgment received for request '%s' (%s).",
                    transaction_id,
                    uri_origin,
                )
                return None

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
            "/areas/data": self.parse_areas_data,
            "/configs/file": MessageHandler.parse_config_data,
            "/configs/gateway/api_mode": partial(no_op, "msg_api_mode"),
            "/devices/cdata": self.parse_devices_cdata,
            "/devices/cmeta": self.parse_cmeta_data,
            "/devices/install": partial(no_op, "msg_pairing"),
            "/devices/meta": self.parse_devices_metadata,
            "/events": event_message,
            "/groups/file": self.parse_groups_file,
            "/info": self.parse_msg_info,
            "/ping": ping_message,
            "/refresh/all": partial(no_op, "msg_refresh_all"),
            "/scenarios/file": self.parse_scenarios_file,
            "/moments/file": self.parse_moments_file,
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
            mapping_key = "/events" if uri_origin.startswith("/events/") else uri_origin
            msg_type = MSG_MAPPING.get(mapping_key)

            if msg_type is None and uri_origin:
                area_data = re.fullmatch(r"/areas/([^/]+)/data", uri_origin)
                if area_data:
                    msg_type = partial(
                        self.parse_areas_data, area_id=area_data.group(1)
                    )

            if msg_type is None and uri_origin:
                # Response to GET /devices/{id}/endpoints/{id}/data (adaptive
                # polling): a single flat {"id", "error", "data"} object, not
                # the list-of-devices shape parse_devices_data expects. Rebuild
                # the canonical shape using the ids from the URI (authoritative,
                # and device/endpoint ids can differ).
                endpoint_data = re.fullmatch(
                    r"/devices/(\d+)/endpoints/(\d+)/data", uri_origin
                )
                if endpoint_data and isinstance(parsed, dict):
                    parsed = [
                        {
                            "id": int(endpoint_data.group(1)),
                            "endpoints": [
                                {
                                    "id": int(endpoint_data.group(2)),
                                    "error": parsed.get("error", 0),
                                    "data": parsed.get("data", []),
                                }
                            ],
                        }
                    ]
                    msg_type = self.parse_devices_data

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
        model = resolve_device_model(
            device_tutorial_id.get(uid),
            last_usage,
            device_metadata.get(uid),
            data,
        )
        if model is not None:
            data = dict(data or {})
            data.setdefault("productName", model)

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
                    device_metadata.get(uid),
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
                    device_metadata.get(uid),
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
                    device_metadata.get(uid),
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
                    device_metadata.get(uid),
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
                    device_metadata.get(uid),
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
                    device_metadata.get(uid),
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
                    device_metadata.get(uid),
                    data,
                )
            case "re2020ControlBoiler":
                if data is None or data.get("area_id") is None:
                    metadata = device_metadata.get(uid)
                    if not _is_physical_tywell_control_endpoint(uid, metadata, data):
                        LOGGER.debug(
                            "Ignoring unlinked Tywell thermal endpoint %s (%s)",
                            uid,
                            name,
                        )
                        return None
                    LOGGER.debug(
                        "Keeping unlinked physical Tywell Control %s (%s) as sensors",
                        uid,
                        name,
                    )
                    return TydomDevice(
                        tydom_client,
                        uid,
                        device_id,
                        name,
                        last_usage,
                        endpoint,
                        metadata,
                        data,
                    )
                return TydomBoiler(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata.get(uid),
                    data,
                )
            case "re2020ControlPassive":
                return TydomDevice(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata.get(uid),
                    data,
                )
            case "interrupter":
                return TydomInterrupter(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata.get(uid),
                    data,
                    interrupter_info.get(uid),
                )
            case "boiler" | "sh_hvac" | "electric" | "aeraulic":
                return TydomBoiler(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata.get(uid),
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
                    device_metadata.get(uid),
                    data,
                )
            case "weather":
                weather_device = TydomWeather(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata.get(uid),
                    data,
                )
                passive_controllers = [
                    controller_uid
                    for controller_uid, controller_type in device_type.items()
                    if controller_type == "re2020ControlPassive"
                ]
                if len(passive_controllers) == 1:
                    controller_uid = passive_controllers[0]
                    weather_device.group_with_registry_device(
                        controller_uid,
                        device_name.get(controller_uid, "Tywell Control"),
                    )
                return weather_device
            case "sensorDF":
                return TydomWater(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata.get(uid),
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
                    device_metadata.get(uid),
                    data,
                )
            case "others" if _is_tyxia_4910_other(uid):
                return TydomSwitch(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata.get(uid),
                    data,
                )
            case "sensorSun":
                return TydomSun(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata.get(uid),
                    data,
                )
            case "plug":
                return TydomPlug(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata.get(uid),
                    data,
                )
            case "remoteControl":
                return TydomRemoteControl(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata.get(uid),
                    data,
                    remote_control_info.get(uid),
                )
            case _:
                LOGGER.info(
                    "Unknown usage : %s for device_id %s, uid %s - creating generic sensor",
                    last_usage,
                    device_id,
                    uid,
                )
                return TydomDevice(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata.get(uid),
                    data,
                )

    @staticmethod
    async def parse_config_data(parsed, transaction_id):
        """Parse config data."""
        LOGGER.debug("parse_config_data : %s", parsed)
        for i in parsed["endpoints"]:
            device_unique_id = str(i["id_endpoint"]) + "_" + str(i["id_device"])

            LOGGER.debug(
                "config_data device parsed : %s - %s", device_unique_id, i["name"]
            )
            device_tutorial_id[device_unique_id] = (i.get("widget_behavior") or {}).get(
                "tutorial_id", ""
            )

            device_name[device_unique_id] = i["name"]
            device_type[device_unique_id] = i["last_usage"] or "unknown"
            device_endpoint[device_unique_id] = i["id_endpoint"]
            widget_behavior = i.get("widget_behavior") or {}
            tutorial_id = str(widget_behavior.get("tutorial_id", ""))
            button_match = re.search(
                r"BUTTON(\d+)", str(i.get("name", ""))
            ) or re.search(r"_btn_(\d+)$", tutorial_id)
            endpoint_config[device_unique_id] = {
                "device_id": i["id_device"],
                "endpoint_id": i["id_endpoint"],
                "name": i.get("name", ""),
                "usage": i.get("last_usage") or "unknown",
                "tutorial_id": tutorial_id,
                "configured_action": widget_behavior.get("action", "TOGGLE"),
                "button_number": (
                    int(button_match.group(1)) if button_match is not None else None
                ),
            }

            if i.get("last_usage") == "remoteControl" and button_match is not None:
                device_name[device_unique_id] = f"Button {button_match.group(1)}"

            if i.get("last_usage") == "interrupter":
                widget_behavior = i.get("widget_behavior") or {}
                tutorial_id = str(widget_behavior.get("tutorial_id", ""))
                button_match = re.search(
                    r"BUTTON([A-Z0-9]+)", str(i.get("name", ""))
                ) or re.search(r"_btn_([a-z0-9]+)$", tutorial_id)
                button = button_match.group(1).upper() if button_match else None
                interrupter_endpoint_config[device_unique_id] = {
                    "device_id": i["id_device"],
                    "endpoint_id": i["id_endpoint"],
                    "name": i.get("name", ""),
                    "tutorial_id": tutorial_id,
                    "configured_action": widget_behavior.get("action", "TOGGLE"),
                    "button": button,
                }
                if button is not None:
                    device_name[device_unique_id] = f"Button {button}"

            if i["last_usage"] == "alarm":
                device_name[device_unique_id] = "Tyxal Alarm"

        _infer_separately_paired_tyxia_2600()

        # Parse scenarios metadata from /configs/file
        if "scenarios" in parsed and isinstance(parsed["scenarios"], list):
            for scenario in parsed["scenarios"]:
                if isinstance(scenario, dict) and "id" in scenario:
                    scenario_id = scenario["id"]
                    scenario_metadata[scenario_id] = {
                        "name": scenario.get("name", f"Scenario {scenario_id}"),
                        "type": scenario.get("type", "NORMAL"),
                        "picto": scenario.get("picto", ""),
                        "rule_id": scenario.get("rule_id", ""),
                    }
                    LOGGER.debug(
                        "Stored scenario metadata: id=%s, name=%s",
                        scenario_id,
                        scenario_metadata[scenario_id]["name"],
                    )

        # Parse groups metadata from /configs/file
        if "groups" in parsed and isinstance(parsed["groups"], list):
            for group in parsed["groups"]:
                if isinstance(group, dict) and "id" in group:
                    group_id = group.get("id")
                    group_id_str = str(group_id)
                    groups_metadata[group_id_str] = {
                        "usage": group.get("usage", ""),
                        "name": group.get("name", f"Group {group_id}"),
                        "group_all": bool(group.get("group_all", False)),
                        "is_group_user": bool(group.get("is_group_user", False)),
                        "tutorial_id": (group.get("widget_behavior") or {}).get(
                            "tutorial_id", ""
                        ),
                    }
                    LOGGER.debug(
                        "Stored group metadata: id=%s, usage=%s, name=%s",
                        group_id_str,
                        groups_metadata[group_id_str]["usage"],
                        groups_metadata[group_id_str]["name"],
                    )

        _refresh_remote_control_info()
        _refresh_interrupter_info()
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
                                        # cmeta declares "reset" as a real
                                        # parameter of this cdata name, unlike
                                        # assumed earlier - keep it.
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
        seen_unique_ids = {}  # Track unique_ids to detect collisions

        if isinstance(parsed, dict):
            # A bare device object would otherwise be iterated key by key,
            # logging one "Unsupported message" warning per key.
            parsed = [parsed]

        for area_id, metadata in _area_control_metadata(parsed).items():
            if _area_metadata_score(metadata) >= _area_metadata_score(
                self._area_metadata.get(area_id, {})
            ):
                self._area_metadata[area_id] = metadata.copy()
        area_metadata = self._area_metadata

        for i in parsed:
            if "endpoints" in i:
                device_id = i["id"]
                for endpoint in i["endpoints"]:
                    endpoint_id = endpoint["id"]
                    unique_id = str(endpoint_id) + "_" + str(device_id)

                    # Check for collisions
                    if unique_id in seen_unique_ids:
                        LOGGER.warning(
                            "Collision d'identifiant détectée : unique_id=%s déjà vu "
                            "(device_id=%s, endpoint_id=%s). "
                            "Appareil précédent : device_id=%s, endpoint_id=%s",
                            unique_id,
                            device_id,
                            endpoint_id,
                            seen_unique_ids[unique_id]["device_id"],
                            seen_unique_ids[unique_id]["endpoint_id"],
                        )

                    # Get device name and type first to check if device is registered
                    name_of_id = self.get_name_from_id(unique_id)
                    type_of_id = self.get_type_from_id(unique_id)

                    # Check if device is registered in configuration
                    if not name_of_id or name_of_id == "":
                        LOGGER.warning(
                            "Endpoint ignoré (appareil non enregistré dans la configuration) : "
                            "device_id=%s, endpoint_id=%s, unique_id=%s",
                            device_id,
                            endpoint_id,
                            unique_id,
                        )
                        continue

                    if not type_of_id or type_of_id == "":
                        LOGGER.warning(
                            "Endpoint ignoré (type d'appareil inconnu) : "
                            "device_id=%s, endpoint_id=%s, unique_id=%s, name=%s",
                            device_id,
                            endpoint_id,
                            unique_id,
                            name_of_id,
                        )
                        continue

                    # Check for errors or missing data, but still try to create device
                    has_error = endpoint.get("error", 0) != 0
                    has_data = "data" in endpoint and len(endpoint.get("data", [])) > 0

                    if has_error:
                        LOGGER.warning(
                            "Endpoint avec erreur (création quand même) : "
                            "device_id=%s, endpoint_id=%s, error=%s",
                            device_id,
                            endpoint_id,
                            endpoint.get("error"),
                        )

                    if not has_data:
                        LOGGER.warning(
                            "Endpoint sans données valides (création avec état par défaut) : "
                            "device_id=%s, endpoint_id=%s, name=%s",
                            device_id,
                            endpoint_id,
                            name_of_id,
                        )

                    try:
                        data = {}
                        area_id = None
                        passive_climate_uid = None

                        link = endpoint.get("link")
                        if (
                            isinstance(link, dict)
                            and link.get("type") == "area"
                            and link.get("id") is not None
                        ):
                            area_id = str(link["id"])
                            reference_uid = unique_id
                            if type_of_id == "re2020ControlPassive":
                                passive_climate_uid = f"{unique_id}_area_climate"
                                reference_uid = passive_climate_uid
                                device_name[passive_climate_uid] = (
                                    f"{name_of_id} Thermostat"
                                )
                                device_type[passive_climate_uid] = "re2020ControlBoiler"
                                device_endpoint[passive_climate_uid] = endpoint_id
                                device_metadata[passive_climate_uid] = (
                                    area_metadata.get(
                                        area_id, device_metadata.get(unique_id, {})
                                    ).copy()
                                )
                            else:
                                data["area_id"] = area_id

                            reference = AreaDeviceReference(
                                uid=reference_uid,
                                device_id=str(device_id),
                                endpoint_id=str(endpoint_id),
                            )
                            self._area_devices.setdefault(area_id, {})[
                                reference_uid
                            ] = reference

                        # Only process data if available and valid
                        if has_data and not has_error:
                            for elem in endpoint["data"]:
                                element_name = elem["name"]
                                element_value = elem["value"]
                                element_validity = elem["validity"]

                                if element_validity == "upToDate":
                                    data[element_name] = element_value

                        if (
                            area_id is not None
                            and area_id in self._area_data
                            and passive_climate_uid is None
                        ):
                            data.update(self._area_data[area_id])

                        # Create the device (even without data)
                        device = await MessageHandler.get_device(
                            self.tydom_client,
                            type_of_id,
                            unique_id,
                            device_id,
                            name_of_id,
                            endpoint_id,
                            data if data else None,
                        )
                        if device is not None:
                            devices.append(device)
                            seen_unique_ids[unique_id] = {
                                "device_id": device_id,
                                "endpoint_id": endpoint_id,
                            }
                            if has_data and not has_error:
                                LOGGER.info(
                                    "Device update (id=%s, endpoint=%s, name=%s, type=%s)",
                                    device_id,
                                    endpoint_id,
                                    name_of_id,
                                    type_of_id,
                                )
                            else:
                                LOGGER.info(
                                    "Device créé sans données (id=%s, endpoint=%s, name=%s, type=%s)",
                                    device_id,
                                    endpoint_id,
                                    name_of_id,
                                    type_of_id,
                                )

                            if passive_climate_uid is not None and area_id is not None:
                                climate_data = self._area_data.get(
                                    area_id, {"area_id": area_id}
                                ).copy()
                                for temperature_attribute in (
                                    "temperature",
                                    "ambientTemperature",
                                ):
                                    if temperature_attribute in data:
                                        climate_data[temperature_attribute] = data[
                                            temperature_attribute
                                        ]
                                climate_device = await MessageHandler.get_device(
                                    self.tydom_client,
                                    "re2020ControlBoiler",
                                    passive_climate_uid,
                                    device_id,
                                    device_name[passive_climate_uid],
                                    endpoint_id,
                                    climate_data,
                                )
                                if climate_device is not None:
                                    devices.append(climate_device)
                                    seen_unique_ids[passive_climate_uid] = {
                                        "device_id": device_id,
                                        "endpoint_id": endpoint_id,
                                    }
                                    LOGGER.debug(
                                        "Area climate created (area=%s, device=%s, "
                                        "endpoint=%s, name=%s)",
                                        area_id,
                                        device_id,
                                        endpoint_id,
                                        climate_device.device_name,
                                    )
                        else:
                            LOGGER.warning(
                                "Device non créé (get_device retourné None) : "
                                "device_id=%s, endpoint_id=%s, name=%s, type=%s",
                                device_id,
                                endpoint_id,
                                name_of_id,
                                type_of_id,
                            )
                    except Exception:
                        LOGGER.exception(
                            "msg_data error in parsing ! device_id=%s, endpoint_id=%s",
                            device_id,
                            endpoint_id,
                        )
            else:
                LOGGER.warning("Unsupported message received: %s", parsed)
        return devices

    async def parse_areas_data(
        self, parsed, transaction_id, area_id: str | None = None
    ):
        """Map area state onto the device endpoint linked to that area."""
        LOGGER.debug("parse_areas_data: %s", parsed)
        devices = []

        areas = parsed if isinstance(parsed, list) else [parsed]
        for area in areas:
            if not isinstance(area, dict):
                continue

            current_area_id = area_id if area_id is not None else area.get("id")
            if current_area_id is None:
                LOGGER.warning("Area data received without an area id: %s", area)
                continue

            current_area_id = str(current_area_id)
            if area.get("error", 0) != 0:
                LOGGER.warning(
                    "Ignoring area %s data with error %s",
                    current_area_id,
                    area.get("error"),
                )
                continue

            references = self._area_devices.get(current_area_id, {})
            if not references:
                LOGGER.debug(
                    "Caching data for area %s until a linked endpoint is discovered",
                    current_area_id,
                )

            data = {"area_id": current_area_id}
            for element in area.get("data", []):
                if (
                    isinstance(element, dict)
                    and element.get("validity") == "upToDate"
                    and "name" in element
                ):
                    data[element["name"]] = element.get("value")

            cached_data = self._area_data.setdefault(
                current_area_id, {"area_id": current_area_id}
            )
            cached_data.update(data)
            data = cached_data.copy()

            for reference in references.values():
                device = await MessageHandler.get_device(
                    self.tydom_client,
                    self.get_type_from_id(reference.uid),
                    reference.uid,
                    reference.device_id,
                    self.get_name_from_id(reference.uid),
                    reference.endpoint_id,
                    data,
                )
                if device is not None:
                    devices.append(device)
                    LOGGER.debug(
                        "Area update (area=%s, device=%s, endpoint=%s, name=%s)",
                        current_area_id,
                        reference.device_id,
                        reference.endpoint_id,
                        device.device_name,
                    )

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
                                data.update(_parse_energy_cdata_element(elem))

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
                                        forgotten_reply = self._cdata_replies.pop()
                                        LOGGER.warning(
                                            "Forget uncomplete request with transaction ID '%s'.",
                                            forgotten_reply["transaction_id"],
                                        )
                                        self._end_reply_events.pop(
                                            forgotten_reply["transaction_id"], None
                                        )

                                values = elem.get("values") or {}
                                if (
                                    elem.get("EOR", False)
                                    or values.get("index") == _HISTO_END_INDEX
                                ):
                                    LOGGER.debug(
                                        "End of reply for request '%s'.", transaction_id
                                    )
                                    reply["done"] = True
                                    if reply["events"]:
                                        # A streamed response has already
                                        # supplied its data, so EOR completes
                                        # it immediately.
                                        if (
                                            event := self._end_reply_events.pop(
                                                transaction_id, None
                                            )
                                        ) is not None:
                                            event.set()
                                    elif transaction_id in self._end_reply_events:
                                        # Some CS8000 firmware emits EOR a few
                                        # milliseconds before its single cdata
                                        # object. Give that object a brief
                                        # chance to arrive before treating the
                                        # response as genuinely empty.
                                        asyncio.get_running_loop().call_later(
                                            _EMPTY_CDATA_EOR_GRACE,
                                            self._complete_empty_cdata_reply,
                                            transaction_id,
                                        )
                                else:
                                    LOGGER.debug(
                                        "Catching new reply for request '%s'.",
                                        transaction_id,
                                    )
                                    reply["events"].append(elem)
                                    # Configuration reads and writes return one
                                    # cdata object. Unlike streamed history,
                                    # they do not require an EOR sentinel.
                                    if elem.get("name") != "histo":
                                        reply["done"] = True
                                        if (
                                            event := self._end_reply_events.pop(
                                                transaction_id, None
                                            )
                                        ) is not None:
                                            event.set()
                            else:
                                LOGGER.debug(
                                    "Ignore cdata message targetting '%s' (%s).",
                                    name_of_id,
                                    type_of_id,
                                )

                        if type_of_id == "conso" and data:
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
                    except Exception as e:
                        LOGGER.exception("Error when parsing msg_cdata", exc_info=e)
        return devices

    async def parse_scenarios_file(self, parsed, transaction_id):
        """Parse scenarios file."""
        LOGGER.debug("parse_scenarios_file : %s", parsed)
        devices = []

        if not parsed or not isinstance(parsed, dict):
            return devices

        scenarios = parsed.get("scn", [])
        if not isinstance(scenarios, list):
            return devices

        for scenario in scenarios:
            if not isinstance(scenario, dict):
                continue

            scenario_id = scenario.get("id")

            if scenario_id is None:
                continue

            # Get scenario metadata from configs/file (stored in scenario_metadata dict)
            scenario_meta = scenario_metadata.get(scenario_id, {})
            scenario_name = scenario_meta.get("name", f"Scenario {scenario_id}")
            scenario_type = scenario_meta.get("type", "NORMAL")
            scenario_picto = scenario_meta.get("picto", "")
            scenario_rule_id = scenario_meta.get("rule_id", "")

            # Create unique ID for scene
            unique_id = f"scene_{scenario_id}"

            # Store scene info in device_name and device_type for consistency
            device_name[unique_id] = scenario_name
            device_type[unique_id] = "scene"

            # Merge scenario data with metadata
            scenario_data = {
                "scene_id": scenario_id,
                "name": scenario_name,
                "type": scenario_type,
                "picto": scenario_picto,
                "rule_id": scenario_rule_id,
                **scenario,  # Include grpAct, epAct, etc. from scenarios/file
            }

            # Create TydomScene device
            scene_device = TydomScene(
                self.tydom_client,
                unique_id,
                str(scenario_id),
                scenario_name,
                "scene",
                None,
                None,
                scenario_data,
            )
            devices.append(scene_device)
            LOGGER.debug(
                "Created scene: %s (id: %s, type: %s, picto: %s)",
                scenario_name,
                scenario_id,
                scenario_type,
                scenario_picto,
            )

        return devices

    async def parse_groups_file(self, parsed, transaction_id):
        """Parse groups file and create TydomGroup devices."""
        LOGGER.debug("parse_groups_file : %s", parsed)
        devices = []
        # Store groups data for resolving grpAct in scenarios
        if parsed and isinstance(parsed, dict):
            groups = parsed.get("groups", [])
            if isinstance(groups, list):
                for group in groups:
                    if isinstance(group, dict) and "id" in group:
                        group_id = group.get("id")
                        group_id_str = str(group_id)

                        # Extract device IDs from the group
                        device_ids = []
                        devices_list = group.get("devices", [])
                        if isinstance(devices_list, list):
                            for device in devices_list:
                                if isinstance(device, dict):
                                    # Get device ID
                                    dev_id = device.get("id")
                                    if dev_id:
                                        device_ids.append(str(dev_id))

                                    # Also get endpoint IDs as they might be used as device IDs
                                    endpoints = device.get("endpoints", [])
                                    if isinstance(endpoints, list):
                                        for endpoint in endpoints:
                                            if isinstance(endpoint, dict):
                                                ep_id = endpoint.get("id")
                                                if ep_id:
                                                    ep_id_str = str(ep_id)
                                                    # Try format epId_devId if dev_id exists
                                                    if dev_id:
                                                        unique_id = (
                                                            f"{ep_id_str}_{dev_id}"
                                                        )
                                                        if unique_id not in device_ids:
                                                            device_ids.append(unique_id)
                                                    # Also add epId alone
                                                    if ep_id_str not in device_ids:
                                                        device_ids.append(ep_id_str)

                        # Get group metadata from /configs/file if available
                        group_meta = groups_metadata.get(group_id_str, {})
                        group_usage = group_meta.get("usage", "")
                        config_name = group_meta.get("name", "")

                        if (
                            config_name == "TOTAL"
                            and group_meta.get("group_all", False)
                            and group_usage in TOTAL_GROUP_NAMES
                        ):
                            group_name = TOTAL_GROUP_NAMES[group_usage]
                        elif config_name and config_name != f"Group {group_id}":
                            group_name = config_name
                        else:
                            group_name = f"Group {group_id}"

                        # Store group data
                        groups_data[group_id_str] = {
                            "devices": device_ids,
                            "name": group_name,
                            "usage": group_usage,
                        }

                        if not device_ids:
                            LOGGER.debug(
                                "Skipping empty %s group %s",
                                group_usage or "unknown",
                                group_id_str,
                            )
                            continue

                        if group_usage in {"remoteControl", "interrupter"}:
                            LOGGER.debug(
                                "Skipping non-controllable input group %s",
                                group_id_str,
                            )
                            continue

                        if group_usage not in SUPPORTED_CONTROL_GROUP_USAGES:
                            LOGGER.debug(
                                "Skipping unsupported %s group %s",
                                group_usage or "unknown",
                                group_id_str,
                            )
                            continue

                        group_device = TydomGroup(
                            self.tydom_client,
                            group_id_str,
                            group_name,
                            device_ids,
                            usage=group_usage,  # Pass usage for translation
                        )
                        devices.append(group_device)

                        LOGGER.debug(
                            "Created group: %s (%s) with %d device(s)",
                            group_id_str,
                            group_name,
                            len(device_ids),
                        )
                LOGGER.debug(
                    "Found and created %d groups",
                    len(groups) if isinstance(groups, list) else 0,
                )
                _refresh_remote_control_info()
                _refresh_interrupter_info()
        return devices

    async def parse_moments_file(self, parsed, transaction_id):
        """Parse moments file and create TydomMoment devices."""
        LOGGER.debug("parse_moments_file : %s", parsed)
        devices = []
        if parsed and isinstance(parsed, dict):
            moments = parsed.get("moments", [])
            if isinstance(moments, list):
                for moment in moments:
                    if isinstance(moment, dict) and "id" in moment:
                        moment_id = moment.get("id")
                        moment_id_str = str(moment_id)
                        moment_name = moment.get("name", f"Moment {moment_id}")

                        # Create TydomMoment device
                        # Import here to avoid circular import
                        from .tydom_devices import TydomMoment

                        moment_device = TydomMoment(
                            self.tydom_client,
                            moment_id_str,
                            moment_name,
                            moment,
                        )
                        devices.append(moment_device)

                        LOGGER.debug(
                            "Created moment: %s (%s)",
                            moment_id_str,
                            moment_name,
                        )
            LOGGER.debug(
                "Found and created %d moments/programs",
                len(moments) if isinstance(moments, list) else 0,
            )
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
    # CoreHTTPResponse expects a socket, but BytesIOSocket implements the interface
    response = CoreHTTPResponse(cast(Any, sock))
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
            if hasattr(self, "_close_conn"):
                # _close_conn is a dynamic attribute added by http.client
                getattr(self, "_close_conn")()
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
    # _FakeHTTPRequest inherits from CoreHTTPResponse which expects a socket
    request = _FakeHTTPRequest(cast(Any, sock))
    request.begin()

    return HTTPRequest(
        method=request.method,
        path=request.path,
        headers=request.headers,
        body=request.read(),
    )
