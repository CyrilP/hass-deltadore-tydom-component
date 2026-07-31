#!/usr/bin/env python3
# ruff: noqa: T201
"""Validate and summarise a raw capture produced by the TYDOM capture tool."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys

try:
    from .capture_support import parse_tydom_message
except ImportError:  # Direct execution: python tools/test_capture_parsing.py
    from capture_support import parse_tydom_message


_SEPARATOR = b"=" * 80
_HTTP_STARTS = (
    b"HTTP/",
    b"DELETE ",
    b"GET ",
    b"PATCH ",
    b"POST ",
    b"PUT ",
)


def _captured_frames(content: bytes):
    """Yield protocol frames from the human-readable raw capture container."""
    for block in content.split(_SEPARATOR):
        starts = [block.find(marker) for marker in _HTTP_STARTS]
        starts = [position for position in starts if position >= 0]
        if not starts:
            continue
        yield block[min(starts) :].strip(b"\r\n")


def validate_captured_messages(capture_dir: Path) -> bool:
    """Parse every saved frame and report the resources represented."""
    raw_file = capture_dir / "raw_messages.txt"
    if not raw_file.exists():
        print(f"❌ Fichier non trouvé: {raw_file}")
        return False

    print(f"📖 Lecture de {raw_file}...")
    frames = list(_captured_frames(raw_file.read_bytes()))
    parsed_messages = []
    error_count = 0

    for index, frame in enumerate(frames, 1):
        try:
            parsed = parse_tydom_message(frame)
        except (ValueError, TypeError) as exception:
            print(f"❌ Message #{index}: {exception}")
            error_count += 1
            continue

        if parsed is None:
            print(f"⚠️  Message #{index}: format non reconnu")
            error_count += 1
            continue

        parsed_messages.append(parsed)
        detail = parsed.get("method") or parsed.get("status") or ""
        print(f"✅ Message #{index}: {parsed['uri']} {detail}".rstrip())

    counts = Counter(message["uri"] for message in parsed_messages)
    print("\n📊 Résultats:")
    print(f"   ✅ Succès: {len(parsed_messages)}")
    print(f"   ❌ Erreurs: {error_count}")
    print("\n📋 Ressources capturées:")
    for uri, count in sorted(counts.items()):
        print(f"   - {uri}: {count}")

    required = ("/info", "/devices/meta")
    print("\n🎯 Messages critiques:")
    for uri in required:
        print(f"   - {uri}: {'✅ Présent' if counts[uri] else '❌ Absent'}")

    return error_count == 0 and all(counts[uri] for uri in required)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 tools/test_capture_parsing.py <capture_dir>")
        sys.exit(1)

    directory = Path(sys.argv[1])
    if not directory.exists():
        print(f"❌ Répertoire non trouvé: {directory}")
        sys.exit(1)

    sys.exit(0 if validate_captured_messages(directory) else 1)
