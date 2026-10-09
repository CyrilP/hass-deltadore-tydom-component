"""Entity defaults and reversible changes for the optional simplified mode."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTITY_MODE, DOMAIN, ENTITY_MODE_ALL, ENTITY_MODE_SIMPLIFIED

_MEASUREMENT_CLASSES = frozenset(
    {
        "temperature",
        "humidity",
        "power",
        "energy",
        "current",
        "voltage",
        "water",
        "gas",
        "illuminance",
        "irradiance",
        "wind_speed",
        "wind_direction",
        "precipitation",
        "precipitation_intensity",
        "pressure",
    }
)
_FUNCTIONAL_ATTRIBUTES = frozenset(
    {
        "temperature",
        "ambienttemperature",
        "outtemperature",
        "hygroin",
        "humidity",
        "lightpower",
        "position",
        "level",
        "state",
        "on",
        "openstate",
        "intrusiondetect",
        "openingdetected",
        "setpoint",
        "setpointmin",
        "setpointmax",
        "minsetpoint",
        "maxsetpoint",
        "hvacmode",
        "thermicmode",
        "usemode",
        "localmode",
        "authorization",
        "speed",
        "speedstring",
        "techsmokedefect",
        "techwaterdefect",
    }
)
_TECHNICAL_ATTRIBUTES = frozenset(
    {
        "config",
        "supervisionmode",
        "bootreference",
        "bootversion",
        "keyreference",
        "keyversionhw",
        "keyversionstack",
        "keyversionsw",
        "mainid",
        "mainreference",
        "mainversionhw",
        "mainversionsw",
        "productname",
        "mac",
        "jobsmp",
        "softplan",
        "softversion",
        "protocols",
        "clock",
        "geoloc",
        "apimode",
        "pltregistered",
        "bddstatus",
        "debugmode",
    }
)


def is_essential_attribute(device: Any, attribute: str, device_class: Any) -> bool:
    """Keep functional readings, adjustable values and alarm safety information."""
    name = attribute.split("_")[0].casefold()
    if name in _TECHNICAL_ATTRIBUTES:
        return False
    device_type = str(getattr(device, "device_type", "")).casefold()
    # Alarm fault and transmission registers differ between generations.
    # Retain their status data conservatively, including battery warnings.
    if "alarm" in device_type or callable(getattr(device, "is_legacy_alarm", None)):
        return True
    if "smoke" in device_type and ("batt" in name or "pile" in name or "smoke" in name):
        return True
    if name in _FUNCTIONAL_ATTRIBUTES or device_class in _MEASUREMENT_CLASSES:
        return True
    metadata = getattr(device, "_metadata", None)
    register = metadata.get(attribute) if isinstance(metadata, dict) else None
    # Preserve RF110 operating limits and modes exposed as writable parameters.
    return isinstance(register, dict) and "w" in str(register.get("permission") or "")


def is_essential_entity(entity: Entity) -> bool:
    """Classify raw ancillary sensors separately from primary entity controls."""
    explicit = getattr(entity, "entity_profile_essential", None)
    if explicit is not None:
        return bool(explicit)
    attribute = getattr(entity, "_attribute", None)
    description = getattr(entity, "entity_description", None)
    if attribute and description is not None and description.key == attribute:
        return is_essential_attribute(
            getattr(entity, "_device", None),
            attribute,
            getattr(entity, "device_class", None),
        )
    return entity.entity_category not in {"diagnostic", "config"}


class EntityProfile:
    """Keep entity identities and individual choices when switching modes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Listen for registration and individual enable/disable changes."""
        self._entry = entry
        self._registry = er.async_get(hass)
        self._mode = entry.data.get(CONF_ENTITY_MODE, ENTITY_MODE_ALL)
        self._known: dict[tuple[str, str], tuple[bool, bool]] = {}
        self._expected_changes: dict[str, er.RegistryEntryDisabler | None] = {}
        entry.async_on_unload(
            hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._registry_updated
            )
        )

    @callback
    def wrap_adder(
        self, domain: str, add_entities: AddEntitiesCallback
    ) -> AddEntitiesCallback:
        """Apply defaults before entities first enter the platform registry."""

        @callback
        def add_with_profile(
            entities: Iterable[Entity], update_before_add: bool = False
        ) -> None:
            entities = list(entities)
            for entity in entities:
                if entity.unique_id is None:
                    continue
                baseline_enabled = entity.entity_registry_enabled_default
                secondary = not is_essential_entity(entity) and baseline_enabled
                self._known[(domain, entity.unique_id)] = (secondary, baseline_enabled)
                entity_id = self._registry.async_get_entity_id(
                    domain, DOMAIN, entity.unique_id
                )
                if entity_id is not None:
                    self._describe(self._registry.async_get(entity_id), is_new=False)
                elif (
                    secondary
                    and self._mode == ENTITY_MODE_SIMPLIFIED
                    and not self._entry.pref_disable_new_entities
                ):
                    entity._attr_entity_registry_enabled_default = False
            add_entities(entities, update_before_add)

        return add_with_profile

    @callback
    def _set_options(self, entity: er.RegistryEntry, **changes: Any) -> None:
        """Persist only the profile metadata in the integration's namespace."""
        options = dict(entity.options.get(DOMAIN, {}))
        options.update(changes)
        if options != entity.options.get(DOMAIN, {}):
            self._registry.async_update_entity_options(
                entity.entity_id, DOMAIN, options
            )

    @callback
    def _set_disabled(
        self, entity_id: str, disabled_by: er.RegistryEntryDisabler | None
    ) -> None:
        """Remember registry changes made by this profile until their event arrives."""
        self._expected_changes[entity_id] = disabled_by
        self._registry.async_update_entity(entity_id, disabled_by=disabled_by)

    @callback
    def _describe(self, entity: er.RegistryEntry | None, *, is_new: bool) -> None:
        """Record classification without reapplying a mode after every reload."""
        if entity is None or entity.config_entry_id != self._entry.entry_id:
            return
        known = self._known.get((entity.domain, entity.unique_id))
        if known is None:
            return
        secondary, baseline_enabled = known
        options = entity.options.get(DOMAIN, {})
        managed = bool(options.get("profile_disabled"))
        if not secondary and managed:
            self._set_options(entity, secondary=False, profile_disabled=False)
            if (
                baseline_enabled
                and entity.disabled_by == er.RegistryEntryDisabler.INTEGRATION
            ):
                self._set_disabled(entity.entity_id, None)
            return
        if secondary or "secondary" in options:
            self._set_options(
                entity,
                secondary=secondary,
                profile_disabled=managed
                or (
                    is_new
                    and secondary
                    and self._mode == ENTITY_MODE_SIMPLIFIED
                    and entity.disabled_by == er.RegistryEntryDisabler.INTEGRATION
                ),
            )

    @callback
    def _registry_updated(self, event: Event) -> None:
        """Release profile ownership when a user changes an entity individually."""
        entity_id = event.data["entity_id"]
        if event.data["action"] == "remove":
            self._expected_changes.pop(entity_id, None)
            return
        entity = self._registry.async_get(entity_id)
        if entity is None or entity.config_entry_id != self._entry.entry_id:
            return
        if event.data["action"] == "create":
            self._describe(entity, is_new=True)
            return
        if "disabled_by" not in event.data.get("changes", {}):
            return
        if entity_id in self._expected_changes:
            expected = self._expected_changes.pop(entity_id)
            if entity.disabled_by == expected:
                return
        if entity.options.get(DOMAIN, {}).get("profile_disabled"):
            self._set_options(entity, profile_disabled=False)

    @callback
    def async_set_mode(self, mode: str) -> None:
        """Apply an explicitly selected mode to this entry's existing entities."""
        if mode == self._mode:
            return
        self._mode = mode
        for entity in er.async_entries_for_config_entry(
            self._registry, self._entry.entry_id
        ):
            if entity.platform != DOMAIN:
                continue
            options = entity.options.get(DOMAIN, {})
            if not options.get("secondary"):
                continue
            if mode == ENTITY_MODE_SIMPLIFIED and entity.disabled_by is None:
                self._set_options(entity, profile_disabled=True)
                self._set_disabled(
                    entity.entity_id, er.RegistryEntryDisabler.INTEGRATION
                )
            elif mode == ENTITY_MODE_ALL and options.get("profile_disabled"):
                self._set_options(entity, profile_disabled=False)
                if entity.disabled_by == er.RegistryEntryDisabler.INTEGRATION:
                    self._set_disabled(entity.entity_id, None)
