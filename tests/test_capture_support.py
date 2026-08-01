"""Tests for the dependency-free TYDOM capture helpers."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import ssl

support_path = Path(__file__).parents[1] / "tools" / "capture_support.py"
support_spec = importlib.util.spec_from_file_location("capture_support", support_path)
assert support_spec is not None and support_spec.loader is not None
support = importlib.util.module_from_spec(support_spec)
support_spec.loader.exec_module(support)

INITIAL_GET_REQUESTS = support.INITIAL_GET_REQUESTS
create_tydom_ssl_context = support.create_tydom_ssl_context
parse_tydom_message = support.parse_tydom_message
redact_raw_message = support.redact_raw_message
sanitise_value = support.sanitise_value


def _chunked(payload: bytes) -> bytes:
    """Encode one HTTP chunk followed by the terminating chunk."""
    return f"{len(payload):X}\r\n".encode() + payload + b"\r\n0\r\n\r\n"


def test_initial_capture_requests_cover_current_discovery_flow() -> None:
    """Capture startup must include current device and area resources."""
    assert INITIAL_GET_REQUESTS == (
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


def test_cloud_tls_context_verifies_the_server_certificate() -> None:
    """Remote mediation must retain the platform's normal TLS verification."""
    context = create_tydom_ssl_context(cloud_mode=True)

    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_local_tls_context_accepts_the_gateway_self_signed_certificate() -> None:
    """Only a local TYDOM gateway may bypass certificate verification."""
    context = create_tydom_ssl_context(cloud_mode=False)

    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE


def test_parse_chunked_http_response() -> None:
    """Ordinary TYDOM responses retain their origin and decoded JSON data."""
    payload = json.dumps([{"id": 12, "endpoints": []}]).encode()
    frame = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Transfer-Encoding: chunked\r\n"
        b"Uri-Origin: /devices/data\r\n\r\n" + _chunked(payload)
    )

    assert parse_tydom_message(frame) == {
        "uri": "/devices/data",
        "status": 200,
        "data": [{"id": 12, "endpoints": []}],
    }


def test_parse_gateway_put_event_with_remote_prefix() -> None:
    """Request-shaped state publications are captured with method and URI."""
    payload = b'[{"id":12,"endpoints":[{"id":12,"error":0}]}]'
    frame = (
        b"\x02PUT /devices/data HTTP/1.1\r\n"
        b"Content-Type: application/json\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n" + _chunked(payload)
    )

    assert parse_tydom_message(frame) == {
        "uri": "/devices/data",
        "method": "PUT",
        "data": [{"id": 12, "endpoints": [{"id": 12, "error": 0}]}],
    }


def test_parse_empty_acknowledgement() -> None:
    """Empty acknowledgements remain visible in parsed capture output."""
    frame = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nUri-Origin: /ping\r\n\r\n"

    assert parse_tydom_message(frame) == {"uri": "/ping", "status": 200}


def test_parsed_values_redact_nested_credentials_and_email() -> None:
    """Parsed JSON must not retain credentials or account identifiers."""
    value = {
        "gateway": {"password": "gateway-secret", "id": 42},
        "contact": "person@example.com",
        "message": "token=abc123",
        "hvac": {"authorization": "HEATING"},
        "command": {"name": "pwd", "value": "1234"},
    }

    assert sanitise_value(value, ("gateway-secret",)) == {
        "gateway": {"password": "<redacted>", "id": 42},
        "contact": "<redacted-email>",
        "message": "token=<redacted>",
        "hvac": {"authorization": "HEATING"},
        "command": {"name": "pwd", "value": "<redacted>"},
    }


def test_raw_redaction_preserves_frame_length_and_parseability() -> None:
    """Redacted raw frames keep valid content lengths and chunk framing."""
    payload = b'{"email":"person@example.com","password":"gateway-secret"}'
    frame = (
        b"PUT /configs/file HTTP/1.1\r\n"
        b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(payload)}\r\n\r\n".encode()
        + payload
    )

    redacted = redact_raw_message(frame, ("gateway-secret", "person@example.com"))

    assert len(redacted) == len(frame)
    assert b"gateway-secret" not in redacted
    assert b"person@example.com" not in redacted
    parsed = parse_tydom_message(redacted)
    assert parsed is not None
    assert parsed["uri"] == "/configs/file"
