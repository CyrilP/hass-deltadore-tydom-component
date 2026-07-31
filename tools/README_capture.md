# Capture des données TYDOM

`capture_tydom_data.py` ouvre une connexion WebSocket en lecture seule vers une
passerelle Delta Dore, demande les principales ressources du protocole et
enregistre les réponses et événements reçus. Il sert notamment à documenter un
équipement encore inconnu avant d'ajouter sa prise en charge à l'intégration.

`capture_simple.py` est conservé comme alias compatible et lance désormais le
même outil afin que les deux commandes ne puissent plus diverger.

## Prérequis

Depuis la racine du dépôt :

```bash
python3 -m pip install aiohttp async-timeout requests urllib3
```

## Utilisation

### Connexion locale avec le mot de passe de la passerelle

```bash
python3 tools/capture_tydom_data.py \
  --host 192.168.1.100 \
  --mac 001A2502419B \
  --password '<mot-de-passe-passerelle>' \
  --duration 120
```

### Connexion distante avec le compte Delta Dore

```bash
python3 tools/capture_tydom_data.py \
  --host mediation.tydom.com \
  --mac 001A2502419B \
  --email utilisateur@example.com \
  --delta-password '<mot-de-passe-compte>' \
  --duration 120
```

Les arguments contenant un mot de passe peuvent rester dans l'historique du
terminal. Utilisez une session temporaire et effacez son historique si cela est
nécessaire sur votre système.

Par défaut, les captures sont placées dans
`tools/captures/capture_YYYYMMDD_HHMMSS/`. Un autre emplacement peut être
fourni avec `--output`.

## Flux de découverte

L'outil envoie uniquement des requêtes `GET`. Il ne modifie donc ni les
équipements ni la configuration de l'installation.

Les ressources demandées sont :

- `/info`
- `/configs/file`
- `/devices/meta`
- `/areas/meta`
- `/devices/cmeta`
- `/areas/cmeta`
- `/devices/data`
- `/areas/data`
- `/scenarios/file`
- `/groups/file`
- `/moments/file`

Après ces requêtes initiales, la connexion reste ouverte pendant la durée
choisie afin de recevoir les événements publiés par la passerelle. Il est alors
possible d'actionner l'équipement depuis l'application Tydom ou physiquement.

## Fichiers produits

- `raw_messages.txt` contient les trames WebSocket avec leur horodatage. Les
  réponses HTTP et les événements `PUT`/`POST` de la passerelle y restent dans
  un format analysable.
- `parsed_messages.json` contient une représentation JSON normalisée avec
  l'URI, la méthode ou le statut HTTP et les données décodées.

Les mots de passe, jetons, en-têtes d'autorisation et adresses électroniques
sont masqués avant leur écriture. La taille des valeurs masquées dans le fichier
brut est conservée pour ne pas invalider les longueurs HTTP et les blocs
`chunked`.

Les identifiants techniques des appareils, les noms, la topologie et certaines
valeurs d'état sont volontairement conservés car ils sont nécessaires pour
comprendre le protocole. Une capture reste donc sensible et ne doit pas être
publiée sans vérification.

## Procédure conseillée pour un nouvel équipement

1. Démarrer une capture de 90 à 120 secondes.
2. Attendre la fin des réponses initiales.
3. Effectuer une seule action identifiable sur l'équipement.
4. Attendre dix secondes et effectuer l'action inverse.
5. Noter les horaires exacts des deux actions.
6. Arrêter la capture avec `Ctrl+C` ou attendre la fin programmée.
7. Vérifier les fichiers avant de les transmettre.

Pour valider et résumer le fichier brut :

```bash
python3 tools/test_capture_parsing.py tools/captures/capture_YYYYMMDD_HHMMSS
```

Quelques recherches utiles :

```bash
jq '.[] | select(.uri == "/devices/data")' \
  tools/captures/capture_*/parsed_messages.json

jq '.[] | select(.uri == "/areas/data")' \
  tools/captures/capture_*/parsed_messages.json

grep -n "1715082810" tools/captures/capture_*/raw_messages.txt
```

## Limite importante

Cette connexion observe les réponses et événements émis par la passerelle. Elle
ne capture pas nécessairement la requête sortante d'un autre client, par exemple
la commande exacte envoyée par l'application mobile officielle.

Une modification effectuée dans l'application peut donc apparaître sous la
forme d'une mise à jour regroupant plusieurs attributs sans indiquer lequel a
été écrit par le téléphone. L'interception directe du trafic mobile nécessite
un proxy HTTPS dédié et ne fait pas partie de cet outil.

## Sécurité et nettoyage

Conservez les captures hors du contrôle de version. Supprimez-les dès que
l'analyse est terminée, après avoir vérifié le chemin ciblé. Le répertoire
`tools/captures/` est ignoré par Git.
