# Changelog

## v0.22 — Corrections climate & nommage des entités

### 🐛 Corrections

#### 1. Climate bloqué sur `off` / consigne absente (splits Zigbee Atlantic/Fujitsu)

Les splits réversibles Atlantic/Fujitsu raccordés via l'adaptateur Zigbee Tydom
(`manufacturer = ATLANTIC GROUP`, `modelIdentifier = Adapter Zigbee FUJITSU`,
catalogue `split_takao_type_1`) exposaient une entité `climate.*` **désynchronisée** :

- `hvac_mode` renvoyait toujours **`off`** alors que l'unité chauffait/refroidissait ;
- `target_temperature` était **`None`** (curseur verrouillé), impossible à régler.

**Cause :** ces produits exposent un `thermicLevel` **dégénéré** (enum `['STOP']` /
`['STOP','STOP']`, valeur toujours `STOP`/`null`), qui ne reflète jamais le mode réel.
Le mode réel est porté par `authorization`
(`STOP`/`HEATING`/`COOLING`/`AUTO`/`VENTILATING`/`DRYING`) et la consigne par
`setpoint`/`coolSetpoint`/`heatSetpoint`. Ces attributs étaient ignorés.

**Correctif (`ha_entities.py`, `HaClimate`) :**
- Nouvelle méthode `_is_thermic_level_degenerate()` : détecte l'enum `thermicLevel`
  réduit à `STOP` (via les métadonnées de l'endpoint).
- `hvac_mode` : quand `thermicLevel` est dégénéré, on dérive le mode depuis
  `authorization`. Sinon, comportement **X3D historique conservé** (thermicLevel
  prioritaire).
- `target_temperature` : repli final sur `setpoint` générique.

> ✅ **Aucune régression** : les radiateurs X3D (pilotés par `hvacMode` ou par un
> `thermicLevel` non dégénéré NORMAL/ECO/COMFORT/…) conservent exactement leur
> comportement précédent. Validé sur données réelles (`tools/traces-naviclim-atlantic.txt`).

#### 2. Doublage du nom des entités principales (`light.salon_salon` = « Salon Salon »)

L'entité principale de chaque appareil était créée avec
`_attr_has_entity_name = True` **et** `_attr_name = <nom de l'appareil>`, ce qui
poussait Home Assistant à composer `<appareil> <entité>` — dédoublant le
`friendly_name` **et** l'`entity_id` (`light.salon_salon`,
`binary_sensor.cuisine_cuisine`, `alarm_control_panel.tyxal_alarm_tyxal_alarm`,
`sensor.fumee_palier_fumee_palier`, …).

**Correctif (`ha_entities.py`) :** `self._attr_name = None` pour les **18 classes
d'entité principale** concernées (HaLight, HaCover, HaAlarm, HaSmoke, HaClimate,
HaWeather, HaMoisture, HaThermo, HASensor, HAEnergy, HAMoment, HASwitch, HAGroup,
HaOpeningBinarySensor, HaWindow, HaDoor, HaGate, HaGarage). L'entité hérite alors
proprement du nom de l'appareil → `light.salon` / « Salon ».

> ✅ **Aucune régression sur les installations existantes** : le `unique_id`
> (`{device_id}_light`, `{device_id}_climate`, …) est **inchangé**. Home Assistant
> conserve donc l'`entity_id` déjà enregistré (les dashboards et automations
> continuent de fonctionner) ; seul le `friendly_name` affiché est nettoyé.
>
> ℹ️ **Nouvelles installations** : les entités sont créées directement avec un
> `entity_id` propre (`light.salon` au lieu de `light.salon_salon`).
>
> La classe passerelle `HATydom` (`_attr_has_entity_name = False`) est
> volontairement **laissée intacte** : `device_name` y est correct.

### Notes

- Version passée de `v0.21` à `v0.22`.
- Aucun changement de dépendances ni de flux de configuration.

