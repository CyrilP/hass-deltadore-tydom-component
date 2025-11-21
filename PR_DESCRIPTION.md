# Pull Request - Améliorations majeures v0.20

## Résumé

Cette PR apporte des améliorations majeures à l'intégration Delta Dore Tydom pour Home Assistant, passant de la version **v0.19** à **v0.20**. Les principales améliorations incluent une interface utilisateur modernisée, l'ajout de **6 nouvelles plateformes**, une implémentation complète des scénarios Tydom, et de nombreuses corrections.

## Principales améliorations

### 1. Interface utilisateur modernisée

**Fichier : `config_flow.py` (+413 lignes, 833 → 1246 lignes)**

- **Mode de configuration dual** : Ajout d'un sélecteur permettant de choisir entre :
  - Mode Cloud : Récupération automatique des identifiants Tydom via le compte Delta Dore
  - Mode Manuel : Saisie directe du mot de passe Tydom
- **Sélecteurs modernes Home Assistant** : Remplacement des champs texte par des sélecteurs typés (TextSelector, NumberSelector, EmailSelector, PasswordSelector)
- **Ré-authentification améliorée** : Support complet de la ré-authentification pour les deux modes
- **Validation renforcée** : Amélioration de la validation des entrées avec messages d'erreur plus clairs
- **Découverte DHCP** : Amélioration du flux de découverte avec choix du mode de configuration

### 2. Nouvelles plateformes Home Assistant (6 nouvelles plateformes)

- **`scene.py`** : Support complet des scénarios Tydom avec activation et affichage des métadonnées
- **`button.py`** : Support des boutons
- **`number.py`** : Support des entités numériques
- **`select.py`** : Support des sélecteurs
- **`switch.py`** : Support des interrupteurs
- **`event.py`** : Support des événements

### 3. Implémentation complète des scénarios Tydom

**Fichier : `ha_entities.py` (+1122 lignes, 1381 → 2503 lignes)**

- **Récupération des métadonnées** : Parsing correct des métadonnées depuis `/configs/file` pour obtenir les noms, types, pictogrammes et règles des scénarios
- **Formatage intelligent** : Les attributs bruts `grpAct` et `epAct` sont masqués et remplacés par des versions formatées et lisibles (`affected_groups`, `affected_endpoints`)
- **Icônes Material Design** : Mapping automatique des pictogrammes Tydom vers des icônes Material Design (light, shutter, heating, alarm, etc.)
- **Attributs d'état enrichis** : Affichage des informations détaillées (scenario_id, scenario_type, picto, rule_id, groupes et endpoints affectés)

### 4. Corrections et améliorations techniques

- **Gestion des exceptions** : Correction de la gestion de l'exception `AbortFlow` dans `config_flow`
- **Méthode native_value** : Ajout de la méthode `native_value` manquante dans `HASensor`
- **Récupération des informations** : Amélioration de la récupération des informations fabricant et modèle des appareils
- **Typage** : Corrections des erreurs de typage dans `tydom_client.py`
- **Compatibilité Python** : Configuration Python 3.10+ avec vérifications None pour `_metadata`
- **Gestion des capteurs** : Amélioration de la gestion des capteurs avec correction des mises à jour
- **Détection des doublons** : Amélioration de la détection et gestion des appareils dupliqués

### 5. Internationalisation

- **Traductions françaises** : Ajout complet du fichier `translations/fr.json` avec toutes les traductions
- **Traductions anglaises** : Mise à jour complète de `translations/en.json`

## Fichiers modifiés

### Nouveaux fichiers (7)

- `custom_components/deltadore_tydom/scene.py` - Plateforme scénarios
- `custom_components/deltadore_tydom/button.py` - Plateforme boutons
- `custom_components/deltadore_tydom/number.py` - Plateforme nombres
- `custom_components/deltadore_tydom/select.py` - Plateforme sélecteurs
- `custom_components/deltadore_tydom/switch.py` - Plateforme interrupteurs
- `custom_components/deltadore_tydom/event.py` - Plateforme événements
- `custom_components/deltadore_tydom/translations/fr.json` - Traductions françaises

### Fichiers modifiés (11)

- `custom_components/deltadore_tydom/__init__.py` - Ajout des 6 nouvelles plateformes
- `custom_components/deltadore_tydom/config_flow.py` - Interface modernisée (+413 lignes)
- `custom_components/deltadore_tydom/ha_entities.py` - Implémentation scénarios (+1122 lignes)
- `custom_components/deltadore_tydom/hub.py` - Améliorations diverses
- `custom_components/deltadore_tydom/tydom/tydom_devices.py` - Classe TydomScene avec gestion epAct/grpAct
- `custom_components/deltadore_tydom/tydom/MessageHandler.py` - Parsing scénarios depuis /configs/file
- `custom_components/deltadore_tydom/tydom/tydom_client.py` - Corrections typage
- `custom_components/deltadore_tydom/manifest.json` - Version v0.20
- `custom_components/deltadore_tydom/translations/en.json` - Mise à jour traductions
- `custom_components/deltadore_tydom/services.yaml` - Mise à jour services

## Statistiques

- **Lignes ajoutées** : ~1500+ lignes de code
- **Nouvelles plateformes** : 6
- **Nouveaux fichiers** : 7
- **Fichiers modifiés** : 11
- **Version** : v0.19 → v0.20

## Notes de migration

Aucune action requise de la part des utilisateurs. Les configurations existantes continuent de fonctionner. Les nouveaux utilisateurs bénéficient automatiquement de l'interface améliorée et des nouvelles plateformes.

## Tests effectués

### Configuration et authentification
- ✅ Tests de configuration en mode Cloud (récupération automatique des identifiants)
- ✅ Tests de configuration en mode Manuel (saisie directe du mot de passe Tydom)
- ✅ Tests de ré-authentification pour les deux modes (cloud et manuel)
- ✅ Validation de la découverte DHCP avec choix du mode de configuration
- ✅ Tests de validation des entrées utilisateur (email, MAC, zones, intervalle de rafraîchissement)

### Scénarios Tydom
- ✅ Validation du formatage des attributs `grpAct` et `epAct` en versions lisibles (`affected_groups`, `affected_endpoints`)
- ✅ Tests d'activation des scénarios Tydom via la plateforme `scene`
- ✅ Vérification de la récupération des métadonnées depuis `/configs/file` (noms, types, pictogrammes, règles)
- ✅ Tests avec différents types de scénarios :
  - Scénarios de volets (position UP/DOWN/STOP)
  - Scénarios de lumières (niveau)
  - Scénarios de garage (position)
- ✅ Validation du mapping des icônes Material Design basé sur les pictogrammes Tydom
- ✅ Vérification de l'affichage des attributs d'état enrichis (scenario_id, scenario_type, picto, rule_id)

### Nouvelles plateformes
- ✅ Vérification de la plateforme `scene` (activation et affichage des métadonnées)
- ✅ Vérification de la plateforme `button`
- ✅ Vérification de la plateforme `number`
- ✅ Vérification de la plateforme `select`
- ✅ Vérification de la plateforme `switch`
- ✅ Vérification de la plateforme `event`

### Internationalisation
- ✅ Validation des traductions françaises complètes (`translations/fr.json`)
- ✅ Validation des traductions anglaises mises à jour (`translations/en.json`)
- ✅ Vérification des messages d'erreur traduits dans les deux langues

### Qualité du code
- ✅ Vérification du linter (ruff) - toutes les erreurs corrigées
- ✅ Validation de la structure des fichiers et des imports
- ✅ Vérification de la compatibilité Python 3.10+

