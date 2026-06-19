#!/usr/bin/env python3
"""
Script de test pour valider le parsing des messages capturés.

Ce script teste que le parser amélioré peut correctement décoder
les messages HTTP chunked depuis les fichiers de capture.
"""

import json
import sys
from pathlib import Path
from http.client import HTTPResponse as CoreHTTPResponse
from io import BytesIO


class BytesIOSocket:
    """Wrapper pour BytesIO pour simuler un socket."""

    def __init__(self, content):
        self.handle = BytesIO(content)

    def makefile(self, mode):
        return self.handle


def parse_http_response(raw_message: bytes) -> tuple[dict, bytes]:
    """
    Parse une réponse HTTP et retourne les headers et le body décodé.
    Gère automatiquement le format chunked.
    """
    sock = BytesIOSocket(raw_message)
    response = CoreHTTPResponse(sock)  # type: ignore[arg-type]
    response.begin()

    headers = {}
    for key, value in response.headers.items():
        headers[key.lower()] = value

    body = response.read()

    return headers, body


def test_parse_captured_messages(capture_dir: Path):
    """Tester le parsing des messages capturés."""
    raw_file = capture_dir / "raw_messages.txt"

    if not raw_file.exists():
        print(f"❌ Fichier non trouvé: {raw_file}")
        return False

    print(f"📖 Lecture de {raw_file}...")

    with open(raw_file, "rb") as f:
        content = f.read()

    # Extraire les messages individuels (séparés par =====)
    separator = b"=" * 80
    parts = content.split(separator)

    success_count = 0
    error_count = 0
    parsed_messages = []

    for i, message_block in enumerate(parts[1:], 1):  # Skip first empty split
        if not message_block.strip():
            continue

        # Chercher le début du message HTTP
        http_start = message_block.find(b"HTTP/")
        if http_start == -1:
            continue

        # Extraire le message HTTP complet
        http_message = message_block[http_start:]

        # Trouver la fin du message (ligne vide suivie de séparateur ou fin de fichier)
        # Pour simplifier, on prend jusqu'à la prochaine séparation ou 64KB
        end_marker = http_message.find(separator)
        if end_marker != -1:
            http_message = http_message[:end_marker]
        elif len(http_message) > 65536:
            http_message = http_message[:65536]

        try:
            headers, body = parse_http_response(http_message)
            uri = headers.get("uri-origin", "")
            content_type = headers.get("content-type", "")

            # Essayer de parser le body comme JSON
            if body and content_type and "json" in content_type.lower():
                try:
                    body_text = body.decode("utf-8", errors="replace")
                    body_json = json.loads(body_text)
                    parsed_messages.append({"uri": uri, "data": body_json})
                    print(f"✅ Message #{i}: {uri} - Parsé avec succès")
                    success_count += 1
                except json.JSONDecodeError as e:
                    print(f"⚠️  Message #{i}: {uri} - Erreur JSON: {e}")
                    error_count += 1
                except Exception as e:
                    print(f"❌ Message #{i}: {uri} - Erreur: {e}")
                    error_count += 1
            elif body:
                print(f"ℹ️  Message #{i}: {uri} - Body non-JSON ({len(body)} bytes)")
                success_count += 1
            else:
                print(f"ℹ️  Message #{i}: {uri} - Pas de body")
                success_count += 1

        except Exception as e:
            print(f"❌ Message #{i}: Erreur de parsing HTTP: {e}")
            error_count += 1

    print("\n📊 Résultats:")
    print(f"   ✅ Succès: {success_count}")
    print(f"   ❌ Erreurs: {error_count}")
    print(f"   📝 Total parsé: {len(parsed_messages)}")

    # Vérifier les types de messages parsés
    uris = [msg["uri"] for msg in parsed_messages]
    print("\n📋 Types de messages parsés:")
    for uri in set(uris):
        count = uris.count(uri)
        print(f"   - {uri}: {count}")

    # Vérifier spécifiquement /info et /devices/meta
    info_parsed = any(msg["uri"] == "/info" for msg in parsed_messages)
    meta_parsed = any(msg["uri"] == "/devices/meta" for msg in parsed_messages)

    print("\n🎯 Messages critiques:")
    print(f"   - /info: {'✅ Parsé' if info_parsed else '❌ Non parsé'}")
    print(f"   - /devices/meta: {'✅ Parsé' if meta_parsed else '❌ Non parsé'}")

    return error_count == 0 and info_parsed and meta_parsed


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 test_capture_parsing.py <capture_dir>")
        print(
            "Exemple: python3 test_capture_parsing.py tools/captures/capture_20251205_233826"
        )
        sys.exit(1)

    capture_dir = Path(sys.argv[1])

    if not capture_dir.exists():
        print(f"❌ Répertoire non trouvé: {capture_dir}")
        sys.exit(1)

    success = test_parse_captured_messages(capture_dir)

    if success:
        print("\n✅ Tous les tests sont passés!")
        sys.exit(0)
    else:
        print("\n❌ Certains tests ont échoué")
        sys.exit(1)
