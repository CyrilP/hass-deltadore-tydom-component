#!/usr/bin/env python3
"""
Script pour découvrir les endpoints disponibles dans l'API Tydom.

Ce script se connecte à l'API Tydom et teste différents endpoints
pour déterminer lesquels sont disponibles et quelles méthodes HTTP
sont supportées.

Usage:
    python discover_endpoints.py --host <IP_TYDOM> --mac <MAC> --password <PASSWORD>
    python discover_endpoints.py --host <IP_TYDOM> --mac <MAC> --password <PASSWORD> --test-all
"""

import argparse
import asyncio
import base64
import hashlib
import json
import re
import ssl
import sys
from typing import Any

import aiohttp
import async_timeout
from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType

# Liste des endpoints connus à tester
KNOWN_ENDPOINTS = [
    # Endpoints système
    "/ping",
    "/info",
    # Endpoints de configuration
    "/configs/file",
    "/configs/gateway/api_mode",
    "/configs/gateway/geoloc",
    "/configs/gateway/local_claim",
    # Endpoints devices
    "/devices/meta",
    "/devices/cmeta",
    "/devices/data",
    "/devices/{device_id}/endpoints/{endpoint_id}/data",
    # Endpoints areas
    "/areas/meta",
    "/areas/cmeta",
    "/areas/data",
    # Endpoints fichiers
    "/scenarios/file",
    "/groups/file",
    "/moments/file",
    # Endpoints actions
    "/refresh/all",
    # Endpoints historiques
    "/historical/events",
    # Endpoints firmware
    "/firmware/update",
]

# Méthodes HTTP à tester pour chaque endpoint
HTTP_METHODS = ["GET", "PUT", "POST", "DELETE", "PATCH"]


class EndpointDiscovery:
    """Classe pour découvrir les endpoints disponibles."""

    def __init__(self, host: str, mac: str, password: str):
        """Initialiser le discoverer."""
        self.host = host
        self.mac = mac
        self.password = password
        self.session: ClientSession | None = None
        self.ws: ClientWebSocketResponse | None = None
        self.results: dict[str, dict[str, Any]] = {}
        self.device_ids: list[str] = []
        self._cmd_prefix = b"" if host != "mediation.tydom.com" else b"\x02"

    def generate_random_key(self) -> str:
        """Générer une clé aléatoire pour WebSocket."""
        import secrets

        return base64.b64encode(secrets.token_bytes(16)).decode("ascii")

    def build_digest_headers(self, nonce: str) -> str:
        """Construire les en-têtes d'authentification digest.

        Cette méthode utilise HTTPDigestAuth de requests.auth comme dans le code original.
        """
        try:
            from requests.auth import HTTPDigestAuth

            # Utiliser HTTPDigestAuth comme dans le code original
            digest_auth = HTTPDigestAuth(self.mac, self.password)
            chal = {}
            chal["nonce"] = nonce
            # Le realm dépend du mode (distant ou local)
            chal["realm"] = (
                "ServiceMedia"
                if self.host == "mediation.tydom.com"
                else "protected area"
            )
            chal["qop"] = "auth"
            digest_auth._thread_local.chal = chal
            digest_auth._thread_local.last_nonce = nonce
            digest_auth._thread_local.nonce_count = 1
            digest = digest_auth.build_digest_header(
                "GET",
                f"https://{self.host}:443/mediation/client?mac={self.mac}&appli=1",
            )
            return digest
        except ImportError:
            # Fallback si requests n'est pas disponible
            print("⚠️  requests non disponible, utilisation du calcul manuel")
            ha1 = hashlib.md5(f"{self.mac}:tydom:{self.password}".encode()).hexdigest()
            ha2 = hashlib.md5(b"GET:/mediation/client").hexdigest()
            response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
            auth_header = (
                f'Digest username="{self.mac}", '
                f'realm="tydom", '
                f'nonce="{nonce}", '
                f'uri="/mediation/client", '
                f'response="{response}"'
            )
            return auth_header

    async def connect_websocket(self) -> bool:
        """Se connecter au WebSocket Tydom."""
        try:

            # Configuration SSL
            sslcontext = await asyncio.to_thread(ssl.create_default_context)
            sslcontext.options |= 0x4  # OP_LEGACY_SERVER_CONNECT
            sslcontext.check_hostname = False
            sslcontext.verify_mode = ssl.CERT_NONE

            # En-têtes pour la requête initiale
            http_headers = {
                "Connection": "Upgrade",
                "Upgrade": "websocket",
                "Host": f"{self.host}:443",
                "Accept": "*/*",
                "Sec-WebSocket-Key": self.generate_random_key(),
                "Sec-WebSocket-Version": "13",
            }

            # Créer une session persistante
            self.session = aiohttp.ClientSession()

            # Faire une requête GET pour obtenir le challenge digest
            try:
                async with async_timeout.timeout(10):
                    response = await self.session.request(
                        method="GET",
                        url=f"https://{self.host}:443/mediation/client?mac={self.mac}&appli=1",
                        headers=http_headers,
                        json=None,
                        ssl=sslcontext,
                    )

                    www_authenticate = response.headers.get("WWW-Authenticate")
                    if www_authenticate is None:
                        response.close()
                        print("✗ Impossible de trouver l'en-tête WWW-Authenticate")
                        return False

                    # Extraire le nonce
                    re_matcher = re.match(
                        r'.*nonce="([a-zA-Z0-9+=]+)".*',
                        www_authenticate,
                    )
                    response.close()

                    if not re_matcher:
                        print("✗ Impossible de trouver le nonce dans WWW-Authenticate")
                        return False

                    # Construire l'en-tête Authorization avec digest
                    http_headers = {}
                    http_headers["Authorization"] = self.build_digest_headers(
                        re_matcher.group(1)
                    )

                    # Se connecter au WebSocket
                    ws_url = (
                        f"wss://{self.host}:443/mediation/client?mac={self.mac}&appli=1"
                    )

                    if self.host == "mediation.tydom.com":
                        # Mode distant: utiliser method="GET" comme dans le code original
                        from aiohttp import ClientWSTimeout

                        connection = await self.session.ws_connect(
                            method="GET",
                            url=ws_url,
                            headers=http_headers,
                            autoping=True,
                            heartbeat=2.0,
                            timeout=ClientWSTimeout(ws_close=10, ws_receive=30),
                            autoclose=True,
                            ssl=sslcontext,
                        )
                    else:
                        # Mode local
                        connection = await self.session.ws_connect(
                            url=ws_url,
                            headers=http_headers,
                            ssl=sslcontext,
                        )

                    self.ws = connection
                    print(f"✓ Connexion WebSocket établie à {self.host}")
                    return True
            except Exception:
                if self.session:
                    await self.session.close()
                raise
        except Exception as e:
            print(f"✗ Erreur de connexion WebSocket: {e}")
            import traceback

            traceback.print_exc()
            return False

    async def send_message(self, method: str, endpoint: str) -> dict[str, Any]:
        """Envoyer un message via WebSocket et attendre la réponse."""
        if not self.ws:
            return {"status": "error", "error": "WebSocket non connecté"}

        # Construire la requête HTTP (format utilisé par Tydom)
        transaction_id = int(asyncio.get_event_loop().time() * 1000)
        request = (
            f"{method} {endpoint} HTTP/1.1\r\n"
            f"Content-Length: 0\r\n"
            f"Content-Type: application/json; charset=UTF-8\r\n"
            f"Transac-Id: {transaction_id}\r\n\r\n"
        )

        try:
            # Envoyer la requête (sans préfixe pour mode local, avec \x02 pour mode distant)
            await self.ws.send_bytes(self._cmd_prefix + request.encode("ascii"))

            # Attendre la réponse (timeout de 5 secondes)
            try:
                msg = await asyncio.wait_for(self.ws.receive(), timeout=5.0)

                if msg.type == WSMsgType.TEXT:
                    return {
                        "status": "success",
                        "response": msg.data,
                        "transaction_id": transaction_id,
                    }
                elif msg.type == WSMsgType.BINARY:
                    # Décoder les données binaires
                    try:
                        response_text = msg.data.decode("utf-8", errors="ignore")
                        return {
                            "status": "success",
                            "response": response_text,
                            "transaction_id": transaction_id,
                            "format": "binary",
                        }
                    except Exception:
                        return {
                            "status": "success",
                            "response": f"<binary data: {len(msg.data)} bytes>",
                            "transaction_id": transaction_id,
                            "format": "binary",
                        }
                elif msg.type == WSMsgType.ERROR:
                    return {
                        "status": "error",
                        "error": str(msg.data) if msg.data else "Erreur WebSocket",
                    }
                elif msg.type == WSMsgType.CLOSE:
                    return {
                        "status": "error",
                        "error": "Connexion fermée par le serveur",
                    }
                else:
                    return {
                        "status": "unknown",
                        "message_type": msg.type,
                        "data": str(msg.data) if hasattr(msg, "data") else None,
                    }
            except TimeoutError:
                return {
                    "status": "timeout",
                    "error": "Aucune réponse reçue dans les 5 secondes",
                }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def test_endpoint(self, endpoint: str, method: str = "GET") -> dict[str, Any]:
        """Tester un endpoint avec une méthode HTTP."""
        # Remplacer les placeholders
        if "{device_id}" in endpoint or "{endpoint_id}" in endpoint:
            if not self.device_ids:
                # Essayer de récupérer la liste des devices d'abord
                await self.get_device_list()

            if self.device_ids:
                # Utiliser le premier device_id disponible
                device_id = self.device_ids[0]
                endpoint = endpoint.replace("{device_id}", device_id).replace(
                    "{endpoint_id}", device_id
                )
            else:
                return {"status": "skipped", "reason": "Aucun device_id disponible"}

        result = await self.send_message(method, endpoint)
        return result

    async def get_device_list(self):
        """Récupérer la liste des devices pour remplacer les placeholders."""
        if not self.device_ids:
            # Essayer de récupérer /devices/data
            result = await self.send_message("GET", "/devices/data")
            if result.get("status") == "success":
                try:
                    # Parser la réponse pour extraire les device_ids
                    # Note: Le format exact dépend de la réponse de l'API
                    response = result.get("response", "")
                    # Ici, on devrait parser la réponse JSON si possible
                    # Pour l'instant, on laisse vide et on utilisera des IDs par défaut
                    pass
                except Exception:
                    pass

    async def discover_all(self, test_all_methods: bool = False):
        """Découvrir tous les endpoints."""
        print("\n" + "=" * 70)
        print("DÉCOUVERTE DES ENDPOINTS TYDOM")
        print("=" * 70)

        if not await self.connect_websocket():
            print("✗ Impossible de se connecter. Arrêt.")
            return

        print(f"\n📋 Test de {len(KNOWN_ENDPOINTS)} endpoints connus...")
        if test_all_methods:
            print(f"   (Test de toutes les méthodes HTTP: {', '.join(HTTP_METHODS)})")
        else:
            print("   (Test de la méthode GET uniquement)")

        print("\n" + "-" * 70)

        for endpoint in KNOWN_ENDPOINTS:
            methods_to_test = HTTP_METHODS if test_all_methods else ["GET"]

            for method in methods_to_test:
                print(f"\n🔍 Test: {method} {endpoint}")
                result = await self.test_endpoint(endpoint, method)

                # Stocker le résultat
                if endpoint not in self.results:
                    self.results[endpoint] = {}
                self.results[endpoint][method] = result

                # Afficher le résultat
                status = result.get("status", "unknown")
                if status == "success":
                    response_preview = result.get("response", "")[:100]
                    print(f"   ✓ Succès - Réponse: {response_preview}...")
                elif status == "timeout":
                    print("   ⏱  Timeout - Aucune réponse")
                elif status == "error":
                    error = result.get("error", "Erreur inconnue")
                    print(f"   ✗ Erreur: {error}")
                elif status == "skipped":
                    reason = result.get("reason", "Raison inconnue")
                    print(f"   ⊘ Ignoré: {reason}")
                else:
                    print(f"   ? Statut inconnu: {status}")

                # Petite pause pour éviter de surcharger
                await asyncio.sleep(0.5)

        # Fermer la connexion
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()

        # Afficher le résumé
        self.print_summary()

    def print_summary(self):
        """Afficher un résumé des résultats."""
        print("\n" + "=" * 70)
        print("RÉSUMÉ DES RÉSULTATS")
        print("=" * 70)

        available_endpoints = []
        unavailable_endpoints = []

        for endpoint, methods in self.results.items():
            has_success = any(
                result.get("status") == "success" for result in methods.values()
            )

            if has_success:
                available_methods = [
                    method
                    for method, result in methods.items()
                    if result.get("status") == "success"
                ]
                available_endpoints.append((endpoint, available_methods))
            else:
                unavailable_endpoints.append(endpoint)

        print(f"\n✓ Endpoints disponibles ({len(available_endpoints)}):")
        for endpoint, methods in available_endpoints:
            print(f"   {endpoint}")
            print(f"      Méthodes supportées: {', '.join(methods)}")

        if unavailable_endpoints:
            print(f"\n✗ Endpoints non disponibles ({len(unavailable_endpoints)}):")
            for endpoint in unavailable_endpoints:
                print(f"   {endpoint}")

        # Sauvegarder les résultats dans un fichier JSON
        output_file = "endpoints_discovery_results.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Résultats sauvegardés dans: {output_file}")


async def get_gateway_password(email: str, password: str, mac: str) -> str | None:
    """Récupérer le mot de passe du gateway depuis l'API Delta Dore."""
    try:
        from urllib3 import encode_multipart_formdata

        DELTADORE_AUTH_URL = "https://deltadoreadb2ciot.b2clogin.com/deltadoreadb2ciot.onmicrosoft.com/v2.0/.well-known/openid-configuration?p=B2C_1_AccountProviderROPC_SignIn"
        DELTADORE_AUTH_GRANT_TYPE = "password"
        DELTADORE_AUTH_CLIENTID = "8782839f-3264-472a-ab87-4d4e23524da4"
        DELTADORE_AUTH_SCOPE = "openid profile offline_access https://deltadoreadb2ciot.onmicrosoft.com/iotapi/video_config https://deltadoreadb2ciot.onmicrosoft.com/iotapi/video_allowed https://deltadoreadb2ciot.onmicrosoft.com/iotapi/sites_management_allowed https://deltadoreadb2ciot.onmicrosoft.com/iotapi/sites_management_gateway_credentials https://deltadoreadb2ciot.onmicrosoft.com/iotapi/sites_management_camera_credentials https://deltadoreadb2ciot.onmicrosoft.com/iotapi/comptage_europe_collect_reader https://deltadoreadb2ciot.onmicrosoft.com/iotapi/comptage_europe_site_config_contributor https://deltadoreadb2ciot.onmicrosoft.com/iotapi/pilotage_allowed https://deltadoreadb2ciot.onmicrosoft.com/iotapi/consent_mgt_contributor https://deltadoreadb2ciot.onmicrosoft.com/iotapi/b2caccountprovider_manage_account https://deltadoreadb2ciot.onmicrosoft.com/iotapi/b2caccountprovider_allow_view_account https://deltadoreadb2ciot.onmicrosoft.com/iotapi/tydom_backend_allowed https://deltadoreadb2ciot.onmicrosoft.com/iotapi/websocket_remote_access https://deltadoreadb2ciot.onmicrosoft.com/iotapi/orkestrator_device https://deltadoreadb2ciot.onmicrosoft.com/iotapi/orkestrator_view https://deltadoreadb2ciot.onmicrosoft.com/iotapi/orkestrator_space https://deltadoreadb2ciot.onmicrosoft.com/iotapi/orkestrator_connector https://deltadoreadb2ciot.onmicrosoft.com/iotapi/orkestrator_endpoint https://deltadoreadb2ciot.onmicrosoft.com/iotapi/rule_management_allowed https://deltadoreadb2ciot.onmicrosoft.com/iotapi/collect_read_datas"
        DELTADORE_API_SITES = (
            "https://prod.iotdeltadore.com/sitesmanagement/api/v1/sites?gateway_mac="
        )

        print("🔐 Récupération du mot de passe du gateway depuis l'API Delta Dore...")

        async with aiohttp.ClientSession() as session:
            # Étape 1: Obtenir l'URL du token endpoint
            async with async_timeout.timeout(10):
                response = await session.request(method="GET", url=DELTADORE_AUTH_URL)
                json_response = await response.json()
                response.close()
                signin_url = json_response["token_endpoint"]
                print(f"   ✓ Token endpoint: {signin_url[:50]}...")

            # Étape 2: Obtenir le token d'accès
            body, ct_header = encode_multipart_formdata(
                {
                    "username": email,
                    "password": password,
                    "grant_type": DELTADORE_AUTH_GRANT_TYPE,
                    "client_id": DELTADORE_AUTH_CLIENTID,
                    "scope": DELTADORE_AUTH_SCOPE,
                }
            )

            async with async_timeout.timeout(10):
                response = await session.post(
                    url=signin_url,
                    headers={"Content-Type": ct_header},
                    data=body,
                )
                json_response = await response.json()
                response.close()

                if "access_token" not in json_response:
                    print(
                        f"   ✗ Erreur d'authentification: {json_response.get('error_description', 'Erreur inconnue')}"
                    )
                    return None

                access_token = json_response["access_token"]
                print("   ✓ Token d'accès obtenu")

            # Étape 3: Récupérer le mot de passe du gateway
            async with async_timeout.timeout(10):
                response = await session.request(
                    method="GET",
                    url=DELTADORE_API_SITES + mac,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                json_response = await response.json()
                response.close()

                if "sites" in json_response and len(json_response["sites"]) > 0:
                    for site in json_response["sites"]:
                        if "gateway" in site and site["gateway"]["mac"] == mac:
                            gateway_password = site["gateway"]["password"]
                            print("   ✓ Mot de passe du gateway récupéré")
                            return gateway_password

                print(f"   ✗ Gateway non trouvé pour la MAC {mac}")
                return None
    except Exception as e:
        print(f"   ✗ Erreur lors de la récupération du mot de passe: {e}")
        return None


async def main():
    """Fonction principale."""
    parser = argparse.ArgumentParser(
        description="Découvrir les endpoints disponibles dans l'API Tydom"
    )
    parser.add_argument(
        "--host",
        required=True,
        help="Adresse IP ou hostname du gateway Tydom (ou 'mediation.tydom.com' pour le mode distant)",
    )
    parser.add_argument("--mac", required=True, help="Adresse MAC du gateway Tydom")
    parser.add_argument(
        "--password",
        help="Mot de passe du gateway Tydom (optionnel si --email est fourni)",
    )
    parser.add_argument(
        "--email",
        help="Email du compte Delta Dore (pour récupérer automatiquement le mot de passe du gateway)",
    )
    parser.add_argument(
        "--delta-password",
        help="Mot de passe du compte Delta Dore (requis si --email est fourni)",
    )
    parser.add_argument(
        "--test-all",
        action="store_true",
        help="Tester toutes les méthodes HTTP (GET, PUT, POST, DELETE, PATCH) pour chaque endpoint",
    )

    args = parser.parse_args()

    # Déterminer le mot de passe du gateway
    gateway_password = args.password

    if not gateway_password:
        if args.email and args.delta_password:
            gateway_password = await get_gateway_password(
                args.email, args.delta_password, args.mac
            )
            if not gateway_password:
                print("\n✗ Impossible de récupérer le mot de passe du gateway. Arrêt.")
                sys.exit(1)
        else:
            print(
                "\n✗ Erreur: --password est requis, ou --email et --delta-password doivent être fournis"
            )
            parser.print_help()
            sys.exit(1)

    discoverer = EndpointDiscovery(args.host, args.mac, gateway_password)
    await discoverer.discover_all(test_all_methods=args.test_all)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interruption par l'utilisateur")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ Erreur fatale: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
