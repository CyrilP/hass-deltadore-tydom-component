# Security Fixes — 2026-06-03

> **Historique** :
> - 2026-06-03 : première ré-application après le merge de la v0.21 (`9d15282`) qui avait réécrit `config_flow.py` et `tydom_client.py` — commit `a47f338`.
> - 2026-06-04 : seconde ré-application après le `rebase from last release` (`632c29c`) qui a de nouveau réécrit les deux fichiers. Le contenu de ce doc reste valide : les patterns vulnérables et les emplacements ciblés sont inchangés.

Ré-application des correctifs de sécurité du commit `db71301` (cf. `2026-05-05-security-fixes.md`) après que le merge de la v0.21 (`9d15282`) a réécrit `config_flow.py` et `tydom_client.py` et annulé la majorité des correctifs.

## Fichiers modifiés

- `custom_components/deltadore_tydom/tydom/tydom_client.py`
- `custom_components/deltadore_tydom/config_flow.py`

---

## Correctifs

### [CRITIQUE] Injection JSON → `json.dumps()`

`put_data()`, `put_devices_data()` et `_put_alarm_cdata()` reconstruisaient les bodies par concaténation. Remplacés par `json.dumps()` (`tydom_client.py` ll.1094, 1131, 1300, 1304, 1307). `import json` ajouté au top du module et doublon local supprimé dans `suspend_moment()`.

### [CRITIQUE] PIN d'alarme dans les logs

Les `LOGGER.debug("… %s %s", "PUT cdata", body)` dans `put_data`, `put_devices_data`, `_put_alarm_cdata` et `get_device_data` exposaient le body (contenant le `pwd`). Le `body` a été retiré du message de log (`tydom_client.py` ll.957, 1105, 1176, 1333). Le `LOGGER.error("Request bytes: %s", sanitized_bytes)` introduit par la v0.21 (l.1348) est conservé car son `sanitize_log_message()` masque déjà `"pwd":"…"` via regex.

### [CRITIQUE] Credentials loggés lors de l'auth cloud

**Déjà couvert par v0.21** — `async_get_credentials()` (`tydom_client.py` ll.222, 243) applique `sanitize_log_message()` qui masque `access_token`, `password`, `pwd`, `token` et `Bearer …`. Approche différente du correctif d'origine mais effective. Aucune action requise.

### [HIGH] TLS désactivé globalement

`check_hostname=False` et `verify_mode=ssl.CERT_NONE` étaient appliqués inconditionnellement, y compris pour `mediation.tydom.com`. Désormais branché sur `self._host == MEDIATION_URL` (`tydom_client.py` ll.301-310) : `CERT_REQUIRED` en mode cloud, `CERT_NONE` conservé pour le mode local (certificat auto-signé de la box Tydom).

### [HIGH] Injection de chemin dans les URLs WebSocket

`device_id`, `endpoint_id`, `cmd` et `type_` étaient interpolés bruts. Encodés via `quote(..., safe="")` (import `from urllib.parse import quote` au top) dans :
- `get_device_data()` l.961
- `put_devices_data()` ll.1133-1134
- `_put_alarm_cdata()` ll.1311-1313
- `get_historic_cdata()` ll.1365-1367

### [HIGH] `traceback.print_exc()` exposait les stack traces

16 appels à `traceback.print_exc()` répartis dans 4 méthodes du config flow écrivaient les stack traces sur stdout. Supprimés — `LOGGER.exception()` qui suit chaque site préserve déjà la trace via le système de logging HA. Import `traceback` supprimé (`config_flow.py` l.4).

### [MEDIUM] Données utilisateur dans les logs d'erreur

`LOGGER.error("Invalid host: %s", user_input[CONF_HOST])` et les variantes MAC / Zone HOME / Zone AWAY / Zone NIGHT loggaient les saisies utilisateur au niveau ERROR. Remplacés par `LOGGER.warning("Invalid <champ>")` statiques (`config_flow.py`, 2 blocs identiques aux ll.~294-320 et ~480-500). Le log email était déjà sanitisé via `sanitize_config_data()` (v0.21).

### [MEDIUM] Validation MAC insuffisante

`len(data[CONF_MAC]) != 12` acceptait toute chaîne de 12 caractères (ex. `"ZZZZZZZZZZZZ"`). Remplacé par `re.fullmatch(r"[0-9A-Fa-f]{12}", data[CONF_MAC])` (`config_flow.py` l.132). Tous les flows (user, cloud, discovery, reauth) passent par `validate_input()` donc une seule modification suffit.

### [MEDIUM] Regex email incorrecte

`[A-Z|a-z]` traitait `|` comme un caractère littéral. Corrigé en `[A-Za-z]`. Le tiret a aussi été échappé dans la classe précédente pour cohérence (`config_flow.py` ll.74-76).

### [LOW] File handle leak

`open(file_name)` dans `async_connect()` (mode debug) sans context manager. Remplacé par `with open(file_name) as file:` (`tydom_client.py` l.283).

### [LOW] Chemin de trace hardcodé

`file_name = "/config/traces.txt"` hardcodé. Remplacé par `os.path.join(os.environ.get("HA_CONFIG_DIR", "/config"), "traces.txt")` (`tydom_client.py` l.106). Commentaire `DEBUG ONLY` ajouté.

---

## Non corrigé

**Digest auth via API privée** (`HTTPDigestAuth._thread_local`) : inchangé depuis le correctif d'origine — pas d'alternative sans réécrire l'authentification (aiohttp ne supporte pas nativement Digest auth).

## Risques résiduels à tester

- **TLS cloud strict** : si un proxy d'entreprise présente un certificat non reconnu pour `mediation.tydom.com`, la connexion échouera désormais (alors qu'elle était silencieusement acceptée avant). Comportement attendu et souhaité.
- **`quote(device_id)`** : les `device_id` Tydom sont normalement numériques donc l'encodage est un no-op. À vérifier en cas d'usage d'identifiants exotiques.
