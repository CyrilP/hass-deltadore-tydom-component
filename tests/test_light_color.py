"""Tests for colour and white-temperature support on lights."""

import ast
from contextlib import contextmanager
import importlib.util
import math
from pathlib import Path
import sys
import types
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, call, patch

_COMPONENT = Path(__file__).parents[1] / "custom_components" / "deltadore_tydom"
_MISSING = object()


def _load_devices_module() -> types.ModuleType:
    """Load the real protocol devices and metadata validation without HA."""
    names = {
        "custom_components": None,
        "custom_components.deltadore_tydom": None,
        "custom_components.deltadore_tydom.tydom": None,
        "custom_components.deltadore_tydom.const": _COMPONENT / "const.py",
        "custom_components.deltadore_tydom.tydom.tydom_devices": _COMPONENT
        / "tydom"
        / "tydom_devices.py",
    }
    originals = {name: sys.modules.get(name, _MISSING) for name in names}
    try:
        for name, path in names.items():
            if path is None:
                package = types.ModuleType(name)
                package.__path__ = []
                sys.modules[name] = package
                continue
            spec = importlib.util.spec_from_file_location(name, path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        return sys.modules["custom_components.deltadore_tydom.tydom.tydom_devices"]
    finally:
        for name, original in originals.items():
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


class ColorMode:
    """Stand-in for the Home Assistant color modes used by HaLight."""

    ONOFF = "onoff"
    BRIGHTNESS = "brightness"
    COLOR_TEMP = "color_temp"
    XY = "xy"


class LightEntity:
    """Stand-in exposing Home Assistant's default kelvin range."""

    min_color_temp_kelvin = 2000
    max_color_temp_kelvin = 6535


class HAEntity:
    """Stand-in for the integration's entity mixin."""


def _load_ha_light():
    """Load only HaLight from ha_entities.py, as the group entity tests do."""
    source_path = _COMPONENT / "ha_entities.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    class_node = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "HaLight"
    )
    isolated_module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            class_node,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(isolated_module)
    namespace = {
        "ATTR_BRIGHTNESS": "brightness",
        "ATTR_COLOR_TEMP_KELVIN": "color_temp_kelvin",
        "ATTR_XY_COLOR": "xy_color",
        "ColorMode": ColorMode,
        "HAEntity": HAEntity,
        "LightEntity": LightEntity,
        "math": math,
        # The two conversions match homeassistant.util.color.
        "color_temperature_kelvin_to_mired": lambda k: math.floor(1000000 / k),
        "color_temperature_mired_to_kelvin": lambda m: math.floor(1000000 / m),
        "percentage_to_ranged_value": lambda _, value: value * 255 / 100,
        "ranged_value_to_percentage": lambda _, value: value * 100 / 255,
    }
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return namespace["HaLight"]


TydomLight = _load_devices_module().TydomLight
HaLight = _load_ha_light()

LEVEL = {"permission": "rw", "type": "numeric", "min": 0, "max": 100, "step": 1}
COLOR_XY = {
    "permission": "rw",
    "type": "numeric",
    "min": 0,
    "max": 4294967294,
    "step": 1,
}
MIRED = {"permission": "rw", "type": "numeric", "min": 0, "max": 65279, "step": 1}
MIRED_LIMIT = {"permission": "r", "type": "numeric", "min": 0, "max": 65279, "step": 1}
COLOR_MODE = {"permission": "r", "type": "string"}
XY_METADATA = {"level": LEVEL, "colorXY": COLOR_XY, "colorMode": COLOR_MODE}
TEMP_METADATA = {
    "level": LEVEL,
    "miredTemperatureW": MIRED,
    "minMiredTemperatureW": MIRED_LIMIT,
    "maxMiredTemperatureW": MIRED_LIMIT,
    "colorMode": COLOR_MODE,
}
COLOR_METADATA = {**XY_METADATA, **TEMP_METADATA}
POLL_URL = "/devices/20/endpoints/10/data"


def _device(metadata: dict | None, **data) -> TydomLight:
    """Return a real light on a mocked gateway client."""
    client = MagicMock()
    client.put_devices_data = AsyncMock()
    return TydomLight(client, "10_20", "20", "Bulb", "light", "10", metadata, data)


def _entity(metadata: dict | None, **data) -> HaLight:
    """Return a real HaLight around a real light."""
    return HaLight(_device(metadata, **data), MagicMock())


@contextmanager
def _home_assistant_error():
    """Provide the HomeAssistantError a device imports when it refuses a write."""

    class HomeAssistantError(Exception):
        pass

    exceptions = types.ModuleType("homeassistant.exceptions")
    exceptions.HomeAssistantError = HomeAssistantError
    with patch.dict(sys.modules, {"homeassistant.exceptions": exceptions}):
        yield HomeAssistantError


def _puts(light: TydomLight | HaLight) -> list:
    """Return the attribute writes sent to the gateway, in order."""
    device = light._device if isinstance(light, HaLight) else light
    return device._tydom_client.put_devices_data.await_args_list


class ColorModeTests(TestCase):
    """Choose modes from gateway metadata and report the active one."""

    def test_no_color_metadata_keeps_brightness(self) -> None:
        """A dim-only bulb stays a plain brightness light."""
        entity = _entity({"level": LEVEL}, level=50)
        self.assertEqual(entity._attr_supported_color_modes, {ColorMode.BRIGHTNESS})
        self.assertEqual(entity.color_mode, ColorMode.BRIGHTNESS)

    def test_no_metadata_keeps_onoff(self) -> None:
        """A light without metadata stays on/off."""
        entity = _entity(None)
        self.assertEqual(entity._attr_supported_color_modes, {ColorMode.ONOFF})
        self.assertEqual(entity.color_mode, ColorMode.ONOFF)

    def test_read_only_metadata_is_not_color(self) -> None:
        """Read-only colour attributes do not advertise colour."""
        metadata = {
            **COLOR_METADATA,
            "colorXY": {"permission": "r"},
            "miredTemperatureW": {"permission": "r"},
        }
        entity = _entity(metadata, level=50)
        self.assertEqual(entity._attr_supported_color_modes, {ColorMode.BRIGHTNESS})

    def test_permission_case_is_ignored(self) -> None:
        """An upper-case permission reads as the lower-case one."""
        metadata = {
            **COLOR_METADATA,
            "level": {**LEVEL, "permission": "RW"},
            "colorXY": {**COLOR_XY, "permission": "RW"},
        }
        self.assertTrue(_device(metadata).supports_color_xy)
        self.assertFalse(
            _device(
                {**metadata, "level": {**LEVEL, "permission": "R"}}
            ).supports_color_xy
        )

    def test_missing_permission_is_not_color(self) -> None:
        """Only an explicit write permission advertises colour."""
        entity = _entity({"level": LEVEL, "colorXY": {"type": "numeric"}}, level=50)
        self.assertEqual(entity._attr_supported_color_modes, {ColorMode.BRIGHTNESS})

    def test_read_only_level_is_not_color(self) -> None:
        """Lighting a bulb for a colour writes level: a read-only one has no colour."""
        entity = _entity({**COLOR_METADATA, "level": {**LEVEL, "permission": "r"}})
        self.assertEqual(entity._attr_supported_color_modes, {ColorMode.BRIGHTNESS})

    def test_level_without_permission_keeps_color(self) -> None:
        """Only an explicit read-only level withdraws colour."""
        unmarked = {k: v for k, v in LEVEL.items() if k != "permission"}
        entity = _entity({**COLOR_METADATA, "level": unmarked}, level=0)
        self.assertEqual(
            entity._attr_supported_color_modes, {ColorMode.XY, ColorMode.COLOR_TEMP}
        )

    def test_color_needs_brightness(self) -> None:
        """Without dimming a colour mode's slider would not work: stay on/off."""
        color_only = {k: v for k, v in COLOR_METADATA.items() if k != "level"}
        binary = {**COLOR_METADATA, "level": {**LEVEL, "step": 100}}
        for metadata in (color_only, binary):
            with self.subTest(metadata=metadata.get("level")):
                entity = _entity(metadata, level=50)
                self.assertEqual(entity._attr_supported_color_modes, {ColorMode.ONOFF})
                self.assertEqual(entity.color_mode, ColorMode.ONOFF)

    def test_xy_only(self) -> None:
        """A writable colorXY alone gives XY without brightness."""
        entity = _entity(XY_METADATA, level=50)
        self.assertEqual(entity._attr_supported_color_modes, {ColorMode.XY})

    def test_temperature_only(self) -> None:
        """A writable temperature with its limits gives COLOR_TEMP alone."""
        entity = _entity(TEMP_METADATA, level=50)
        self.assertEqual(entity._attr_supported_color_modes, {ColorMode.COLOR_TEMP})

    def test_both(self) -> None:
        """A full colour bulb gets both modes and nothing else."""
        entity = _entity(COLOR_METADATA, level=50)
        self.assertEqual(
            entity._attr_supported_color_modes,
            {ColorMode.XY, ColorMode.COLOR_TEMP},
        )

    def test_temperature_needs_both_limits(self) -> None:
        """A temperature without its min or max attribute is not supported."""
        for missing in ("minMiredTemperatureW", "maxMiredTemperatureW"):
            with self.subTest(missing=missing):
                metadata = dict(TEMP_METADATA)
                del metadata[missing]
                self.assertFalse(_device(metadata).supports_color_temp)

    def test_reported_modes(self) -> None:
        """The gateway's colorMode picks the active mode."""
        for reported, expected in (
            ("TEMP. MIRED", ColorMode.COLOR_TEMP),
            ("XY", ColorMode.XY),
            ("HUE_SAT", ColorMode.XY),
        ):
            with self.subTest(reported=reported):
                # colorXY and mired both hold values, as they do in white mode.
                entity = _entity(
                    COLOR_METADATA,
                    level=50,
                    colorMode=reported,
                    colorXY=2899071598,
                    miredTemperatureW=300,
                )
                self.assertEqual(entity.color_mode, expected)

    def test_reported_temperature_without_mired_value(self) -> None:
        """The reported mode wins over the fallback, which would pick XY here."""
        entity = _entity(
            COLOR_METADATA, level=50, colorMode="TEMP. MIRED", colorXY=2899071598
        )
        self.assertEqual(entity.color_mode, ColorMode.COLOR_TEMP)

    def test_unknown_mode_falls_back(self) -> None:
        """A missing or unknown colorMode still returns a mode."""
        for data in ({}, {"colorMode": "OTHER"}, {"colorMode": None}):
            with self.subTest(data=data):
                entity = _entity(
                    COLOR_METADATA, level=50, miredTemperatureW=300, **data
                )
                self.assertEqual(entity.color_mode, ColorMode.COLOR_TEMP)
                entity = _entity(COLOR_METADATA, level=50, **data)
                self.assertEqual(entity.color_mode, ColorMode.XY)

    def test_mode_is_always_supported(self) -> None:
        """A reported or fallback mode the bulb lacks is never returned."""
        entity = _entity(TEMP_METADATA, level=50, colorMode="XY")
        self.assertEqual(entity.color_mode, ColorMode.COLOR_TEMP)
        entity = _entity(TEMP_METADATA, level=50)
        self.assertEqual(entity.color_mode, ColorMode.COLOR_TEMP)
        entity = _entity(XY_METADATA, level=50, colorMode="TEMP. MIRED")
        self.assertEqual(entity.color_mode, ColorMode.XY)
        entity = _entity(XY_METADATA, level=50, miredTemperatureW=300)
        self.assertEqual(entity.color_mode, ColorMode.XY)


class ColorValueTests(TestCase):
    """Decode gateway values and derive limits."""

    def test_metadata_without_values(self) -> None:
        """Colour metadata without values reads as None, without error."""
        entity = _entity(COLOR_METADATA)
        self.assertIsNone(entity.xy_color)
        self.assertIsNone(entity.color_temp_kelvin)
        self.assertIsNone(entity._device.mired_limits)
        self.assertIsNone(entity._device.color_mode_name)

    def test_zero_values_read_as_none(self) -> None:
        """Zero means unset for both colorXY and mired."""
        entity = _entity(COLOR_METADATA, colorXY=0, miredTemperatureW=0)
        self.assertIsNone(entity.xy_color)
        self.assertIsNone(entity.color_temp_kelvin)

    def test_unusable_values_read_as_none(self) -> None:
        """A malformed or out-of-range value reads as None."""
        for value in ("n/a", {"x": 1}, -1, 1 << 32, float("inf")):
            with self.subTest(value=value):
                entity = _entity(COLOR_METADATA, colorXY=value)
                self.assertIsNone(entity.xy_color)

    def test_decode_xy(self) -> None:
        """High 16 bits are x and low 16 bits are y, each over 65535."""
        x, y = _entity(XY_METADATA, colorXY=(32768 << 16) | 16384).xy_color
        self.assertEqual((x, y), (32768 / 65535, 16384 / 65535))

    def test_decode_mired(self) -> None:
        """Mired converts to Kelvin."""
        entity = _entity(TEMP_METADATA, miredTemperatureW=500)
        self.assertEqual(entity.color_temp_kelvin, 2000)

    def test_pack_unpack_round_trip(self) -> None:
        """A packed value decodes to the same colour within one step."""
        for xy in ((0.675, 0.322), (0.0, 0.5), (0.5, 0.0), (1.0, 0.25), (1.0, 1.0)):
            with self.subTest(xy=xy):
                device = _device(XY_METADATA, colorXY=TydomLight._pack_color_xy(xy))
                decoded = device.color_xy
                self.assertAlmostEqual(decoded[0], xy[0], delta=1 / 65535)
                self.assertAlmostEqual(decoded[1], xy[1], delta=1 / 65535)

    def test_pack_is_exact_and_string_value_decodes(self) -> None:
        """A value the gateway accepted survives a decode and pack."""
        device = _device(XY_METADATA, colorXY="2899071598")
        self.assertEqual(TydomLight._pack_color_xy(device.color_xy), 2899071598)

    def test_pack_clamps_to_gateway_maximum(self) -> None:
        """Full-scale x and y would exceed the attribute's maximum."""
        self.assertEqual(TydomLight._pack_color_xy((1.0, 1.0)), 4294967294)

    def test_limits_per_bulb(self) -> None:
        """Min kelvin comes from max mired and max kelvin from min mired."""
        for maximum, min_kelvin in ((447, 2237), (500, 2000)):
            with self.subTest(maximum=maximum):
                entity = _entity(
                    TEMP_METADATA,
                    minMiredTemperatureW=153,
                    maxMiredTemperatureW=maximum,
                )
                self.assertEqual(entity.min_color_temp_kelvin, min_kelvin)
                self.assertEqual(entity.max_color_temp_kelvin, 6535)

    def test_unusable_limits_use_home_assistant_defaults(self) -> None:
        """Missing, partial or inverted limits fall back to HA's range."""
        for data in (
            {},
            {"minMiredTemperatureW": 153},
            {"maxMiredTemperatureW": 447},
            {"minMiredTemperatureW": 447, "maxMiredTemperatureW": 153},
        ):
            with self.subTest(data=data):
                entity = _entity(TEMP_METADATA, **data)
                self.assertEqual(entity.min_color_temp_kelvin, 2000)
                self.assertEqual(entity.max_color_temp_kelvin, 6535)


class LightWriteTests(IsolatedAsyncioTestCase):
    """Check the writes sent to the gateway, and their order."""

    async def test_color_while_dimmed_sends_no_level(self) -> None:
        """A dimmed bulb stays dimmed when only its colour changes."""
        entity = _entity(COLOR_METADATA, level=30)
        await entity.async_turn_on(xy_color=(0.5, 0.25))
        packed = (round(0.5 * 65535) << 16) | round(0.25 * 65535)
        self.assertEqual(_puts(entity), [call("20", "10", "colorXY", str(packed))])
        entity._device._tydom_client.add_poll_device_url_1s.assert_called_once_with(
            POLL_URL
        )

    async def test_temperature_while_dimmed_sends_no_level(self) -> None:
        """A dimmed bulb stays dimmed when only its temperature changes."""
        entity = _entity(
            COLOR_METADATA,
            level=30,
            minMiredTemperatureW=153,
            maxMiredTemperatureW=500,
        )
        await entity.async_turn_on(color_temp_kelvin=2000)
        self.assertEqual(_puts(entity), [call("20", "10", "miredTemperatureW", "500")])
        entity._device._tydom_client.add_poll_device_url_1s.assert_called_once_with(
            POLL_URL
        )

    async def test_color_while_off_sends_level_first(self) -> None:
        """An off bulb, or one without a level value, is lit before the colour."""
        for data in ({"level": 0}, {"level": None}, {}):
            with self.subTest(data=data):
                entity = _entity(COLOR_METADATA, **data)
                await entity.async_turn_on(xy_color=(0.0, 1.0))
                self.assertEqual(
                    _puts(entity),
                    [
                        call("20", "10", "level", "100"),
                        call("20", "10", "colorXY", "65535"),
                    ],
                )

    async def test_read_only_level_is_never_written(self) -> None:
        """A level marked read-only is refused, whatever the request asked for."""
        metadata = {**COLOR_METADATA, "level": {**LEVEL, "permission": "r"}}
        requests = (
            {},
            {"brightness": 128},
            {"xy_color": (0.0, 1.0)},
            {"color_temp_kelvin": 3000},
            {"brightness": 128, "xy_color": (0.0, 1.0)},
        )
        with _home_assistant_error() as error:
            for request in requests:
                for level in (0, 30):
                    with self.subTest(request=request, level=level):
                        entity = _entity(metadata, level=level)
                        with self.assertRaises(error):
                            await entity.async_turn_on(**request)
                        self.assertEqual(_puts(entity), [])
            entity = _entity(metadata, level=30)
            with self.assertRaises(error):
                await entity.async_turn_off()
            self.assertEqual(_puts(entity), [])

    async def test_read_only_level_still_switches_through_level_command(self) -> None:
        """A levelCmd needs no level write, so it keeps switching such a light."""
        metadata = {
            **COLOR_METADATA,
            "level": {**LEVEL, "permission": "r"},
            "levelCmd": {"permission": "w", "enum_values": ["ON", "OFF"]},
        }
        entity = _entity(metadata, level=0)
        await entity.async_turn_on(xy_color=(0.0, 1.0))
        await entity.async_turn_off()
        self.assertEqual(
            _puts(entity),
            [call("20", "10", "levelCmd", "ON"), call("20", "10", "levelCmd", "OFF")],
        )

    async def test_level_without_permission_is_still_written(self) -> None:
        """Only an explicit read-only stops the write: other lights are unchanged."""
        unmarked = {"type": "numeric", "min": 0, "max": 100, "step": 1}
        levels = [unmarked, "n/a"]
        levels += [{**unmarked, "permission": p} for p in (None, "", "RW", "w")]
        for metadata in (None, {}, *({"level": level} for level in levels)):
            with self.subTest(metadata=metadata):
                entity = _entity(metadata, level=0)
                await entity.async_turn_on()
                await entity.async_turn_off()
                self.assertEqual(
                    _puts(entity),
                    [call("20", "10", "level", "100"), call("20", "10", "level", "0")],
                )

    async def test_color_never_toggles(self) -> None:
        """Without a writable ON, a stale off level must not toggle a lit bulb off."""
        for level_cmd in (
            {"permission": "w", "enum_values": ["TOGGLE"]},
            {"permission": "w", "enum_values": ["TOGGLE", "OFF"]},
            {"permission": "w", "enum_values": []},
            {"permission": "w", "enum_values": None},
            {"permission": "r", "enum_values": ["ON", "OFF"]},
        ):
            for data in ({"level": 0}, {"level": None}, {}):
                with self.subTest(level_cmd=level_cmd, data=data):
                    metadata = {**COLOR_METADATA, "levelCmd": level_cmd}
                    entity = _entity(metadata, **data)
                    await entity.async_turn_on(xy_color=(0.0, 1.0))
                    self.assertEqual(
                        _puts(entity),
                        [
                            call("20", "10", "level", "100"),
                            call("20", "10", "colorXY", "65535"),
                        ],
                    )
                    self.assertEqual(entity._device.level, 100)

    async def test_toggle_flips_the_remembered_state(self) -> None:
        """A TOGGLE-only bulb is remembered as what the TOGGLE left it."""
        metadata = {
            **COLOR_METADATA,
            "levelCmd": {"permission": "w", "enum_values": ["TOGGLE"]},
        }
        for level, action, expected in (
            (40, "on", 0),
            (0, "on", 100),
            (40, "off", 0),
            (0, "off", 100),
            (None, "on", None),
            (None, "off", None),
        ):
            with self.subTest(level=level, action=action):
                entity = _entity(metadata, level=level)
                if action == "on":
                    await entity.async_turn_on()
                else:
                    await entity.async_turn_off()
                self.assertEqual(
                    _puts(entity), [call("20", "10", "levelCmd", "TOGGLE")]
                )
                self.assertEqual(entity._device.level, expected)

    async def test_color_from_off_lights_as_a_plain_on_does(self) -> None:
        """The level that lights an off bulb is 100 unchecked, as for a plain on."""
        metadata = {**COLOR_METADATA, "level": {**LEVEL, "max": 99}}
        plain = _entity(metadata, level=0)
        await plain.async_turn_on()
        entity = _entity(metadata, level=0)
        await entity.async_turn_on(xy_color=(0.0, 1.0))
        self.assertEqual(
            _puts(entity), [*_puts(plain), call("20", "10", "colorXY", "65535")]
        )

    async def test_on_command_without_permission_is_used(self) -> None:
        """Only a read-only levelCmd is passed over: an unmarked ON still lights."""
        metadata = {**COLOR_METADATA, "levelCmd": {"enum_values": ["ON", "OFF"]}}
        entity = _entity(metadata, level=0)
        await entity.async_turn_on(xy_color=(0.0, 1.0))
        self.assertEqual(
            _puts(entity),
            [call("20", "10", "levelCmd", "ON"), call("20", "10", "colorXY", "65535")],
        )

    async def test_temperature_snaps_to_metadata_step(self) -> None:
        """A slider value between two steps lands on the nearest one in range."""
        for kelvin, expected in (
            (3000, "330"),  # 333 mired
            (2970, "340"),  # 336 mired
            (6600, "160"),  # clamped to 153, whose nearest step 150 is out of range
            (2000, "500"),
            (2040, "490"),
        ):
            with self.subTest(kelvin=kelvin):
                metadata = {
                    **COLOR_METADATA,
                    "miredTemperatureW": {**MIRED, "min": 150, "max": 500, "step": 10},
                }
                entity = _entity(
                    metadata,
                    level=30,
                    minMiredTemperatureW=153,
                    maxMiredTemperatureW=500,
                )
                await entity.async_turn_on(color_temp_kelvin=kelvin)
                self.assertEqual(
                    _puts(entity),
                    [call("20", "10", "miredTemperatureW", expected)],
                )

    async def test_temperature_step_counts_from_metadata_minimum(self) -> None:
        """Steps start at the metadata minimum, as the validator counts them."""
        metadata = {
            **COLOR_METADATA,
            "miredTemperatureW": {**MIRED, "min": 153, "max": 500, "step": 10},
        }
        entity = _entity(metadata, level=30)
        await entity.async_turn_on(color_temp_kelvin=3000)
        self.assertEqual(_puts(entity), [call("20", "10", "miredTemperatureW", "333")])

    async def test_temperature_stays_inside_metadata_range(self) -> None:
        """Without usable limits, HA's default range is cut to the metadata's."""
        for step in ({}, {"step": 1}):
            for kelvin, expected in ((2000, "454"), (6535, "250"), (3000, "333")):
                with self.subTest(step=step, kelvin=kelvin):
                    metadata = {
                        **COLOR_METADATA,
                        "miredTemperatureW": {**MIRED, "min": 250, "max": 454, **step},
                    }
                    entity = _entity(metadata, level=30)
                    await entity.async_turn_on(color_temp_kelvin=kelvin)
                    self.assertEqual(
                        _puts(entity), [call("20", "10", "miredTemperatureW", expected)]
                    )

    async def test_temperature_never_passes_a_warm_limit(self) -> None:
        """Kelvin and back can land one mired past a limit above 1000 mired."""
        entity = _entity(
            COLOR_METADATA,
            level=30,
            minMiredTemperatureW=153,
            maxMiredTemperatureW=1500,
        )
        await entity.async_turn_on(color_temp_kelvin=500)
        self.assertEqual(_puts(entity), [call("20", "10", "miredTemperatureW", "1500")])

    async def test_temperature_snaps_without_maximum_or_limits(self) -> None:
        """A step alone still snaps: no metadata maximum, no limits reported."""
        metadata = {
            **COLOR_METADATA,
            "miredTemperatureW": {"permission": "rw", "type": "numeric", "step": 10},
        }
        entity = _entity(metadata, level=30)
        await entity.async_turn_on(color_temp_kelvin=3000)
        self.assertEqual(_puts(entity), [call("20", "10", "miredTemperatureW", "330")])

    async def test_temperature_without_usable_step_is_unchanged(self) -> None:
        """A missing, zero or malformed step sends the requested mired."""
        for step in ({}, {"step": 0}, {"step": "n/a"}, {"step": 1}):
            with self.subTest(step=step):
                metadata = {**COLOR_METADATA, "miredTemperatureW": {**MIRED, **step}}
                entity = _entity(metadata, level=30)
                await entity.async_turn_on(color_temp_kelvin=3000)
                self.assertEqual(
                    _puts(entity), [call("20", "10", "miredTemperatureW", "333")]
                )

    async def test_color_after_brightness_keeps_that_brightness(self) -> None:
        """A colour right after dimming an off bulb, before any poll, sends no level."""
        entity = _entity(COLOR_METADATA, level=0)
        await entity.async_turn_on(brightness=255)
        await entity.async_turn_on(xy_color=(0.0, 1.0))
        self.assertEqual(
            _puts(entity),
            [
                call("20", "10", "level", "100"),
                call("20", "10", "colorXY", "65535"),
            ],
        )
        entity = _entity(COLOR_METADATA, level=0)
        await entity._device.set_light_state(30)
        await entity.async_turn_on(xy_color=(0.0, 1.0))
        self.assertEqual(
            _puts(entity),
            [
                call("20", "10", "level", "30"),
                call("20", "10", "colorXY", "65535"),
            ],
        )

    async def test_color_after_turn_off_lights_the_bulb(self) -> None:
        """A colour right after turning off, before any poll, lights the bulb again."""
        entity = _entity(COLOR_METADATA, level=30)
        await entity.async_turn_off()
        await entity.async_turn_on(xy_color=(0.0, 1.0))
        self.assertEqual(
            _puts(entity),
            [
                call("20", "10", "level", "0"),
                call("20", "10", "level", "100"),
                call("20", "10", "colorXY", "65535"),
            ],
        )

    async def test_color_after_plain_on_sends_no_level(self) -> None:
        """A plain on counts as lit for the colour that follows it."""
        entity = _entity(COLOR_METADATA, level=0)
        await entity.async_turn_on()
        await entity.async_turn_on(xy_color=(0.0, 1.0))
        self.assertEqual(
            _puts(entity),
            [
                call("20", "10", "level", "100"),
                call("20", "10", "colorXY", "65535"),
            ],
        )

    async def test_color_from_off_uses_level_command(self) -> None:
        """With an explicit ON, colour from off lights the bulb through it."""
        metadata = {
            **COLOR_METADATA,
            "levelCmd": {"permission": "w", "enum_values": ["ON", "OFF"]},
        }
        entity = _entity(metadata, level=0)
        await entity.async_turn_on(xy_color=(0.0, 1.0))
        await entity.async_turn_on(xy_color=(0.0, 1.0))
        await entity.async_turn_off()
        await entity.async_turn_on(xy_color=(0.0, 1.0))
        self.assertEqual(
            _puts(entity),
            [
                call("20", "10", "levelCmd", "ON"),
                call("20", "10", "colorXY", "65535"),
                call("20", "10", "colorXY", "65535"),
                call("20", "10", "levelCmd", "OFF"),
                call("20", "10", "levelCmd", "ON"),
                call("20", "10", "colorXY", "65535"),
            ],
        )

    async def test_failed_write_still_polls(self) -> None:
        """A failure after a partial change still queues the poll."""
        entity = _entity(COLOR_METADATA, level=0)
        client = entity._device._tydom_client
        client.put_devices_data.side_effect = [None, OSError]
        with self.assertRaises(OSError):
            await entity.async_turn_on(xy_color=(0.0, 1.0))
        self.assertEqual(client.put_devices_data.await_count, 2)
        client.add_poll_device_url_1s.assert_called_once_with(POLL_URL)

    async def test_failed_level_write_is_not_remembered(self) -> None:
        """Only a level the gateway accepted replaces the cached one."""
        entity = _entity(COLOR_METADATA, level=30)
        client = entity._device._tydom_client
        client.put_devices_data.side_effect = OSError
        with self.assertRaises(OSError):
            await entity.async_turn_off()
        self.assertEqual(entity._device.level, 30)
        entity = _entity(COLOR_METADATA, level=0)
        client = entity._device._tydom_client
        client.put_devices_data.side_effect = OSError
        with self.assertRaises(OSError):
            await entity.async_turn_on(brightness=255)
        self.assertEqual(entity._device.level, 0)

    async def test_non_color_light_keeps_cached_level(self) -> None:
        """Only a gateway report changes the level of a light without colour."""
        entity = _entity({"level": LEVEL}, level=30)
        await entity.async_turn_on(brightness=255)
        await entity.async_turn_off()
        self.assertEqual(entity._device.level, 30)

    async def test_brightness_and_color_send_both_in_order(self) -> None:
        """Brightness is written before the colour."""
        for data in ({"level": 30}, {"level": 0}):
            with self.subTest(data=data):
                entity = _entity(COLOR_METADATA, **data)
                await entity.async_turn_on(brightness=255, xy_color=(0.0, 1.0))
                self.assertEqual(
                    _puts(entity),
                    [
                        call("20", "10", "level", "100"),
                        call("20", "10", "colorXY", "65535"),
                    ],
                )

    async def test_brightness_and_temperature_send_both_in_order(self) -> None:
        """Brightness is written before the temperature."""
        entity = _entity(COLOR_METADATA, level=30)
        await entity.async_turn_on(brightness=255, color_temp_kelvin=2500)
        self.assertEqual(
            _puts(entity),
            [
                call("20", "10", "level", "100"),
                call("20", "10", "miredTemperatureW", "400"),
            ],
        )

    async def test_kelvin_clamps_per_bulb(self) -> None:
        """Requests outside a bulb's own range land on its limits."""
        for maximum, kelvin, expected in (
            (447, 1000, "447"),
            (447, 10000, "153"),
            (447, 0, "447"),
            (447, 2500, "400"),
            (500, 1000, "500"),
            (500, 10000, "153"),
            (500, 2237, "447"),
        ):
            with self.subTest(maximum=maximum, kelvin=kelvin):
                entity = _entity(
                    COLOR_METADATA,
                    level=30,
                    minMiredTemperatureW=153,
                    maxMiredTemperatureW=maximum,
                )
                await entity.async_turn_on(color_temp_kelvin=kelvin)
                self.assertEqual(
                    _puts(entity),
                    [call("20", "10", "miredTemperatureW", expected)],
                )

    async def test_invalid_value_writes_nothing(self) -> None:
        """A value metadata rejects fails before the first write."""
        metadata = {**COLOR_METADATA, "colorXY": {**COLOR_XY, "max": 100}}
        device = _device(metadata, level=0)
        with _home_assistant_error() as error, self.assertRaises(error):
            await device.set_light_state(50, (0.5, 0.5), None)
        self.assertEqual(_puts(device), [])
        device._tydom_client.add_poll_device_url_1s.assert_not_called()

    async def test_plain_on_off_on_color_bulb(self) -> None:
        """Without colour, a colour bulb uses the existing commands."""
        entity = _entity(COLOR_METADATA, level=30)
        await entity.async_turn_on()
        await entity.async_turn_on(brightness=255)
        await entity.async_turn_off()
        self.assertEqual(
            _puts(entity),
            [
                call("20", "10", "level", "100"),
                call("20", "10", "level", "100"),
                call("20", "10", "level", "0"),
            ],
        )
        self.assertEqual(
            entity._device._tydom_client.add_poll_device_url_1s.call_count, 3
        )

    async def test_non_color_light_is_unchanged(self) -> None:
        """A light without colour metadata writes what it always wrote."""
        metadata = {
            "level": LEVEL,
            "levelCmd": {"permission": "w", "enum_values": ["ON", "OFF"]},
        }
        entity = _entity(metadata, level=0)
        await entity.async_turn_on()
        await entity.async_turn_on(brightness=255)
        await entity.async_turn_off()
        self.assertEqual(
            _puts(entity),
            [
                call("20", "10", "levelCmd", "ON"),
                call("20", "10", "level", "100"),
                call("20", "10", "levelCmd", "OFF"),
            ],
        )

    async def test_unsupported_color_arguments_are_ignored(self) -> None:
        """A colour argument the bulb cannot take sends no write."""
        entity = _entity({"level": LEVEL}, level=30)
        await entity.async_turn_on(xy_color=(0.5, 0.5), color_temp_kelvin=3000)
        self.assertEqual(_puts(entity), [call("20", "10", "level", "100")])

        entity = _entity(XY_METADATA, level=30)
        await entity.async_turn_on(color_temp_kelvin=3000)
        self.assertEqual(_puts(entity), [call("20", "10", "level", "100")])

        entity = _entity(TEMP_METADATA, level=30)
        await entity.async_turn_on(xy_color=(0.5, 0.5))
        self.assertEqual(_puts(entity), [call("20", "10", "level", "100")])
