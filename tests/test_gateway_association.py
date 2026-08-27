"""Tests for gateway-level TYDOM product association."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from custom_components.deltadore_tydom.gateway_association import (
    ASSOCIATION_CATALOG,
    get_install_payload,
    remove_product_association,
    start_product_association,
)
from custom_components.deltadore_tydom.hub import Hub


class _Client:
    def __init__(self) -> None:
        self.payloads: list[dict[str, str | int]] = []

    async def post_device_install(self, payload: dict[str, str | int]) -> None:
        self.payloads.append(payload)


class GatewayAssociationTests(IsolatedAsyncioTestCase):
    """Ensure pairing starts at the gateway, not an existing device."""

    def test_x3d_payload_omits_the_network(self) -> None:
        """X3D pairing leaves the optional network field out."""
        self.assertEqual(
            get_install_payload("opening_x3d"),
            {"protocol": "X3D", "type": "x3d_rm", "profile": "opening"},
        )

    def test_zigbee_defaults_to_the_first_network(self) -> None:
        """Zigbee uses the official application's default network."""
        self.assertEqual(
            get_install_payload("light_zigbee"),
            {"protocol": "ZIGBEE", "type": "", "profile": "light", "net": 0},
        )

    def test_unknown_profile_is_rejected_before_writing(self) -> None:
        """Reject a profile that is not an official request template."""
        with self.assertRaisesRegex(ValueError, "Unknown TYDOM"):
            get_install_payload("not-a-product")

    def test_same_radio_recipe_can_be_exposed_in_multiple_categories(self) -> None:
        """Keep usage choice separate from the protocol recipe it selects."""
        lighting = ASSOCIATION_CATALOG["Éclairage"]
        gate = ASSOCIATION_CATALOG["Portails et garages"]

        self.assertIn("light_x3d", {choice.profile_id for choice in lighting})
        self.assertIn("light_x3d", {choice.profile_id for choice in gate})

    def test_category_change_updates_the_available_product_family(self) -> None:
        """A category controls its product list without changing the gateway."""
        tydom_hub = object.__new__(Hub)
        tydom_hub._association_controls = []
        tydom_hub._association_category = "Éclairage"
        tydom_hub._association_profile = "light_x3d"

        tydom_hub.set_association_category("Volets et stores")

        self.assertEqual(tydom_hub.association_category, "Volets et stores")
        self.assertEqual(
            tydom_hub.association_product_label, "Récepteur volet roulant X3D"
        )

    async def test_association_uses_the_gateway_client(self) -> None:
        """Association is sent through the configured gateway client."""
        client = _Client()
        tydom_hub = SimpleNamespace(_tydom_client=client)

        payload = await start_product_association(tydom_hub, "opening_x3d")

        self.assertEqual(client.payloads, [payload])

    async def test_removal_uses_the_physical_device_identifier(self) -> None:
        """A removal is performed against the gateway inventory ID."""
        calls: list[str] = []

        async def delete_device(device_id: str) -> None:
            calls.append(device_id)

        device = SimpleNamespace(
            _id="42", _tydom_client=SimpleNamespace(delete_device=delete_device)
        )

        await remove_product_association(device)

        self.assertEqual(calls, ["42"])
