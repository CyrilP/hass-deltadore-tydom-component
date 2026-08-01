#!/usr/bin/env python3
# ruff: noqa: T201
"""
Script pour capturer toutes les données brutes de Delta Dore Tydom.

Ce script se connecte à la passerelle Tydom et capture tous les messages
WebSocket entrants, les organise et les sauvegarde dans des fichiers texte
pour analyse.

Usage:
    python3 capture_tydom_data.py --host <IP> --mac <MAC> [--email <EMAIL> --delta-password <PASSWORD>] [options]
"""

import argparse
import asyncio
import base64
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
import time

try:
    from .capture_support import (
        INITIAL_GET_REQUESTS,
        create_tydom_ssl_context,
        parse_tydom_message,
        redact_raw_message,
        sanitise_text,
        sanitise_value,
        strip_tydom_prefix,
    )
except ImportError:  # Direct execution: python tools/capture_tydom_data.py
    from capture_support import (  # type: ignore[no-redef]
        INITIAL_GET_REQUESTS,
        create_tydom_ssl_context,
        parse_tydom_message,
        redact_raw_message,
        sanitise_text,
        sanitise_value,
        strip_tydom_prefix,
    )

try:
    import aiohttp
    from aiohttp import WSMsgType
    from requests.auth import HTTPDigestAuth
    import async_timeout
except ImportError:
    print("❌ Erreur: aiohttp et requests sont requis")
    print("   Installez-les avec: pip install aiohttp requests")
    sys.exit(1)

# Constantes
DELTADORE_AUTH_URL = "https://deltadoreadb2ciot.b2clogin.com/deltadoreadb2ciot.onmicrosoft.com/v2.0/.well-known/openid-configuration?p=B2C_1_AccountProviderROPC_SignIn"


def sanitize_error_message(
    message: str, password: str | None = None, email: str | None = None
) -> str:
    """Masquer les informations sensibles dans les messages d'erreur."""
    return sanitise_text(message, (password, email))


DELTADORE_AUTH_GRANT_TYPE = "password"
DELTADORE_AUTH_CLIENTID = "8782839f-3264-472a-ab87-4d4e23524da4"
DELTADORE_AUTH_SCOPE = "openid profile offline_access https://deltadoreadb2ciot.onmicrosoft.com/iotapi/video_config https://deltadoreadb2ciot.onmicrosoft.com/iotapi/video_allowed https://deltadoreadb2ciot.onmicrosoft.com/iotapi/sites_management_allowed https://deltadoreadb2ciot.onmicrosoft.com/iotapi/sites_management_gateway_credentials https://deltadoreadb2ciot.onmicrosoft.com/iotapi/sites_management_camera_credentials https://deltadoreadb2ciot.onmicrosoft.com/iotapi/comptage_europe_collect_reader https://deltadoreadb2ciot.onmicrosoft.com/iotapi/comptage_europe_site_config_contributor https://deltadoreadb2ciot.onmicrosoft.com/iotapi/pilotage_allowed https://deltadoreadb2ciot.onmicrosoft.com/iotapi/consent_mgt_contributor https://deltadoreadb2ciot.onmicrosoft.com/iotapi/b2caccountprovider_manage_account https://deltadoreadb2ciot.onmicrosoft.com/iotapi/b2caccountprovider_allow_view_account https://deltadoreadb2ciot.onmicrosoft.com/iotapi/tydom_backend_allowed https://deltadoreadb2ciot.onmicrosoft.com/iotapi/websocket_remote_access https://deltadoreadb2ciot.onmicrosoft.com/iotapi/orkestrator_device https://deltadoreadb2ciot.onmicrosoft.com/iotapi/orkestrator_view https://deltadoreadb2ciot.onmicrosoft.com/iotapi/orkestrator_space https://deltadoreadb2ciot.onmicrosoft.com/iotapi/orkestrator_connector https://deltadoreadb2ciot.onmicrosoft.com/iotapi/orkestrator_endpoint https://deltadoreadb2ciot.onmicrosoft.com/iotapi/rule_management_allowed https://deltadoreadb2ciot.onmicrosoft.com/iotapi/collect_read_datas"
DELTADORE_API_SITES = (
    "https://prod.iotdeltadore.com/sitesmanagement/api/v1/sites?gateway_mac="
)


async def get_tydom_password(session, email: str, password: str, mac: str) -> str:
    """Récupérer le mot de passe Tydom."""
    from urllib3 import encode_multipart_formdata

    async with async_timeout.timeout(10):
        response = await session.request(method="GET", url=DELTADORE_AUTH_URL)
        json_response = await response.json()
        response.close()
        signin_url = json_response["token_endpoint"]

    body, ct_header = encode_multipart_formdata(
        {
            "username": email,
            "password": password,
            "grant_type": DELTADORE_AUTH_GRANT_TYPE,
            "client_id": DELTADORE_AUTH_CLIENTID,
            "scope": DELTADORE_AUTH_SCOPE,
        }
    )

    response = await session.post(
        url=signin_url, headers={"Content-Type": ct_header}, data=body
    )
    json_response = await response.json()
    response.close()
    access_token = json_response["access_token"]

    response = await session.request(
        method="GET",
        url=DELTADORE_API_SITES + mac,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    json_response = await response.json()
    response.close()

    if "sites" in json_response and len(json_response["sites"]) > 0:
        return json_response["sites"][0]["gateway"]["password"]
    raise ValueError("Mot de passe Tydom non trouvé")


def build_digest_header(
    mac: str, password: str, nonce: str, host: str, cloud_mode: bool
) -> str:
    """Construire l'en-tête d'authentification digest."""
    digest_auth = HTTPDigestAuth(mac, password)
    chal = {}
    chal["nonce"] = nonce
    chal["realm"] = "ServiceMedia" if cloud_mode else "protected area"
    chal["qop"] = "auth"
    digest_auth._thread_local.chal = chal
    digest_auth._thread_local.last_nonce = nonce
    digest_auth._thread_local.nonce_count = 1
    result = digest_auth.build_digest_header(
        "GET",
        f"https://{host}:443/mediation/client?mac={mac}&appli=1",
    )
    # build_digest_header retourne toujours une string, mais le type checker ne le sait pas
    assert result is not None, "build_digest_header ne devrait jamais retourner None"
    return result


async def capture(
    host: str,
    mac: str,
    password: str | None,
    email: str | None,
    delta_password: str | None,
    duration: int,
    output_dir: Path,
):
    """Capture les messages WebSocket."""
    session = aiohttp.ClientSession()

    try:
        # Récupérer le mot de passe si nécessaire
        if not password:
            if not email or not delta_password:
                raise ValueError("Email et mot de passe Delta Dore requis")
            print("🔐 Récupération du mot de passe Tydom...")
            password = await get_tydom_password(session, email, delta_password, mac)
            print("✅ Mot de passe récupéré")

        # À ce point, password ne peut pas être None
        if password is None:
            raise ValueError("Mot de passe Tydom non disponible")

        # Créer le répertoire de sortie
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = output_dir / f"capture_{timestamp}"
        session_dir.mkdir(parents=True, exist_ok=True)

        raw_file = session_dir / "raw_messages.txt"
        parsed_file = session_dir / "parsed_messages.json"

        print(f"📁 Sauvegarde dans: {session_dir}")

        # Connexion WebSocket
        cloud_mode = "mediation" in host.lower()
        sslcontext = create_tydom_ssl_context(cloud_mode)

        # Étape 1: Obtenir le challenge
        sec_key = base64.b64encode(os.urandom(16)).decode()

        http_headers = {
            "Connection": "Upgrade",
            "Upgrade": "websocket",
            "Host": f"{host}:443",
            "Accept": "*/*",
            "Sec-WebSocket-Key": sec_key,
            "Sec-WebSocket-Version": "13",
        }

        async with async_timeout.timeout(10):
            response = await session.request(
                method="GET",
                url=f"https://{host}:443/mediation/client?mac={mac}&appli=1",
                headers=http_headers,
                ssl=sslcontext,
            )

            www_authenticate = response.headers.get("WWW-Authenticate")
            if not www_authenticate:
                raise ValueError("WWW-Authenticate header manquant")

            re_matcher = re.match(r'.*nonce="([a-zA-Z0-9+=]+)".*', www_authenticate)
            response.close()

            if not re_matcher:
                raise ValueError("Nonce non trouvé")

            nonce = re_matcher.group(1)

        # Étape 2: Connexion WebSocket avec auth
        # À ce point, password ne peut pas être None
        if password is None:
            raise ValueError("Mot de passe requis pour la connexion")
        http_headers = {
            "Authorization": build_digest_header(mac, password, nonce, host, cloud_mode)
        }

        print(f"🔌 Connexion à wss://{host}:443/mediation/client?mac={mac}&appli=1...")

        ws = await session.ws_connect(
            f"wss://{host}:443/mediation/client?mac={mac}&appli=1",
            headers=http_headers,
            ssl=sslcontext,
            autoping=True,
            heartbeat=2.0,
        )

        print("✅ Connecté!")

        # Envoyer le flux de découverte actuel de l'intégration. Ces requêtes
        # sont toutes en lecture seule afin que la capture ne modifie jamais
        # l'installation.
        prefix = b"\x02" if cloud_mode else b""

        for uri in INITIAL_GET_REQUESTS:
            trans_id = str(time.time_ns())
            msg = (
                f"GET {uri} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "Content-Type: application/json; charset=UTF-8\r\n"
                f"Transac-Id: {trans_id}\r\n"
                "Content-Length: 0\r\n\r\n"
            )
            await ws.send_bytes(prefix + msg.encode("ascii"))
            await asyncio.sleep(0.3)

        print(f"👂 Écoute des messages ({duration}s)...\n")

        # Écouter les messages
        start_time = asyncio.get_event_loop().time()
        message_count = 0
        parsed_messages: list[dict] = []
        secrets = (password, delta_password, email)

        try:
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= duration:
                    break

                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=1.0)
                except TimeoutError:
                    continue

                if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING):
                    print("🔌 Connexion fermée")
                    break
                elif msg.type == WSMsgType.ERROR:
                    error_msg = sanitize_error_message(str(msg.data), password, email)
                    print(f"❌ Erreur: {error_msg}")
                    break
                elif msg.type in (WSMsgType.PING, WSMsgType.PONG):
                    continue
                elif msg.type in (WSMsgType.TEXT, WSMsgType.BINARY):
                    message_count += 1
                    data = (
                        msg.data if isinstance(msg.data, bytes) else msg.data.encode()
                    )
                    data = strip_tydom_prefix(data)

                    # Conserver une trame brute rejouable, mais jamais les
                    # identifiants transmis au script ni les champs secrets.
                    timestamp = datetime.now().isoformat()
                    safe_raw_data = redact_raw_message(data, secrets)
                    with raw_file.open("ab") as capture_file:
                        capture_file.write(
                            f"\n{'=' * 80}\n[{timestamp}] Message #{message_count}\n{'=' * 80}\n".encode()
                        )
                        capture_file.write(safe_raw_data)
                        capture_file.write(b"\n")

                    # Les réponses HTTP classiques et les événements PUT/POST
                    # émis par la passerelle suivent deux formes différentes.
                    try:
                        parsed = parse_tydom_message(data)
                        if parsed is None:
                            print(f"⚠️  #{message_count}: trame non HTTP conservée")
                            continue

                        safe_parsed = sanitise_value(parsed, secrets)
                        parsed_messages.append({"timestamp": timestamp, **safe_parsed})
                        method = safe_parsed.get("method")
                        status = safe_parsed.get("status")
                        detail = method or status or ""
                        print(
                            f"📥 #{message_count}: {safe_parsed['uri']}"
                            f" {detail}".rstrip()
                        )
                    except Exception as e:
                        error_msg = sanitize_error_message(str(e), password, email)
                        print(
                            f"⚠️  Erreur lors du parsing du message #{message_count}: {error_msg}"
                        )

        except KeyboardInterrupt:
            print("\n⏹️  Arrêt demandé")
        finally:
            # Sauvegarder les messages parsés
            with parsed_file.open("w", encoding="utf-8") as capture_file:
                json.dump(
                    parsed_messages,
                    capture_file,
                    indent=2,
                    ensure_ascii=False,
                )

            await ws.close()
            print(f"\n✅ Capture terminée: {message_count} messages")
            print(f"📁 Fichiers: {raw_file}, {parsed_file}")

    finally:
        await session.close()


async def main():
    """Run the command-line capture client."""
    parser = argparse.ArgumentParser(description="Capture simple des messages Tydom")
    parser.add_argument("--host", required=True)
    parser.add_argument("--mac", required=True)
    parser.add_argument("--password")
    parser.add_argument("--email")
    parser.add_argument("--delta-password")
    parser.add_argument("--duration", type=int, default=300)
    parser.add_argument("--output", default="tools/captures")

    args = parser.parse_args()

    if not args.password and (not args.email or not args.delta_password):
        parser.error("--password ou --email+--delta-password requis")

    await capture(
        args.host,
        args.mac,
        args.password,
        args.email,
        args.delta_password,
        args.duration,
        Path(args.output),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️  Interrompu")
        sys.exit(0)
