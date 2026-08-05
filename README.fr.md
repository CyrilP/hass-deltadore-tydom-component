# Delta Dore Tydom

[English](README.md) | **Français**

[![Licence][license-shield]](LICENSE)

[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

Ce dépôt contient un *composant personnalisé* pour
[Home Assistant](https://www.home-assistant.io/).

L'intégration `Delta Dore Tydom` permet de surveiller et de piloter votre
[passerelle domotique Delta Dore Tydom](https://www.deltadore.fr/).

Elle peut fonctionner en mode local ou cloud, selon sa configuration. La
passerelle Delta Dore peut être détectée par découverte DHCP.

![Version GitHub](https://img.shields.io/github/release/CyrilP/hass-deltadore-tydom-component)
[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)

## Sommaire

- [Matériel testé](#matériel-testé)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Configuration](#configuration)
- [Dépannage](#dépannage)
- [Capturer les données d'un appareil non pris en charge](#capturer-les-données-dun-appareil-non-pris-en-charge)
- [Gestion à distance TYXAL+](#gestion-à-distance-tyxal)
- [Limites connues](#limites-connues)
- [Sécurité](#sécurité)
- [Contribuer](#contribuer)

**Cette intégration configure les plateformes suivantes.**

Plateforme | Description
-- | --
`alarm_control_panel` | Pilote une alarme TYXAL.
`binary_sensor` | Indique les états binaires et les diagnostics.
`button` | Fournit des commandes sans état, notamment pour les portails, portes de garage et alarmes.
`climate` | Pilote le chauffage, la climatisation et la ventilation.
`cover` | Pilote les volets, stores et bannes.
`event` | Signale les appuis sur les télécommandes et interrupteurs physiques.
`light` | Pilote les éclairages et variateurs.
`lock` | Pilote une serrure.
`number` | Modifie les paramètres numériques réglables exposés par un appareil.
`scene` | Active les scénarios TYDOM.
`select` | Modifie les paramètres à choix multiple exposés par un appareil.
`sensor` | Indique les mesures et informations des appareils.
`switch` | Pilote les sorties binaires, prises et moments TYDOM.
`update` | Installe les mises à jour de micrologiciel TYDOM prises en charge.
`weather` | Indique les informations météorologiques.

### Matériel testé

L'intégration s'appuie sur les capacités des appareils : les équipements
compatibles sont découverts à partir des types d'utilisation et métadonnées
annoncés par TYDOM, et non à partir d'une liste figée de modèles. Le matériel
et les configurations ci-dessous ont été testés par des contributeurs ; cette
liste de compatibilité n'est pas exhaustive.

Catégorie | Matériel ou configuration confirmés | Prise en charge dans Home Assistant
-- | -- | --
Alarme et sécurité | TYXAL+, CS8000, CSX40 et détecteurs de fumée DFR | Pilotage de l'alarme, modes par zone, diagnostics, historique et acquittement des événements, ainsi que la gestion à distance des produits et zones compatibles.
Chauffage et régulation | Tybox 5101 avec Typass ATL, Tywell Control, TYXIA 1137, Calybox et RF 6600 FP | Régulation par zone, températures, consignes, modes de fonctionnement, humidité, batterie et commandes de chauffage annoncées par l'appareil.
Suivi énergétique | TYWATT 1000, TYWATT 2000 et TYWATT 5400 avec EMIC | Mesures de puissance, courant et énergie, y compris les canaux de chauffage et d'eau chaude sanitaire lorsqu'ils sont annoncés.
Portails et portes de garage | Récepteurs à contact sec TYXIA 4620 | Boutons impulsionnels reproduisant la séquence ouverture/arrêt/fermeture du récepteur, sans prétendre connaître une position qui n'est pas remontée.
Éclairage et commutation | TYXIA 4910 configuré dans l'usage `Autres` de TYDOM, TYXIA 6610, éclairages, variateurs et prises X3D compatibles | Éclairages, luminosité, interrupteurs et prises selon les capacités annoncées par le point de terminaison.
Ouvertures et protections solaires | Moteurs de volets roulants TYMOOV, installations BSO, fenêtres et portes K-Line DVI, volets et bannes X3D compatibles | Commandes montée, descente et arrêt ; état d'ouverture ou de contact lorsque le matériel fournit un retour.
Commandes physiques | Interrupteurs muraux TYXIA 2600, télécommandes TYXIA 1410, télécommandes TL 2000 et télécommandes TYXAL+ | Événements Home Assistant natifs utilisables dans les automatisations, avec diagnostic de batterie lorsqu'il est fourni.
Capteurs solaires | TySense Sun | Irradiance solaire en W/m² et diagnostics associés.
Ventilation | Naviclim Atlantic 875311 | Régulation, modes de fonctionnement et vitesses de ventilation prises en charge.

Les appareils absents de cette liste peuvent néanmoins fonctionner entièrement
ou exposer une partie utile de leurs attributs. Lorsque vous signalez un
appareil non testé, joignez des données de débogage anonymisées afin d'étendre
la prise en charge sans coder en dur une installation particulière.

## Prérequis

- Home Assistant 2024.7.0 ou version ultérieure.
- HACS 2.0.1 ou version ultérieure pour une installation ou une mise à jour
  effectuée avec HACS.
- Un accès réseau depuis Home Assistant vers la passerelle TYDOM locale ou
  `mediation.tydom.com`, selon l'hôte configuré.

## Installation

La méthode recommandée consiste à installer l'intégration Delta Dore Tydom
avec HACS.

Ajoutez l'intégration depuis la page **Paramètres > Appareils et services** de
Home Assistant.

[![Ouvrir votre instance Home Assistant et commencer à configurer une nouvelle intégration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=deltadore_tydom)

### Installation manuelle

1. Ouvrez le répertoire de configuration Home Assistant contenant
   `configuration.yaml`.
1. Créez le répertoire `custom_components` s'il n'existe pas encore.
1. Dans `custom_components`, créez un répertoire nommé `deltadore_tydom`.
1. Téléchargez tous les fichiers du répertoire
   `custom_components/deltadore_tydom` de ce dépôt.
1. Placez les fichiers téléchargés dans le nouveau répertoire
   `custom_components/deltadore_tydom`.
1. Redémarrez Home Assistant.
1. Ouvrez **Paramètres > Appareils et services**, sélectionnez
   **Ajouter une intégration**, puis recherchez **Delta Dore Tydom**.

### Mise à jour

Pour une installation HACS, installez la mise à jour proposée par HACS. Chaque
version publiée fournit une archive `deltadore_tydom.zip` générée, contenant
une version cohérente de l'intégration.

Pour une installation manuelle, remplacez la totalité du répertoire
`custom_components/deltadore_tydom` par les fichiers d'une même version, puis
redémarrez Home Assistant. Ne mélangez pas des fichiers individuels provenant
de versions ou de branches de test différentes.

## Configuration

La configuration s'effectue depuis l'interface de Home Assistant.

### Modes de connexion

Le mode de configuration sélectionné détermine la manière dont le mot de passe
de la passerelle TYDOM est obtenu. L'hôte détermine si la connexion elle-même
est locale ou utilise le service de médiation Delta Dore.

Mode | Identifiants | Connexion
-- | -- | --
Cloud | Saisissez l'adresse e-mail et le mot de passe du compte Delta Dore. L'intégration récupère automatiquement le mot de passe de la passerelle correspondante. | Utilisez le nom d'hôte ou l'adresse IP de la passerelle pour une connexion locale, ou `mediation.tydom.com` pour une connexion cloud.
Manuel | Saisissez directement le mot de passe de la passerelle TYDOM. Aucun compte Delta Dore n'est nécessaire pendant la configuration. | Normalement le nom d'hôte ou l'adresse IP de la passerelle locale ; tout hôte compatible explicitement configuré est accepté.

### Champs de configuration

Champ | Obligatoire | Description
-- | -- | --
Hôte | Oui | Nom d'hôte ou adresse IP du TYDOM local, ou `mediation.tydom.com` pour une connexion cloud.
Adresse MAC | Oui | Adresse MAC de la passerelle sous la forme de 12 caractères hexadécimaux sans séparateurs.
E-mail et mot de passe Delta Dore | Mode cloud | Identifiants du compte Delta Dore contenant la passerelle. Ils servent à récupérer son mot de passe de passerelle.
Mot de passe TYDOM | Mode manuel | Mot de passe de la passerelle, différent du mot de passe ordinaire du compte Delta Dore.
Intervalle de rafraîchissement | Oui | Intervalle de rafraîchissement périodique compris entre 1 et 1 440 minutes ; la valeur par défaut est de 30 minutes. Les événements transmis en temps réel restent actifs entre les rafraîchissements.
Zones Présent, Absent et Nuit | Non | Identifiants de zones TYXAL compris entre 0 et 8, séparés par des virgules, par exemple `1,2,4`. Chaque champ définit les zones armées par le mode d'alarme Home Assistant correspondant.
Code PIN de l'alarme | Non | Nécessaire pour modifier le mode de l'alarme depuis Home Assistant ; inutile pour consulter uniquement son état.

Après la configuration, ouvrez le menu **Configurer** de l'intégration pour
modifier l'intervalle de rafraîchissement, les zones d'alarme ou le code PIN.

## Dépannage

### Activer la journalisation de débogage

Ouvrez **Paramètres > Appareils et services**, sélectionnez **Delta Dore
Tydom**, ouvrez le menu à trois points et sélectionnez **Activer la
journalisation de débogage**. Reproduisez le problème, puis utilisez le même
menu pour désactiver la journalisation de débogage et télécharger le journal
obtenu.

Pour enregistrer le comportement au démarrage, ajoutez la configuration
suivante à `configuration.yaml`, puis redémarrez Home Assistant :

```yaml
logger:
  default: info
  logs:
    custom_components.deltadore_tydom: debug
```

### Erreurs d'authentification et de communication

Erreur | Signification | Vérifications
-- | -- | --
Erreur d'authentification | Les identifiants fournis ou récupérés ont été refusés. | En mode Cloud, vérifiez l'adresse e-mail Delta Dore, le mot de passe du compte et l'adresse MAC de la passerelle. En mode Manuel, vérifiez que vous avez saisi le mot de passe de la passerelle TYDOM, et non celui du compte Delta Dore.
Erreur de communication | Home Assistant n'a pas pu joindre l'hôte configuré ou terminer la connexion. | Vérifiez le nom d'hôte ou l'adresse IP, l'accès au réseau local, le DNS, l'alimentation de la passerelle et, pour un accès cloud, la connectivité avec `mediation.tydom.com`.

### Supprimer les appareils obsolètes

Ouvrez **Paramètres > Appareils et services > Delta Dore Tydom > Appareils**,
ouvrez le menu de l'appareil obsolète et sélectionnez **Supprimer l'appareil**.
Cette opération supprime son entrée du registre des appareils Home Assistant ;
elle ne supprime rien de la passerelle TYDOM ni de l'application officielle.
L'appareil peut être découvert de nouveau si la passerelle continue à
l'annoncer.

## Capturer les données d'un appareil non pris en charge

Le dépôt fournit un outil de capture en lecture seule destiné à documenter les
appareils et comportements du protocole que l'intégration ne prend pas encore
en charge :

```bash
python3 tools/capture_tydom_data.py \
  --host 192.168.1.100 \
  --mac AABBCCDDEEFF \
  --password '<Mot de passe de la passerelle Tydom>' \
  --duration 120
```

L'outil interroge les ressources actuelles de configuration, appareils, zones,
scénarios, groupes et moments, notamment `/devices/meta`, `/devices/cmeta`,
`/devices/data`, `/areas/meta`, `/areas/cmeta` et `/areas/data`. Il continue
ensuite à écouter les événements pendant que l'équipement est actionné
physiquement ou depuis l'application Tydom.

Chaque capture produit :

- `raw_messages.txt`, qui contient des trames WebSocket horodatées et
  réutilisables ;
- `parsed_messages.json`, qui contient les URI, méthodes ou états de réponse
  normalisés, ainsi que les charges utiles décodées.

Les mots de passe, jetons, en-têtes d'autorisation et adresses e-mail sont
masqués avant l'écriture des fichiers. Les identifiants, noms, topologies et
valeurs d'état des appareils sont conservés, car ils sont nécessaires à
l'analyse du protocole. Les captures doivent donc toujours être vérifiées
avant d'être partagées publiquement.

Pour obtenir une capture utile, effectuez une action clairement identifiable,
attendez environ dix secondes, effectuez l'action inverse et notez les deux
horodatages. La capture enregistre les réponses et événements publiés par la
passerelle ; elle ne permet pas nécessairement d'identifier la requête exacte
envoyée par un autre client, notamment l'application mobile officielle.

Consultez le [guide de capture complet](tools/README_capture.md) pour les
exemples de connexion locale et distante, l'analyse des résultats, la
validation de l'analyseur et les consignes de sécurité. Le
[guide de découverte des points de terminaison](tools/README_discover_endpoints.md)
explique comment interroger les ressources et méthodes HTTP disponibles.

## Gestion à distance TYXAL+

Le panneau de commande de l'alarme fournit des services pour les fonctions
TYXAL+ utiles dans Home Assistant :

- `deltadore_tydom.get_events` renvoie l'historique et permet de le filtrer sur
  les alarmes, les activations/désactivations ou les événements non acquittés ;
- `deltadore_tydom.acknowledge_events` acquitte les événements en attente ;
- `deltadore_tydom.get_alarm_products` répertorie les produits et zones
  configurés ;
- `deltadore_tydom.enter_alarm_maintenance` déverrouille la configuration à
  distance et place une CS8000 désarmée en mode maintenance ;
- `deltadore_tydom.get_alarm_product_configuration` lit l'état actif et la
  zone d'un produit ;
- `deltadore_tydom.configure_alarm_product` active ou désactive un produit et
  peut l'affecter à une autre zone ;
- `deltadore_tydom.rename_alarm_zone` modifie le nom personnalisé d'une zone
  ou efface son libellé lorsqu'un nom vide est fourni ;
- `deltadore_tydom.exit_alarm_maintenance` remet la CS8000 dans son état normal
  désarmé et verrouille la session de configuration à distance.

Utilisez le premier service pour obtenir les identifiants des produits et des
zones nécessaires aux autres services. La CS8000 doit être désarmée et le code
installateur TYXAL doit être fourni lors de chaque appel de configuration d'un
produit. Activez le mode maintenance avant de lire ou modifier la
configuration, puis quittez-le toujours une fois l'opération terminée. Le code
installateur n'est utilisé que pour la requête et est masqué dans les journaux.
La suppression de produits, les codes d'accès, les réglages téléphoniques et la
configuration des sirènes ne sont pas exposés.

L'appareil d'alarme TYXAL fournit également un bouton **Acquitter les
événements** utilisable directement dans un tableau de bord, sans appel de
service ni automatisation.

## Limites connues

- Les récepteurs de portail et de porte de garage TYXIA 4620 fournissent une
  commande impulsionnelle, mais aucun retour de position ou de direction. Home
  Assistant expose donc un bouton sans état et ne peut pas déterminer si
  l'impulsion suivante ouvrira, arrêtera ou fermera la motorisation.
- Les appareils radio ou alimentés par batterie transmettent selon leur propre
  cadence. L'actualisation ou l'interrogation de la passerelle ne peut pas
  forcer un appareil endormi à transmettre une valeur plus récente.
- Un nom de modèle exact n'est affiché que lorsque TYDOM fournit des métadonnées
  produit ou tutoriel fiables. Les autres appareils compatibles conservent un
  nom de modèle Delta Dore générique plutôt que d'être identifiés à partir de
  capacités trop générales.
- L'outil de capture enregistre les messages renvoyés ou publiés par la
  passerelle. Il ne permet pas toujours d'identifier la requête sortante exacte
  envoyée par l'application mobile officielle.
- La gestion à distance TYXAL expose uniquement les opérations sûres et
  confirmées décrites ci-dessus. La suppression de produits, les codes d'accès,
  les réglages téléphoniques et la configuration des sirènes ne sont pas pris
  en charge.

## Sécurité

Ne signalez pas une vulnérabilité présumée dans un ticket public. Consultez la
[politique de sécurité](SECURITY.md) et utilisez la procédure de signalement
privé qui y est décrite.

## Contribuer

Si vous souhaitez contribuer, consultez les
[consignes de contribution](CONTRIBUTING.md).

***

[buymecoffee]: https://www.buymeacoffee.com/cyrilp
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/CyrilP/hass-deltadore-tydom-component.svg?style=for-the-badge
