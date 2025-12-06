# Script de capture des données Tydom

## 📋 Description

Ce script permet de capturer **toutes les données brutes** de votre passerelle Delta Dore Tydom et de les sauvegarder dans des fichiers texte organisés pour analyse.

## 🚀 Utilisation

### Prérequis

```bash
pip install aiohttp requests urllib3
```

### Commandes de base

#### Mode cloud avec identifiants Delta Dore (recommandé)

```bash
python3 tools/capture_tydom_data.py \
  --host mediation.tydom.com \
  --mac 001122334455 \
  --email votre_email@example.com \
  --delta-password votre_mot_de_passe_delta_dore
```

#### Mode local avec mot de passe Tydom direct

```bash
python3 tools/capture_tydom_data.py \
  --host 192.168.1.100 \
  --mac 001A2502419B \
  --password votre_mot_de_passe_tydom
```

#### Capturer pendant une durée spécifique

```bash
# Capturer pendant 60 secondes
python3 tools/capture_tydom_data.py \
  --host mediation.tydom.com \
  --mac 001122334455 \
  --email votre_email@example.com \
  --delta-password votre_mot_de_passe \
  --duration 60
```

#### Changer le répertoire de sortie

```bash
python3 tools/capture_tydom_data.py \
  --host mediation.tydom.com \
  --mac 001122334455 \
  --email votre_email@example.com \
  --delta-password votre_mot_de_passe \
  --output /chemin/vers/sortie
```

## 📁 Fichiers générés

Chaque capture crée un dossier avec timestamp : `capture_YYYYMMDD_HHMMSS/`

### Fichiers créés :

- **`raw_messages.txt`** : Tous les messages WebSocket bruts avec timestamps
- **`parsed_messages.json`** : Messages parsés en JSON avec URI et données

## 🔍 Analyse des données

### Exemple : Analyser les scénarios

```bash
# Extraire les scénarios depuis les messages parsés
cat tools/captures/capture_*/parsed_messages.json | jq '.[] | select(.uri == "/scenarios/file") | .data.scn'

# Compter le nombre de scénarios
cat tools/captures/capture_*/parsed_messages.json | jq '[.[] | select(.uri == "/scenarios/file") | .data.scn[]] | length'

# Extraire les IDs des scénarios
cat tools/captures/capture_*/parsed_messages.json | jq '.[] | select(.uri == "/scenarios/file") | .data.scn[] | .id'
```

### Exemple : Analyser les appareils

```bash
# Voir tous les messages de devices
cat tools/captures/capture_*/parsed_messages.json | jq '.[] | select(.uri | contains("devices"))'

# Chercher dans les messages bruts
grep "Uri-Origin: /devices" tools/captures/capture_*/raw_messages.txt -A 50
```

### Exemple : Chercher dans tous les messages

```bash
# Chercher un terme dans tous les messages
grep -r "terme_recherché" tools/captures/capture_*/raw_messages.txt

# Voir les messages d'un type spécifique
grep "Uri-Origin: /scenarios/file" tools/captures/capture_*/raw_messages.txt -A 20
```

## 📊 Statistiques

Le script affiche en temps réel :
- Le nombre de messages capturés
- Les types de données sauvegardés
- Les événements détectés

À la fin, un rapport complet est généré dans `README.md`.

## ⚙️ Options disponibles

| Option | Description | Défaut |
|--------|-------------|--------|
| `--host` | Adresse IP ou hostname de la passerelle | **Requis** |
| `--mac` | Adresse MAC de la passerelle | **Requis** |
| `--password` | Mot de passe Tydom (ou utiliser --email + --delta-password) | Optionnel |
| `--email` | Email du compte Delta Dore | Optionnel |
| `--delta-password` | Mot de passe du compte Delta Dore | Optionnel |
| `--output` | Répertoire de sortie | `tools/captures` |
| `--duration` | Durée de capture (secondes) | `300` |

## 🎯 Cas d'usage

### 1. Déboguer un problème spécifique

```bash
# Capturer pendant 2 minutes pour analyser un problème
python3 tools/capture_tydom_data.py \
  --host 192.168.1.100 \
  --mac 001A2502419B \
  --password votre_mot_de_passe \
  --duration 120
```

### 2. Capturer toutes les données au démarrage

```bash
# Capturer pendant 10 minutes pour avoir une vue complète
python3 tools/capture_tydom_data.py \
  --host 192.168.1.100 \
  --mac 001A2502419B \
  --password votre_mot_de_passe \
  --duration 600
```

### 3. Analyser les scènes

```bash
# Capturer et analyser les scénarios
python3 tools/capture_tydom_data.py \
  --host 192.168.1.100 \
  --mac 001A2502419B \
  --password votre_mot_de_passe \
  --duration 60

# Puis analyser
cat tools/captures/capture_*/scenarios.json | jq '.[0].data.scn[] | {id, name: .name // "N/A"}'
```

## 🔧 Dépannage

### Erreur de connexion

Si vous obtenez une erreur de connexion :
1. Vérifiez que la passerelle est accessible : `ping <IP>`
2. Vérifiez que le MAC et le mot de passe sont corrects
3. Essayez le mode cloud avec `--cloud`

### Pas de données capturées

Si aucun message n'est capturé :
1. Vérifiez que la passerelle répond (LEDs actives)
2. Augmentez la durée avec `--duration`
3. Vérifiez les logs dans la console

### Authentification échouée

Si l'authentification échoue :
- Vérifiez le mot de passe Tydom (pas le mot de passe WiFi)
- Le mot de passe peut être récupéré depuis l'API Delta Dore

## 📝 Notes

- Les données sont sauvegardées en temps réel
- Le script continue à capturer même si certaines requêtes échouent
- Appuyez sur `Ctrl+C` pour arrêter la capture à tout moment
- Chaque capture crée un nouveau dossier avec timestamp

## 🔒 Sécurité

⚠️ **Attention** : Les fichiers de capture contiennent des données sensibles (mots de passe, configurations). Ne les partagez pas publiquement.

Pour supprimer les captures :
```bash
rm -rf tools/captures/capture_*
```

