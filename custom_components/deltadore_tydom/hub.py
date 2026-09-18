"""A demonstration 'hub' that connects several devices."""

from __future__ import annotations

import asyncio
import copy
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

from aiohttp import ClientWebSocketResponse, ClientSession

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from .tydom.tydom_client import TydomClient
from .tydom.tydom_devices import (
    Tydom,
    TydomShutter,
    TydomEnergy,
    TydomSmoke,
    TydomBoiler,
    TydomWindow,
    TydomDoor,
    TydomGate,
    TydomGarage,
    TydomLight,
    TydomSwitch,
    TydomInterrupter,
    TydomPlug,
    TydomAlarm,
    TydomWeather,
    TydomWater,
    TydomThermo,
    TydomSun,
    TydomDevice,
    TydomScene,
    TydomGroup,
    TydomMoment,
    TydomRemoteControl,
)
from .ha_entities import (
    HATydom,
    HACover,
    HAEnergy,
    HASmoke,
    HaClimate,
    HaWindow,
    HaDoor,
    HaWindowOpening,
    HaDoorOpening,
    HaGate,
    HaGarage,
    HaLight,
    HAInterrupterBattery,
    HAInterrupterEvent,
    HaAlarm,
    HaWeather,
    HaMoisture,
    HaThermo,
    HaSun,
    HAGenericBinarySensor,
    HASensor,
    HAScene,
    HATwcShutterCover,
    HASwitch,
    HAButton,
    HADeviceAssociationButton,
    HADeviceRemovalButton,
    HAGroupableProductFinalizeAssociationButton,
    HAGatewayAssociationCategorySelect,
    HAGatewayAssociationChannelSelect,
    HAGatewayAssociationGuideButton,
    HAGatewayAssociationNameText,
    HAGatewayAssociationProductSelect,
    HAGatewayAssociationUsageSelect,
    HAGatewayStartAssociationButton,
    HAAlarmAcknowledgeButton,
    HACancelBoostButton,
    HAAlarmPendingEventsSensor,
    HAReloadButton,
    HARefreshEnergyButton,
    HACoverGroup,
    HALightGroup,
    HASwitchGroup,
    HAMoment,
    HARemoteBattery,
    HARemoteEvent,
    is_binary_attribute,
    ASSOCIATION_COMMAND,
    IDENTIFY_COMMAND,
    supports_command,
)

from .const import DOMAIN, LOGGER, STRUCTURED_LOGGER, get_polling_interval_for_validity
from .official_association_tutorials import (
    get_association_illustration_layout,
    get_association_illustration_ids,
    get_official_association_tutorial,
    get_official_association_tutorial_id,
)
from .remote_registry_migration import migrate_legacy_remote_endpoint


@dataclass(frozen=True, slots=True)
class DiscoveryProfile:
    """One radio/product family accepted by the gateway install API."""

    label: str
    protocol: str
    type: str
    profile: str


@dataclass(frozen=True, slots=True)
class AssociationChoice:
    """A product-family choice shown under one user-facing category."""

    label: str
    profile_id: str | None
    required_gateway_names: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class GroupableAssociationChannel:
    """One independently-associated channel of an official product."""

    label: str
    config_name: str
    tutorial_id: str


@dataclass(frozen=True, slots=True)
class GroupableAssociationProduct:
    """Official post-discovery configuration for a multi-channel product."""

    label: str
    category: str
    usage: str
    usage_label: str
    tutorial_id: str
    group_picto: str
    endpoint_picto: str
    name_prefix: str
    gateway_refs: frozenset[str]
    channels: tuple[GroupableAssociationChannel, ...]
    guide: tuple[str, ...]
    illustration_step_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class StandaloneAssociationRecipe:
    """Configuration written for a newly discovered one-endpoint product.

    The gateway discovery request only opens the radio listening window.  On
    current TYDOM firmware it can leave the successfully paired endpoint as
    an untyped ``Produit N`` until the application writes its usage to
    ``/configs/file``.  These recipes represent that second, local step.
    """

    usage: str
    picto: str
    name_prefix: str
    first_usage: str | None = None
    widget_action: str | None = None


# These profiles are the request values used by the official TYDOM app. The
# gateway stays authoritative and accepts only values supported by its firmware.
DISCOVERY_PROFILES: dict[str, DiscoveryProfile] = {
    "alarm_x2d": DiscoveryProfile("TYXAL / alarm X2D", "X3D", "x2d_a", "alarm"),
    "alarm_x3d": DiscoveryProfile("TYXAL+ / alarm X3D", "X3D", "x3d_ppa", "alarm"),
    "aeraulic_zigbee": DiscoveryProfile("Aéraulique Zigbee", "ZIGBEE", "", "aeraulic"),
    "awning_x3d": DiscoveryProfile("Store banne X3D", "X3D", "x3d_rm", "awning"),
    "boiler_drive_x3d": DiscoveryProfile(
        "Chaudière Drive X3D", "X3D", "x3d_rm", "boilerDrive"
    ),
    "controller_x3d": DiscoveryProfile(
        "Contrôleur X3D", "X3D", "x3d_pps", "controller"
    ),
    "detector_x3d": DiscoveryProfile("Détecteur X3D", "X3D", "direct", "detector"),
    "electric_zigbee": DiscoveryProfile(
        "Équipement électrique Zigbee", "ZIGBEE", "", "electric"
    ),
    "light_x3d": DiscoveryProfile("Éclairage X3D", "X3D", "x3d_rm", "light"),
    "light_zigbee": DiscoveryProfile("Éclairage Zigbee", "ZIGBEE", "", "light"),
    "generic_x3d": DiscoveryProfile(
        "Produit générique X3D", "X3D", "x3d_pp", "generic"
    ),
    "meter_x3d": DiscoveryProfile("Compteur / mesure X3D", "X3D", "direct", "meter"),
    "multi_x3d": DiscoveryProfile(
        "Produit multifonction X3D", "X3D", "x3d_pped", "multi"
    ),
    "opening_x3d": DiscoveryProfile(
        "Ouvrant / porte / fenêtre X3D", "X3D", "x3d_rm", "opening"
    ),
    "pod_x3d": DiscoveryProfile("Produit POD X3D", "X3D", "x3d_rm", "pod"),
    "remote_x3d": DiscoveryProfile("Télécommande X3D", "X3D", "direct", "remote"),
    "rt2012_measure_x3d": DiscoveryProfile(
        "Mesure RT2012 X3D", "X3D", "x3d_pped", "rt2012_meas"
    ),
    "rt2012_no_outdoor_temp_x3d": DiscoveryProfile(
        "RT2012 sans sonde extérieure X3D", "X3D", "x3d_pped", "rt2012_noOutTemp"
    ),
    "rt2012_x3d": DiscoveryProfile("RT2012 X3D", "X3D", "x3d_pped", "rt2012"),
    "sensor_x3d": DiscoveryProfile("Capteur X3D", "X3D", "direct", "sensor"),
    "shared_thermic_x3d": DiscoveryProfile(
        "Chauffage partagé X3D", "X3D", "x3d_rmloop", "shThermic"
    ),
    "shutter_x3d": DiscoveryProfile("Volet roulant X3D", "X3D", "x3d_rm", "shutter"),
    "shutter_activhome_x3d": DiscoveryProfile(
        "Volet Activ'Home X3D", "X3D", "x3d_rm", "shutterActivHome"
    ),
    "shutter_brushless_x3d": DiscoveryProfile(
        "Volet Brushless X3D", "X3D", "x3d_rm", "shutterBrushless"
    ),
    "shutter_projected_x3d": DiscoveryProfile(
        "Volet projeté X3D", "X3D", "x3d_rm", "shutterProjected"
    ),
    "shutter_profalux_zigbee": DiscoveryProfile(
        "Volet Profalux Zigbee", "ZIGBEE", "PROFALUX", "shutter"
    ),
    "shutter_rmlp_x3d": DiscoveryProfile(
        "Volet RMLP X3D", "X3D", "x3d_rmlp", "shutter"
    ),
    "shutter_stella_zigbee": DiscoveryProfile(
        "Volet Stella Zigbee", "ZIGBEE", "", "shutter"
    ),
    "shutter_zigbee": DiscoveryProfile("Volet roulant Zigbee", "ZIGBEE", "", "shutter"),
    "temperature_x3d": DiscoveryProfile(
        "Sonde de température X3D", "X3D", "direct", "temperature"
    ),
    "thermic_x3d": DiscoveryProfile("Chauffage X3D", "X3D", "x3d_rm", "thermic"),
    "thermic_x2d": DiscoveryProfile("Chauffage X2D", "X3D", "x2d_d", "thermic"),
    "thermic_x3d_es": DiscoveryProfile(
        "Chauffage X3D (émetteur spécifique)", "X3D", "x3d_rm", "thermicES"
    ),
    "thermic_zigbee": DiscoveryProfile("Chauffage Zigbee", "ZIGBEE", "", "thermic"),
    "typass_atl_x3d": DiscoveryProfile("TYPASS ATL X3D", "X3D", "direct", "typassAtl"),
    "typass_saunier_x3d": DiscoveryProfile(
        "TYPASS Saunier X3D", "X3D", "direct", "typassSaunier"
    ),
    "weather_plt": DiscoveryProfile("Station météo", "PltService", "", "weather"),
}


# The official application first asks for a usage, then a product family. Keep
# its initial list of groups intact. A recipe may occur in several categories.
ASSOCIATION_CATALOG: dict[str, tuple[AssociationChoice, ...]] = {
    "Volets": (
        AssociationChoice("Récepteur volet roulant X3D", "shutter_x3d"),
        AssociationChoice("Volet Activ'Home", "shutter_activhome_x3d"),
        AssociationChoice("Volet Brushless", "shutter_brushless_x3d"),
        AssociationChoice("Volet projeté", "shutter_projected_x3d"),
        AssociationChoice("Volet Profalux Zigbee", "shutter_profalux_zigbee"),
        AssociationChoice("Volet Stella Zigbee", "shutter_stella_zigbee"),
        AssociationChoice("Volet roulant Zigbee", "shutter_zigbee"),
    ),
    "Éclairages": (
        AssociationChoice("Récepteur éclairage X3D", "light_x3d"),
        AssociationChoice("Éclairage Zigbee", "light_zigbee"),
    ),
    "Thermique": (
        AssociationChoice("Récepteur chauffage X3D", "thermic_x3d"),
        AssociationChoice("Récepteur chauffage X2D", "thermic_x2d"),
        AssociationChoice("Émetteur chauffage X3D spécifique", "thermic_x3d_es"),
        AssociationChoice("Chaudière Drive", "boiler_drive_x3d"),
        AssociationChoice("Chauffage Zigbee", "thermic_zigbee"),
        AssociationChoice("Chauffage partagé X3D", "shared_thermic_x3d"),
        AssociationChoice("TYPASS ATL", "typass_atl_x3d"),
        AssociationChoice("TYPASS Saunier", "typass_saunier_x3d"),
        AssociationChoice("Aéraulique Zigbee", "aeraulic_zigbee"),
    ),
    "Garage": (
        AssociationChoice("Récepteur portail / garage X3D", "light_x3d"),
        AssociationChoice("Récepteur volet / garage X3D", "shutter_x3d"),
        AssociationChoice("Volet Profalux Zigbee", "shutter_profalux_zigbee"),
    ),
    "Portail": (
        AssociationChoice("Récepteur portail X3D", "light_x3d"),
        AssociationChoice("Produit générique X3D", "generic_x3d"),
    ),
    "Alarme": (
        AssociationChoice("TYXAL / alarme X2D", "alarm_x2d"),
        AssociationChoice("TYXAL+ / alarme X3D", "alarm_x3d"),
        AssociationChoice("Détecteur X3D", "detector_x3d"),
        AssociationChoice("Télécommande / clavier X3D", "remote_x3d"),
    ),
    "Caméras": (AssociationChoice("Aucun profil local documenté", None),),
    "Consommation": (
        AssociationChoice("Compteur ou mesure X3D", "meter_x3d"),
        AssociationChoice("RT2012", "rt2012_x3d"),
        AssociationChoice("RT2012 sans sonde extérieure", "rt2012_no_outdoor_temp_x3d"),
        AssociationChoice("Mesure RT2012", "rt2012_measure_x3d"),
    ),
    "Porte": (
        AssociationChoice("Ouvrant, porte ou fenêtre X3D", "opening_x3d"),
        AssociationChoice("Produit POD X3D", "pod_x3d"),
    ),
    "Fenêtres": (
        AssociationChoice("Ouvrant, porte ou fenêtre X3D", "opening_x3d"),
        AssociationChoice("Produit POD X3D", "pod_x3d"),
    ),
    "Stores": (
        AssociationChoice("Store banne X3D", "awning_x3d"),
        AssociationChoice("Store projeté X3D", "shutter_projected_x3d"),
    ),
    "Prise": (
        AssociationChoice("Prise / équipement électrique Zigbee", "electric_zigbee"),
        AssociationChoice("Récepteur prise X3D", "light_x3d"),
    ),
    "Autres": (
        AssociationChoice("Produit générique X3D", "generic_x3d"),
        AssociationChoice("Produit multifonction X3D", "multi_x3d"),
        AssociationChoice("Produit POD X3D", "pod_x3d"),
        AssociationChoice("Station météo", "weather_plt"),
    ),
    "Télécommandes et claviers": (
        AssociationChoice("Télécommande X3D", "remote_x3d"),
        AssociationChoice("Contrôleur X3D", "controller_x3d"),
    ),
    "Interrupteurs": (
        AssociationChoice("Interrupteur / récepteur éclairage X3D", "light_x3d"),
        AssociationChoice("Éclairage Zigbee", "light_zigbee"),
        AssociationChoice("Contrôleur X3D", "controller_x3d"),
    ),
    "Capteurs": (
        AssociationChoice("Capteur X3D", "sensor_x3d"),
        AssociationChoice("Détecteur X3D", "detector_x3d"),
        AssociationChoice("Sonde de température X3D", "temperature_x3d"),
        AssociationChoice("Station météo", "weather_plt"),
    ),
}

# Official product-to-discovery mappings are kept separately from the
# generic fallback recipes above. They are generated from the product catalog
# bundled with the official TYDOM application, but only the small, declarative
# association facts are versioned here (never the APK itself).
OFFICIAL_DISCOVERY_PROFILES: dict[str, DiscoveryProfile] = {
    "official:aeraulic_ZIGBEE": DiscoveryProfile(
        "aeraulic_ZIGBEE", "ZIGBEE", "", "aeraulic"
    ),
    "official:alarm_X3D_x2d_a": DiscoveryProfile(
        "alarm_X3D_x2d_a", "X3D", "x2d_a", "alarm"
    ),
    "official:alarm_X3D_x3d_ppa": DiscoveryProfile(
        "alarm_X3D_x3d_ppa", "X3D", "x3d_ppa", "alarm"
    ),
    "official:awning_X3D_x3d_rm": DiscoveryProfile(
        "awning_X3D_x3d_rm", "X3D", "x3d_rm", "awning"
    ),
    "official:detector_X3D_direct": DiscoveryProfile(
        "detector_X3D_direct", "X3D", "direct", "detector"
    ),
    "official:electric_ZIGBEE": DiscoveryProfile(
        "electric_ZIGBEE", "ZIGBEE", "", "electric"
    ),
    "official:generic_X3D_x3d_pp": DiscoveryProfile(
        "generic_X3D_x3d_pp", "X3D", "x3d_pp", "generic"
    ),
    "official:light_X3D_x3d_rm": DiscoveryProfile(
        "light_X3D_x3d_rm", "X3D", "x3d_rm", "light"
    ),
    "official:light_ZIGBEE": DiscoveryProfile("light_ZIGBEE", "ZIGBEE", "", "light"),
    "official:meter_X3D_direct": DiscoveryProfile(
        "meter_X3D_direct", "X3D", "direct", "meter"
    ),
    "official:multi_X3D_x3d_pped": DiscoveryProfile(
        "multi_X3D_x3d_pped", "X3D", "x3d_pped", "multi"
    ),
    "official:opening_x3d_x3d_rm": DiscoveryProfile(
        "opening_x3d_x3d_rm", "X3D", "x3d_rm", "opening"
    ),
    "official:pod_X3D_x3d_rm": DiscoveryProfile(
        "pod_X3D_x3d_rm", "X3D", "x3d_rm", "pod"
    ),
    "official:remote_X3D_direct": DiscoveryProfile(
        "remote_X3D_direct", "X3D", "direct", "remote"
    ),
    "official:rt2012_meas_X3D_x3d_pped": DiscoveryProfile(
        "rt2012_meas_X3D_x3d_pped", "X3D", "x3d_pped", "rt2012_meas"
    ),
    "official:rt2012_noOutTemp_X3D_x3d_pped": DiscoveryProfile(
        "rt2012_noOutTemp_X3D_x3d_pped", "X3D", "x3d_pped", "rt2012_noOutTemp"
    ),
    "official:rt2012_X3D_x3d_pped": DiscoveryProfile(
        "rt2012_X3D_x3d_pped", "X3D", "x3d_pped", "rt2012"
    ),
    "official:sensor_X3D_direct": DiscoveryProfile(
        "sensor_X3D_direct", "X3D", "direct", "sensor"
    ),
    "official:shThermic_X3D_x3d_rmloop": DiscoveryProfile(
        "shThermic_X3D_x3d_rmloop", "X3D", "x3d_rmloop", "shThermic"
    ),
    "official:shutter_X3D_x3d_rm": DiscoveryProfile(
        "shutter_X3D_x3d_rm", "X3D", "x3d_rm", "shutter"
    ),
    "official:shutter_X3D_x3d_rmlp": DiscoveryProfile(
        "shutter_X3D_x3d_rmlp", "X3D", "x3d_rmlp", "shutter"
    ),
    "official:shutter_ZIGBEE": DiscoveryProfile(
        "shutter_ZIGBEE", "ZIGBEE", "", "shutter"
    ),
    "official:shutter_ZIGBEE_PROFALUX": DiscoveryProfile(
        "shutter_ZIGBEE_PROFALUX", "ZIGBEE", "PROFALUX", "shutter"
    ),
    "official:shutter_ZIGBEE_STELLA": DiscoveryProfile(
        "shutter_ZIGBEE_STELLA", "ZIGBEE", "", "shutter"
    ),
    "official:shutterActivHome_X3D_x3d_rm": DiscoveryProfile(
        "shutterActivHome_X3D_x3d_rm", "X3D", "x3d_rm", "shutterActivHome"
    ),
    "official:shutterBrushless_X3D_x3d_rm": DiscoveryProfile(
        "shutterBrushless_X3D_x3d_rm", "X3D", "x3d_rm", "shutterBrushless"
    ),
    "official:shutterProjected_X3D_x3d_rm": DiscoveryProfile(
        "shutterProjected_X3D_x3d_rm", "X3D", "x3d_rm", "shutterProjected"
    ),
    "official:temperature_X3D_direct": DiscoveryProfile(
        "temperature_X3D_direct", "X3D", "direct", "temperature"
    ),
    "official:thermic_X3D_x2d_d": DiscoveryProfile(
        "thermic_X3D_x2d_d", "X3D", "x2d_d", "thermic"
    ),
    "official:thermic_X3D_x3d_pps": DiscoveryProfile(
        "thermic_X3D_x3d_pps", "X3D", "x3d_pps", "controller"
    ),
    "official:thermic_X3D_x3d_rm": DiscoveryProfile(
        "thermic_X3D_x3d_rm", "X3D", "x3d_rm", "thermic"
    ),
    "official:thermic_X3D_x3d_rm_drive": DiscoveryProfile(
        "thermic_X3D_x3d_rm_drive", "X3D", "x3d_rm", "boilerDrive"
    ),
    "official:thermic_X3D_x3d_rm_es": DiscoveryProfile(
        "thermic_X3D_x3d_rm_es", "X3D", "x3d_rm", "thermicES"
    ),
    "official:thermic_ZIGBEE": DiscoveryProfile(
        "thermic_ZIGBEE", "ZIGBEE", "", "thermic"
    ),
    "official:typassATL_X3D_direct": DiscoveryProfile(
        "typassATL_X3D_direct", "X3D", "direct", "typassAtl"
    ),
    "official:typassSaunier_X3D_direct": DiscoveryProfile(
        "typassSaunier_X3D_direct", "X3D", "direct", "typassSaunier"
    ),
    "official:weather_plt": DiscoveryProfile(
        "weather_plt", "PltService", "", "weather"
    ),
}


# The TYXIA 2600 is not a generic radio product: its two physical buttons are
# associated independently. The setup starts on the chosen channel. Per the
# product instructions, A cycles the input modes and B validates that choice.
TYXIA_2600_ASSOCIATION_GUIDE = (
    "Parcours Home Assistant — ajout du TYXIA 2600 comme interrupteur :",
    "1. Dans Home Assistant, choisissez d'abord la voie à associer : {channel}.",
    "   Le module peut n'avoir qu'une seule voie raccordée : n'ajoutez que les voies réellement utilisées.",
    "2. Maintenez le bouton {button} physique pendant 6 secondes. Le voyant rouge "
    "s'allume, s'éteint, puis reste fixe : relâchez alors le bouton.",
    "3. Le voyant vert clignote par séries. Appuyez brièvement sur A pour faire défiler "
    "les modes, puis conservez celui correspondant au type d'interrupteur raccordé.",
    "4. Maintenez B pendant 3 secondes, jusqu'à l'allumage fixe du voyant vert, "
    "pour valider le mode sélectionné.",
    "5. Cliquez maintenant sur « Lancer l'écoute de la passerelle » ci-dessous, "
    "avant de poursuivre avec le TYXIA 2600.",
    "6. Maintenez le bouton {button} physique pendant 3 secondes, jusqu'à ce que le "
    "voyant rouge clignote.",
    "7. Attendez que Home Assistant détecte le nouveau produit.",
    "8. Pour confirmer la voie {button} ({channel}), appuyez sur l'interrupteur "
    "physique qui lui est relié. Ce n'est pas un nouvel appui sur le bouton du "
    "module TYXIA.",
)


# These are the six active ``groupable`` products in the official TYDOM 4.20
# catalogue.  A radio discovery alone is deliberately not enough for them:
# each discovered channel must be written to /configs/file and linked through
# a related-endpoints group in /groups/file.  The guide texts are transcribed
# from the French tutorial resources embedded in the official application.
MODERN_TYDOM_GATEWAY_REFS = frozenset({"25170010", "24930010", "24900010", "27170010"})

GROUPABLE_ASSOCIATION_PRODUCTS: tuple[GroupableAssociationProduct, ...] = (
    GroupableAssociationProduct(
        label="TL 2000",
        category="Télécommandes et claviers",
        usage="remoteControl",
        usage_label="télécommande",
        tutorial_id="tl2000",
        group_picto="picto_remote_control",
        endpoint_picto="default_device",
        name_prefix="Télécommande",
        gateway_refs=MODERN_TYDOM_GATEWAY_REFS,
        channels=(
            GroupableAssociationChannel(
                "Bouton 1", "CG_DD_COMMON_BUTTON1", "tl2000_btn_1"
            ),
            GroupableAssociationChannel(
                "Bouton 2", "CG_DD_COMMON_BUTTON2", "tl2000_btn_2"
            ),
        ),
        guide=(
            "1. Vérifiez au dos de la télécommande la présence du logo « Works with Tydom » : une version TL 2000 sans ce logo existe et ne peut pas être associée. Dans Home Assistant, sélectionnez ensuite la voie à associer : {channel}.",
            "2. Maintenez simultanément 1 et 2 pendant 5 secondes, jusqu'au voyant orange.",
            "3. Appuyez une fois sur {button}. Continuez lorsque le voyant clignote par séries de 4 ; un nouvel appui sur {button} change ce nombre.",
            "4. Si le voyant clignote encore, appuyez sur ON pour qu'il devienne vert.",
            "5. Cliquez maintenant sur « Lancer l'écoute de la passerelle » ci-dessous.",
            "6. Pendant que l'écoute est active, maintenez simultanément ON et {button} pendant 5 secondes, jusqu'au voyant rouge.",
            "7. Attendez que Home Assistant détecte la télécommande, puis appuyez sur {button} pour confirmer la voie sélectionnée.",
        ),
        # Verified against catalog_rcu_tl2000_btn1_step1..6 from the APK:
        # the first visual is the compatibility mark; the gateway-listening
        # instruction intentionally has no physical illustration.
        illustration_step_indexes=(0, 1, 2, 3, 5, 6),
    ),
    GroupableAssociationProduct(
        label="TYXIA 1410",
        category="Télécommandes et claviers",
        usage="remoteControl",
        usage_label="télécommande",
        tutorial_id="rcu_tyxia1410",
        group_picto="picto_remote_control",
        endpoint_picto="default_device",
        name_prefix="Télécommande",
        gateway_refs=MODERN_TYDOM_GATEWAY_REFS,
        channels=(
            GroupableAssociationChannel(
                "Bouton 1", "CG_DD_COMMON_BUTTON1", "rcu_tyxia1410_btn_1"
            ),
            GroupableAssociationChannel(
                "Bouton 2", "CG_DD_COMMON_BUTTON2", "rcu_tyxia1410_btn_2"
            ),
            GroupableAssociationChannel(
                "Bouton 3", "CG_DD_COMMON_BUTTON3", "rcu_tyxia1410_btn_3"
            ),
            GroupableAssociationChannel(
                "Bouton 4", "CG_DD_COMMON_BUTTON4", "rcu_tyxia1410_btn_4"
            ),
        ),
        guide=(
            "1. Vérifiez au dos de la télécommande la présence du logo « Works with Tydom » : une version TYXIA 1410 sans ce logo existe et ne peut pas être associée. Dans Home Assistant, sélectionnez ensuite la voie à associer : {channel}.",
            "2. Cliquez maintenant sur « Lancer l'écoute de la passerelle » ci-dessous. La passerelle est alors prête à recevoir la télécommande.",
            "3. Pendant que l'écoute est active, maintenez le {button} de la télécommande pendant 5 secondes, jusqu'à ce que le voyant rouge clignote. Relâchez-le.",
            "4. Attendez la détection dans Home Assistant. Il n'y a pas de confirmation à attendre dans l'application TYDOM ni de second appui à effectuer.",
        ),
        # Verified against catalog_rcu_tyxia1410_btn1_step1..3 from the APK:
        # compatibility mark, 5-second press, then channel confirmation.
        illustration_step_indexes=(0, 2, 3),
    ),
    GroupableAssociationProduct(
        label="CLE 8000",
        category="Télécommandes et claviers",
        usage="remoteControl",
        usage_label="clavier",
        tutorial_id="cle8000",
        group_picto="picto_remote_control",
        endpoint_picto="default_device",
        name_prefix="Clavier",
        gateway_refs=MODERN_TYDOM_GATEWAY_REFS,
        channels=(
            GroupableAssociationChannel(
                "Touche A", "CG_DD_COMMON_KEYA", "cle8000_btn_1"
            ),
            GroupableAssociationChannel(
                "Touche B", "CG_DD_COMMON_KEYB", "cle8000_btn_2"
            ),
        ),
        guide=(
            "1. Dans Home Assistant, sélectionnez la touche à associer : {channel}.",
            "2. Maintenez la touche 2 jusqu'au clignotement vert par séries de 1. La touche 5 change le nombre de clignotements.",
            "3. Cliquez maintenant sur « Lancer l'écoute de la passerelle » ci-dessous.",
            "4. Pendant que l'écoute est active, appuyez sur {button} pour lancer l'association. Si le voyant s'est éteint, recommencez l'étape 2 puis validez avec {button}.",
            "5. Saisissez le code du clavier, puis appuyez sur {button} pour confirmer l'association.",
        ),
        illustration_step_indexes=(1, 1, 2, 3, 4),
    ),
    GroupableAssociationProduct(
        label="TYXIA 2310",
        category="Interrupteurs",
        usage="interrupter",
        usage_label="interrupteur",
        tutorial_id="switch_tyxia2310",
        group_picto="picto_interrupter",
        endpoint_picto="picto_interrupter",
        name_prefix="Interrupteur",
        gateway_refs=MODERN_TYDOM_GATEWAY_REFS,
        channels=(
            GroupableAssociationChannel(
                "Bouton 1", "CG_DD_COMMON_BUTTON1", "switch_tyxia2310_btn_1"
            ),
            GroupableAssociationChannel(
                "Bouton 2", "CG_DD_COMMON_BUTTON2", "switch_tyxia2310_btn_2"
            ),
        ),
        guide=(
            "1. Dans Home Assistant, sélectionnez le bouton à associer : {channel}.",
            "2. Appuyez une fois sur T2, au dos de l'interrupteur. Continuez lorsque le voyant frontal clignote par séries de 1 ; T2 change ce nombre.",
            "3. Cliquez maintenant sur « Lancer l'écoute de la passerelle » ci-dessous.",
            "4. Pendant que l'écoute est active, maintenez {button} pendant 3 secondes, jusqu'à l'allumage du voyant.",
            "5. Attendez que Home Assistant détecte l'interrupteur, puis appuyez sur {button} pour confirmer le bouton sélectionné.",
        ),
        illustration_step_indexes=(1, 3, 4),
    ),
    GroupableAssociationProduct(
        label="TYXIA 2600",
        category="Interrupteurs",
        usage="interrupter",
        usage_label="interrupteur",
        tutorial_id="switch_tyxia2600",
        group_picto="picto_interrupter",
        endpoint_picto="picto_interrupter",
        name_prefix="Interrupteur",
        gateway_refs=MODERN_TYDOM_GATEWAY_REFS,
        channels=(
            GroupableAssociationChannel(
                "Bouton A", "CG_DD_COMMON_BUTTONA", "switch_tyxia2600_btn_a"
            ),
            GroupableAssociationChannel(
                "Bouton B", "CG_DD_COMMON_BUTTONB", "switch_tyxia2600_btn_b"
            ),
        ),
        guide=TYXIA_2600_ASSOCIATION_GUIDE,
        illustration_step_indexes=(1, 2, 3, 5, 7),
    ),
    GroupableAssociationProduct(
        label="TYXIA 2700",
        category="Interrupteurs",
        usage="interrupter",
        usage_label="interrupteur",
        tutorial_id="switch_tyxia2700",
        group_picto="picto_interrupter",
        endpoint_picto="picto_interrupter",
        name_prefix="Interrupteur",
        gateway_refs=MODERN_TYDOM_GATEWAY_REFS,
        channels=(
            GroupableAssociationChannel(
                "Voie 1", "CG_DD_COMMON_CHANNEL1", "switch_tyxia2700_btn_a"
            ),
            GroupableAssociationChannel(
                "Voie 2", "CG_DD_COMMON_CHANNEL2", "switch_tyxia2700_btn_b"
            ),
        ),
        guide=(
            "1. Tournez le sélecteur sur le mode 1.",
            "2. Sélectionnez {channel} avec le sélecteur.",
            "3. Cliquez maintenant sur « Lancer l'écoute de la passerelle » ci-dessous.",
            "4. Pendant que l'écoute est active, appuyez brièvement sur le bouton : le voyant clignote une fois, puis replacez le sélecteur sur « Auto ».",
            "5. Attendez que Home Assistant détecte le produit, puis appuyez sur l'interrupteur relié à {channel_lower} pour confirmer l'association.",
        ),
        illustration_step_indexes=(0, 1, 1, 3, 4),
    ),
)

GROUPABLE_ASSOCIATION_BY_LABEL = {
    product.label: product for product in GROUPABLE_ASSOCIATION_PRODUCTS
}

OFFICIAL_ASSOCIATION_CATALOG: dict[str, tuple[AssociationChoice, ...]] = {
    "Volets": (
        AssociationChoice("ACTIVE HOME KLINE", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("BRISE SOLEIL WELLCOM", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("BRISE SOLEIL ZIGBEE", "official:shutter_ZIGBEE_PROFALUX"),
        AssociationChoice("BSO KLINE", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("KLINE TYMOOV SOLAR", "official:shutter_X3D_x3d_rmlp"),
        AssociationChoice("PROFALUX BRANDS", "official:shutter_ZIGBEE_PROFALUX"),
        AssociationChoice("PROFALUX STELLA SHUTTER", "official:shutter_ZIGBEE_STELLA"),
        AssociationChoice("ROLLIA RADIO", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("SHUTTER TYMOOV SOLAR", "official:shutter_X3D_x3d_rmlp"),
        AssociationChoice("STORE VERTICAL ZIGBEE", "official:shutter_ZIGBEE_PROFALUX"),
        AssociationChoice("TYMOOV RADIO", "official:shutterBrushless_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4630", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4730", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4731", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("TYXIA 5630", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("TYXIA 5730", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("TYXIA 5731", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("VLO BUBENDORFF SHUTTER", "official:shutter_ZIGBEE"),
        AssociationChoice("VOLET BATTANT WELLCOM", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("VOLET KLINE", "official:shutter_X3D_x3d_rm"),
        AssociationChoice(
            "VOLET PROJECTION WELLCOM", "official:shutterProjected_X3D_x3d_rm"
        ),
        AssociationChoice("VOLET ROULANT WELLCOM", "official:shutter_X3D_x3d_rm"),
        AssociationChoice(
            "VOLET ROULANT WELLCOM SOLAR", "official:shutter_X3D_x3d_rmlp"
        ),
        AssociationChoice("VOLET ROULANT ZIGBEE", "official:shutter_ZIGBEE_PROFALUX"),
        AssociationChoice("VR BUBENDORFF SHUTTER", "official:shutter_ZIGBEE"),
    ),
    "Éclairages": (
        AssociationChoice("BULB DELTA DORE", "official:light_ZIGBEE"),
        AssociationChoice("BULB GENERIQUE", "official:light_ZIGBEE"),
        AssociationChoice("TYXIA 4600", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4610", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4801", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4811", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4840", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4850", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4860", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4910", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4940", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 5610", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 5612", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 5640", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 5650", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 6410", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 6610", "official:light_X3D_x3d_rm"),
    ),
    "Thermique": (
        AssociationChoice("ALLAUVE KONECT", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("ATLANTIC", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("CALYBOX 1020 WT", "official:rt2012_noOutTemp_X3D_x3d_pped"),
        AssociationChoice("CALYBOX 2020 WT", "official:rt2012_X3D_x3d_pped"),
        AssociationChoice("CALYBOX 210", "official:thermic_X3D_x2d_d"),
        AssociationChoice("CALYBOX 220", "official:thermic_X3D_x2d_d"),
        AssociationChoice("CALYBOX 220 WT", "official:thermic_X3D_x2d_d"),
        AssociationChoice("CALYBOX 230", "official:thermic_X3D_x2d_d"),
        AssociationChoice("CALYBOX 230 WT", "official:thermic_X3D_x2d_d"),
        AssociationChoice("CALYBOX 320", "official:thermic_X3D_x2d_d"),
        AssociationChoice("CALYBOX 320 WT", "official:thermic_X3D_x2d_d"),
        AssociationChoice("CALYBOX 330", "official:thermic_X3D_x2d_d"),
        AssociationChoice("CALYBOX 420", "official:thermic_X3D_x2d_d"),
        AssociationChoice("CALYBOX 430", "official:thermic_X3D_x2d_d"),
        AssociationChoice("DELTA 8000", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("HITACHI ATW", "official:thermic_X3D_x3d_rm_es"),
        AssociationChoice("HOMEPILOTE PURE", "official:thermic_X3D_x3d_rm_es"),
        AssociationChoice("MINOR 1000", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("MULTIZONE KIT", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("NAVILINK PAC", "official:thermic_ZIGBEE"),
        AssociationChoice("NAVILINK PAC BOILER", "official:thermic_ZIGBEE"),
        AssociationChoice("NSC RF ELM Leblanc", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("PARTNER HVAC", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("RADIO TYBOX 810 (RF 640)", "official:thermic_X3D_x2d_d"),
        AssociationChoice("RADIO TYBOX 811 (RF 640)", "official:thermic_X3D_x2d_d"),
        AssociationChoice("RF 4890", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("RF 6050+", "official:thermic_X3D_x3d_rm_es"),
        AssociationChoice("RF 6600 FP", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("RF 6620", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("RF 6630", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("RF 6640", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("RF 6650", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("RF 6700 FP", "official:thermic_X3D_x3d_rm_es"),
        AssociationChoice("RF 7110", "official:thermic_X3D_x3d_rm_es"),
        AssociationChoice("RF 7130", "official:thermic_X3D_x3d_rm_es"),
        AssociationChoice("RF 7210", "official:thermic_X3D_x3d_rm_es"),
        AssociationChoice("SPLIT TAKAO", "official:aeraulic_ZIGBEE"),
        AssociationChoice("TA 5555 ZIGBEE DD", "official:electric_ZIGBEE"),
        AssociationChoice("TA 5555 ZIGBEE OTHERS", "official:electric_ZIGBEE"),
        AssociationChoice("THERMOSTAT ATLANTIC", "official:temperature_X3D_direct"),
        AssociationChoice("THERMOSTAT DELTA 8000", "official:temperature_X3D_direct"),
        AssociationChoice(
            "THERMOSTAT MULTIZONE KIT", "official:temperature_X3D_direct"
        ),
        AssociationChoice("TRV 1.0", "official:shThermic_X3D_x3d_rmloop"),
        AssociationChoice("TRV 2", "official:thermic_ZIGBEE"),
        AssociationChoice("TYBOX 1010 WT", "official:rt2012_noOutTemp_X3D_x3d_pped"),
        AssociationChoice("TYBOX 1137 (RF6000+)", "official:thermic_X3D_x3d_rm_es"),
        AssociationChoice("TYBOX 137 (RF 640)", "official:thermic_X3D_x2d_d"),
        AssociationChoice("TYBOX 137+ (RF6000+)", "official:thermic_X3D_x3d_rm_es"),
        AssociationChoice("TYBOX 2010 WT", "official:rt2012_X3D_x3d_pped"),
        AssociationChoice("TYBOX 2300 (RF 6000+)", "official:thermic_X3D_x3d_rm_es"),
        AssociationChoice("TYBOX 237 (RF 640)", "official:thermic_X3D_x2d_d"),
        AssociationChoice("TYBOX 337 (RF 640)", "official:thermic_X3D_x2d_d"),
        AssociationChoice("TYBOX 4100", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("TYBOX 4110", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("TYBOX 4150", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("TYBOX 4210", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("TYBOX 4250", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("TYBOX 5000", "official:multi_X3D_x3d_pped"),
        AssociationChoice("TYBOX 5100 (RF 6000)", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("TYBOX 5150 (RF 6200)", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("TYBOX 5200 (RF 6050)", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("TYBOX 5300 (RF 6050+)", "official:thermic_X3D_x3d_rm_es"),
        AssociationChoice(
            "TYBOX 5701 FP (RF 6700 FP)", "official:thermic_X3D_x3d_rm_es"
        ),
        AssociationChoice(
            "TYBOX 5702 FP (2 x RF 6700 FP)", "official:thermic_X3D_x3d_rm_es"
        ),
        AssociationChoice(
            "TYBOX HOME RF 210 (RF 7210)", "official:thermic_X3D_x3d_rm_es"
        ),
        AssociationChoice("TYBOX RF 110 (RF 7110)", "official:thermic_X3D_x3d_rm_es"),
        AssociationChoice("TYBOX RF 130 (RF 7130)", "official:thermic_X3D_x3d_rm_es"),
        AssociationChoice("TYBOX RF 210 (RF 7210)", "official:thermic_X3D_x3d_rm_es"),
        AssociationChoice(
            "TYBOX RF 210 XL (RF 7210)", "official:thermic_X3D_x3d_rm_es"
        ),
        AssociationChoice("TYPASS ATL", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("TYPASS CHX", "official:thermic_X3D_x3d_rm"),
        AssociationChoice("TYPASS SD", "official:thermic_X3D_x3d_rm"),
        AssociationChoice(
            "Tywell Control",
            "official:thermic_X3D_x3d_pps",
            required_gateway_names=frozenset({"tywell pro", "tywell home"}),
        ),
        AssociationChoice("Tywell 2050 (RF 6050+)", "official:thermic_X3D_x3d_rm_es"),
        AssociationChoice("Tywell 2050 L (RF 6050+)", "official:thermic_X3D_x3d_rm_es"),
    ),
    "Garage": (
        AssociationChoice("GARAGE HORIZONTAL WELLCOM", "official:light_X3D_x3d_rm"),
        AssociationChoice("GARAGE VERTICAL WELLCOM", "official:light_X3D_x3d_rm"),
        AssociationChoice("HORMANN SupraMatic", "official:light_X3D_x3d_rm"),
        AssociationChoice("NOVOFERM Novomatic 423", "official:light_X3D_x3d_rm"),
        AssociationChoice("NOVOFERM Novomatic 563", "official:light_X3D_x3d_rm"),
        AssociationChoice("NOVOFERM Novoport", "official:light_X3D_x3d_rm"),
        AssociationChoice("ROLLIA RADIO", "official:shutter_X3D_x3d_rm"),
        AssociationChoice(
            "SOMMER ROLLER DOOR CONTROL UNIT", "official:light_X3D_x3d_rm"
        ),
        AssociationChoice("SOMMER S 90XX HORIZONTAL", "official:light_X3D_x3d_rm"),
        AssociationChoice("SOMMER S 90XX VERTICAL", "official:light_X3D_x3d_rm"),
        AssociationChoice("TUBAUTO Procom 10-3", "official:light_X3D_x3d_rm"),
        AssociationChoice("TUBAUTO Procom 10-4", "official:light_X3D_x3d_rm"),
        AssociationChoice("TUBAUTO Procom 20-3", "official:light_X3D_x3d_rm"),
        AssociationChoice("TUBAUTO Procom 20-4", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYMOOV RADIO", "official:shutterBrushless_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4620", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4630", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4730", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("TYXIA 5630", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("TYXIA 5730", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("TYXIA 6410", "official:light_X3D_x3d_rm"),
        AssociationChoice(
            "WELLCOM ROLLER DOOR CONTROL UNIT", "official:light_X3D_x3d_rm"
        ),
        AssociationChoice("WELLCOM S 90XX HORIZONTAL", "official:light_X3D_x3d_rm"),
        AssociationChoice("WELLCOM S 90XX VERTICAL", "official:light_X3D_x3d_rm"),
    ),
    "Portail": (
        AssociationChoice("SOMMER STARTER S 2 COULISSANT", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4620", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 6410", "official:light_X3D_x3d_rm"),
    ),
    "Alarme": (
        AssociationChoice("CSTX 50", "official:alarm_X3D_x2d_a"),
        AssociationChoice("CSX 20", "official:alarm_X3D_x2d_a"),
        AssociationChoice("CSX 40", "official:alarm_X3D_x2d_a"),
        AssociationChoice("CTX 60", "official:alarm_X3D_x2d_a"),
        AssociationChoice("DELTAL 2.00", "official:alarm_X3D_x2d_a"),
        AssociationChoice("DELTAL 2.10", "official:alarm_X3D_x2d_a"),
        AssociationChoice("DELTAL 2.15", "official:alarm_X3D_x2d_a"),
        AssociationChoice("DELTAL 2.50", "official:alarm_X3D_x2d_a"),
        AssociationChoice("DELTAL 3.00", "official:alarm_X3D_x2d_a"),
        AssociationChoice("DELTAL 4.00", "official:alarm_X3D_x2d_a"),
        AssociationChoice("DELTAL 4.50", "official:alarm_X3D_x2d_a"),
        AssociationChoice("DELTAL 7.00", "official:alarm_X3D_x2d_a"),
        AssociationChoice("EVOLOGY 2 ZONES", "official:alarm_X3D_x2d_a"),
        AssociationChoice("EVOLOGY 4 ZONES", "official:alarm_X3D_x2d_a"),
        AssociationChoice("HUB ALARM", "official:alarm_X3D_x3d_ppa"),
        AssociationChoice("KIT EVOLUTYX 26", "official:alarm_X3D_x2d_a"),
        AssociationChoice("KIT HABITAT 10", "official:alarm_X3D_x2d_a"),
        AssociationChoice("KIT HABITAT 20", "official:alarm_X3D_x2d_a"),
        AssociationChoice("KIT TYXAL 20", "official:alarm_X3D_x2d_a"),
        AssociationChoice("KIT TYXAL 30", "official:alarm_X3D_x2d_a"),
        AssociationChoice("KIT TYXAL 5", "official:alarm_X3D_x2d_a"),
        AssociationChoice("KIT TYXAL 50", "official:alarm_X3D_x2d_a"),
        AssociationChoice("KIT TYXAL 51", "official:alarm_X3D_x2d_a"),
        AssociationChoice("KIT TYXAL 70", "official:alarm_X3D_x2d_a"),
        AssociationChoice("KIT TYXAL 71", "official:alarm_X3D_x2d_a"),
        AssociationChoice("PACK TYXAL APPARTEMENT", "official:alarm_X3D_x2d_a"),
        AssociationChoice("PACK TYXAL MAISON", "official:alarm_X3D_x2d_a"),
        AssociationChoice("PACK TYXAL MAISON ANIMAUX", "official:alarm_X3D_x2d_a"),
        AssociationChoice("TYXAL PLUS PACK CS 8000", "official:alarm_X3D_x3d_ppa"),
        AssociationChoice("TYXAL PLUS VIRGIN", "official:alarm_X3D_x3d_ppa"),
        AssociationChoice("TYXAL PLUS WITH CLT 8000", "official:alarm_X3D_x3d_ppa"),
        AssociationChoice("TYXAL PLUS WITH TL 2000", "official:alarm_X3D_x3d_ppa"),
    ),
    "Caméras": (AssociationChoice("Aucun profil local documenté", None),),
    "Consommation": (
        AssociationChoice("CALYBOX 1020 WT", "official:rt2012_noOutTemp_X3D_x3d_pped"),
        AssociationChoice("CALYBOX 2020 WT", "official:rt2012_X3D_x3d_pped"),
        AssociationChoice("EM.IC", "official:generic_X3D_x3d_pp"),
        AssociationChoice("HITACHI ATW", "official:typassATL_X3D_direct"),
        AssociationChoice("TYBOX 1010 WT", "official:rt2012_noOutTemp_X3D_x3d_pped"),
        AssociationChoice("TYBOX 2000 WT", "official:rt2012_X3D_x3d_pped"),
        AssociationChoice("TYBOX 2010 WT", "official:rt2012_X3D_x3d_pped"),
        AssociationChoice("TYBOX 2020 WT", "official:rt2012_X3D_x3d_pped"),
        AssociationChoice("TYPASS ATL", "official:typassATL_X3D_direct"),
        AssociationChoice("TYPASS CHX", "official:typassATL_X3D_direct"),
        AssociationChoice("TYPASS SD", "official:typassSaunier_X3D_direct"),
        AssociationChoice("TYWATT 1000", "official:rt2012_noOutTemp_X3D_x3d_pped"),
        AssociationChoice("TYWATT 2000", "official:rt2012_X3D_x3d_pped"),
        AssociationChoice("TYWATT 5100", "official:meter_X3D_direct"),
        AssociationChoice("TYWATT 5400", "official:generic_X3D_x3d_pp"),
        AssociationChoice("TYWATT 5450", "official:generic_X3D_x3d_pp"),
        AssociationChoice("TYWATT 5600", "official:generic_X3D_x3d_pp"),
    ),
    "Porte": (
        AssociationChoice("CAPTEUR CPA", "official:detector_X3D_direct"),
        AssociationChoice("DETECTEUR OUVERTURE", "official:detector_X3D_direct"),
        AssociationChoice("DETECTEUR VERROUILLAGE DVI", "official:detector_X3D_direct"),
        AssociationChoice("I-SECURE (CPA)", "official:detector_X3D_direct"),
        AssociationChoice("POD", "official:pod_X3D_x3d_rm"),
        AssociationChoice("PORTE BELEM", "official:pod_X3D_x3d_rm"),
    ),
    "Fenêtres": (
        AssociationChoice("CAPTEUR CPA", "official:detector_X3D_direct"),
        AssociationChoice("DETECTEUR OUVERTURE", "official:detector_X3D_direct"),
        AssociationChoice(
            "DETECTEUR VERROUILLAGE DVI SLIDING", "official:detector_X3D_direct"
        ),
        AssociationChoice(
            "DETECTEUR VERROUILLAGE DVI SWING", "official:detector_X3D_direct"
        ),
        AssociationChoice("I-SECURE (CPA)", "official:detector_X3D_direct"),
        AssociationChoice("USAGE DETECT WINDOW FPI", "official:opening_x3d_x3d_rm"),
    ),
    "Stores": (
        AssociationChoice("PROFALUX STELLA STORE", "official:shutter_ZIGBEE_STELLA"),
        AssociationChoice("ROLLIA RADIO", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("STORE WELLCOM", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("TYMOOV RADIO", "official:shutterBrushless_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4630", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4730", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4731", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("TYXIA 5630", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("TYXIA 5730", "official:shutter_X3D_x3d_rm"),
        AssociationChoice("TYXIA 5731", "official:shutter_X3D_x3d_rm"),
    ),
    "Prise": (
        AssociationChoice("SMART PLUG DELTA DORE", "official:light_ZIGBEE"),
        AssociationChoice("SMART PLUG GENERIQUE", "official:light_ZIGBEE"),
    ),
    "Autres": (
        AssociationChoice("TYXIA 4600", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4610", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4620", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4801", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4811", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4840", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4850", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4860", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4910", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 4940", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 5610", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 5612", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 5640", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 5650", "official:light_X3D_x3d_rm"),
        AssociationChoice("TYXIA 6410", "official:light_X3D_x3d_rm"),
    ),
    "Télécommandes et claviers": (
        AssociationChoice("CLE 8000", "official:remote_X3D_direct"),
        AssociationChoice("TL 2000", "official:remote_X3D_direct"),
        AssociationChoice("TYXIA 1410", "official:remote_X3D_direct"),
    ),
    "Interrupteurs": (
        AssociationChoice("TYXIA 2310", "official:remote_X3D_direct"),
        AssociationChoice("TYXIA 2600", "official:remote_X3D_direct"),
        AssociationChoice("TYXIA 2700", "official:remote_X3D_direct"),
    ),
    "Capteurs": (
        AssociationChoice("SENSOR STI 2000", "official:sensor_X3D_direct"),
        AssociationChoice("TYBOX CONTROL", "official:sensor_X3D_direct"),
        AssociationChoice("TYBOX CONTROL XL", "official:sensor_X3D_direct"),
        # Tysense feeds the Tywell bioclimatic controller.  The RT2012 route
        # pairs it with an energy manager directly, not through a TYDOM
        # gateway, so it is intentionally outside this gateway workflow.
        AssociationChoice(
            "Tysense Sun",
            "official:sensor_X3D_direct",
            required_gateway_names=frozenset({"tywell pro", "tywell home"}),
        ),
        AssociationChoice(
            "Tysense Thermo",
            "official:temperature_X3D_direct",
            required_gateway_names=frozenset({"tywell pro", "tywell home"}),
        ),
        AssociationChoice("USAGE SENSOR DF", "official:detector_X3D_direct"),
        AssociationChoice("USAGE SENSOR DFR", "official:detector_X3D_direct"),
        AssociationChoice("USAGE WEATHER", "official:weather_plt"),
    ),
}

# The generic recipes above remain useful as readable protocol documentation,
# but the UI must use the complete, product-specific catalogue extracted from
# the official app.  Keep both profile maps addressable because existing YAML
# automations may still call a legacy profile id directly.
DISCOVERY_PROFILES.update(OFFICIAL_DISCOVERY_PROFILES)
ASSOCIATION_CATALOG = OFFICIAL_ASSOCIATION_CATALOG


# The official discovery request identifies the radio family.  The official
# application then writes a *model-and-usage* configuration in /configs/file.
# Keep this separate from the radio profile: TYXIA 4620, for example, uses the
# same X3D discovery payload as a light receiver but becomes a gate when it is
# selected under ``Portail``.
_OFFICIAL_CATEGORY_ASSOCIATION_RECIPES: dict[str, StandaloneAssociationRecipe] = {
    "Volets": StandaloneAssociationRecipe("shutter", "picto_shutter", "Volet"),
    "Éclairages": StandaloneAssociationRecipe("light", "picto_lamp", "Éclairage"),
    "Thermique": StandaloneAssociationRecipe(
        "electric", "picto_thermometer", "Chauffage"
    ),
    "Garage": StandaloneAssociationRecipe(
        "garage_door", "picto_sectional_door", "Garage"
    ),
    "Portail": StandaloneAssociationRecipe("gate", "picto_gate", "Portail"),
    "Alarme": StandaloneAssociationRecipe("alarm", "picto_alarm", "Alarme"),
    "Consommation": StandaloneAssociationRecipe("conso", "picto_conso", "Consommation"),
    "Porte": StandaloneAssociationRecipe("belmDoor", "picto_belmdoor", "Porte"),
    "Fenêtres": StandaloneAssociationRecipe(
        "windowFrench", "picto_window", "Fenêtre", "window"
    ),
    "Stores": StandaloneAssociationRecipe("awning", "picto_awning_awning", "Store"),
    "Prise": StandaloneAssociationRecipe("plug", "picto_smartplug", "Prise"),
    "Autres": StandaloneAssociationRecipe("others", "default_device", "Appareil"),
    "Capteurs": StandaloneAssociationRecipe("sensor", "picto_sensor1", "Capteur"),
}

# These products are explicitly marked as ``boiler`` by the app catalogue;
# treating them as the generic ``electric`` thermal class is incorrect.
_OFFICIAL_THERMIC_BOILER_PRODUCTS = frozenset(
    {
        "NSC RF ELM Leblanc",
        "RADIO TYBOX 810 (RF 640)",
        "RADIO TYBOX 811 (RF 640)",
        "RF 6050+",
        "RF 7210",
        "TRV 1.0",
        "TYBOX 1010 WT",
        "TYBOX 1137 (RF6000+)",
        "TYBOX 137 (RF 640)",
        "TYBOX 137+ (RF6000+)",
        "TYBOX 2010 WT",
        "TYBOX 2300 (RF 6000)",
        "TYBOX 237 (RF 640)",
        "TYBOX 337 (RF 640)",
        "TYBOX 4100",
        "TYBOX 4110",
        "TYBOX 4150",
        "TYBOX 4210",
        "TYBOX 4250",
        "TYBOX 5000",
        "TYBOX 5100 (RF 6000)",
        "TYBOX 5150 (RF 6200)",
        "TYBOX 5200 (RF 6050)",
        "TYBOX 5300 (RF 6050+)",
        "TYBOX RF 210 (RF 7210)",
        "Tywell 2050 (RF 6050+)",
        "Tywell 2050 L (RF 6050+)",
    }
)

_OFFICIAL_MODEL_ASSOCIATION_RECIPES: dict[
    tuple[str, str], StandaloneAssociationRecipe
] = {
    # Tywell Control is a RE2020 wall controller, distinct from the Tywell
    # 2050 thermostat kits. The values mirror its Tywell Pro/Home recipe.
    ("Thermique", "Tywell Control"): StandaloneAssociationRecipe(
        "re2020ControlBoiler",
        "",
        "Tywell Control",
        "hvac",
        "shutterCmd",
    ),
    ("Fenêtres", "DETECTEUR VERROUILLAGE DVI SLIDING"): StandaloneAssociationRecipe(
        "windowSliding", "picto_window", "Fenêtre", "window"
    ),
    ("Fenêtres", "DETECTEUR VERROUILLAGE DVI SWING"): StandaloneAssociationRecipe(
        "windowFrench", "picto_window", "Fenêtre", "window"
    ),
    ("Fenêtres", "USAGE DETECT WINDOW FPI"): StandaloneAssociationRecipe(
        "windowFPI", "picto_window", "Fenêtre", "window"
    ),
    ("Capteurs", "TYBOX CONTROL"): StandaloneAssociationRecipe(
        "sensorThermo", "picto_sensor5", "Sonde Température", "sensor"
    ),
    ("Capteurs", "TYBOX CONTROL XL"): StandaloneAssociationRecipe(
        "sensorThermo", "picto_sensor5", "Sonde Température", "sensor"
    ),
    ("Capteurs", "Tysense Sun"): StandaloneAssociationRecipe(
        "sensorSun", "picto_sensor6", "Sonde Soleil", "sensor"
    ),
    ("Capteurs", "Tysense Thermo"): StandaloneAssociationRecipe(
        "sensorThermo", "picto_sensor5", "Sonde Température", "sensor"
    ),
    ("Capteurs", "USAGE SENSOR DF"): StandaloneAssociationRecipe(
        "sensorDF", "picto_sensor_df", "Détecteur", "sensor"
    ),
    ("Capteurs", "USAGE SENSOR DFR"): StandaloneAssociationRecipe(
        "sensorDFR", "picto_sensor_dfr", "Détecteur", "sensor"
    ),
    ("Capteurs", "USAGE WEATHER"): StandaloneAssociationRecipe(
        "weather", "picto_weather", "Météo"
    ),
}


def _get_official_model_association_recipe(
    category: str, product_label: str
) -> StandaloneAssociationRecipe:
    """Return the extracted app recipe for one catalogue selection."""
    recipe = _OFFICIAL_MODEL_ASSOCIATION_RECIPES.get((category, product_label))
    if recipe is not None:
        return recipe
    if category == "Thermique" and product_label in _OFFICIAL_THERMIC_BOILER_PRODUCTS:
        return StandaloneAssociationRecipe("boiler", "picto_boiler", "Chaudière")
    return _OFFICIAL_CATEGORY_ASSOCIATION_RECIPES[category]


# Materialise every selected app model rather than applying a fuzzy category
# fallback at discovery time.  Multi-channel remote products stay on their
# existing dedicated workflow and are deliberately excluded from this table.
_OFFICIAL_STANDALONE_ASSOCIATION_RECIPES: dict[
    tuple[str, str], StandaloneAssociationRecipe
] = {
    (category, choice.label): _get_official_model_association_recipe(
        category, choice.label
    )
    for category, choices in OFFICIAL_ASSOCIATION_CATALOG.items()
    if category in _OFFICIAL_CATEGORY_ASSOCIATION_RECIPES
    for choice in choices
    if choice.profile_id is not None
    and choice.label not in GROUPABLE_ASSOCIATION_BY_LABEL
}


def get_standalone_association_recipe(
    category: str,
    product_label: str | None = None,
) -> StandaloneAssociationRecipe | None:
    """Return the exact app-derived recipe for one selected model.

    The association UI always supplies ``product_label``.  The category-only
    form remains for compatibility with prior callers but is never used for a
    gateway discovery, so an unknown model cannot be configured by accident.
    """
    if product_label is not None:
        return _OFFICIAL_STANDALONE_ASSOCIATION_RECIPES.get((category, product_label))
    return _OFFICIAL_CATEGORY_ASSOCIATION_RECIPES.get(category)


def get_association_choices(category: str) -> tuple[AssociationChoice, ...]:
    """Return the product families available under one displayed category."""
    try:
        return ASSOCIATION_CATALOG[category]
    except KeyError as err:
        raise ValueError(f"Unknown TYDOM association category: {category}") from err


def get_install_payload(
    profile_id: str, network: int | None = None
) -> dict[str, str | int]:
    """Build a validated ``POST /devices`` discovery request body."""
    try:
        profile = DISCOVERY_PROFILES[profile_id]
    except KeyError as err:
        raise ValueError(f"Unknown TYDOM discovery profile: {profile_id}") from err
    payload: dict[str, str | int] = {
        "protocol": profile.protocol,
        "type": profile.type,
        "profile": profile.profile,
    }
    if network is not None:
        if network < 0:
            raise ValueError("TYDOM network must be a non-negative integer")
        payload["net"] = network
    elif profile.protocol == "ZIGBEE":
        payload["net"] = 0
    return payload


async def start_product_association(
    tydom_hub, profile_id: str, network: int | None = None
) -> dict[str, str | int]:
    """Start association through the physical gateway's LAN connection."""
    payload = get_install_payload(profile_id, network)
    local_hub = _get_local_association_hub(tydom_hub)
    await local_hub._tydom_client.post_device_discovery(payload)
    return payload


def _normalized_gateway_mac(gateway_mac: object) -> str:
    """Return a comparison-safe gateway MAC address."""
    return "".join(
        character for character in str(gateway_mac) if character.isalnum()
    ).upper()


def _get_local_association_hub(tydom_hub):
    """Prefer the matching LAN entry when the selected entry uses mediation.

    Radio discovery is a gateway-local operation. A user can legitimately have
    several distinct TYDOM installations in Home Assistant, so only an entry
    with the *same gateway MAC* may replace the selected entry. Keep the
    selected connection when there is no unambiguous local match: the official
    cloud workflow must keep working for cloud-only installations.
    """
    tydom_client = getattr(tydom_hub, "_tydom_client", None)
    if tydom_client is None:
        raise ValueError("The selected TYDOM gateway has no active client")
    if not getattr(tydom_client, "_remote_mode", False):
        return tydom_hub

    hass = getattr(tydom_hub, "_hass", None)
    gateway_mac = _normalized_gateway_mac(getattr(tydom_hub, "_mac", ""))
    if hass is not None and gateway_mac:
        local_hubs = [
            hub
            for hub in getattr(hass, "data", {}).get(DOMAIN, {}).values()
            if _normalized_gateway_mac(getattr(hub, "_mac", "")) == gateway_mac
            and not getattr(getattr(hub, "_tydom_client", None), "_remote_mode", True)
        ]
        if len(local_hubs) == 1:
            return local_hubs[0]

    return tydom_hub


async def remove_product_association(device) -> None:
    """Remove a product cleanly from the TYDOM gateway.

    A button endpoint of a remote control or wall switch is removed on its
    own while sibling buttons are still configured.  Only removal of the last
    configured button deletes the physical radio product.

    A radio DELETE alone is insufficient for devices created as a
    ``relatedendpoints`` group (for example a TYXIA 2600): it leaves the
    group's configuration in the gateway.  The official application removes
    that group from both complete configuration files as well as deleting the
    radio product.  Standalone products follow the same configuration-first
    transaction: every endpoint is removed and every group membership is
    cleaned before their radio product is deleted.
    """
    device_id = getattr(device, "_id", None)
    tydom_client = getattr(device, "_tydom_client", None)
    if device_id is None or tydom_client is None:
        raise ValueError("The selected entity does not expose a TYDOM device")
    config = await tydom_client.get_config_file_document()
    groups = await tydom_client.get_groups_file_document()
    config_groups = config.get("groups")
    group_memberships = groups.get("groups")
    endpoints = config.get("endpoints")
    if not all(
        isinstance(value, list)
        for value in (config_groups, group_memberships, endpoints)
    ):
        raise ValueError("The gateway returned an incomplete configuration")

    association_group_id = getattr(device, "association_group_id", None)
    is_button_endpoint = isinstance(device, (TydomInterrupter, TydomRemoteControl))
    endpoint_id = getattr(device, "_endpoint", None)
    device_id = str(device_id)

    if is_button_endpoint and endpoint_id is not None:
        endpoint_id = str(endpoint_id)
        matching_endpoints = [
            endpoint
            for endpoint in endpoints
            if isinstance(endpoint, dict)
            and str(endpoint.get("id_device")) == device_id
            and str(endpoint.get("id_endpoint")) == endpoint_id
        ]
        if len(matching_endpoints) != 1:
            raise ValueError("The selected button is no longer configured")

        # The association group, rather than an assumption that every button
        # shares one device id, is the source of truth for sibling buttons.
        # This also covers every multi-channel remote/control format handled
        # by the official application.
        configured_siblings = {
            (str(endpoint.get("id_device")), str(endpoint.get("id_endpoint")))
            for endpoint in endpoints
            if isinstance(endpoint, dict)
            and str(endpoint.get("id_device")) == device_id
        }
        membership = None
        if association_group_id is not None:
            group_id = str(association_group_id)
            membership = next(
                (
                    group
                    for group in group_memberships
                    if isinstance(group, dict) and str(group.get("id")) == group_id
                ),
                None,
            )
            if membership is None:
                raise ValueError(
                    "The dedicated association group is no longer present on the gateway"
                )
            configured_siblings = {
                (str(member.get("id")), str(member_endpoint.get("id")))
                for member in membership.get("devices", [])
                if isinstance(member, dict)
                for member_endpoint in member.get("endpoints", [])
                if isinstance(member_endpoint, dict)
                and any(
                    isinstance(endpoint, dict)
                    and str(endpoint.get("id_device")) == str(member.get("id"))
                    and str(endpoint.get("id_endpoint"))
                    == str(member_endpoint.get("id"))
                    for endpoint in endpoints
                )
            }
            if (device_id, endpoint_id) not in configured_siblings:
                raise ValueError(
                    "The selected button is no longer part of its association group"
                )

        # A multi-button product remains paired until its final configured
        # button is removed. Remove only the selected reference from both
        # documents; do not issue a radio DELETE at this stage.
        if len(configured_siblings) > 1:
            updated_config = copy.deepcopy(config)
            updated_config["endpoints"] = [
                endpoint
                for endpoint in endpoints
                if endpoint is not matching_endpoints[0]
            ]

            updated_groups = copy.deepcopy(groups)
            if membership is not None:
                updated_membership = next(
                    (
                        group
                        for group in updated_groups["groups"]
                        if isinstance(group, dict) and str(group.get("id")) == group_id
                    ),
                    None,
                )
                if updated_membership is None:
                    raise ValueError(
                        "The dedicated association group is no longer present on the gateway"
                    )
                device_membership = next(
                    (
                        member
                        for member in updated_membership.get("devices", [])
                        if isinstance(member, dict)
                        and str(member.get("id")) == device_id
                    ),
                    None,
                )
                if device_membership is None or not isinstance(
                    device_membership.get("endpoints"), list
                ):
                    raise ValueError(
                        "The selected button is no longer part of its association group"
                    )
                retained_endpoints = [
                    member_endpoint
                    for member_endpoint in device_membership["endpoints"]
                    if not (
                        isinstance(member_endpoint, dict)
                        and str(member_endpoint.get("id")) == endpoint_id
                    )
                ]
                if retained_endpoints:
                    device_membership["endpoints"] = retained_endpoints
                else:
                    # A member without endpoints makes a related-endpoints
                    # group invalid in TYDOM and moves the surviving channels
                    # to "Non géré" in the official app.
                    updated_membership["devices"] = [
                        member
                        for member in updated_membership["devices"]
                        if member is not device_membership
                    ]

            config_updated = False
            try:
                await tydom_client.post_config_file_document(updated_config)
                config_updated = True
                if association_group_id is not None:
                    await tydom_client.post_groups_file_document(updated_groups)
            except Exception:
                if config_updated:
                    try:
                        await tydom_client.post_config_file_document(config)
                    except Exception:
                        LOGGER.exception(
                            "Unable to restore /configs/file after failed button removal"
                        )
                raise
            return

    if association_group_id is None:
        # Standalone products may have one or several configuration endpoints.
        # Remove every endpoint of the physical product and every membership
        # reference before radio deletion. Empty related-endpoints groups are
        # invalid in TYDOM, so their matching configuration records are also
        # removed; user-defined groups are retained even when now empty.
        matching_endpoints = [
            endpoint
            for endpoint in endpoints
            if isinstance(endpoint, dict)
            and str(endpoint.get("id_device")) == device_id
        ]
        if not matching_endpoints:
            raise ValueError(
                "The selected product is no longer present in the gateway configuration"
            )

        updated_config = copy.deepcopy(config)
        updated_config["endpoints"] = [
            endpoint for endpoint in endpoints if endpoint not in matching_endpoints
        ]

        updated_groups = copy.deepcopy(groups)
        emptied_group_ids: set[str] = set()
        for membership in updated_groups["groups"]:
            if not isinstance(membership, dict):
                continue
            members = membership.get("devices")
            if not isinstance(members, list):
                continue
            retained_members = [
                member
                for member in members
                if not (isinstance(member, dict) and str(member.get("id")) == device_id)
            ]
            if len(retained_members) == len(members):
                continue
            membership["devices"] = retained_members
            if not retained_members and membership.get("id") is not None:
                emptied_group_ids.add(str(membership["id"]))

        related_group_ids = {
            str(group.get("id"))
            for group in config_groups
            if isinstance(group, dict)
            and group.get("type") == "relatedendpoints"
            and group.get("id") is not None
        }
        obsolete_group_ids = emptied_group_ids & related_group_ids
        if obsolete_group_ids:
            updated_config["groups"] = [
                group
                for group in config_groups
                if not (
                    isinstance(group, dict)
                    and str(group.get("id")) in obsolete_group_ids
                )
            ]
            updated_groups["groups"] = [
                group
                for group in updated_groups["groups"]
                if not (
                    isinstance(group, dict)
                    and str(group.get("id")) in obsolete_group_ids
                )
            ]

        config_updated = False
        groups_updated = False
        await tydom_client.post_config_file_document(updated_config)
        config_updated = True
        try:
            await tydom_client.post_groups_file_document(updated_groups)
            groups_updated = True
            await tydom_client.delete_device(device_id)
        except Exception:
            if groups_updated:
                try:
                    await tydom_client.post_groups_file_document(groups)
                except Exception:
                    LOGGER.exception(
                        "Unable to restore /groups/file after failed removal"
                    )
            try:
                if config_updated:
                    await tydom_client.post_config_file_document(config)
            except Exception:
                LOGGER.exception("Unable to restore /configs/file after failed removal")
            raise
        return

    group_id = str(association_group_id)
    config_group = next(
        (
            group
            for group in config_groups
            if isinstance(group, dict) and str(group.get("id")) == group_id
        ),
        None,
    )
    group_membership = next(
        (
            group
            for group in group_memberships
            if isinstance(group, dict) and str(group.get("id")) == group_id
        ),
        None,
    )
    if config_group is None or group_membership is None:
        raise ValueError(
            "The dedicated association group is no longer present on the gateway"
        )
    if config_group.get("type") != "relatedendpoints":
        raise ValueError(
            "Safe complete removal is only available for dedicated "
            "related-endpoints groups"
        )

    member_ids = {
        str(member.get("id"))
        for member in group_membership.get("devices", [])
        if isinstance(member, dict) and member.get("id") is not None
    }
    if device_id not in member_ids:
        raise ValueError(
            "The selected product is not a member of its dedicated association group"
        )

    updated_config = copy.deepcopy(config)
    updated_config["groups"] = [
        group
        for group in config_groups
        if not (isinstance(group, dict) and str(group.get("id")) == group_id)
    ]
    updated_config["endpoints"] = [
        endpoint
        for endpoint in endpoints
        if not (
            isinstance(endpoint, dict) and str(endpoint.get("id_device")) == device_id
        )
    ]
    updated_groups = copy.deepcopy(groups)
    updated_groups["groups"] = [
        group
        for group in group_memberships
        if not (isinstance(group, dict) and str(group.get("id")) == group_id)
    ]

    # Nothing is deleted from the radio until the two source-of-truth files
    # have both been accepted.  If the second write or the radio DELETE fails,
    # restore the original documents so the official app keeps a coherent view.
    config_updated = False
    groups_updated = False
    try:
        await tydom_client.post_config_file_document(updated_config)
        config_updated = True
        await tydom_client.post_groups_file_document(updated_groups)
        groups_updated = True
        await tydom_client.delete_device(device_id)
    except Exception:
        if groups_updated:
            try:
                await tydom_client.post_groups_file_document(groups)
            except Exception:
                LOGGER.exception("Unable to restore /groups/file after failed removal")
        if config_updated:
            try:
                await tydom_client.post_config_file_document(config)
            except Exception:
                LOGGER.exception("Unable to restore /configs/file after failed removal")
        raise


def _next_groupable_product_name(
    config: dict[str, object], product: GroupableAssociationProduct
) -> str:
    """Return the next official-style name for a multi-channel product."""
    used_names = {
        str(endpoint.get("name"))
        for endpoint in config.get("endpoints", [])
        if isinstance(endpoint, dict)
    }
    used_names.update(
        str(group.get("name"))
        for group in config.get("groups", [])
        if isinstance(group, dict)
    )
    number = 1
    while f"{product.name_prefix} {number}" in used_names:
        number += 1
    return f"{product.name_prefix} {number}"


def _new_related_endpoints_group_id(config: dict[str, object]) -> int:
    """Return an unused positive group id for a locally configured product."""
    existing_ids = {
        str(group.get("id"))
        for group in config.get("groups", [])
        if isinstance(group, dict) and group.get("id") is not None
    }
    while True:
        group_id = secrets.randbelow(2_147_483_646) + 1
        if str(group_id) not in existing_ids:
            return group_id


async def configure_groupable_product(
    device,
    product: GroupableAssociationProduct,
    channel: str,
    name_override: str | None = None,
) -> str:
    """Configure one discovered channel as an app-visible product.

    Every product in this family is marked ``groupable`` by the official
    catalogue. It creates a ``relatedendpoints`` group even if only one channel
    is in use. A later discovery extends that group; Home Assistant never
    fabricates an unused channel.
    """
    channel_spec = next(
        (candidate for candidate in product.channels if candidate.label == channel),
        None,
    )
    if channel_spec is None:
        raise ValueError(f"Unsupported {product.label} channel: {channel!r}")

    device_id = str(getattr(device, "_id", ""))
    endpoint_id = str(getattr(device, "_endpoint", ""))
    tydom_client = getattr(device, "_tydom_client", None)
    get_config = getattr(tydom_client, "get_config_file_document", None)
    post_config = getattr(tydom_client, "post_config_file_document", None)
    get_groups = getattr(tydom_client, "get_groups_file_document", None)
    post_groups = getattr(tydom_client, "post_groups_file_document", None)
    if (
        not device_id
        or not endpoint_id
        or not callable(get_config)
        or not callable(post_config)
        or not callable(get_groups)
        or not callable(post_groups)
    ):
        raise ValueError("The selected endpoint cannot be configured safely")

    config = await get_config()
    endpoints = config.get("endpoints") if isinstance(config, dict) else None
    config_groups = config.get("groups") if isinstance(config, dict) else None
    if not isinstance(endpoints, list) or not isinstance(config_groups, list):
        raise TypeError("The gateway returned a malformed /configs/file document")
    groups = await get_groups()
    group_memberships = groups.get("groups") if isinstance(groups, dict) else None
    if not isinstance(group_memberships, list):
        raise TypeError("The gateway returned malformed association documents")

    configured_endpoint = next(
        (
            endpoint
            for endpoint in endpoints
            if isinstance(endpoint, dict)
            and str(endpoint.get("id_device")) == device_id
            and str(endpoint.get("id_endpoint")) == endpoint_id
        ),
        None,
    )
    tutorial_id = channel_spec.tutorial_id

    def is_member(group: dict, candidate_endpoint_id: str) -> bool:
        """Return whether a groups/file record contains this exact endpoint."""
        return any(
            isinstance(member, dict)
            and str(member.get("id")) == device_id
            and any(
                isinstance(endpoint, dict)
                and str(endpoint.get("id")) == candidate_endpoint_id
                for endpoint in member.get("endpoints", [])
            )
            for member in group.get("devices", [])
        )

    existing_membership = next(
        (
            membership
            for membership in group_memberships
            if isinstance(membership, dict) and is_member(membership, endpoint_id)
        ),
        None,
    )
    if configured_endpoint is not None and existing_membership is not None:
        behavior = configured_endpoint.get("widget_behavior")
        if isinstance(behavior, dict) and behavior.get("tutorial_id") == tutorial_id:
            raise ValueError("This TYXIA 2600 button is already configured")
        raise ValueError("This endpoint already belongs to another configured product")

    requested_name = " ".join((name_override or "").split())
    name = requested_name or (
        str(configured_endpoint.get("name"))
        if configured_endpoint is not None and configured_endpoint.get("name")
        else _next_groupable_product_name(config, product)
    )
    endpoint_config = {
        "id_device": int(device_id),
        "id_endpoint": int(endpoint_id),
        "name": channel_spec.config_name,
        "picto": product.endpoint_picto,
        "first_usage": product.usage,
        "last_usage": product.usage,
        "widget_behavior": {"tutorial_id": tutorial_id, "action": "TOGGLE"},
        "anticipation_start": False,
        "skill": "TYDOM_X3D",
    }

    related_group = next(
        (
            group
            for group in config_groups
            if isinstance(group, dict)
            and group.get("type") == "relatedendpoints"
            and isinstance(group.get("widget_behavior"), dict)
            and group["widget_behavior"].get("tutorial_id") == product.tutorial_id
            and any(
                isinstance(membership, dict)
                and str(membership.get("id")) == str(group.get("id"))
                and any(
                    isinstance(member, dict) and str(member.get("id")) == device_id
                    for member in membership.get("devices", [])
                )
                for membership in group_memberships
            )
        ),
        None,
    )

    updated_config = copy.deepcopy(config)
    updated_groups = copy.deepcopy(groups)
    if configured_endpoint is not None:
        for endpoint in updated_config["endpoints"]:
            if (
                isinstance(endpoint, dict)
                and str(endpoint.get("id_device")) == device_id
                and str(endpoint.get("id_endpoint")) == endpoint_id
            ):
                endpoint.update(endpoint_config)
                break
    else:
        updated_config["endpoints"].append(endpoint_config)

    if related_group is None:
        group_id = _new_related_endpoints_group_id(config)
        updated_config["groups"].append(
            {
                "id": group_id,
                "name": name,
                "picto": product.group_picto,
                "usage": product.usage,
                "type": "relatedendpoints",
                "group_all": False,
                "is_group_user": False,
                "widget_behavior": {"tutorial_id": product.tutorial_id},
            }
        )
        updated_groups["groups"].append(
            {
                "id": group_id,
                "devices": [
                    {"id": int(device_id), "endpoints": [{"id": int(endpoint_id)}]}
                ],
                "areas": [],
            }
        )
    else:
        group_id = related_group.get("id")
        membership = next(
            (
                item
                for item in updated_groups["groups"]
                if isinstance(item, dict) and str(item.get("id")) == str(group_id)
            ),
            None,
        )
        if membership is None:
            raise ValueError(
                f"The {product.label} group has no /groups/file membership"
            )
        device_membership = next(
            (
                item
                for item in membership.get("devices", [])
                if isinstance(item, dict) and str(item.get("id")) == device_id
            ),
            None,
        )
        if device_membership is None:
            raise ValueError(f"The {product.label} group cannot be extended safely")
        device_membership.setdefault("endpoints", []).append({"id": int(endpoint_id)})
        name = str(related_group.get("name") or name)

    config_updated = False
    try:
        await post_config(updated_config)
        config_updated = True
        await post_groups(updated_groups)
    except Exception:
        if config_updated:
            try:
                await post_config(config)
            except Exception:
                LOGGER.exception(
                    "Unable to restore /configs/file after pairing failure"
                )
        raise
    return name


async def configure_tyxia_2600_interrupter(device, channel: str) -> str:
    """Compatibility wrapper for the original TYXIA 2600 helper."""
    return await configure_groupable_product(
        device, GROUPABLE_ASSOCIATION_BY_LABEL["TYXIA 2600"], channel
    )


def _next_standalone_product_name(
    config: dict[str, object], recipe: StandaloneAssociationRecipe
) -> str:
    """Return a readable unused name instead of retaining ``Produit N``."""
    used_names = {
        str(endpoint.get("name"))
        for endpoint in config.get("endpoints", [])
        if isinstance(endpoint, dict)
    }
    number = 1
    while f"{recipe.name_prefix} {number}" in used_names:
        number += 1
    return f"{recipe.name_prefix} {number}"


async def configure_standalone_product(
    device,
    recipe: StandaloneAssociationRecipe,
    tutorial_id: str | None,
    name_override: str | None = None,
) -> str:
    """Turn one raw radio discovery into an application-managed product.

    This is intentionally restricted to a fresh, otherwise untyped endpoint.
    It never changes an already configured product such as a Tywatt meter,
    thermostat, or remote control; those retain the gateway's own metadata.
    """
    device_id = str(getattr(device, "_id", ""))
    endpoint_id = str(getattr(device, "_endpoint", ""))
    tydom_client = getattr(device, "_tydom_client", None)
    get_config = getattr(tydom_client, "get_config_file_document", None)
    post_config = getattr(tydom_client, "post_config_file_document", None)
    if (
        not device_id
        or not endpoint_id
        or not callable(get_config)
        or not callable(post_config)
    ):
        raise ValueError("The discovered endpoint cannot be configured safely")

    config = await get_config()
    endpoints = config.get("endpoints") if isinstance(config, dict) else None
    if not isinstance(endpoints, list):
        raise TypeError("The gateway returned a malformed /configs/file document")

    endpoint = next(
        (
            item
            for item in endpoints
            if isinstance(item, dict)
            and str(item.get("id_device")) == device_id
            and str(item.get("id_endpoint")) == endpoint_id
        ),
        None,
    )
    # Repair the exact generic Tysense Sun entry written by older association
    # code.  It is unambiguously identified by the official tutorial and is
    # the only already-configured endpoint this helper may rewrite.
    is_tysense_sun_repair = (
        recipe.usage == "sensorSun"
        and endpoint is not None
        and endpoint.get("last_usage") == "sensor"
        and isinstance(endpoint.get("widget_behavior"), dict)
        and endpoint["widget_behavior"].get("tutorial_id") == "tysense_sun"
    )
    if (
        endpoint is not None
        and endpoint.get("last_usage")
        and not is_tysense_sun_repair
    ):
        raise ValueError("The discovered endpoint is already configured")

    requested_name = " ".join((name_override or "").split())
    name = requested_name or _next_standalone_product_name(config, recipe)
    configured_endpoint = {
        "id_device": int(device_id),
        "id_endpoint": int(endpoint_id),
        "name": name,
        "picto": recipe.picto,
        "first_usage": recipe.first_usage or recipe.usage,
        "last_usage": recipe.usage,
        "anticipation_start": False,
        "skill": "TYDOM_X3D",
        "space_id": "",
    }
    if tutorial_id:
        configured_endpoint["widget_behavior"] = {"tutorial_id": tutorial_id}
        if recipe.widget_action:
            configured_endpoint["widget_behavior"]["action"] = recipe.widget_action

    updated_config = copy.deepcopy(config)
    if endpoint is None:
        # Some gateways accept the radio association but never add the raw
        # ``Produit N`` placeholder to /configs/file.  The endpoint was just
        # observed during a selected standalone association, so append its
        # application configuration directly rather than leaving a radio-only
        # product invisible to both HA and the TYDOM application.
        updated_config["endpoints"].append(configured_endpoint)
    else:
        for item in updated_config["endpoints"]:
            if (
                isinstance(item, dict)
                and str(item.get("id_device")) == device_id
                and str(item.get("id_endpoint")) == endpoint_id
            ):
                item.update(configured_endpoint)
                break
    await post_config(updated_config)
    return name


class Hub:
    """Hub for Delta Dore Tydom."""

    manufacturer = "Delta Dore"

    def handle_event(self, event):
        """Event callback."""
        pass

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        host: str,
        mac: str,
        password: str,
        refresh_interval: str,
        zone_home: str,
        zone_away: str,
        zone_night: str,
        alarmpin: str,
    ) -> None:
        """Init hub."""
        self._host = host
        self._mac = mac
        self._pass = password
        self._refresh_interval = int(refresh_interval) * 60
        self._zone_home = zone_home
        self._zone_away = zone_away
        self._zone_night = zone_night
        self._pin = alarmpin
        self._hass = hass
        self._entry = entry
        self._name = mac
        self._id = "Tydom-" + mac[6:]
        self.devices = {}
        self.ha_devices = {}
        self.add_cover_callback = None
        self.add_sensor_callback = None
        self.add_climate_callback = None
        self.add_light_callback = None
        self.add_lock_callback = None
        self.add_alarm_callback = None
        self.add_update_callback = None
        self.add_weather_callback = None
        self.add_binary_sensor_callback = None
        self.add_scene_callback = None
        self.add_switch_callback = None
        self.add_button_callback = None
        self.add_number_callback = None
        self.add_select_callback = None
        self.add_text_callback = None
        self.add_event_callback = None

        self._tydom_client = TydomClient(
            hass=self._hass,
            id=self._id,
            mac=self._mac,
            host=self._host,
            password=self._pass,
            zone_home=self._zone_home,
            zone_away=self._zone_away,
            zone_night=self._zone_night,
            alarm_pin=self._pin,
            event_callback=self.handle_event,
        )

        self.online = True
        self._reload_button_created = False
        self._inventory_syncing = False
        self._inventory_sync_error: str | None = None
        self._association_controls_created = False
        self._association_controls: list = []
        self._association_category = next(iter(ASSOCIATION_CATALOG))
        first_choice = get_association_choices(self._association_category)[0]
        self._association_product = first_choice.label
        self._association_profile = first_choice.profile_id
        self._association_channel = "Bouton A"
        self._association_name = ""
        self._pending_groupable_association: (
            tuple[GroupableAssociationProduct, str] | None
        ) = None
        self._pending_groupable_name: str | None = None
        self._pending_groupable_known_device_ids: set[str] = set()
        self._pending_groupable_candidate_device_id: str | None = None
        self._pending_groupable_auto_finalize_task: asyncio.Task[None] | None = None
        self._pending_groupable_auto_finalize_failed = False
        self._pending_association_name: str | None = None
        self._pending_association_known_device_ids: set[str] = set()
        self._pending_standalone_association: (
            tuple[StandaloneAssociationRecipe, str | None] | None
        ) = None
        self._pending_standalone_known_device_ids: set[str] = set()
        self._pending_standalone_candidate_device_id: str | None = None
        self._pending_standalone_auto_finalize_task: asyncio.Task[None] | None = None
        self._pending_standalone_auto_finalize_failed = False
        self._refresh_energy_buttons_created: set[str] = set()
        self._device_association_buttons_created: set[tuple[str, str]] = set()
        self._remote_battery_entities: dict[str, HARemoteBattery] = {}
        self._interrupter_battery_entities: dict[str, HAInterrupterBattery] = {}
        self._twc_scene_sets: dict[str, dict[str, HAScene]] = {}
        self._twc_cover_entities: dict[str, HATwcShutterCover] = {}
        self._shutting_down = False

        # Polling cache for optimization
        self._polling_cache: dict[
            tuple[str, str], int
        ] = {}  # (device_key, attr_name) -> interval
        self._polling_cache_timestamp = 0
        self._polling_cache_ttl = 300  # 5 minutes
        self._next_poll_due: dict[int, float] = {}  # interval -> monotonic due time

        # Device factory registry for create_ha_device
        self._device_factories: dict[type, Callable] = {
            Tydom: self._create_tydom_device,
            TydomShutter: self._create_shutter_device,
            TydomEnergy: self._create_energy_device,
            TydomSmoke: self._create_smoke_device,
            TydomBoiler: self._create_boiler_device,
            TydomWindow: self._create_window_device,
            TydomDoor: self._create_door_device,
            TydomGate: self._create_gate_device,
            TydomGarage: self._create_garage_device,
            TydomLight: self._create_light_device,
            TydomSwitch: self._create_switch_device,
            TydomInterrupter: self._create_interrupter_device,
            TydomPlug: self._create_switch_device,
            TydomAlarm: self._create_alarm_device,
            TydomWeather: self._create_weather_device,
            TydomWater: self._create_water_device,
            TydomThermo: self._create_thermo_device,
            TydomSun: self._create_sun_device,
            TydomScene: self._create_scene_device,
            TydomGroup: self._create_group_device,
            TydomMoment: self._create_moment_device,
            TydomRemoteControl: self._create_remote_control_device,
            TydomDevice: self._create_generic_device,
        }

    def update_config(self, refresh_interval, zone_home, zone_away, zone_night):
        """Update zone configuration."""
        self._tydom_client.update_config(zone_home, zone_away, zone_night)
        self._refresh_interval = int(refresh_interval) * 60
        self._zone_home = zone_home
        self._zone_away = zone_away
        self._zone_night = zone_night

    @property
    def hub_id(self) -> str:
        """ID for dummy hub."""
        return self._id

    async def connect(self) -> ClientWebSocketResponse:
        """Connect to Tydom."""
        if self._shutting_down:
            raise asyncio.CancelledError()
        connection = await self._tydom_client.async_connect_and_initialise()
        if self._shutting_down:
            await self._tydom_client.async_disconnect()
            raise asyncio.CancelledError()
        return connection

    async def async_shutdown(self) -> None:
        """Stop background work and release the Tydom websocket."""
        if self._shutting_down:
            return
        self._shutting_down = True
        await self._tydom_client.async_disconnect()

    async def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep in short slices so shutdown is picked up quickly."""
        remaining = seconds
        while remaining > 0 and not self._shutting_down:
            await asyncio.sleep(min(1.0, remaining))
            remaining -= 1.0

    @staticmethod
    async def get_tydom_credentials(
        session: ClientSession, email: str, password: str, macaddress: str
    ):
        """Get Tydom credentials."""
        return await TydomClient.async_get_credentials(
            session, email, password, macaddress
        )

    async def test_credentials(self) -> None:
        """Validate credentials."""
        connection = await self._tydom_client.async_connect()
        if hasattr(connection, "close"):
            try:
                await asyncio.wait_for(connection.close(), timeout=3.0)
            except TimeoutError:
                LOGGER.warning(
                    "Timed out closing Tydom websocket after credential test"
                )

    def ready(self) -> bool:
        """Check if we're ready to work."""
        # and self.add_alarm_callback is not None
        is_ready = (
            self.add_cover_callback is not None
            and self.add_sensor_callback is not None
            and self.add_climate_callback is not None
            and self.add_light_callback is not None
            and self.add_lock_callback is not None
            and self.add_update_callback is not None
            and self.add_alarm_callback is not None
            and self.add_weather_callback is not None
            and self.add_scene_callback is not None
            and self.add_switch_callback is not None
            and self.add_button_callback is not None
            and self.add_number_callback is not None
            and self.add_select_callback is not None
            and self.add_text_callback is not None
            and self.add_event_callback is not None
            and self.add_binary_sensor_callback is not None
        )
        # Créer le bouton de rechargement une fois que les callbacks sont prêts
        if (
            is_ready
            and not self._reload_button_created
            and self.add_button_callback is not None
        ):
            reload_button = HAReloadButton(self, self._hass)
            self.add_button_callback([reload_button])
            self._reload_button_created = True
            LOGGER.debug("Bouton de rechargement créé")
        if (
            is_ready
            and not self._association_controls_created
            and self.add_button_callback is not None
            and self.add_select_callback is not None
            and self.add_text_callback is not None
        ):
            self.add_select_callback(
                [
                    HAGatewayAssociationCategorySelect(self),
                    HAGatewayAssociationProductSelect(self),
                    HAGatewayAssociationChannelSelect(self),
                    HAGatewayAssociationUsageSelect(self),
                ]
            )
            self.add_button_callback(
                [
                    HAGatewayAssociationGuideButton(self),
                    HAGatewayStartAssociationButton(self),
                ]
            )
            self.add_text_callback([HAGatewayAssociationNameText(self)])
            self._association_controls_created = True
            LOGGER.debug("Gateway product-association controls created")
        return is_ready

    @property
    def association_categories(self) -> tuple[str, ...]:
        """Return the usage categories offered by gateway association."""
        return tuple(ASSOCIATION_CATALOG)

    @property
    def association_category(self) -> str:
        """Return the currently selected association category."""
        return self._association_category

    @property
    def association_product_labels(self) -> tuple[str, ...]:
        """Return product families for the selected category."""
        return tuple(choice.label for choice in self._association_choices())

    @property
    def association_product_label(self) -> str:
        """Return the label of the currently selected product family."""
        return self._association_product

    @property
    def association_product_supported(self) -> bool:
        """Whether the current choice has a documented local install profile."""
        choice = next(
            (
                choice
                for choice in get_association_choices(self._association_category)
                if choice.label == self._association_product
            ),
            None,
        )
        return (
            self._association_profile is not None
            and choice is not None
            and self._is_association_choice_supported(choice)
        )

    @property
    def association_usage_labels(self) -> tuple[str, ...]:
        """Return the official categories that support the selected product."""
        return tuple(
            category
            for category in ASSOCIATION_CATALOG
            if any(
                choice.label == self._association_product
                for choice in self._association_choices(category)
            )
        )

    @property
    def association_usage_label(self) -> str:
        """Return the selected product's currently assigned application usage."""
        return self._association_category

    @property
    def association_channel_labels(self) -> tuple[str, ...]:
        """Return independent physical channels for the selected product."""
        product = self._selected_groupable_product()
        return tuple(channel.label for channel in product.channels) if product else ()

    @property
    def association_channel_label(self) -> str | None:
        """Return the selected physical channel, if this product has one."""
        if not self.association_channel_labels:
            return None
        return self._association_channel

    @property
    def association_name(self) -> str:
        """Return the optional name requested for a groupable product."""
        return self._association_name

    @property
    def association_name_supported(self) -> bool:
        """Whether the selected product can be associated by this gateway."""
        return self.association_product_supported

    @property
    def association_illustration_ids(self) -> tuple[str, ...]:
        """Return official visual steps for the selected product or channel."""
        product = self._selected_groupable_product()
        if product is None:
            return get_association_illustration_ids(
                get_official_association_tutorial_id(
                    self._association_product, self._association_category
                )
            )
        channel = next(
            (
                item
                for item in product.channels
                if item.label == self._association_channel
            ),
            None,
        )
        return get_association_illustration_ids(
            channel.tutorial_id if channel is not None else None
        )

    @property
    def association_illustration_layout(
        self,
    ) -> tuple[str | None, tuple[str, ...], bool]:
        """Return a product overview separately from its instructional visuals."""
        product = self._selected_groupable_product()
        if product is None:
            return get_association_illustration_layout(
                get_official_association_tutorial_id(
                    self._association_product, self._association_category
                )
            )
        channel = next(
            (
                item
                for item in product.channels
                if item.label == self._association_channel
            ),
            None,
        )
        return get_association_illustration_layout(
            channel.tutorial_id if channel is not None else None
        )

    @property
    def association_illustration_step_indexes(self) -> tuple[int, ...]:
        """Return the instruction index described by each official visual.

        Generic catalogue tutorials contain one visual per displayed step. The
        multi-channel products have extra HA-only steps (selection, listening,
        discovery) with no Android visual, so their mapping is declared next
        to the model's physical procedure.
        """
        product = self._selected_groupable_product()
        if product is not None:
            return product.illustration_step_indexes
        if self._association_product == "Tywell Control":
            # The Android tutorial has a device-side preparation followed by
            # the gateway action. Its sole visual depicts that preparation.
            return (0,)
        _, illustrations, _ = self.association_illustration_layout
        return tuple(range(len(illustrations)))

    @property
    def association_gateway_listening_step_indexes(self) -> tuple[int, ...]:
        """Return the precise guide steps where gateway listening starts.

        The frontend uses this structured information rather than infer an
        action location from translated guide text. The official catalogue
        exposes this marker for every standard product.
        """
        product = self._selected_groupable_product()
        if product is not None:
            return tuple(
                index
                for index, step in enumerate(product.guide)
                if "Lancer l'écoute de la passerelle" in step
            )
        if self._association_product == "Tywell Control":
            return (1,)
        return tuple(
            index
            for index, step in enumerate(
                get_official_association_tutorial(
                    self._association_product, self._association_category
                )
            )
            if step.starts_gateway_listening
        )

    @property
    def association_instructions(self) -> tuple[str, ...]:
        """Return the app-derived procedure for the selected product/channel."""
        product = self._selected_groupable_product()
        if product is not None:
            channel = self._association_channel
            button = channel.removeprefix("Bouton ").removeprefix("Touche ")
            return tuple(
                step.format(
                    channel=channel,
                    button=button,
                    channel_lower=channel.lower(),
                )
                for step in product.guide
            )

        if self._association_product == "Tywell Control":
            # The official sentence combines a control on the device with the
            # TYDOM application's "Associer" button. Split it into the order
            # required by Home Assistant, whose button opens the gateway's
            # listening window instead.
            return (
                "1. Sur le Tywell Control, lancez « Association avec la box Tywell ».",
                "2. Dans Home Assistant, cliquez sur « Lancer l'écoute de la passerelle » ci-dessous.",
                "3. Attendez la découverte et l'ajout automatique du contrôleur.",
            )

        tutorial = get_official_association_tutorial(
            self._association_product, self._association_category
        )
        instructions = []
        for index, step in enumerate(tutorial, start=1):
            # The catalogue stores some French quotes as JSON-escaped text.
            # They are already decoded at this point, so remove the remaining
            # literal escape marker before exposing the instruction in HA.
            text = " ".join(step.text.split()).replace('\\"', '"')
            # "Associer" is the button shown by the official TYDOM app.  In
            # Home Assistant the matching action is the gateway-listening
            # button below, so do not instruct the user to look for an app
            # control which is not present here.
            if (
                text.lower()
                == 'la led rouge clignote, maintenant appuyez sur "associer".'
            ):
                text = (
                    "Lorsque la LED rouge clignote, l'appareil est prêt à être associé."
                )
            if step.starts_gateway_listening:
                text = (
                    f"{text} Dans Home Assistant, appuyez alors sur "
                    "« Lancer l'écoute de la passerelle »."
                )
            instructions.append(f"{index}. {text}")
        return tuple(instructions)

    def _association_gateway_reference(self) -> str | None:
        """Return the gateway main reference when it has been discovered."""
        gateway = getattr(self, "devices", {}).get(getattr(self, "_id", ""))
        reference = getattr(gateway, "mainReference", None)
        return str(reference) if reference is not None else None

    def _association_choices(
        self, category: str | None = None
    ) -> tuple[AssociationChoice, ...]:
        """Return choices allowed by the current gateway and app catalogue."""
        choices = get_association_choices(category or self._association_category)
        return tuple(
            choice
            for choice in choices
            if self._is_association_choice_supported(choice)
        )

    def _is_association_choice_supported(self, choice: AssociationChoice) -> bool:
        """Return whether a product choice is supported by this gateway."""
        gateway = getattr(self, "devices", {}).get(getattr(self, "_id", ""))
        gateway_name = str(getattr(gateway, "productName", "")).casefold()
        if (
            choice.required_gateway_names
            and gateway_name
            and gateway_name not in choice.required_gateway_names
        ):
            return False

        product = GROUPABLE_ASSOCIATION_BY_LABEL.get(choice.label)
        reference = self._association_gateway_reference()
        return product is None or reference is None or reference in product.gateway_refs

    def _selected_groupable_product(self) -> GroupableAssociationProduct | None:
        """Return the special product selected in the gateway controls."""
        product = GROUPABLE_ASSOCIATION_BY_LABEL.get(self._association_product)
        if (
            product is None
            or product.category != self._association_category
            or not self._is_groupable_product_supported(product)
        ):
            return None
        return product

    def _is_groupable_product_supported(
        self, product: GroupableAssociationProduct
    ) -> bool:
        """Prevent a stale special-product choice on an incompatible gateway."""
        reference = self._association_gateway_reference()
        return reference is None or reference in product.gateway_refs

    def register_association_control(self, entity) -> None:
        """Register a gateway control that needs selection-state updates."""
        if entity not in self._association_controls:
            self._association_controls.append(entity)

    def unregister_association_control(self, entity) -> None:
        """Forget a gateway control removed by Home Assistant."""
        if entity in self._association_controls:
            self._association_controls.remove(entity)

    def _notify_association_controls(self) -> None:
        """Update the category/product controls after a selection change."""
        for entity in self._association_controls:
            entity.async_write_ha_state()

    @property
    def inventory_syncing(self) -> bool:
        """Whether the gateway inventory is currently being rebuilt."""
        return self._inventory_syncing

    @property
    def inventory_sync_status(self) -> str:
        """Return a user-facing inventory synchronization status."""
        if self._inventory_syncing:
            return "Synchronisation de l'inventaire en cours"
        if self._inventory_sync_error:
            return f"Échec de la synchronisation : {self._inventory_sync_error}"
        return "Inventaire à jour"

    async def reload_devices_with_status(self) -> None:
        """Reload devices once while exposing progress to gateway controls."""
        if self._inventory_syncing:
            return
        self._inventory_syncing = True
        self._inventory_sync_error = None
        self._notify_association_controls()
        try:
            await self.reload_devices()
        except Exception as err:
            self._inventory_sync_error = str(err)
            raise
        finally:
            self._inventory_syncing = False
            self._notify_association_controls()

    def set_association_category(self, category: str) -> None:
        """Choose a usage category and its first valid product family."""
        choices = self._association_choices(category)
        if not choices:
            raise ValueError(
                f"No product in {category!r} is supported by this TYDOM gateway"
            )
        self._association_category = category
        choice = next(
            (choice for choice in choices if choice.label == self._association_product),
            choices[0],
        )
        self._association_product = choice.label
        self._association_profile = choice.profile_id
        self._ensure_association_channel()
        self._notify_association_controls()

    def set_association_product(self, label: str) -> None:
        """Choose one product family from the current category."""
        for choice in self._association_choices():
            if choice.label == label:
                self._association_product = choice.label
                self._association_profile = choice.profile_id
                self._ensure_association_channel()
                self._notify_association_controls()
                return
        raise ValueError(
            f"{label!r} is not available for {self._association_category!r}"
        )

    def set_association_usage(self, category: str) -> None:
        """Choose a documented usage compatible with the selected product."""
        if category not in self.association_usage_labels:
            raise ValueError(
                f"{category!r} is not available for {self._association_product!r}"
            )
        choice = next(
            choice
            for choice in self._association_choices(category)
            if choice.label == self._association_product
        )
        self._association_category = category
        self._association_profile = choice.profile_id
        self._notify_association_controls()

    def _ensure_association_channel(self) -> None:
        """Keep the selected physical channel valid after a product change."""
        choices = self.association_channel_labels
        if choices and self._association_channel not in choices:
            self._association_channel = choices[0]

    def set_association_channel(self, channel: str) -> None:
        """Choose a documented physical channel for the selected product."""
        if channel not in self.association_channel_labels:
            raise ValueError(
                f"{channel!r} is not available for {self._association_product!r}"
            )
        self._association_channel = channel
        self._notify_association_controls()

    def set_association_name(self, name: str) -> None:
        """Set an optional friendly name for the product being associated."""
        normalized_name = " ".join(name.split())
        if len(normalized_name) > 64:
            raise ValueError("The association name must not exceed 64 characters")
        self._association_name = normalized_name
        self._notify_association_controls()

    async def start_selected_product_association(self) -> None:
        """Start association using the product selected in the gateway controls."""
        if self._association_profile is None:
            raise ValueError(
                "The selected category has no documented local TYDOM install profile"
            )
        choice = next(
            (
                choice
                for choice in get_association_choices(self._association_category)
                if choice.label == self._association_product
            ),
            None,
        )
        if choice is None or not self._is_association_choice_supported(choice):
            raise ValueError(
                f"{self._association_product} is not supported by this TYDOM gateway"
            )
        configured_product = GROUPABLE_ASSOCIATION_BY_LABEL.get(
            self._association_product
        )
        if configured_product and not self._is_groupable_product_supported(
            configured_product
        ):
            raise ValueError(
                f"{configured_product.label} is not supported by this TYDOM gateway"
            )
        product = self._selected_groupable_product()
        self._pending_association_name = self._association_name or None
        self._pending_association_known_device_ids = set(self.devices)
        standalone_recipe = (
            None
            if product is not None
            else get_standalone_association_recipe(
                self._association_category, self._association_product
            )
        )
        if standalone_recipe is not None:
            self._pending_standalone_association = (
                standalone_recipe,
                get_official_association_tutorial_id(
                    self._association_product, self._association_category
                ),
            )
            self._pending_standalone_known_device_ids = set(self.devices)
            self._pending_standalone_candidate_device_id = None
            self._pending_standalone_auto_finalize_failed = False
            # A few gateways announce a newly paired one-endpoint actuator in
            # /devices/data without first creating a /configs/file entry. Let
            # MessageHandler expose exactly a newly observed endpoint while
            # this selected standalone workflow is pending; finalisation then
            # writes the missing app-visible configuration.
            self._tydom_client._allow_configless_standalone_discovery = True
            self._tydom_client._configless_standalone_known_device_ids = {
                str(getattr(device, "_id", device_id))
                for device_id, device in self.devices.items()
            }
            # A previous version could leave exactly one radio-successful
            # endpoint as ``Produit N``.  Adopt that explicit raw placeholder
            # when the user starts the matching workflow again; do not guess
            # when several unconfigured products exist.
            raw_candidates = [
                device
                for device in self.devices.values()
                if type(device) is TydomDevice
                and (
                    str(getattr(device, "device_name", "")).startswith("Produit ")
                    or (
                        standalone_recipe.usage == "sensorSun"
                        and device.device_type == "sensor"
                        and getattr(device, "configSensor", None) == 8
                        and hasattr(device, "lightPower")
                    )
                )
            ]
            recovered_standalone = (
                raw_candidates[0] if len(raw_candidates) == 1 else None
            )
            if recovered_standalone is not None:
                self._pending_standalone_known_device_ids.discard(
                    recovered_standalone.device_id
                )
                self._pending_standalone_candidate_device_id = (
                    recovered_standalone.device_id
                )
        else:
            recovered_standalone = None
        if product is not None:
            # The receive loop may discover the product before the /devices/
            # install request has returned.  Arm its finalisation state before
            # the LAN request so that first radio frame is never relegated to
            # the manual "Configurer" fallback.
            self._pending_groupable_known_device_ids = set(self.devices)
            self._pending_groupable_association = (
                product,
                self._association_channel,
            )
            self._pending_groupable_name = self._association_name or None
            self._pending_groupable_candidate_device_id = None
            self._pending_groupable_auto_finalize_failed = False
            # Only expose a truly new endpoint (or one currently represented
            # by a generic Produit N object).  A configuration refresh during
            # listening must never turn every known remote into X3D remote
            # control <id> candidates.
            self._tydom_client._allow_configless_remote_discovery = True
            self._tydom_client._configless_remote_known_endpoint_ids = set(self.devices)
            self._tydom_client._configless_remote_generic_endpoint_ids = {
                device_id
                for device_id, device in self.devices.items()
                if type(device) is TydomDevice
            }
        try:
            payload = await start_product_association(self, self._association_profile)
        except Exception:
            self._pending_groupable_association = None
            self._pending_groupable_name = None
            self._pending_groupable_candidate_device_id = None
            self._tydom_client._allow_configless_remote_discovery = False
            self._tydom_client._configless_remote_known_endpoint_ids = set()
            self._tydom_client._configless_remote_generic_endpoint_ids = set()
            self._pending_groupable_known_device_ids.clear()
            self._clear_pending_standalone_association()
            self._clear_pending_association_name()
            raise
        if product is None:
            self._pending_groupable_association = None
            self._pending_groupable_name = None
            self._pending_groupable_known_device_ids.clear()
            self._tydom_client._allow_configless_remote_discovery = False
            self._tydom_client._configless_remote_known_endpoint_ids = set()
            self._tydom_client._configless_remote_generic_endpoint_ids = set()
        if recovered_standalone is not None:
            self._pending_standalone_auto_finalize_task = self._hass.async_create_task(
                self._async_auto_finalize_standalone_product(recovered_standalone)
            )
        elif standalone_recipe is not None:
            # Recover a product that is already paired on the radio but was
            # never written to /configs/file.  This is deliberately a single
            # best-effort data refresh: it makes a retry adopt the existing
            # endpoint without asking the user to repeat the physical ritual,
            # while a later physical association is still delivered normally.
            refresh_data = getattr(self._tydom_client, "get_devices_data", None)
            if callable(refresh_data):
                try:
                    await refresh_data()
                except Exception:
                    LOGGER.debug(
                        "Could not immediately probe for a standalone "
                        "association candidate",
                        exc_info=True,
                    )
        LOGGER.info(
            "Started gateway association for %s on config entry %s",
            payload,
            self._entry.entry_id,
        )

    def _add_discovered_entities(self, entities: list) -> None:
        """Add discovered entities to the platform matching their entity type."""
        binary_sensors = [
            entity for entity in entities if isinstance(entity, BinarySensorEntity)
        ]
        sensors = [
            entity for entity in entities if not isinstance(entity, BinarySensorEntity)
        ]

        if sensors and self.add_sensor_callback is not None:
            self.add_sensor_callback(sensors)
        if binary_sensors and self.add_binary_sensor_callback is not None:
            self.add_binary_sensor_callback(binary_sensors)

    async def setup(self, connection: ClientWebSocketResponse) -> None:
        """Listen to tydom events."""
        # wait for callbacks to become available
        while not self.ready():
            if self._shutting_down:
                return
            await asyncio.sleep(1)
        LOGGER.debug("Listen to tydom events")

        # Validate data consistency after initial setup
        await self._validate_data_consistency()
        while not self._shutting_down:
            devices = await self._tydom_client.consume_messages()
            if self._shutting_down:
                return
            if devices is not None:
                for device in devices:
                    if device.device_id not in self.devices:
                        self.devices[device.device_id] = device
                        STRUCTURED_LOGGER.device_operation(
                            "debug",
                            "create",
                            device.device_id,
                            type=device.device_type,
                            name=device.device_name,
                        )
                        await self.create_ha_device(device)
                    else:
                        # Check for collision: same device_id but different device
                        stored_device = self.devices[device.device_id]
                        is_type_promotion = (
                            type(stored_device) is TydomDevice
                            and type(device) is not TydomDevice
                        )
                        if stored_device is not device and (
                            is_type_promotion
                            or stored_device.device_name != device.device_name
                            or stored_device.device_type != device.device_type
                        ):
                            # A product first seen by TYDOM as an unconfigured
                            # ``Produit N`` is parsed as the generic base class.
                            # During an explicit association we can subsequently
                            # identify that same endpoint as a remote or wall
                            # switch.  Updating only the generic object's name
                            # and type loses its protocol-specific metadata, so
                            # the association finalisation can never run.
                            if is_type_promotion:
                                STRUCTURED_LOGGER.device_operation(
                                    "info",
                                    "device_type_promoted",
                                    device.device_id,
                                    stored_type=stored_device.device_type,
                                    promoted_type=device.device_type,
                                )
                                self.devices[device.device_id] = device
                                await self.create_ha_device(device)
                                continue

                            # Resolve collision: update stored device with new data
                            STRUCTURED_LOGGER.device_operation(
                                "warning",
                                "collision_resolved",
                                device.device_id,
                                stored_name=stored_device.device_name,
                                stored_type=stored_device.device_type,
                                new_name=device.device_name,
                                new_type=device.device_type,
                                action="updating_existing",
                            )

                            # Update stored device attributes to match new device
                            # This ensures consistency and prevents future collisions
                            if hasattr(stored_device, "_name"):
                                stored_device._name = device.device_name
                            if hasattr(stored_device, "_type"):
                                stored_device._type = device.device_type

                            # Also update metadata if available
                            if (
                                hasattr(device, "_metadata")
                                and device._metadata is not None
                            ):
                                if hasattr(stored_device, "_metadata"):
                                    stored_device._metadata = device._metadata

                        LOGGER.debug(
                            "update device %s : %s",
                            device.device_id,
                            self.devices[device.device_id],
                        )
                        await self.update_ha_device(
                            self.devices[device.device_id], device
                        )
                self._refresh_group_members()

    def _refresh_group_members(self) -> None:
        """Resolve group members again after each protocol message batch."""
        for device in self.devices.values():
            if not isinstance(device, TydomGroup):
                continue
            ha_device = getattr(device, "_ha_device", None)
            if ha_device is not None and hasattr(ha_device, "refresh_members"):
                ha_device.refresh_members()

    async def create_ha_device(self, device: TydomDevice) -> None:
        """Create a new HA device using factory pattern.

        This method uses a factory pattern to delegate device-specific creation
        logic to specialized methods. This improves maintainability and reduces
        complexity compared to a large match/case statement.

        Args:
            device: TydomDevice instance to create Home Assistant entity for

        Raises:
            None: Exceptions are caught and logged, but do not propagate

        """
        device_type = type(device)
        factory = self._device_factories.get(device_type)

        if factory is None:
            LOGGER.error(
                "Unsupported device type: %s for device %s",
                device_type.__name__,
                device.device_id,
            )
            return

        try:
            await factory(device)
            self._maybe_create_device_association_buttons(device)
        except Exception as e:
            LOGGER.exception(
                "Error creating HA device for %s (%s): %s",
                device.device_id,
                device_type.__name__,
                e,
            )

    async def _create_tydom_device(self, device: Tydom) -> None:
        """Create Tydom gateway device."""
        LOGGER.debug("Create Tydom gateway %s", device.device_id)
        self.devices[device.device_id] = device
        ha_device = HATydom(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_update_callback is not None:
            self.add_update_callback([ha_device])
        self._add_discovered_entities(ha_device.get_sensors())
        # Le bouton de rechargement est créé dans ready() pour être toujours présent

    async def _create_shutter_device(self, device: TydomShutter) -> None:
        """Create shutter/cover device."""
        LOGGER.debug("Create cover %s", device.device_id)
        ha_device = HACover(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_cover_callback is not None:
            self.add_cover_callback([ha_device])
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_energy_device(self, device: TydomEnergy) -> None:
        """Create energy consumption device."""
        LOGGER.debug("Create conso %s", device.device_id)
        ha_device = HAEnergy(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        # HAEnergy itself carries no device_class/unit/value: it only groups
        # the per-attribute sensors below and must not be added as an entity,
        # or it shows up as a useless "unknown" sensor (e.g. sensor.tywatt_tywatt).
        self._add_discovered_entities(ha_device.get_sensors())
        # The device has no energy* attribute yet at first discovery (they only
        # appear once the first cdata poll response is parsed), so this rarely
        # creates the button here -- update_ha_device() does it once data arrives.
        self._maybe_create_refresh_energy_button(device, ha_device)

    def _maybe_create_refresh_energy_button(
        self, device: TydomEnergy, ha_device: HAEnergy
    ) -> None:
        """Create one on-demand refresh button per real Tywatt device.

        Some TydomEnergy devices only carry outTemperature (e.g. an outdoor
        probe reusing this class), not real Tywatt consumption data -- only
        attach the button to a device that actually exposes one of the polled
        cdata attributes (energyIndex/energyInstant/energyHisto/energyDistrib),
        or it ends up on the wrong HA device.
        """
        has_energy_attrs = any(
            key.startswith("energy") for key in vars(device) if not key.startswith("_")
        )
        device_key = device.device_id
        if (
            has_energy_attrs
            and device_key not in self._refresh_energy_buttons_created
            and self.add_button_callback is not None
        ):
            refresh_energy_button = HARefreshEnergyButton(self, self._hass, ha_device)
            self.add_button_callback([refresh_energy_button])
            self._refresh_energy_buttons_created.add(device_key)
            LOGGER.debug("Created energy refresh button for %s", device_key)

    async def _create_smoke_device(self, device: TydomSmoke) -> None:
        """Create smoke detector device."""
        LOGGER.debug("Create smoke %s", device.device_id)
        ha_device = HASmoke(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities([ha_device, *ha_device.get_sensors()])

    async def _create_boiler_device(self, device: TydomBoiler) -> None:
        """Create boiler/climate device."""
        LOGGER.debug("Create boiler %s", device.device_id)
        ha_device = HaClimate(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_climate_callback is not None:
            self.add_climate_callback([ha_device])
        if device.is_area_trv and self.add_button_callback is not None:
            self.add_button_callback([HACancelBoostButton(device, self._hass)])
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_window_device(self, device: TydomWindow) -> None:
        """Create window device (cover if motorized, else binary_sensor)."""
        LOGGER.debug("Create window %s", device.device_id)

        # Décision automatique selon les attributs du device
        if any(
            hasattr(device, a) for a in ["position", "positionCmd", "level", "levelCmd"]
        ):
            LOGGER.debug(
                "Window %s has motor control → adding as cover",
                device.device_id,
            )
            ha_device = HaWindow(device, self._hass)
            if self.add_cover_callback:
                self.add_cover_callback([ha_device])
        else:
            LOGGER.debug(
                "Window %s is passive → adding as binary_sensor",
                device.device_id,
            )
            ha_device = HaWindowOpening(device, self._hass)
            if self.add_binary_sensor_callback:
                self.add_binary_sensor_callback([ha_device])

        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_door_device(self, device: TydomDoor) -> None:
        """Create door device (cover if motorized, else binary_sensor)."""
        LOGGER.debug("Create door %s", device.device_id)

        # Décision automatique selon les attributs du device
        # podPosition : attribut utilisé par les portes motorisées KLINE
        # (device_type "belmDoor" / "klineDoor"), en lecture/écriture avec
        # les valeurs OPEN / CLOSE / LOCK.
        if any(
            hasattr(device, a)
            for a in [
                "position",
                "positionCmd",
                "level",
                "levelCmd",
                "podPosition",
            ]
        ):
            LOGGER.debug(
                "Door %s has motor control → adding as cover", device.device_id
            )
            ha_device = HaDoor(device, self._hass)
            if self.add_cover_callback:
                self.add_cover_callback([ha_device])
        else:
            LOGGER.debug(
                "Door %s is passive → adding as binary_sensor", device.device_id
            )
            ha_device = HaDoorOpening(device, self._hass)
            if self.add_binary_sensor_callback:
                self.add_binary_sensor_callback([ha_device])

        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_gate_device(self, device: TydomGate) -> None:
        """Create gate device."""
        LOGGER.debug("Create gate %s", device.device_id)
        if device.is_toggle_only:
            ha_device = HAButton(
                device,
                self._hass,
                "Toggle",
                "toggle",
                icon="mdi:gate",
                primary=True,
            )
            if self.add_button_callback is not None:
                self.add_button_callback([ha_device])
        else:
            ha_device = HaGate(device, self._hass)
            if self.add_cover_callback is not None:
                self.add_cover_callback([ha_device])
        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_garage_device(self, device: TydomGarage) -> None:
        """Create garage device."""
        LOGGER.debug("Create garage %s", device.device_id)
        if device.is_toggle_only:
            ha_device = HAButton(
                device,
                self._hass,
                "Toggle",
                "toggle",
                icon="mdi:garage",
                primary=True,
            )
            if self.add_button_callback is not None:
                self.add_button_callback([ha_device])
        else:
            ha_device = HaGarage(device, self._hass)
            if self.add_cover_callback is not None:
                self.add_cover_callback([ha_device])
        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_light_device(self, device: TydomLight) -> None:
        """Create light device."""
        LOGGER.debug("Create light %s", device.device_id)
        ha_device = HaLight(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_light_callback is not None:
            self.add_light_callback([ha_device])
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_interrupter_device(self, device: TydomInterrupter) -> None:
        """Create a wall-switch event entity and one battery diagnostic."""
        LOGGER.debug("Create wall-switch button %s", device.device_id)
        ha_device = HAInterrupterEvent(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_event_callback is not None:
            self.add_event_callback([ha_device])

        battery = self._interrupter_battery_entities.get(device.physical_device_id)
        if battery is None:
            battery = HAInterrupterBattery(device, self._hass)
            self._interrupter_battery_entities[device.physical_device_id] = battery
            if self.add_binary_sensor_callback is not None:
                self.add_binary_sensor_callback([battery])
        else:
            battery.add_device(device)

    async def _create_switch_device(self, device: TydomPlug | TydomSwitch) -> None:
        """Create a switch device for a controllable binary output."""
        LOGGER.debug("Create switch %s", device.device_id)
        ha_device = HASwitch(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_switch_callback is not None:
            self.add_switch_callback([ha_device])
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_alarm_device(self, device: TydomAlarm) -> None:
        """Create alarm device."""
        LOGGER.debug("Create alarm %s", device.device_id)
        ha_device = HaAlarm(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_alarm_callback is not None:
            self.add_alarm_callback([ha_device])
        if self.add_button_callback is not None:
            self.add_button_callback([HAAlarmAcknowledgeButton(device, self._hass)])
        self._add_discovered_entities(
            [
                HAAlarmPendingEventsSensor(device, self._hass),
                *ha_device.get_sensors(),
            ]
        )

    async def _create_weather_device(self, device: TydomWeather) -> None:
        """Create weather device."""
        LOGGER.debug("Create weather %s", device.device_id)
        ha_device = HaWeather(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_weather_callback is not None:
            self.add_weather_callback([ha_device])
        self._add_discovered_entities(ha_device.get_sensors())

    async def _create_water_device(self, device: TydomWater) -> None:
        """Create water/moisture device."""
        LOGGER.debug("Create moisture %s", device.device_id)
        ha_device = HaMoisture(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities([ha_device, *ha_device.get_sensors()])

    async def _create_thermo_device(self, device: TydomThermo) -> None:
        """Create thermostat device."""
        LOGGER.debug("Create thermo %s", device.device_id)
        ha_device = HaThermo(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities([ha_device, *ha_device.get_sensors()])

    async def _create_sun_device(self, device: TydomSun) -> None:
        """Create a Tysense Sun irradiance sensor."""
        LOGGER.debug("Create Tysense Sun %s", device.device_id)
        ha_device = HaSun(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities([ha_device, *ha_device.get_sensors()])

    async def _create_scene_device(self, device: TydomScene) -> None:
        """Create a normal scene or aggregate TWC commands into one cover."""
        LOGGER.debug("Create scene %s", device.device_id)
        ha_device = HAScene(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        action = ha_device.twc_action
        if action is None:
            if self.add_scene_callback is not None:
                self.add_scene_callback([ha_device])
            return

        zone_key = ha_device._get_zone_from_scene()
        controller_id = ha_device._find_tywell_device(zone_key)
        parent_key = controller_id or f"tywell_control_{zone_key or 'default'}"
        # A Tywell Control can expose more than one UP/DOWN/STOP trio.  The
        # scenario names only contain the action, so group by the exact target
        # set as well as its parent.  Otherwise a second Tywell Control (or a
        # second shutter zone) overwrites the first controller's actions.
        target_ids = sorted(ha_device._get_affected_device_ids())
        target_key = "-".join(target_ids) if target_ids else "unknown-targets"
        grouping_key = f"{parent_key}:{zone_key or 'default'}:{target_key}"
        scenes = self._twc_scene_sets.setdefault(grouping_key, {})
        scenes[action] = ha_device

        cover = self._twc_cover_entities.get(grouping_key)
        if cover is None:
            cover = HATwcShutterCover(
                grouping_key,
                scenes,
                ha_device,
                self._hass,
                zone_key,
            )
            self._twc_cover_entities[grouping_key] = cover
            self.ha_devices[f"twc_cover_{grouping_key}"] = cover
            if self.add_cover_callback is not None:
                self.add_cover_callback([cover])
            LOGGER.debug(
                "Created Tywell shutter cover %s from scenario %s",
                grouping_key,
                device.device_name,
            )
        else:
            cover.refresh_scenes(ha_device)

    async def _create_group_device(self, device: TydomGroup) -> None:
        """Create a native Home Assistant entity for a controllable group."""
        LOGGER.debug("Create %s group %s", device.group_usage, device.device_id)
        if device.group_usage == "light":
            ha_device = HALightGroup(device, self._hass)
            callback = self.add_light_callback
        elif device.group_usage in {"awning", "shutter"}:
            ha_device = HACoverGroup(device, self._hass)
            callback = self.add_cover_callback
        elif device.group_usage == "plug":
            ha_device = HASwitchGroup(device, self._hass)
            callback = self.add_switch_callback
        else:
            LOGGER.debug(
                "Ignore unsupported group %s (%s)",
                device.device_id,
                device.group_usage,
            )
            return

        self.ha_devices[device.device_id] = ha_device
        if callback is not None:
            callback([ha_device])

    async def _create_moment_device(self, device: TydomMoment) -> None:
        """Create moment device."""
        LOGGER.debug("Create moment %s", device.device_id)
        ha_device = HAMoment(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_switch_callback is not None:
            self.add_switch_callback([ha_device])

    async def _create_remote_control_device(self, device: TydomRemoteControl) -> None:
        """Create an event entity for a remote button and one battery diagnostic."""
        LOGGER.debug("Create remote-control button %s", device.device_id)
        migrate_legacy_remote_endpoint(
            self._hass,
            self._entry.entry_id,
            device.device_id,
        )
        ha_device = HARemoteEvent(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        if self.add_event_callback is not None:
            self.add_event_callback([ha_device])

        battery = self._remote_battery_entities.get(device.physical_device_id)
        if battery is None:
            battery = HARemoteBattery(device, self._hass)
            self._remote_battery_entities[device.physical_device_id] = battery
            if self.add_binary_sensor_callback is not None:
                self.add_binary_sensor_callback([battery])
        else:
            battery.add_device(device)

    async def _create_generic_device(self, device: TydomDevice) -> None:
        """Create generic sensor device."""
        LOGGER.debug("Create generic sensor %s", device.device_id)
        primary_binary_attribute = next(
            (
                attribute
                for attribute in ("on", "state")
                if hasattr(device, attribute)
                and is_binary_attribute(device, attribute, getattr(device, attribute))
            ),
            None,
        )
        if primary_binary_attribute is not None:
            ha_device = HAGenericBinarySensor(
                device, self._hass, primary_binary_attribute
            )
        else:
            ha_device = HASensor(device, self._hass)
        self.ha_devices[device.device_id] = ha_device
        self._add_discovered_entities([ha_device, *ha_device.get_sensors()])

        # Try to detect if device should also be a switch
        # Check for on/off capabilities that aren't already handled
        if device.device_type not in ["light", "cover", "alarm"]:
            has_on_off = (
                hasattr(device, "level")
                or hasattr(device, "on")
                or hasattr(device, "state")
            )
            # Check if device has levelCmd or onCmd in metadata (writable)
            has_control = False
            if device._metadata is not None:
                for key in device._metadata:
                    if key.endswith("Cmd") or key in ["level", "on", "state"]:
                        has_control = True
                        break

            if has_on_off and has_control:
                LOGGER.debug(
                    "Device %s has on/off capabilities, creating switch",
                    device.device_id,
                )
                switch_device = HASwitch(device, self._hass)
                if self.add_switch_callback is not None:
                    self.add_switch_callback([switch_device])

    async def update_ha_device(self, stored_device, device):
        """Update HA device values."""
        try:
            await stored_device.update_device(device)
            ha_device = self.ha_devices[device.device_id]

            # Special handling for scenes: invalidate caches and recreate relations
            if isinstance(device, TydomScene) and isinstance(ha_device, HAScene):
                await ha_device.async_device_update(device)

            new_sensors = ha_device.get_sensors()
            if new_sensors:
                # add new sensors
                LOGGER.debug(
                    "Ajout de %d nouveau(x) capteur(s) pour le device %s: %s",
                    len(new_sensors),
                    device.device_id,
                    [s._attr_name for s in new_sensors],
                )
                self._add_discovered_entities(new_sensors)
            if isinstance(ha_device, HAEnergy):
                self._maybe_create_refresh_energy_button(stored_device, ha_device)
            self._maybe_create_device_association_buttons(stored_device)
            # ha_device.publish_updates()
            # ha_device.update()
        except KeyError as e:
            LOGGER.warning(
                "Device %s non trouvé dans ha_devices lors de la mise à jour: %s",
                device.device_id,
                e,
            )
        except Exception:
            LOGGER.exception(
                "Erreur lors de la mise à jour du device %s", device.device_id
            )

    def _maybe_create_device_association_buttons(self, device: TydomDevice) -> None:
        """Expose product controls, including permanent removal for every product."""
        if self.add_button_callback is None:
            return

        # Scenarios, moments and groups are configuration objects, not radio
        # products. In particular, TWC_UP/DOWN/STOP are three scenarios that
        # form one virtual shutter cover. Giving each of them product-removal
        # controls creates misleading device pages and can never remove a
        # physical product.
        if isinstance(device, (TydomScene, TydomMoment, TydomGroup)):
            return

        # Some protocol endpoints are auxiliary data sources grouped under a
        # physical product in Home Assistant (for example, the Tywell weather
        # endpoint).  They are not independently removable radio products;
        # exposing a removal control for them duplicates the physical
        # controller's button and risks targeting the wrong endpoint.
        registry_device_id = str(
            getattr(device, "registry_device_id", device.device_id)
        )
        if registry_device_id != device.device_id:
            return

        pending_standalone = getattr(self, "_pending_standalone_association", None)
        pending_standalone_known_device_ids = getattr(
            self, "_pending_standalone_known_device_ids", set()
        )
        is_new_standalone_candidate = (
            pending_standalone is not None
            and type(device) is TydomDevice
            and device.device_id not in pending_standalone_known_device_ids
        )
        if (
            is_new_standalone_candidate
            and not getattr(self, "_pending_standalone_auto_finalize_failed", False)
            and getattr(self, "_pending_standalone_candidate_device_id", None) is None
        ):
            # A raw ``Produit N`` must be promoted before HA exposes its
            # generic controls.  Delay one loop iteration for the gateway to
            # finish publishing the matching endpoint metadata.
            self._pending_standalone_candidate_device_id = device.device_id
            self._pending_standalone_auto_finalize_task = self._hass.async_create_task(
                self._async_auto_finalize_standalone_product(device)
            )
            return
        if (
            pending_standalone is not None
            and device.device_id not in pending_standalone_known_device_ids
            and type(device) is not TydomDevice
        ):
            # Products such as Tywatt publish their definitive configuration
            # themselves.  Never overwrite that gateway-owned metadata.
            self._clear_pending_standalone_association()

        self._maybe_apply_pending_association_name(device)

        buttons = []
        finalization_key = (device.device_id, "finalize_groupable_product")
        pending_association = self._pending_groupable_association
        # A configuration reload can temporarily reconstruct an already known
        # remote endpoint as an ``X3D remote control``.  It must never be
        # mistaken for the channel currently being paired: doing so produces
        # a second candidate and exposes duplicate manual "Configurer" actions.
        # A pre-existing generic ``Produit N`` is the sole exception: it is a
        # genuine pending endpoint that needs promotion to the selected family.
        pending_generic_device_ids = getattr(
            self._tydom_client,
            "_configless_remote_generic_endpoint_ids",
            set(),
        )
        is_new_groupable_candidate = (
            pending_association is not None
            and (
                device.device_id not in self._pending_groupable_known_device_ids
                or device.device_id in pending_generic_device_ids
            )
            and (
                (
                    isinstance(device, TydomRemoteControl)
                    and device.device_name.startswith("X3D remote control ")
                )
                or isinstance(device, TydomInterrupter)
            )
        )
        if (
            is_new_groupable_candidate
            and not self._pending_groupable_auto_finalize_failed
            and self._pending_groupable_candidate_device_id is None
        ):
            # A selected TYXIA channel supplies all necessary metadata.  Wait
            # briefly for a second discovery event: if another product appears
            # too, keep the conservative manual choice instead of guessing.
            self._pending_groupable_candidate_device_id = device.device_id
            self._pending_groupable_auto_finalize_task = self._hass.async_create_task(
                self._async_auto_finalize_groupable_product(device)
            )
            return
        if (
            is_new_groupable_candidate
            and not self._pending_groupable_auto_finalize_failed
            and self._pending_groupable_candidate_device_id != device.device_id
        ):
            candidate_id = self._pending_groupable_candidate_device_id
            self._pending_groupable_auto_finalize_failed = True
            self._pending_groupable_candidate_device_id = None
            if self._pending_groupable_auto_finalize_task is not None:
                self._pending_groupable_auto_finalize_task.cancel()
                self._pending_groupable_auto_finalize_task = None
            if (
                candidate_id is not None
                and (candidate := self.devices.get(candidate_id)) is not None
            ):
                self._maybe_create_device_association_buttons(candidate)
        if (
            finalization_key not in self._device_association_buttons_created
            and is_new_groupable_candidate
            and (
                self._pending_groupable_auto_finalize_failed
                or self._pending_groupable_candidate_device_id is None
            )
        ):
            product, channel = pending_association
            buttons.append(
                HAGroupableProductFinalizeAssociationButton(
                    device,
                    self._hass,
                    product.label,
                    channel,
                    product.usage_label,
                    self._finalize_groupable_product_association,
                )
            )
            self._device_association_buttons_created.add(finalization_key)
        removal_key = (device.device_id, "remove_association")
        if (
            removal_key not in self._device_association_buttons_created
            and getattr(device, "_id", None) is not None
        ):
            buttons.append(
                HADeviceRemovalButton(
                    device,
                    self._hass,
                    self._remove_product_association_and_reload,
                )
            )
            self._device_association_buttons_created.add(removal_key)

        for command in (ASSOCIATION_COMMAND, IDENTIFY_COMMAND):
            key = (device.device_id, command)
            if key in self._device_association_buttons_created:
                continue
            if not supports_command(device, command):
                continue
            buttons.append(HADeviceAssociationButton(device, self._hass, command))
            self._device_association_buttons_created.add(key)

        if buttons:
            self._enable_existing_removal_buttons(buttons)
            self.add_button_callback(buttons)

    def _enable_existing_removal_buttons(self, buttons: list[object]) -> None:
        """Migrate the enabled state of permanent-removal controls.

        Home Assistant preserves ``disabled_by`` in its entity registry, even
        after an integration changes an entity's enabled-by-default setting.
        Product controls are deliberate user actions and must be available.
        Conversely, the gateway's own control would remove the complete
        integration: migrate pre-existing gateway entities to disabled too,
        rather than only applying that default to newly created entities.
        """
        if self._hass is None:
            return
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(self._hass)
        for button in buttons:
            if not isinstance(button, HADeviceRemovalButton):
                continue
            if isinstance(button._device, Tydom):
                entity_id = registry.async_get_entity_id(
                    "button", DOMAIN, button.unique_id
                )
                if entity_id is None:
                    continue
                entry = registry.async_get(entity_id)
                if entry is not None and entry.disabled_by is None:
                    registry.async_update_entity(
                        entity_id,
                        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
                    )
                continue
            entity_id = registry.async_get_entity_id("button", DOMAIN, button.unique_id)
            if entity_id is None:
                continue
            entry = registry.async_get(entity_id)
            if entry is not None and entry.disabled_by is not None:
                registry.async_update_entity(entity_id, disabled_by=None)

    async def _remove_product_association_and_reload(self, device) -> None:
        """Remove a product, then immediately rebuild the local inventory."""
        await remove_product_association(device)
        await self.reload_devices_with_status()

    async def _async_auto_finalize_standalone_product(
        self, device: TydomDevice
    ) -> None:
        """Write the selected usage for one newly discovered raw endpoint."""
        await asyncio.sleep(1)
        pending = self._pending_standalone_association
        if (
            pending is None
            or self._pending_standalone_auto_finalize_failed
            or self._pending_standalone_candidate_device_id != device.device_id
        ):
            return
        recipe, tutorial_id = pending
        try:
            name = await configure_standalone_product(
                device,
                recipe,
                tutorial_id,
                self._pending_association_name,
            )
        except Exception:
            LOGGER.exception(
                "Automatic post-discovery configuration failed for raw product %s; "
                "keeping it available for diagnosis",
                device.device_id,
            )
            self._pending_standalone_auto_finalize_failed = True
            self._pending_standalone_candidate_device_id = None
            self._pending_standalone_auto_finalize_task = None
            self._clear_pending_association_name()
            self._maybe_create_device_association_buttons(device)
            return

        LOGGER.info("Configured discovered product %s as %s", device.device_id, name)
        self._clear_pending_association_name()
        self._clear_pending_standalone_association()
        await self.reload_devices_with_status()

    async def _async_auto_finalize_groupable_product(
        self, device: TydomRemoteControl | TydomInterrupter
    ) -> None:
        """Finalize one unambiguous discovered TYXIA channel automatically."""
        await asyncio.sleep(1)
        if (
            self._pending_groupable_association is None
            or self._pending_groupable_auto_finalize_failed
            or self._pending_groupable_candidate_device_id != device.device_id
        ):
            return
        try:
            await self._finalize_groupable_product_association(
                device, self._pending_groupable_association[1]
            )
        except Exception:
            LOGGER.exception(
                "Automatic post-discovery configuration failed for %s; "
                "keeping the manual finalization action",
                device.device_id,
            )
            self._pending_groupable_auto_finalize_failed = True
            self._pending_groupable_candidate_device_id = None
            self._pending_groupable_auto_finalize_task = None
            self._tydom_client._allow_configless_remote_discovery = False
            self._tydom_client._configless_remote_known_endpoint_ids = set()
            self._tydom_client._configless_remote_generic_endpoint_ids = set()
            self._maybe_create_device_association_buttons(device)

    async def _finalize_groupable_product_association(
        self, device: TydomRemoteControl | TydomInterrupter, channel: str
    ) -> None:
        """Persist the selected product channel, then rebuild HA entities."""
        pending_association = self._pending_groupable_association
        if pending_association is None:
            raise ValueError("No multi-channel product association is pending")
        product, expected_channel = pending_association
        if channel != expected_channel:
            raise ValueError(f"This {product.label} association is no longer pending")
        name = await configure_groupable_product(
            device, product, channel, self._pending_groupable_name
        )
        self._rename_new_groupable_device(device, name, product.label)
        self._pending_groupable_association = None
        self._pending_groupable_name = None
        self._clear_pending_association_name()
        self._pending_groupable_known_device_ids.clear()
        self._pending_groupable_candidate_device_id = None
        self._pending_groupable_auto_finalize_failed = False
        self._pending_groupable_auto_finalize_task = None
        self._tydom_client._allow_configless_remote_discovery = False
        self._tydom_client._configless_remote_known_endpoint_ids = set()
        self._tydom_client._configless_remote_generic_endpoint_ids = set()
        LOGGER.info("Configured %s %s as %s", product.label, channel, name)
        await self.reload_devices_with_status()

    def _rename_new_groupable_device(
        self,
        device: TydomRemoteControl | TydomInterrupter,
        name: str,
        model: str,
    ) -> None:
        """Replace the transient radio-discovery name in HA's device registry.

        A fresh X3D device necessarily arrives before its related-endpoint
        configuration.  Keep a user-created name intact, but replace only the
        temporary ``X3D remote control <id>`` label with the already known
        product name as soon as configuration succeeds.
        """
        registry = dr.async_get(self._hass)
        entry = registry.async_get_device(
            identifiers={(DOMAIN, device.registry_device_id)}
        )
        if entry is None:
            return
        if entry.name is not None and not entry.name.startswith("X3D remote control "):
            return
        registry.async_update_device(entry.id, name=name, model=model)

    def _maybe_apply_pending_association_name(self, device: TydomDevice) -> None:
        """Name one newly discovered non-groupable product in Home Assistant.

        Groupable products are named during their own configuration transaction,
        because that also writes their TYDOM related-endpoint group. Other
        product formats are managed by the gateway, so only update HA's device
        registry here rather than risk altering an unknown TYDOM document.
        """
        if (
            self._pending_groupable_association is not None
            or self._selected_groupable_product() is not None
        ):
            return
        name = self._pending_association_name
        if not name or device.device_id in self._pending_association_known_device_ids:
            return
        registry = dr.async_get(self._hass)
        entry = registry.async_get_device(
            identifiers={(DOMAIN, device.registry_device_id)}
        )
        if entry is None:
            return
        discovered_name = device.device_name
        if (
            entry.name is None
            or entry.name
            in {
                discovered_name,
            }
            or entry.name.startswith("X3D remote control ")
        ):
            registry.async_update_device(entry.id, name=name)
        self._clear_pending_association_name()

    def _clear_pending_association_name(self) -> None:
        """Forget the association-name request once it has been handled."""
        self._pending_association_name = None
        self._pending_association_known_device_ids.clear()

    def _clear_pending_standalone_association(self) -> None:
        """Forget the one-endpoint configuration request after discovery."""
        self._pending_standalone_association = None
        self._pending_standalone_known_device_ids.clear()
        self._pending_standalone_candidate_device_id = None
        self._pending_standalone_auto_finalize_task = None
        self._pending_standalone_auto_finalize_failed = False
        self._tydom_client._allow_configless_standalone_discovery = False
        self._tydom_client._configless_standalone_known_device_ids = set()

    async def ping(self) -> None:
        """Periodically send pings."""
        while not self._shutting_down:
            await self._tydom_client.ping()
            await self._interruptible_sleep(30)

    async def refresh_all(self) -> None:
        """Periodically refresh all metadata and data.

        It allows new devices to be discovered.
        """
        while not self._shutting_down:
            await self._tydom_client.get_info()
            await self._tydom_client.put_api_mode()
            await self._tydom_client.post_refresh()
            await self._tydom_client.get_configs_file()
            await self._tydom_client.get_groups()
            await self._tydom_client.get_devices_meta()
            await self._tydom_client.get_devices_cmeta()
            await self._tydom_client.get_devices_data()
            await self._tydom_client.get_scenarii()
            await self._tydom_client.get_moments()
            await self._interruptible_sleep(600)

    async def refresh_data_1s(self) -> None:
        """Refresh data for devices in list."""
        while not self._shutting_down:
            await self._tydom_client.poll_devices_data_1s()
            await self._interruptible_sleep(1)

    def _rebuild_polling_cache(self) -> None:
        """Rebuild polling cache efficiently.

        This method scans all devices and their metadata to build a cache
        mapping (device_key, attribute_name) to polling intervals based on
        the validity metadata. The cache is rebuilt periodically to account
        for metadata changes.

        The cache structure: {(device_key, attr_name): interval_seconds}
        - Devices with validity=INFINITE or upToDate are not cached (no polling)
        - Devices with validity=ES_SUPERVISION are cached with 300s interval
        - Devices with validity=SENSOR_SUPERVISION are cached with 60s interval
        - Devices with validity=SYNCHRO_SUPERVISION are cached with 30s interval
        """
        new_cache: dict[tuple[str, str], int] = {}
        for device_key, device in self.devices.items():
            if not hasattr(device, "_metadata") or device._metadata is None:
                continue
            for attr_name, attr_metadata in device._metadata.items():
                if isinstance(attr_metadata, dict):
                    validity = attr_metadata.get("validity")
                    interval = get_polling_interval_for_validity(validity)
                    if interval is not None:
                        new_cache[(device_key, attr_name)] = interval

        # Update cache atomically
        self._polling_cache = new_cache
        LOGGER.debug("Polling cache rebuilt with %d entries", len(self._polling_cache))

    async def refresh_data(self) -> None:
        """Periodically refresh data for devices which don't do push.

        Uses adaptive polling based on validity metadata:
        - INFINITE/upToDate: No polling needed
        - ES_SUPERVISION: Poll every 5 minutes
        - SENSOR_SUPERVISION: Poll every 1 minute
        - SYNCHRO_SUPERVISION: Poll every 30 seconds

        The polling groups are rebuilt every 5 minutes to account for
        metadata changes.
        """
        while not self._shutting_down:
            current_time = time.monotonic()

            # Rebuild cache only if expired
            if current_time - self._polling_cache_timestamp > self._polling_cache_ttl:
                self._rebuild_polling_cache()
                self._polling_cache_timestamp = current_time

            # Group devices by interval from cache
            interval_groups: dict[int, set[str]] = {}
            for (device_key, _attr_name), interval in self._polling_cache.items():
                interval_groups.setdefault(interval, set()).add(device_key)

            active_intervals = set(interval_groups)
            self._next_poll_due = {
                interval: due
                for interval, due in self._next_poll_due.items()
                if interval in active_intervals
            }

            # Poll devices according to their intervals
            if interval_groups:
                # Sort intervals from shortest to longest
                sorted_intervals = sorted(interval_groups.keys())
                shortest_interval = sorted_intervals[0]

                # Poll every interval group whose due time has elapsed, not just
                # the shortest one - otherwise ES_SUPERVISION/SENSOR_SUPERVISION
                # devices are starved forever as soon as any device needs
                # SYNCHRO_SUPERVISION (shortest_interval always wins otherwise).
                for interval, device_keys in interval_groups.items():
                    if current_time < self._next_poll_due.get(interval, 0):
                        continue
                    self._next_poll_due[interval] = current_time + interval
                    for device_key in device_keys:
                        if device_key in self.devices:
                            device = self.devices[device_key]
                            if hasattr(device, "_tydom_client"):
                                try:
                                    await device._tydom_client.poll_device_data(
                                        device._id, device.device_endpoint
                                    )
                                except Exception as e:
                                    LOGGER.warning(
                                        "Error polling device %s: %s", device_key, e
                                    )

                # Sleep for the shortest interval so due longer-interval groups
                # still get checked promptly on the next wake-up.
                await self._interruptible_sleep(shortest_interval)
            else:
                # No devices need validity-based polling, use default refresh interval
                if self._refresh_interval > 0:
                    await self._interruptible_sleep(self._refresh_interval)
                else:
                    await self._interruptible_sleep(60)

    async def refresh_energy_now(self, device_id: str, endpoint_id: str | None) -> None:
        """Poll one Tywatt cdata endpoint immediately, on demand."""
        await self._tydom_client.poll_devices_data_5m(device_id, endpoint_id)

    async def refresh_cdata(self) -> None:
        """Periodically poll the cdata endpoints registered for devices like Tywatt.

        Endpoints such as energyIndex, energyInstant, energyHisto and
        energyDistrib are registered via add_poll_device_url_5m() while parsing
        /devices/cmeta (see MessageHandler.parse_cmeta_data) and must be polled
        on their own schedule. They must NOT be polled only from within
        refresh_data()'s "no validity-based polling needed" branch: as soon as
        any other device exposes validity metadata (the common case), that
        branch never runs and these cdata endpoints (e.g. the Tywatt instant
        consumption sensor) would never be queried.

        Poll once at startup, then follow the refresh interval selected in the
        integration options. The per-device Refresh button remains available
        for an immediate reading between scheduled polls.
        """
        while not self._shutting_down:
            try:
                await self._tydom_client.poll_devices_data_5m()
            except Exception:
                LOGGER.exception("Error polling registered cdata endpoints")
            await self._interruptible_sleep(self._refresh_interval)

    async def reload_devices(self) -> None:
        """Recharger tous les appareils et entités comme au démarrage initial.

        Cette méthode vide tous les appareils existants et les recharges depuis zéro.
        """
        LOGGER.info("Début du rechargement de tous les appareils")

        # Vider les dictionnaires d'appareils
        self.devices.clear()
        self.ha_devices.clear()
        self._remote_battery_entities.clear()
        self._interrupter_battery_entities.clear()
        self._twc_scene_sets.clear()
        self._twc_cover_entities.clear()
        # Réinitialiser le flag pour recréer le bouton après le rechargement
        self._reload_button_created = False
        self._association_controls_created = False
        self._association_controls.clear()
        self._refresh_energy_buttons_created.clear()
        self._device_association_buttons_created.clear()

        # Supprimer toutes les entités existantes via l'Entity Registry
        from homeassistant.helpers import entity_registry as er

        entity_registry = er.async_get(self._hass)
        entities_to_remove = []

        # Parcourir toutes les entités enregistrées pour cette intégration
        for entity_id, entity_entry in entity_registry.entities.items():
            if entity_entry.config_entry_id == self._entry.entry_id:
                entities_to_remove.append(entity_id)

        # Supprimer les entités
        for entity_id in entities_to_remove:
            entity_registry.async_remove(entity_id)

        LOGGER.info(
            "Suppression de %d entité(s) existante(s) et rechargement des appareils",
            len(entities_to_remove),
        )

        # Recharger toutes les métadonnées et données comme au démarrage
        await self._tydom_client.get_info()
        await self._tydom_client.put_api_mode()
        await self._tydom_client.post_refresh()
        await self._tydom_client.get_configs_file()
        await self._tydom_client.get_groups()
        await self._tydom_client.get_devices_meta()
        await self._tydom_client.get_devices_cmeta()
        await self._tydom_client.get_devices_data()
        await self._tydom_client.get_scenarii()
        await self._tydom_client.get_moments()

        # Recréer le bouton de rechargement après le rechargement
        # (le bouton d'actualisation énergie est recréé par _create_energy_device
        # quand le device Tywatt est redécouvert)
        if self.add_button_callback is not None:
            reload_button = HAReloadButton(self, self._hass)
            self.add_button_callback([reload_button])
            LOGGER.debug("Bouton de rechargement recréé après le rechargement")
        if (
            self.add_button_callback is not None
            and self.add_select_callback is not None
            and self.add_text_callback is not None
        ):
            self.add_select_callback(
                [
                    HAGatewayAssociationCategorySelect(self),
                    HAGatewayAssociationProductSelect(self),
                    HAGatewayAssociationChannelSelect(self),
                    HAGatewayAssociationUsageSelect(self),
                ]
            )
            self.add_button_callback(
                [
                    HAGatewayAssociationGuideButton(self),
                    HAGatewayStartAssociationButton(self),
                ]
            )
            self.add_text_callback([HAGatewayAssociationNameText(self)])
            self._association_controls_created = True

        LOGGER.info(
            "Rechargement terminé, les nouveaux appareils seront découverts automatiquement"
        )

        # Validate data consistency after reload
        await self._validate_data_consistency()

    async def _validate_data_consistency(self) -> None:
        """Validate data consistency: check that devices in groups exist, scenarios reference valid devices."""
        LOGGER.debug("Validating data consistency...")

        issues = []

        # Check groups: verify that all device IDs in groups exist
        for device_id, device in self.devices.items():
            if isinstance(device, TydomGroup):
                for group_device_id in device.device_ids:
                    if group_device_id not in self.devices:
                        # Try to find by various ID formats
                        found = False
                        for _id, _device in self.devices.items():
                            if (
                                _id == group_device_id
                                or str(getattr(_device, "device_id", ""))
                                == group_device_id
                                or str(getattr(_device, "_id", "")) == group_device_id
                            ):
                                found = True
                                break

                        if not found:
                            issues.append(
                                f"Group {device.device_name} ({device_id}) references non-existent device: {group_device_id}"
                            )

        # Check scenarios: verify that grpAct and epAct reference valid devices/groups
        for device_id, device in self.devices.items():
            if isinstance(device, TydomScene):
                # Check grpAct
                grp_act = getattr(device, "grpAct", None)
                if grp_act and isinstance(grp_act, list):
                    from .tydom.MessageHandler import groups_data

                    for grp_action in grp_act:
                        if isinstance(grp_action, dict):
                            grp_id = grp_action.get("id")
                            if grp_id:
                                grp_id_str = str(grp_id)
                                # All groups remain in protocol metadata even
                                # when no Home Assistant control is appropriate.
                                if grp_id_str not in groups_data:
                                    issues.append(
                                        f"Scene {device.device_name} ({device_id}) references non-existent group: {grp_id_str}"
                                    )

                # Check epAct
                ep_act = getattr(device, "epAct", None)
                if ep_act and isinstance(ep_act, list):
                    for ep_action in ep_act:
                        if isinstance(ep_action, dict):
                            ep_id = ep_action.get("id")
                            if ep_id:
                                ep_id_str = str(ep_id)
                                # Check if device/endpoint exists
                                device_found = False
                                for _id, _device in self.devices.items():
                                    if (
                                        _id == ep_id_str
                                        or str(getattr(_device, "device_id", ""))
                                        == ep_id_str
                                        or str(getattr(_device, "_id", "")) == ep_id_str
                                    ):
                                        device_found = True
                                        break

                                if not device_found:
                                    issues.append(
                                        f"Scene {device.device_name} ({device_id}) references non-existent device/endpoint: {ep_id_str}"
                                    )

        # Log issues
        if issues:
            LOGGER.warning(
                "Found %d data consistency issue(s):",
                len(issues),
            )
            for issue in issues:
                LOGGER.warning("  - %s", issue)
        else:
            LOGGER.debug("Data consistency validation passed: no issues found")
