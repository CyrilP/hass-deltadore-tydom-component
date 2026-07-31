"""Tests for TYDOM device model identification."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import MagicMock


_MISSING = object()
_original_modules: dict[str, object] = {}


def _module(name: str, **attributes) -> types.ModuleType:
    """Install a minimal module needed to load the protocol code in isolation."""
    _original_modules.setdefault(name, sys.modules.get(name, _MISSING))
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    sys.modules[name] = module
    return module


for package_name in (
    "custom_components",
    "custom_components.deltadore_tydom",
    "custom_components.deltadore_tydom.tydom",
):
    package = _module(package_name)
    package.__path__ = []

_module(
    "custom_components.deltadore_tydom.const",
    LOGGER=MagicMock(),
    validate_value_with_metadata=MagicMock(return_value=(True, None)),
)

protocol_path = (
    Path(__file__).parents[1] / "custom_components" / "deltadore_tydom" / "tydom"
)
devices_name = "custom_components.deltadore_tydom.tydom.tydom_devices"
devices_spec = importlib.util.spec_from_file_location(
    devices_name, protocol_path / "tydom_devices.py"
)
assert devices_spec is not None and devices_spec.loader is not None
devices_module = importlib.util.module_from_spec(devices_spec)
_original_modules.setdefault(devices_name, sys.modules.get(devices_name, _MISSING))
sys.modules[devices_name] = devices_module
devices_spec.loader.exec_module(devices_module)

handler_name = "custom_components.deltadore_tydom.tydom.MessageHandler"
handler_spec = importlib.util.spec_from_file_location(
    handler_name, protocol_path / "MessageHandler.py"
)
assert handler_spec is not None and handler_spec.loader is not None
handler_module = importlib.util.module_from_spec(handler_spec)
_original_modules.setdefault(handler_name, sys.modules.get(handler_name, _MISSING))
sys.modules[handler_name] = handler_module
handler_spec.loader.exec_module(handler_module)

is_binary_tyxia_4900_profile = devices_module.is_binary_tyxia_4900_profile
is_tymoov_profile = devices_module.is_tymoov_profile
resolve_device_model = devices_module.resolve_device_model
MessageHandler = handler_module.MessageHandler

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


def _binary_4900_metadata() -> dict:
    return {
        "level": {"min": 0, "max": 100, "step": 100},
        "levelCmd": {"enum_values": ["OFF", "ON"]},
    }


class TestDeviceModels(TestCase):
    """Exercise model resolution from protocol-provided descriptors."""

    def test_exact_tutorial_models(self) -> None:
        """Exact product tutorial identifiers expose their product models."""
        cases = {
            "sensor_dfr": "DFR TYXAL+",
            "35_se2000": "STI 2000",
            "tysense_sun": "Tysense Sun",
            "tywell_control": "Tywell Control",
            "switch_tyxia2600_btn_a": "TYXIA 2600",
            "rcu_tyxia1410_btn_4": "TYXIA 1410",
            "tl2000_btn_2": "TL 2000 TYXAL+",
        }

        for tutorial_id, expected_model in cases.items():
            with self.subTest(tutorial_id=tutorial_id):
                self.assertEqual(
                    resolve_device_model(tutorial_id, "unknown"), expected_model
                )

    def test_family_tutorial_models(self) -> None:
        """Family-only tutorial identifiers do not invent a product reference."""
        cases = {
            "14_TyxalPlus_high": "TYXAL+",
            "25_tymoov": "TYMOOV",
            "5_detectouverture_kline": "DVI K-Line",
            "6_RecepteurRF_serie6000_2_twc": "RF 6000 series receiver",
            "7_Tyxia_serie4000": "TYXIA 4000 series",
        }

        for tutorial_id, expected_model in cases.items():
            with self.subTest(tutorial_id=tutorial_id):
                self.assertEqual(
                    resolve_device_model(tutorial_id, "light"), expected_model
                )

    def test_series_4000_gate_is_tyxia_4620(self) -> None:
        """The series-4000 impulsional gate profile identifies a TYXIA 4620."""
        self.assertEqual(
            resolve_device_model("7_Tyxia_serie4000", "gate"), "TYXIA 4620"
        )
        self.assertEqual(
            resolve_device_model("7_Tyxia_serie4000", "garage_door"),
            "TYXIA 4620",
        )

    def test_binary_series_4900_profile_is_tyxia_4910(self) -> None:
        """Binary series-4900 metadata narrows the family to TYXIA 4910."""
        metadata = _binary_4900_metadata()

        self.assertTrue(is_binary_tyxia_4900_profile(metadata))
        self.assertEqual(
            resolve_device_model("9_tyxia_modulaire_serie4900", "others", metadata),
            "TYXIA 4910",
        )

    def test_non_binary_series_4900_remains_a_family(self) -> None:
        """A different series-4900 profile must not be labelled TYXIA 4910."""
        metadata = {
            "level": {"min": 0, "max": 100, "step": 1},
            "levelCmd": {"enum_values": ["OFF", "ON"]},
        }

        self.assertFalse(is_binary_tyxia_4900_profile(metadata))
        self.assertEqual(
            resolve_device_model("9_tyxia_modulaire_serie4900", "others", metadata),
            "TYXIA 4900 series",
        )

    def test_unknown_or_missing_tutorial_is_not_guessed(self) -> None:
        """Unknown descriptors retain Home Assistant's existing fallback."""
        self.assertIsNone(resolve_device_model(None, "light"))
        self.assertIsNone(resolve_device_model("unknown_product", "light"))

    def test_tymoov_firmware_profile_fills_a_missing_tutorial(self) -> None:
        """Known TYMOOV firmware plans identify a motor with no tutorial id."""
        data = {
            "softPlan0": "24.28.00.20",
            "softPlan1": "24.94.00.11",
            "softPlan2": "24.28.00.31",
            "softPlan3": "22.10.00.30",
        }

        self.assertTrue(is_tymoov_profile(data))
        self.assertEqual(resolve_device_model(None, "shutter", data=data), "TYMOOV")

    def test_partial_tymoov_firmware_profile_is_not_guessed(self) -> None:
        """An incomplete firmware resemblance must retain the fallback."""
        data = {
            "softPlan0": "24.28.00.20",
            "softPlan2": "different-product",
            "softPlan3": "22.10.00.30",
        }

        self.assertFalse(is_tymoov_profile(data))
        self.assertIsNone(resolve_device_model(None, "shutter", data=data))


class TestDeviceModelApplication(IsolatedAsyncioTestCase):
    """Exercise model application when protocol devices are created."""

    def setUp(self) -> None:
        """Reset the protocol descriptors used by the device factory."""
        handler_module.device_name.clear()
        handler_module.device_type.clear()
        handler_module.device_metadata.clear()
        handler_module.device_tutorial_id.clear()
        handler_module.endpoint_config.clear()

    async def test_resolved_model_is_added_to_device_data(self) -> None:
        """A descriptor-derived model is exposed through productName."""
        uid = "20_10"
        handler_module.device_tutorial_id[uid] = "sensor_dfr"

        device = await MessageHandler.get_device(
            MagicMock(), "sensorDFR", uid, "10", "Smoke detector", "20", None
        )

        self.assertIsNotNone(device)
        self.assertEqual(device.productName, "DFR TYXAL+")

    async def test_reported_product_name_takes_precedence(self) -> None:
        """An explicit model reported by TYDOM is never overwritten."""
        uid = "20_10"
        handler_module.device_tutorial_id[uid] = "sensor_dfr"

        device = await MessageHandler.get_device(
            MagicMock(),
            "sensorDFR",
            uid,
            "10",
            "Smoke detector",
            "20",
            {"productName": "Reported model"},
        )

        self.assertIsNotNone(device)
        self.assertEqual(device.productName, "Reported model")

    async def test_separately_paired_tyxia_2600_is_identified(self) -> None:
        """The observed two-record pairing retains its physical model."""
        device_id = 30
        endpoint_ids = (30, 31)
        await MessageHandler.parse_config_data(
            {
                "endpoints": [
                    {
                        "id_device": device_id,
                        "id_endpoint": endpoint_ids[0],
                        "name": "Interrupteur 1",
                        "last_usage": "interrupter",
                    },
                    {
                        "id_device": device_id,
                        "id_endpoint": endpoint_ids[1],
                        "name": "CG_DD_COMMON_BUTTONB",
                        "last_usage": "interrupter",
                    },
                ]
            },
            None,
        )

        for endpoint_id in endpoint_ids:
            uid = f"{endpoint_id}_{device_id}"
            device = await MessageHandler.get_device(
                MagicMock(), "interrupter", uid, device_id, "Button", endpoint_id
            )
            self.assertIsNotNone(device)
            self.assertEqual(device.productName, "TYXIA 2600")


if __name__ == "__main__":
    unittest.main()
