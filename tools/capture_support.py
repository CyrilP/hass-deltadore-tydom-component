"""Shared helpers for TYDOM capture tools.

This module deliberately contains no network or Home Assistant dependencies so
that captured protocol frames can be parsed and sanitised independently.
"""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress
import json
import re
from typing import Any


INITIAL_GET_REQUESTS = (
    "/info",
    "/configs/file",
    "/devices/meta",
    "/areas/meta",
    "/devices/cmeta",
    "/areas/cmeta",
    "/devices/data",
    "/areas/data",
    "/scenarios/file",
    "/groups/file",
    "/moments/file",
)

_HTTP_METHODS = {"DELETE", "GET", "PATCH", "POST", "PUT"}
_SENSITIVE_KEYS = {
    "access_token",
    "delta_password",
    "id_token",
    "passwd",
    "password",
    "pwd",
    "refresh_token",
    "token",
}
_EMAIL_PATTERN = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}")
_JSON_SECRET_PATTERN = re.compile(
    r'(?i)("(?:access_token|id_token|passwd|password|pwd|'
    r'refresh_token|token)"\s*:\s*")([^"]*)(")'
)
_ASSIGNMENT_SECRET_PATTERN = re.compile(
    r"(?i)((?:access_token|id_token|passwd|password|pwd|"
    r"refresh_token|token)\s*[=:]\s*)([^\s&;,]+)"
)
_AUTH_HEADER_PATTERN = re.compile(r"(?im)^(authorization\s*:\s*)([^\r\n]+)")
_NAMED_SECRET_PATTERN = re.compile(
    r'(?is)("name"\s*:\s*"(?:access_token|id_token|passwd|password|pwd|'
    r'refresh_token|token)"[^{}]*?"value"\s*:\s*")([^"]*)(")'
)


def strip_tydom_prefix(raw_message: bytes) -> bytes:
    """Remove the remote-mediation prefix from a TYDOM frame."""
    return raw_message[1:] if raw_message.startswith(b"\x02") else raw_message


def _decode_chunked_body(body: bytes) -> bytes:
    """Decode an HTTP chunked body used by TYDOM responses and events."""
    decoded = bytearray()
    cursor = 0

    while True:
        line_end = body.find(b"\r\n", cursor)
        if line_end == -1:
            raise ValueError("Incomplete chunk-size line")

        size_text = body[cursor:line_end].split(b";", 1)[0].strip()
        try:
            size = int(size_text, 16)
        except ValueError as exception:
            raise ValueError(f"Invalid chunk size: {size_text!r}") from exception

        cursor = line_end + 2
        if size == 0:
            return bytes(decoded)

        chunk_end = cursor + size
        if chunk_end > len(body):
            raise ValueError("Incomplete chunk body")
        decoded.extend(body[cursor:chunk_end])
        cursor = chunk_end

        if body[cursor : cursor + 2] != b"\r\n":
            raise ValueError("Chunk is not terminated by CRLF")
        cursor += 2


def _parse_headers(header_lines: list[str]) -> dict[str, str]:
    """Return case-insensitive HTTP headers as lower-case keys."""
    headers: dict[str, str] = {}
    for line in header_lines:
        if not line or ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    return headers


def parse_tydom_message(raw_message: bytes) -> dict[str, Any] | None:
    """Parse a TYDOM HTTP response or gateway-originated HTTP request.

    TYDOM sends ordinary responses as ``HTTP/1.1 ...`` frames and publishes
    state changes as request-shaped frames such as ``PUT /devices/data``.
    Both forms may use HTTP chunked transfer encoding.
    """
    message = strip_tydom_prefix(raw_message)
    header_bytes, separator, body = message.partition(b"\r\n\r\n")
    if not separator:
        return None

    header_lines = header_bytes.decode("latin-1", errors="replace").split("\r\n")
    if not header_lines:
        return None

    start_line = header_lines[0].strip()
    headers = _parse_headers(header_lines[1:])
    method: str | None = None
    status: int | None = None
    uri = headers.get("uri-origin", "")

    if start_line.startswith("HTTP/"):
        parts = start_line.split(" ", 2)
        if len(parts) >= 2:
            try:
                status = int(parts[1])
            except ValueError:
                status = None
    else:
        parts = start_line.split(" ", 2)
        if len(parts) < 2 or parts[0].upper() not in _HTTP_METHODS:
            return None
        method = parts[0].upper()
        uri = parts[1]

    if "chunked" in headers.get("transfer-encoding", "").lower():
        body = _decode_chunked_body(body)
    elif "content-length" in headers:
        with suppress(ValueError):
            body = body[: int(headers["content-length"])]

    content_type = headers.get("content-type", "")
    parsed_data: Any = None
    if body:
        body_text = body.decode("utf-8", errors="replace")
        if "json" in content_type.lower() or body_text.lstrip().startswith(("{", "[")):
            try:
                parsed_data = json.loads(body_text)
            except json.JSONDecodeError:
                parsed_data = body_text
        else:
            parsed_data = body_text

    result: dict[str, Any] = {"uri": uri or "unknown"}
    if method is not None:
        result["method"] = method
    if status is not None:
        result["status"] = status
    if parsed_data is not None:
        result["data"] = parsed_data
    return result


def _normalise_secrets(secrets: Iterable[str | None]) -> tuple[str, ...]:
    """Return non-empty secrets longest first to avoid partial replacement."""
    return tuple(
        sorted({str(secret) for secret in secrets if secret}, key=len, reverse=True)
    )


def sanitise_text(text: str, secrets: Iterable[str | None] = ()) -> str:
    """Redact credentials and account identifiers from human-readable text."""
    sanitised = str(text)
    for secret in _normalise_secrets(secrets):
        sanitised = sanitised.replace(secret, "<redacted>")

    sanitised = _JSON_SECRET_PATTERN.sub(r"\1<redacted>\3", sanitised)
    sanitised = _NAMED_SECRET_PATTERN.sub(r"\1<redacted>\3", sanitised)
    sanitised = _ASSIGNMENT_SECRET_PATTERN.sub(r"\1<redacted>", sanitised)
    sanitised = _AUTH_HEADER_PATTERN.sub(r"\1<redacted>", sanitised)
    return _EMAIL_PATTERN.sub("<redacted-email>", sanitised)


def sanitise_value(value: Any, secrets: Iterable[str | None] = ()) -> Any:
    """Recursively redact sensitive values before writing parsed JSON."""
    if isinstance(value, dict):
        named_secret = str(value.get("name", "")).casefold() in _SENSITIVE_KEYS
        return {
            key: (
                "<redacted>"
                if str(key).casefold() in _SENSITIVE_KEYS
                or (named_secret and str(key).casefold() == "value")
                else sanitise_value(item, secrets)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitise_value(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitise_value(item, secrets) for item in value)
    if isinstance(value, str):
        return sanitise_text(value, secrets)
    return value


def redact_raw_message(raw_message: bytes, secrets: Iterable[str | None] = ()) -> bytes:
    """Return a sanitised raw frame without changing its byte length.

    Keeping the same length preserves HTTP content lengths and chunk sizes, so
    the saved raw frame remains suitable for replaying through the parser.
    """
    text = raw_message.decode("latin-1", errors="replace")

    def same_length_replacement(match: re.Match[str], group: int = 0) -> str:
        return "*" * len(match.group(group))

    for secret in _normalise_secrets(secrets):
        text = text.replace(secret, "*" * len(secret))

    def redact_json_secret(match: re.Match[str]) -> str:
        return f"{match.group(1)}{'*' * len(match.group(2))}{match.group(3)}"

    def redact_assignment(match: re.Match[str]) -> str:
        return f"{match.group(1)}{'*' * len(match.group(2))}"

    def redact_auth_header(match: re.Match[str]) -> str:
        return f"{match.group(1)}{'*' * len(match.group(2))}"

    text = _JSON_SECRET_PATTERN.sub(redact_json_secret, text)
    text = _NAMED_SECRET_PATTERN.sub(redact_json_secret, text)
    text = _ASSIGNMENT_SECRET_PATTERN.sub(redact_assignment, text)
    text = _AUTH_HEADER_PATTERN.sub(redact_auth_header, text)
    text = _EMAIL_PATTERN.sub(lambda match: same_length_replacement(match), text)
    return text.encode("latin-1", errors="replace")
