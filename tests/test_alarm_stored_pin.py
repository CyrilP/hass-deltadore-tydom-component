"""Tests for the additive Home Assistant stored-PIN alarm action."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock

import voluptuous as vol
import yaml


ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "deltadore_tydom"
SERVICE = "set_mode_using_stored_pin"
METHOD = "async_set_mode_using_stored_pin"


class _HomeAssistantError(Exception):
    """Record translated errors without requiring Home Assistant."""

    def __init__(self, message=None, **kwargs) -> None:
        self.translation_key = kwargs.get("translation_key")
        self.translation_domain = kwargs.get("translation_domain")
        super().__init__(message or self.translation_key)


class _AlarmCommandError(Exception):
    """Represent an asynchronous rejection from the central unit."""

    def __init__(self, result: str) -> None:
        self.result = result


def _load_alarm_harness():
    """Load the real new action, standard commands and result handler."""
    source_path = COMPONENT / "ha_entities.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    alarm = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "HaAlarm"
    )
    method_names = {
        METHOD,
        "async_alarm_arm_away",
        "async_alarm_arm_home",
        "async_alarm_arm_night",
        "async_alarm_disarm",
        "_run_alarm_command",
    }
    methods = [
        node
        for node in alarm.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name in method_names
    ]
    isolated_module = ast.Module(
        body=[
            ast.ClassDef(
                name="Harness", bases=[], keywords=[], body=methods, decorator_list=[]
            )
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(isolated_module)
    namespace = {
        "DOMAIN": "deltadore_tydom",
        "HomeAssistantError": _HomeAssistantError,
        "TydomAlarmCommandError": _AlarmCommandError,
    }
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return namespace["Harness"]


_AlarmHarness = _load_alarm_harness()


def _make_alarm(pin="001234"):
    """Create an isolated alarm with its own client and observable commands."""
    alarm = _AlarmHarness()
    alarm._device = SimpleNamespace(
        _tydom_client=SimpleNamespace(_alarm_pin=pin),
        alarm_arm_away=AsyncMock(return_value=True),
        alarm_arm_home=AsyncMock(return_value=True),
        alarm_arm_night=AsyncMock(return_value=True),
        alarm_disarm=AsyncMock(return_value=True),
        force_arm=AsyncMock(),
        clear_open_issues=Mock(),
    )
    alarm._schedule_open_issues_refresh = Mock()
    alarm.async_write_ha_state = Mock()
    return alarm


def _assert_no_commands(test, alarm):
    """Ensure validation failures cannot send any alarm command."""
    for name in ("arm_away", "arm_home", "arm_night", "disarm"):
        getattr(alarm._device, f"alarm_{name}").assert_not_awaited()
    alarm._device.force_arm.assert_not_awaited()
    test.assertFalse(alarm._schedule_open_issues_refresh.called)


class StoredAlarmPinTests(IsolatedAsyncioTestCase):
    """Exercise dispatch without changing standard alarm behaviour."""

    async def test_all_modes_use_the_stored_pin(self) -> None:
        """The same new action supplies the configured PIN for all modes."""
        for mode, command in (
            ("away", "arm_away"),
            ("home", "arm_home"),
            ("night", "arm_night"),
            ("disarm", "disarm"),
        ):
            with self.subTest(mode=mode):
                alarm = _make_alarm()
                result = await alarm.async_set_mode_using_stored_pin(mode)
                getattr(alarm._device, f"alarm_{command}").assert_awaited_once_with(
                    "001234"
                )
                for other in ("arm_away", "arm_home", "arm_night", "disarm"):
                    if other != command:
                        getattr(alarm._device, f"alarm_{other}").assert_not_awaited()
                alarm._device.force_arm.assert_not_awaited()
                self.assertIsNone(result)

    async def test_missing_pin_fails_before_any_command(self) -> None:
        """Missing and whitespace-only PINs must fail for arming and disarming."""
        for pin in (None, "", " \t "):
            for mode in ("away", "home", "night", "disarm"):
                with self.subTest(pin=pin, mode=mode):
                    alarm = _make_alarm(pin)
                    with self.assertRaises(_HomeAssistantError) as raised:
                        await alarm.async_set_mode_using_stored_pin(mode)
                    self.assertEqual(
                        raised.exception.translation_key, "stored_alarm_pin_missing"
                    )
                    self.assertEqual(
                        raised.exception.translation_domain, "deltadore_tydom"
                    )
                    _assert_no_commands(self, alarm)

    async def test_invalid_modes_cannot_force_or_trigger_alarm(self) -> None:
        """Even direct calls reject panic, force and unknown modes."""
        for mode in ("panic", "force", "OFF", "unknown", ""):
            with self.subTest(mode=mode):
                alarm = _make_alarm()
                with self.assertRaises(_HomeAssistantError) as raised:
                    await alarm.async_set_mode_using_stored_pin(mode)
                self.assertEqual(
                    raised.exception.translation_key,
                    "unsupported_stored_pin_alarm_mode",
                )
                self.assertNotIn("001234", str(raised.exception))
                _assert_no_commands(self, alarm)

    async def test_leading_zeroes_are_preserved(self) -> None:
        """Normalising whitespace must not turn a code into an integer."""
        alarm = _make_alarm(" 001234 ")
        await alarm.async_set_mode_using_stored_pin("away")
        alarm._device.alarm_arm_away.assert_awaited_once_with("001234")

    async def test_updated_pin_is_not_cached_by_action(self) -> None:
        """The action reads the client's currently configured code each time."""
        alarm = _make_alarm("001234")
        await alarm.async_set_mode_using_stored_pin("home")
        alarm._device._tydom_client._alarm_pin = "005678"
        await alarm.async_set_mode_using_stored_pin("disarm")
        alarm._device.alarm_arm_home.assert_awaited_once_with("001234")
        alarm._device.alarm_disarm.assert_awaited_once_with("005678")

    async def test_multiple_entries_do_not_share_pins(self) -> None:
        """An alarm must only use the PIN held by its own TYDOM client."""
        first = _make_alarm("001234")
        second = _make_alarm("005678")
        await first.async_set_mode_using_stored_pin("night")
        await second.async_set_mode_using_stored_pin("night")
        first._device.alarm_arm_night.assert_awaited_once_with("001234")
        second._device.alarm_arm_night.assert_awaited_once_with("005678")

    async def test_existing_explicit_code_commands_remain_unchanged(self) -> None:
        """Existing automations keep their explicitly supplied code."""
        for command in ("arm_away", "arm_home", "arm_night", "disarm"):
            with self.subTest(command=command):
                alarm = _make_alarm()
                await getattr(alarm, f"async_alarm_{command}")("009999")
                getattr(alarm._device, f"alarm_{command}").assert_awaited_once_with(
                    "009999"
                )

    async def test_existing_pin_free_disarm_is_not_changed(self) -> None:
        """The standard disarm path still delegates fallback to the client."""
        alarm = _make_alarm()
        await alarm.async_alarm_disarm()
        alarm._device.alarm_disarm.assert_awaited_once_with(None)

    async def test_denied_arming_keeps_existing_blocker_handling(self) -> None:
        """The new action must not force arming when the central refuses."""
        alarm = _make_alarm()
        alarm._device.alarm_arm_away.side_effect = _AlarmCommandError("DENIED")
        with self.assertRaisesRegex(_HomeAssistantError, "refused arming"):
            await alarm.async_set_mode_using_stored_pin("away")
        alarm._schedule_open_issues_refresh.assert_called_once_with()
        alarm._device.force_arm.assert_not_awaited()

    async def test_rejected_disarm_is_not_reported_as_success(self) -> None:
        """A bad stored PIN must propagate the existing gateway rejection."""
        alarm = _make_alarm()
        alarm._device.alarm_disarm.side_effect = _AlarmCommandError("BAD_PASSWORD")
        with self.assertRaisesRegex(
            _HomeAssistantError, "rejected disarming"
        ) as raised:
            await alarm.async_set_mode_using_stored_pin("disarm")
        self.assertNotIn("001234", str(raised.exception))
        alarm._device.force_arm.assert_not_awaited()

    async def test_unconfirmed_arming_retains_state_verification(self) -> None:
        """Older gateways without an outcome keep the normal refresh path."""
        alarm = _make_alarm()
        alarm._device.alarm_arm_night.return_value = False
        await alarm.async_set_mode_using_stored_pin("night")
        alarm._schedule_open_issues_refresh.assert_called_once_with(
            after_unconfirmed_arm=True
        )
        alarm._device.clear_open_issues.assert_not_called()


class StoredAlarmPinRegistrationTests(IsolatedAsyncioTestCase):
    """Exercise the actual platform registration and action schema."""

    async def asyncSetUp(self) -> None:
        """Load the setup function with a recording entity platform."""
        source_path = COMPONENT / "alarm_control_panel.py"
        module = ast.parse(source_path.read_text(encoding="utf-8"))
        module.body = [
            node
            for node in module.body
            if not isinstance(node, ast.ImportFrom | ast.Import)
        ]
        calls = []
        platform = SimpleNamespace(
            async_register_entity_service=lambda *args, **kwargs: calls.append(
                (args, kwargs)
            )
        )
        namespace = {
            "vol": vol,
            "cv": SimpleNamespace(string=str, boolean=bool),
            "DOMAIN": "deltadore_tydom",
            "HomeAssistant": object,
            "ConfigEntry": object,
            "AddEntitiesCallback": object,
            "SupportsResponse": SimpleNamespace(ONLY="only"),
            "async_get_current_platform": lambda: platform,
        }
        exec(compile(module, source_path, "exec"), namespace)
        await namespace["async_setup_entry"](
            SimpleNamespace(data={"deltadore_tydom": {"entry": SimpleNamespace()}}),
            SimpleNamespace(entry_id="entry"),
            lambda _: None,
        )
        self.calls = calls
        self.args, self.kwargs = next(call for call in calls if call[0][0] == SERVICE)
        self.schema = vol.Schema(self.args[1])

    async def test_new_action_is_registered_on_existing_alarm_entity(self) -> None:
        """Registration must dispatch to the existing alarm, not a new entity."""
        self.assertEqual(self.args[2], METHOD)
        self.assertEqual(self.kwargs, {})
        self.assertEqual(sum(call[0][0] == SERVICE for call in self.calls), 1)

    async def test_schema_accepts_all_modes_without_code(self) -> None:
        """The action only needs a mode; it cannot accept a duplicated PIN."""
        for mode in ("away", "home", "night", "disarm"):
            self.assertEqual(self.schema({"mode": mode}), {"mode": mode})

    async def test_schema_rejects_missing_mode_and_extra_code(self) -> None:
        """Invalid mode, forced mode and code overrides are not supported."""
        for data in ({}, {"mode": "force"}, {"mode": "away", "code": "001234"}):
            with self.subTest(data=data), self.assertRaises(vol.Invalid):
                self.schema(data)

    async def test_existing_services_are_still_registered(self) -> None:
        """The additive action leaves existing management services available."""
        self.assertIn("force_arm", {call[0][0] for call in self.calls})
        self.assertIn("acknowledge_events", {call[0][0] for call in self.calls})


class StoredAlarmPinPresentationTests(TestCase):
    """Verify manual controls, action descriptions and both translations."""

    def test_alarm_panel_and_entity_identity_are_unchanged(self) -> None:
        """The existing PIN request and unique ID must stay in the constructor."""
        source = (COMPONENT / "ha_entities.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        alarm = next(
            node
            for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == "HaAlarm"
        )
        constructor = next(
            node
            for node in alarm.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        constructor_source = ast.get_source_segment(source, constructor)
        self.assertIn("self._attr_code_arm_required = True", constructor_source)
        self.assertIn("self._attr_code_format = CodeFormat.NUMBER", constructor_source)
        self.assertIn('f"{self._device.device_id}_alarm"', constructor_source)

    def test_descriptions_match_registered_modes_and_target(self) -> None:
        """The UI description offers the exact schema modes on alarm entities."""
        services = yaml.safe_load(
            (COMPONENT / "services.yaml").read_text(encoding="utf-8")
        )
        service = services[SERVICE]
        self.assertEqual(service["target"]["entity"]["domain"], "alarm_control_panel")
        self.assertEqual(service["target"]["entity"]["integration"], "deltadore_tydom")
        self.assertEqual(set(service["fields"]), {"mode"})
        options = service["fields"]["mode"]["selector"]["select"]["options"]
        self.assertEqual(
            {option["value"] for option in options}, {"away", "home", "night", "disarm"}
        )
        self.assertTrue(service["fields"]["mode"]["required"])

    def test_both_languages_describe_action_and_errors(self) -> None:
        """English and French must cover the new action and safe failures."""
        for language in ("en", "fr"):
            with self.subTest(language=language):
                translations = json.loads(
                    (COMPONENT / "translations" / f"{language}.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertIn(SERVICE, translations["services"])
                self.assertEqual(
                    set(translations["services"][SERVICE]["fields"]), {"mode"}
                )
                for key in (
                    "stored_alarm_pin_missing",
                    "unsupported_stored_pin_alarm_mode",
                ):
                    self.assertTrue(translations["exceptions"][key]["message"])
