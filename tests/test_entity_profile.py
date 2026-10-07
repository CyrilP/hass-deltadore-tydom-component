"""Tests for the global entity mode without requiring a running HA instance."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import MagicMock

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "deltadore_tydom"
DOMAIN = "deltadore_tydom"


class Disabler(StrEnum):
    """Match Home Assistant's entity disabler values."""

    INTEGRATION = "integration"
    USER = "user"
    CONFIG_ENTRY = "config_entry"


@dataclass(frozen=True)
class RegistryEntry:
    """Represent the immutable fields used by the production profile."""

    entity_id: str
    unique_id: str
    config_entry_id: str = "gateway-one"
    platform: str = DOMAIN
    disabled_by: Disabler | None = None
    options: dict = field(default_factory=dict)

    @property
    def domain(self):
        """Return the entity platform domain."""
        return self.entity_id.split(".")[0]


class FakeRegistry:
    """Immutable entries and queued update events, as in HA's registry."""

    def __init__(self):
        """Initialise the test double."""
        self.entities = {}
        self.events = []

    def async_get(self, entity_id):
        """Find an entry by entity ID."""
        return self.entities.get(entity_id)

    def async_get_entity_id(self, domain, platform, unique_id):
        """Resolve an entry's stable platform and unique ID."""
        return next(
            (
                e.entity_id
                for e in self.entities.values()
                if (e.domain, e.platform, e.unique_id) == (domain, platform, unique_id)
            ),
            None,
        )

    def async_update_entity_options(self, entity_id, domain, options):
        """Merge only the requested options namespace."""
        entry = self.entities[entity_id]
        self.entities[entity_id] = replace(
            entry, options={**entry.options, domain: options}
        )
        self.events.append(
            {
                "action": "update",
                "entity_id": entity_id,
                "changes": {"options": entry.options},
            }
        )

    def async_update_entity(self, entity_id, *, disabled_by):
        """Queue a change of disabled status."""
        entry = self.entities[entity_id]
        self.entities[entity_id] = replace(entry, disabled_by=disabled_by)
        self.events.append(
            {
                "action": "update",
                "entity_id": entity_id,
                "changes": {"disabled_by": entry.disabled_by},
            }
        )

    def flush(self, profile):
        """Deliver pending registry events to the profile."""
        while self.events:
            profile._registry_updated(SimpleNamespace(data=self.events.pop(0)))


class FakeEntity:
    """Expose the entity properties used during registration."""

    def __init__(self, unique_id="raw", *, category=None, essential=None, enabled=True):
        """Initialise the test double."""
        self.unique_id = unique_id
        self.entity_category = category
        self.entity_profile_essential = essential
        self._attr_entity_registry_enabled_default = enabled

    @property
    def entity_registry_enabled_default(self):
        """Return the default without changing individual registry decisions."""
        return self._attr_entity_registry_enabled_default


def load_source(filename, namespace):
    """Execute production definitions without importing unrelated HA modules."""
    tree = ast.parse((COMPONENT / filename).read_text(encoding="utf-8"))
    tree.body = [
        node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    exec(
        compile(
            tree,
            str(COMPONENT / filename),
            "exec",
            flags=__import__("__future__").annotations.compiler_flag,
        ),
        namespace,
    )
    return namespace


def profile_types(registry):
    """Load the profile with isolated registry dependencies."""
    er = SimpleNamespace(
        async_get=lambda hass: registry,
        async_entries_for_config_entry=lambda reg, entry_id: [
            e for e in reg.entities.values() if e.config_entry_id == entry_id
        ],
        EVENT_ENTITY_REGISTRY_UPDATED="entity_registry_updated",
        RegistryEntryDisabler=Disabler,
    )
    return load_source(
        "entity_profile.py",
        {
            "callback": lambda f: f,
            "er": er,
            "CONF_ENTITY_MODE": "entity_mode",
            "DOMAIN": DOMAIN,
            "ENTITY_MODE_ALL": "all",
            "ENTITY_MODE_SIMPLIFIED": "simplified",
        },
    )


class TestClassification(TestCase):
    """Check functional and safety information across device families."""

    def setUp(self):
        """Create isolated dependencies for each test."""
        self.classify = profile_types(FakeRegistry())["is_essential_entity"]

    def raw(self, device_type, attribute, *, device_class=None, metadata=None):
        """Build an ancillary register-backed sensor."""
        entity = FakeEntity()
        entity._attribute = attribute
        entity.entity_description = SimpleNamespace(key=attribute)
        entity.device_class = device_class
        entity._device = SimpleNamespace(device_type=device_type, _metadata=metadata)
        return entity

    def test_everyday_entities_are_kept(self):
        """Retain primary commands and event entities across platforms."""
        for domain in (
            "climate",
            "cover",
            "light",
            "event",
            "switch",
            "lock",
            "number",
            "select",
            "scene",
            "weather",
            "alarm_control_panel",
        ):
            with self.subTest(domain=domain):
                self.assertTrue(self.classify(FakeEntity(domain)))

    def test_door_and_water_detection_without_extra_technical_registers(self):
        """Keep detection while disabling ancillary registers."""
        for device_type, attribute in (
            ("door", "openState"),
            ("door", "openingDetected"),
            ("water", "techWaterDefect"),
        ):
            self.assertTrue(self.classify(self.raw(device_type, attribute)))
        for attribute in (
            "config",
            "productName",
            "supervisionMode",
            "battFault",
            "networkQuality",
        ):
            self.assertFalse(self.classify(self.raw("door", attribute)))

    def test_smoke_battery_and_alarm_safety_are_retained(self):
        """Keep safety faults even if they are diagnostic entities."""
        for attribute in (
            "techSmokeDefect",
            "battFault",
            "batteryLevel",
            "techPileDefect",
        ):
            self.assertTrue(self.classify(self.raw("smoke", attribute)))
        for attribute in (
            "battFault",
            "transmissionFault",
            "gsmFault",
            "ethernetFault",
            "openIssues",
            "tamperDefect",
        ):
            self.assertTrue(self.classify(self.raw("alarm", attribute)))
        self.assertTrue(
            self.classify(FakeEntity(category="diagnostic", essential=True))
        )
        self.assertFalse(self.classify(self.raw("alarm", "softVersion")))

    def test_useful_measurements_and_rf110_settings_are_retained(self):
        """Keep measurements and writable functional operating limits."""
        for attribute, device_class in (
            ("temperature", None),
            ("myConsumption", "energy"),
            ("instantaneous", "power"),
        ):
            self.assertTrue(
                self.classify(self.raw("sensor", attribute, device_class=device_class))
            )
        for attribute in ("setpointMin", "setpointMax", "hvacMode", "useMode"):
            self.assertTrue(self.classify(self.raw("thermic", attribute)))
        self.assertTrue(
            self.classify(
                self.raw(
                    "thermic",
                    "specialOperatingLimit",
                    metadata={"specialOperatingLimit": {"permission": "rw"}},
                )
            )
        )
        self.assertFalse(
            self.classify(
                self.raw(
                    "thermic",
                    "softVersion",
                    metadata={"softVersion": {"permission": "rw"}},
                )
            )
        )

    def test_config_and_diagnostics_are_optional_not_primary_controls(self):
        """Respect category defaults and explicit classification overrides."""
        for category in ("config", "diagnostic"):
            self.assertFalse(self.classify(FakeEntity(category=category)))
        self.assertFalse(self.classify(FakeEntity(essential=False)))
        self.assertTrue(self.classify(FakeEntity(category="config", essential=True)))


class TestRegistryModes(TestCase):
    """Check defaults, ownership, reversibility and individual choices."""

    def setUp(self):
        """Create isolated dependencies for each test."""
        self.registry = FakeRegistry()
        self.entry = SimpleNamespace(
            entry_id="gateway-one",
            data={},
            pref_disable_new_entities=False,
            async_on_unload=MagicMock(),
        )
        self.hass = SimpleNamespace(bus=SimpleNamespace(async_listen=MagicMock()))
        self.Profile = profile_types(self.registry)["EntityProfile"]
        self.profile = self.Profile(self.hass, self.entry)
        self.update_before_add = None

    def add(self, entities, domain="sensor", profile=None):
        """Register supplied entities through the production adder wrapper."""

        def original_adder(items, update_before_add):
            self.update_before_add = update_before_add
            for entity in items:
                entity_id = f"{domain}.{entity.unique_id}"
                if entity_id in self.registry.entities:
                    continue
                disabled = None
                if not entity.entity_registry_enabled_default:
                    disabled = Disabler.INTEGRATION
                elif self.entry.pref_disable_new_entities:
                    disabled = Disabler.CONFIG_ENTRY
                self.registry.entities[entity_id] = RegistryEntry(
                    entity_id, entity.unique_id, disabled_by=disabled
                )
                self.registry.events.append(
                    {"action": "create", "entity_id": entity_id}
                )

        (profile or self.profile).wrap_adder(domain, original_adder)(
            iter(entities), True
        )
        self.registry.flush(profile or self.profile)

    def switch(self, mode):
        """Apply a mode selection as the config-entry listener does."""
        self.entry.data = {"entity_mode": mode}
        self.profile.async_set_mode(mode)
        self.registry.flush(self.profile)

    def row(self, unique_id):
        """Read the latest immutable entry."""
        return self.registry.entities[f"sensor.{unique_id}"]

    def test_default_full_mode_does_not_disable_existing_entities(self):
        """Do not alter the usual defaults in full mode."""
        self.add(
            [
                FakeEntity("control"),
                FakeEntity("technical", category="diagnostic"),
                FakeEntity("native_disabled", enabled=False),
            ]
        )
        self.assertIsNone(self.row("control").disabled_by)
        self.assertIsNone(self.row("technical").disabled_by)
        self.assertEqual(self.row("native_disabled").disabled_by, Disabler.INTEGRATION)
        self.assertTrue(self.update_before_add)

    def test_initial_simplified_defaults_and_full_restore_keep_same_ids(self):
        """Apply simplified defaults once without replacing entity identities."""
        self.entry.data = {"entity_mode": "simplified"}
        self.profile = self.Profile(self.hass, self.entry)
        self.add(
            [
                FakeEntity("control"),
                FakeEntity("technical", category="diagnostic"),
                FakeEntity("gateway_removal", category="config", enabled=False),
            ]
        )
        ids_before = set(self.registry.entities)
        self.assertIsNone(self.row("control").disabled_by)
        self.assertEqual(self.row("technical").disabled_by, Disabler.INTEGRATION)
        self.assertTrue(self.row("technical").options[DOMAIN]["profile_disabled"])
        self.switch("all")
        self.assertIsNone(self.row("technical").disabled_by)
        self.assertEqual(self.row("gateway_removal").disabled_by, Disabler.INTEGRATION)
        self.assertEqual(ids_before, set(self.registry.entities))

    def test_options_changes_apply_to_existing_entities_reversibly(self):
        """Change existing entities only on an explicit mode switch."""
        self.add(
            [FakeEntity("technical", category="diagnostic"), FakeEntity("control")]
        )
        self.switch("simplified")
        self.assertEqual(self.row("technical").disabled_by, Disabler.INTEGRATION)
        self.assertIsNone(self.row("control").disabled_by)
        self.switch("all")
        self.assertIsNone(self.row("technical").disabled_by)

    def test_user_disabled_entities_are_never_reenabled(self):
        """Leave user-disabled entries untouched in either mode."""
        self.add([FakeEntity("technical", category="diagnostic")])
        self.registry.async_update_entity("sensor.technical", disabled_by=Disabler.USER)
        self.registry.flush(self.profile)
        self.switch("simplified")
        self.switch("all")
        self.assertEqual(self.row("technical").disabled_by, Disabler.USER)

    def test_individual_override_survives_reload_and_restart(self):
        """Retain a manually enabled exception through discovery and restart."""
        self.add([FakeEntity("technical", category="diagnostic")])
        self.switch("simplified")
        self.registry.async_update_entity("sensor.technical", disabled_by=None)
        self.registry.flush(self.profile)
        self.assertFalse(self.row("technical").options[DOMAIN]["profile_disabled"])
        self.add([FakeEntity("technical", category="diagnostic")])
        self.assertIsNone(self.row("technical").disabled_by)
        restarted = self.Profile(self.hass, self.entry)
        self.add([FakeEntity("technical", category="diagnostic")], profile=restarted)
        self.assertIsNone(self.row("technical").disabled_by)
        restarted.async_set_mode("simplified")
        self.assertIsNone(self.row("technical").disabled_by)

    def test_later_user_disable_is_not_undone_when_returning_to_full(self):
        """Stop managing an entity after an individual user change."""
        self.add([FakeEntity("technical", category="diagnostic")])
        self.switch("simplified")
        self.registry.async_update_entity("sensor.technical", disabled_by=Disabler.USER)
        self.registry.flush(self.profile)
        self.switch("all")
        self.assertEqual(self.row("technical").disabled_by, Disabler.USER)

    def test_other_entries_and_other_registry_options_are_untouched(self):
        """Limit changes to the owning entry and integration namespace."""
        self.add([FakeEntity("technical", category="diagnostic")])
        self.registry.async_update_entity_options(
            "sensor.technical", "other_integration", {"custom": 42}
        )
        self.registry.entities["sensor.other"] = RegistryEntry(
            "sensor.other",
            "other",
            "gateway-two",
            options={DOMAIN: {"secondary": True}},
        )
        self.registry.entities["sensor.other_platform"] = RegistryEntry(
            "sensor.other_platform",
            "other_platform",
            platform="other",
            options={DOMAIN: {"secondary": True}},
        )
        self.switch("simplified")
        self.assertIsNone(self.registry.entities["sensor.other"].disabled_by)
        self.assertIsNone(self.registry.entities["sensor.other_platform"].disabled_by)
        self.assertEqual(
            self.row("technical").options["other_integration"], {"custom": 42}
        )

    def test_ha_disable_new_entities_preference_is_respected(self):
        """Do not override HA's entry-wide disable-new-entities preference."""
        self.entry.data = {"entity_mode": "simplified"}
        self.entry.pref_disable_new_entities = True
        self.profile = self.Profile(self.hass, self.entry)
        self.add([FakeEntity("technical", category="diagnostic")])
        self.assertEqual(self.row("technical").disabled_by, Disabler.CONFIG_ENTRY)
        self.switch("all")
        self.assertEqual(self.row("technical").disabled_by, Disabler.CONFIG_ENTRY)

    def test_new_entities_after_mode_change_use_current_mode(self):
        """Apply the current mode to newly discovered entities."""
        self.switch("simplified")
        self.add([FakeEntity("new", category="config")])
        self.assertEqual(self.row("new").disabled_by, Disabler.INTEGRATION)
        self.switch("all")
        self.add([FakeEntity("new_full", category="config")])
        self.assertIsNone(self.row("new_full").disabled_by)

    def test_promoted_essential_entity_recovers_without_changing_identity(self):
        """Recover a profile-disabled entity when classification improves."""
        self.add([FakeEntity("temperature", category="diagnostic")])
        self.switch("simplified")
        self.add([FakeEntity("temperature", essential=True)])
        self.assertIsNone(self.row("temperature").disabled_by)
        self.assertFalse(self.row("temperature").options[DOMAIN]["secondary"])


class TestConfigValidation(IsolatedAsyncioTestCase):
    """Check configuration persistence without contacting a gateway."""

    async def test_selected_mode_survives_validation_in_manual_and_cloud_setup(self):
        """Keep the selected mode across both credential validation paths."""
        constants = {
            "CONF_HOST": "host",
            "CONF_MAC": "mac",
            "CONF_EMAIL": "email",
            "CONF_PASSWORD": "password",
            "CONF_TYDOM_PASSWORD": "tydom_password",
            "CONF_REFRESH_INTERVAL": "refresh_interval",
            "CONF_PIN": "pin",
            "CONF_ZONES_HOME": "zones_home",
            "CONF_ZONES_AWAY": "zones_away",
            "CONF_ZONES_NIGHT": "zones_night",
            "CONF_ENTITY_MODE": "entity_mode",
        }
        tree = ast.parse((COMPONENT / "config_flow.py").read_text(encoding="utf-8"))
        tree.body = [
            n
            for n in tree.body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "validate_input"
        ]

        async def credentials(*args):
            """Return a test-only gateway secret without network access."""
            return "gateway-password"

        namespace = {
            **constants,
            "ENTITY_MODE_ALL": "all",
            "LOGGER": MagicMock(),
            "sanitize_config_data": lambda x: x,
            "host_valid": lambda x: True,
            "email_valid": lambda x: True,
            "zones_valid": lambda x: True,
            "re": __import__("re"),
            "InvalidZoneHome": ValueError,
            "InvalidZoneAway": ValueError,
            "InvalidZoneNight": ValueError,
            "hub": SimpleNamespace(
                Hub=SimpleNamespace(get_tydom_credentials=credentials)
            ),
            "async_create_clientsession": lambda *args: None,
        }
        exec(
            compile(
                tree,
                "config_flow.py",
                "exec",
                flags=__import__("__future__").annotations.compiler_flag,
            ),
            namespace,
        )
        for cloud in (True, False):
            for mode in (None, "all", "simplified"):
                with self.subTest(cloud=cloud, mode=mode):
                    data = {
                        "host": "192.0.2.1",
                        "mac": "012345abcdef",
                        "refresh_interval": 30,
                        "email": "example@example.com",
                        "password": "cloud-password",
                        "tydom_password": "gateway-password",
                    }
                    if mode:
                        data["entity_mode"] = mode
                    result = await namespace["validate_input"](None, cloud, data)
                    self.assertEqual(result["entity_mode"], mode or "all")


class TestConfigurationForms(IsolatedAsyncioTestCase):
    """Exercise the production form schemas and options submission."""

    def setUp(self):
        """Load flow methods with simple UI and registry dependencies."""
        self.defaults = {}

        def marker(name, **kwargs):
            """Record schema defaults while keeping keys readable."""
            self.defaults[name] = kwargs.get("default")
            return name

        source = ast.parse((COMPONENT / "config_flow.py").read_text(encoding="utf-8"))
        methods = []
        for node in source.body:
            if isinstance(node, ast.ClassDef) and node.name in (
                "ConfigFlow",
                "OptionsFlowHandler",
            ):
                methods.extend(
                    n for n in node.body if isinstance(n, ast.AsyncFunctionDef)
                )
        source.body = methods
        self.namespace = {
            "ENTITY_MODE_ALL": "all",
            "ENTITY_MODE_SELECTOR": "translated-mode-selector",
            "vol": SimpleNamespace(
                Required=marker, Optional=marker, Schema=lambda schema: schema
            ),
            "selector": MagicMock(),
            "LOGGER": MagicMock(),
            "zones_valid": lambda value: True,
        }
        for suffix in (
            "HOST",
            "MAC",
            "EMAIL",
            "PASSWORD",
            "TYDOM_PASSWORD",
            "REFRESH_INTERVAL",
            "ZONES_HOME",
            "ZONES_AWAY",
            "ZONES_NIGHT",
            "PIN",
            "ENTITY_MODE",
        ):
            self.namespace[f"CONF_{suffix}"] = suffix.lower()
        exec(
            compile(
                source,
                "config_flow.py",
                "exec",
                flags=__import__("__future__").annotations.compiler_flag,
            ),
            self.namespace,
        )
        self.flow = SimpleNamespace(
            _discovered_host="192.0.2.1",
            _discovered_mac="012345abcdef",
            _name="Gateway",
            async_show_form=lambda **kwargs: kwargs,
            async_create_entry=lambda **kwargs: kwargs,
        )

    async def test_all_initial_setup_paths_offer_full_default(self):
        """Expose the mode in manual, cloud, local and discovered forms."""
        for name in (
            "user_manual",
            "user_cloud",
            "user_local_pair",
            "discovery_confirm_manual",
            "discovery_confirm_cloud",
        ):
            with self.subTest(step=name):
                self.defaults.clear()
                result = await self.namespace[f"async_step_{name}"](self.flow)
                self.assertEqual(
                    result["data_schema"]["entity_mode"], "translated-mode-selector"
                )
                self.assertEqual(self.defaults["entity_mode"], "all")
                self.assertIn("pin", result["data_schema"])
        local_pair = self.namespace["async_step_user_local_pair"]

        async def discovered_local(user_input, **kwargs):
            """Delegate the discovered form to the shared pairing form."""
            return await local_pair(self.flow, user_input, **kwargs)

        self.flow.async_step_user_local_pair = discovered_local
        result = await self.namespace["async_step_discovery_confirm_local_pair"](
            self.flow
        )
        self.assertEqual(result["step_id"], "discovery_confirm_local_pair")
        self.assertIn("entity_mode", result["data_schema"])
        self.assertEqual(self.defaults["entity_mode"], "all")

    async def test_options_form_displays_current_mode_alongside_pin(self):
        """Keep the selector in the existing global configuration form."""
        self.flow.config_entry = SimpleNamespace(data={"entity_mode": "simplified"})
        result = await self.namespace["async_step_configure"](self.flow)
        self.assertEqual(result["step_id"], "configure")
        self.assertIn("pin", result["data_schema"])
        self.assertIn("entity_mode", result["data_schema"])
        self.assertEqual(self.defaults["entity_mode"], "simplified")

    async def test_options_submission_keeps_credentials_and_other_options(self):
        """Store the mode without replacing credentials or integration options."""
        entry = SimpleNamespace(
            data={"tydom_password": "test-secret", "entity_mode": "all"},
            options={"other_option": True},
        )
        update = MagicMock()
        self.flow.config_entry = entry
        self.flow.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update)
        )
        result = await self.namespace["async_step_configure"](
            self.flow,
            {
                "refresh_interval": 30,
                "entity_mode": "simplified",
                "pin": "1234",
                "zones_home": "1",
                "zones_away": "1,2",
                "zones_night": "2",
            },
        )
        self.assertEqual(result, {"title": "", "data": {}})
        kwargs = update.call_args.kwargs
        self.assertEqual(kwargs["data"]["entity_mode"], "simplified")
        self.assertEqual(kwargs["data"]["tydom_password"], "test-secret")
        self.assertEqual(kwargs["data"]["pin"], "1234")
        self.assertEqual(kwargs["options"], entry.options)

    def test_mode_labels_and_help_exist_in_both_languages(self):
        """Provide translated selector choices and warnings in every form."""

        def unique_keys(pairs):
            """Reject duplicate keys rather than silently hiding a translation."""
            result = dict(pairs)
            self.assertEqual(len(result), len(pairs))
            return result

        for language in ("en", "fr"):
            translations = json.loads(
                (COMPONENT / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                ),
                object_pairs_hook=unique_keys,
            )
            choices = translations["selector"]["entity_mode"]["options"]
            self.assertEqual(set(choices), {"all", "simplified"})
            for step in (
                "user_manual",
                "user_cloud",
                "user_local_pair",
                "discovery_confirm_manual",
                "discovery_confirm_cloud",
                "discovery_confirm_local_pair",
            ):
                self.assertTrue(
                    translations["config"]["step"][step]["data"]["entity_mode"]
                )
                self.assertTrue(
                    translations["config"]["step"][step]["data_description"][
                        "entity_mode"
                    ]
                )
            options = translations["options"]["step"]["configure"]
            self.assertTrue(options["data"]["entity_mode"])
            self.assertTrue(options["data_description"]["entity_mode"])
