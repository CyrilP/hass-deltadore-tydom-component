# Security Fixes — 2026-05-05

Correctifs de sécurité appliqués suite à un audit du plugin.

## Fichiers modifiés

- `custom_components/deltadore_tydom/tydom/tydom_client.py`
- `custom_components/deltadore_tydom/config_flow.py`

---

## Correctifs

### [CRITIQUE] Injection JSON → json.dumps()

`put_data()`, `put_devices_data()`, `_put_alarm_cdata()` construisaient les corps JSON par concaténation de chaînes. Remplacé par `json.dumps()` dans les trois fonctions.

### [CRITIQUE] PIN d'alarme dans les logs

Le log de `_put_alarm_cdata()` incluait le body complet (contenant le PIN). Remplacé par un message générique. Supprimé également le `LOGGER.error(a_bytes)` qui exposait les bytes encodés.

### [CRITIQUE] Credentials loggés lors de l'auth cloud

`async_get_credentials()` loggait les réponses HTTP complètes (tokens OAuth, mot de passe Tydom) au niveau DEBUG. Les logs ne conservent plus que le status HTTP.

### [HIGH] TLS désactivé globalement

`check_hostname=False` et `verify_mode=ssl.CERT_NONE` s'appliquaient aussi bien au mode cloud qu'au mode local. En mode cloud (`mediation.tydom.com`), TLS est maintenant vérifié (`CERT_REQUIRED`). Le mode local conserve `CERT_NONE` (certificat auto-signé de la box Tydom) avec commentaire explicatif.

### [HIGH] Injection de chemin dans les URLs WebSocket

`device_id`, `endpoint_id`, `cmd` et `type_` étaient interpolés directement dans les URLs. Encodés avec `urllib.parse.quote()` dans `get_device_data()`, `put_devices_data()`, `_put_alarm_cdata()` et `get_historic_cdata()`.

### [HIGH] traceback.print_exc() exposait les stack traces

10 appels à `traceback.print_exc()` répartis dans 4 méthodes du config flow écrivaient les stack traces sur stdout. Supprimés — `LOGGER.exception()` conserve déjà la trace via le système de logging HA. Import `traceback` supprimé.

### [MEDIUM] Données utilisateur dans les logs d'erreur

Les handlers de validation (`config_flow.py`) loggaient host, MAC, email et zones au niveau ERROR en cas de saisie invalide. Remplacés par des messages statiques au niveau WARNING.

### [MEDIUM] Validation MAC insuffisante

La validation acceptait toute chaîne de 12 caractères (ex. `"ZZZZZZZZZZZZ"`). Remplacé par `re.fullmatch(r"[0-9A-Fa-f]{12}", ...)`.

### [MEDIUM] Regex email incorrecte

Autorisation du tiret + `[A-Z|a-z]` dans la classe de caractères traitait `|` comme un caractère littéral. Corrigé en `[A-Za-z]`.

### [LOW] File handle leak

`open(file_name)` dans `async_connect()` (mode debug) sans context manager. Remplacé par `with open(file_name) as file:`.

### [LOW] Chemin de trace hardcodé

`file_name = "/config/traces.txt"` hardcodé. Remplacé par `os.path.join(os.environ.get("HA_CONFIG_DIR", "/config"), "traces.txt")`. Commentaire `DEBUG ONLY` ajouté sur le bloc de variables globales.

---

## Non corrigé

**Digest auth via API privée** (`HTTPDigestAuth._thread_local`) : pas d'alternative sans réécrire l'authentification digest — aiohttp ne supporte pas nativement Digest auth.
