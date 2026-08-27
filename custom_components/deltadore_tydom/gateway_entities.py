"""Gateway-level controls for TYDOM product association."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


class _GatewayAssociationEntity:
    """Shared Home Assistant device information for gateway controls."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, tydom_hub) -> None:
        """Attach the control to its configured TYDOM gateway."""
        self._hub = tydom_hub
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tydom_hub.hub_id)},
            name=tydom_hub._name,
            manufacturer=tydom_hub.manufacturer,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to selection changes made by the companion control."""
        await super().async_added_to_hass()
        self._hub.register_association_control(self)

    async def async_will_remove_from_hass(self) -> None:
        """Stop receiving updates when the integration unloads."""
        self._hub.unregister_association_control(self)
        await super().async_will_remove_from_hass()


class HAGatewayAssociationCategorySelect(_GatewayAssociationEntity, SelectEntity):
    """Choose the intended usage before choosing a product family."""

    _attr_icon = "mdi:shape-outline"

    def __init__(self, tydom_hub) -> None:
        """Initialise the association-category selector."""
        super().__init__(tydom_hub)
        self._attr_unique_id = f"{tydom_hub.hub_id}_association_category"
        self._attr_name = "Catégorie à associer"

    @property
    def options(self) -> list[str]:
        """Return the product categories derived from the official workflow."""
        return list(self._hub.association_categories)

    @property
    def current_option(self) -> str:
        """Return the selected product category."""
        return self._hub.association_category

    async def async_select_option(self, option: str) -> None:
        """Select a category and reset the product selection if necessary."""
        self._hub.set_association_category(option)


class HAGatewayAssociationProductSelect(_GatewayAssociationEntity, SelectEntity):
    """Choose a product family compatible with the selected category."""

    _attr_icon = "mdi:devices"

    def __init__(self, tydom_hub) -> None:
        """Initialise the product-family selector."""
        super().__init__(tydom_hub)
        self._attr_unique_id = f"{tydom_hub.hub_id}_association_product"
        self._attr_name = "Produit à associer"

    @property
    def options(self) -> list[str]:
        """Return products for the currently selected category only."""
        return list(self._hub.association_product_labels)

    @property
    def current_option(self) -> str:
        """Return the selected product-family label."""
        return self._hub.association_product_label

    async def async_select_option(self, option: str) -> None:
        """Select the exact protocol profile represented by an option."""
        self._hub.set_association_product(option)


class HAGatewayStartAssociationButton(_GatewayAssociationEntity, ButtonEntity):
    """Start the generic add-product workflow on the selected gateway."""

    _attr_icon = "mdi:link-plus"

    def __init__(self, tydom_hub) -> None:
        """Initialise the gateway association button."""
        super().__init__(tydom_hub)
        self._attr_unique_id = f"{tydom_hub.hub_id}_start_product_association"
        self._attr_name = "Démarrer l'association"

    @property
    def available(self) -> bool:
        """Disable the action for groups without a local install API profile."""
        return self._hub.association_product_supported

    async def async_press(self) -> None:
        """Start association using the selected product-family recipe."""
        await self._hub.start_selected_product_association()
