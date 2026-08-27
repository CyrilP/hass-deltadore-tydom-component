"""Gateway-level product association helpers.

The TYDOM mobile application starts its generic "add product" workflow with
``POST /devices/install``.  The request is shared by TYDOM 1.0/2.0, TYDOM
Home/Pro and Tywell gateways: the selected radio/product family is conveyed in
the request body, rather than being inferred from an existing endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass


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
    profile_id: str


# These profiles are the public request values used by the official TYDOM app.
# A gateway remains authoritative: it accepts only the radio/product families
# that its firmware supports.  Keeping this list protocol based, rather than
# reference based, makes it work across TYDOM and Tywell gateway generations.
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


# The official application first asks for a usage, then a product family.  A
# profile may deliberately occur in more than one category: a TYXIA receiver,
# for example, can be fitted to lighting, a gate, or a garage door.  The
# category is for a clear UX; ``profile_id`` remains the protocol value sent to
# the gateway.
ASSOCIATION_CATALOG: dict[str, tuple[AssociationChoice, ...]] = {
    "Éclairage": (
        AssociationChoice("Récepteur éclairage X3D", "light_x3d"),
        AssociationChoice("Éclairage Zigbee", "light_zigbee"),
    ),
    "Volets et stores": (
        AssociationChoice("Récepteur volet roulant X3D", "shutter_x3d"),
        AssociationChoice("Volet Activ'Home", "shutter_activhome_x3d"),
        AssociationChoice("Volet Brushless", "shutter_brushless_x3d"),
        AssociationChoice("Volet projeté", "shutter_projected_x3d"),
        AssociationChoice("Store banne", "awning_x3d"),
        AssociationChoice("Volet Profalux Zigbee", "shutter_profalux_zigbee"),
        AssociationChoice("Volet Stella Zigbee", "shutter_stella_zigbee"),
        AssociationChoice("Volet roulant Zigbee", "shutter_zigbee"),
    ),
    "Portails et garages": (
        AssociationChoice("Récepteur portail / garage X3D", "light_x3d"),
        AssociationChoice("Récepteur volet / garage X3D", "shutter_x3d"),
        AssociationChoice("Produit générique X3D", "generic_x3d"),
    ),
    "Chauffage": (
        AssociationChoice("Récepteur chauffage X3D", "thermic_x3d"),
        AssociationChoice("Récepteur chauffage X2D", "thermic_x2d"),
        AssociationChoice("Émetteur chauffage X3D spécifique", "thermic_x3d_es"),
        AssociationChoice("Chaudière Drive", "boiler_drive_x3d"),
        AssociationChoice("Chauffage Zigbee", "thermic_zigbee"),
        AssociationChoice("TYPASS ATL", "typass_atl_x3d"),
        AssociationChoice("TYPASS Saunier", "typass_saunier_x3d"),
    ),
    "Sécurité et ouvrants": (
        AssociationChoice("TYXAL / alarme X2D", "alarm_x2d"),
        AssociationChoice("TYXAL+ / alarme X3D", "alarm_x3d"),
        AssociationChoice("Détecteur X3D", "detector_x3d"),
        AssociationChoice("Ouvrant, porte ou fenêtre X3D", "opening_x3d"),
        AssociationChoice("Capteur X3D", "sensor_x3d"),
    ),
    "Énergie et mesure": (
        AssociationChoice("Compteur ou mesure X3D", "meter_x3d"),
        AssociationChoice("RT2012", "rt2012_x3d"),
        AssociationChoice("RT2012 sans sonde extérieure", "rt2012_no_outdoor_temp_x3d"),
        AssociationChoice("Mesure RT2012", "rt2012_measure_x3d"),
    ),
    "Commandes et autres": (
        AssociationChoice("Télécommande X3D", "remote_x3d"),
        AssociationChoice("Contrôleur X3D", "controller_x3d"),
        AssociationChoice("Produit multifonction X3D", "multi_x3d"),
        AssociationChoice("Produit POD X3D", "pod_x3d"),
        AssociationChoice("Station météo", "weather_plt"),
    ),
    "Ventilation": (
        AssociationChoice("Aéraulique Zigbee", "aeraulic_zigbee"),
        AssociationChoice("Chauffage partagé X3D", "shared_thermic_x3d"),
    ),
}


def get_association_choices(category: str) -> tuple[AssociationChoice, ...]:
    """Return the product families available under one displayed category."""
    try:
        return ASSOCIATION_CATALOG[category]
    except KeyError as err:
        raise ValueError(f"Unknown TYDOM association category: {category}") from err


def get_install_payload(
    profile_id: str, network: int | None = None
) -> dict[str, str | int]:
    """Build a validated request body for ``POST /devices/install``.

    The official app defaults Zigbee association to network 0 when no network
    is supplied.  X3D association intentionally omits ``net``.
    """
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
    """Start association on one configured TYDOM/Tywell gateway."""
    payload = get_install_payload(profile_id, network)
    await tydom_hub._tydom_client.post_device_install(payload)
    return payload


async def remove_product_association(device) -> None:
    """Remove one already-associated product from its TYDOM gateway."""
    device_id = getattr(device, "_id", None)
    tydom_client = getattr(device, "_tydom_client", None)
    if device_id is None or tydom_client is None:
        raise ValueError("The selected entity does not expose a TYDOM device")
    await tydom_client.delete_device(device_id)
