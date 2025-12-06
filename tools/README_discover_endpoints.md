# Script de Découverte des Endpoints Tydom

Ce script permet de découvrir les endpoints disponibles dans l'API Tydom et de déterminer quelles méthodes HTTP sont supportées.

## Prérequis

```bash
pip install aiohttp async-timeout
```

## Usage

### Mode local (connexion directe au gateway)

```bash
python discover_endpoints.py --host <IP_TYDOM> --mac <MAC> --password <PASSWORD>
```

Exemple:
```bash
python discover_endpoints.py --host 192.168.1.100 --mac 001122334455 --password monMotDePasse
```

### Mode distant (via serveur de médiation)

```bash
python discover_endpoints.py --host mediation.tydom.com --mac <MAC> --password <PASSWORD>
```

### Tester toutes les méthodes HTTP

Par défaut, le script teste uniquement la méthode GET. Pour tester toutes les méthodes (GET, PUT, POST, DELETE, PATCH):

```bash
python discover_endpoints.py --host <IP_TYDOM> --mac <MAC> --password <PASSWORD> --test-all
```

## Fonctionnalités

- ✅ Teste une liste d'endpoints connus
- ✅ Détecte les méthodes HTTP supportées pour chaque endpoint
- ✅ Gère l'authentification digest Tydom
- ✅ Affiche un résumé des endpoints disponibles
- ✅ Sauvegarde les résultats dans un fichier JSON

## Endpoints testés

Le script teste les endpoints suivants:

- **Système**: `/ping`, `/info`
- **Configuration**: `/configs/file`, `/configs/gateway/*`
- **Devices**: `/devices/meta`, `/devices/cmeta`, `/devices/data`
- **Areas**: `/areas/meta`, `/areas/cmeta`, `/areas/data`
- **Fichiers**: `/scenarios/file`, `/groups/file`, `/moments/file`
- **Actions**: `/refresh/all`
- **Historiques**: `/historical/events`
- **Firmware**: `/firmware/update`

## Résultats

Le script génère:

1. **Sortie console**: Affichage en temps réel des tests et un résumé final
2. **Fichier JSON**: `endpoints_discovery_results.json` avec tous les détails

### Format du fichier JSON

```json
{
  "/info": {
    "GET": {
      "status": "success",
      "response": "...",
      "transaction_id": 1234567890
    }
  },
  "/ping": {
    "GET": {
      "status": "timeout",
      "error": "Aucune réponse reçue dans les 5 secondes"
    }
  }
}
```

## Exemple de sortie

```
======================================================================
DÉCOUVERTE DES ENDPOINTS TYDOM
======================================================================
✓ Connexion WebSocket établie à 192.168.1.100

📋 Test de 20 endpoints connus...
   (Test de la méthode GET uniquement)

----------------------------------------------------------------------

🔍 Test: GET /ping
   ✓ Succès - Réponse: HTTP/1.1 200 OK...

🔍 Test: GET /info
   ✓ Succès - Réponse: {"productName":"TYWELL PRO"...

...

======================================================================
RÉSUMÉ DES RÉSULTATS
======================================================================

✓ Endpoints disponibles (15):
   /info
      Méthodes supportées: GET
   /devices/meta
      Méthodes supportées: GET
   ...

✗ Endpoints non disponibles (5):
   /areas/meta
   /areas/cmeta
   ...

💾 Résultats sauvegardés dans: endpoints_discovery_results.json
```

## Notes

- Le script utilise l'authentification digest Tydom (comme le composant Home Assistant)
- Les timeouts sont configurés à 5 secondes par requête
- Les endpoints avec placeholders (`{device_id}`, `{endpoint_id}`) nécessitent d'abord de récupérer la liste des devices
- Le script peut être interrompu avec Ctrl+C

## Dépannage

### Erreur d'authentification

Vérifiez que le mot de passe est correct:
```bash
# Le mot de passe peut être récupéré via l'API Delta Dore
# ou configuré dans Home Assistant
```

### Timeout de connexion

Vérifiez que:
- Le gateway Tydom est accessible sur le réseau
- Le port 443 est ouvert
- Le firewall n'bloque pas les connexions WebSocket

### Erreur SSL

Le script désactive la vérification SSL pour les connexions locales. C'est normal et sécurisé pour un réseau local.

