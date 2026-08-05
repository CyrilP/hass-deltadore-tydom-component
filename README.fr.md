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

## Configuration

La configuration s'effectue depuis l'interface de Home Assistant. Le nom
d'hôte ou l'adresse IP peut être :

* Le nom d'hôte ou l'adresse IP de votre TYDOM (mode local uniquement). Un
  accès au cloud reste nécessaire pour récupérer les identifiants de la
  passerelle.
* `mediation.tydom.com` pour utiliser l'intégration à travers le cloud.

L'adresse MAC est celle de votre passerelle TYDOM.

L'adresse e-mail et le mot de passe sont ceux de votre compte Delta Dore.

Le code PIN de l'alarme est facultatif et sert à modifier son mode.

## Capturer les données d'un appareil non pris en charge

Le dépôt fournit un outil de capture en lecture seule destiné à documenter les
appareils et comportements du protocole que l'intégration ne prend pas encore
en charge :

```bash
python3 tools/capture_tydom_data.py \
  --host 192.168.1.100 \
  --mac 001A2502419B \
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

## Contributions bienvenues !

Si vous souhaitez contribuer, consultez les
[consignes de contribution](CONTRIBUTING.md).

***

[buymecoffee]: https://www.buymeacoffee.com/cyrilp
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/CyrilP/hass-deltadore-tydom-component.svg?style=for-the-badge
