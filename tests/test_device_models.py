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

is_binary_tyxia_receiver_profile = devices_module.is_binary_tyxia_receiver_profile
is_trv_1_profile = devices_module.is_trv_1_profile
is_tymoov_profile = devices_module.is_tymoov_profile
is_tybox_1137_profile = devices_module.is_tybox_1137_profile
is_tyxia_dimmer_profile = devices_module.is_tyxia_dimmer_profile
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
            "25_tymoov": "TYMOOV",
            "35_se2000": "Tysense Thermo",
            "4_dvi_kline": "DVI K-Line",
            "6_pod_kline": "POD K-Line",
            "7_dvi_kline_fenetre_coul_battant": "DVI K-Line",
            "tysense_sun": "Tysense Sun",
            "tywell_control": "Tywell Control",
            "tywell_control_2050": "Tywell 2050",
            "8_Tyxia6610": "TYXIA 6610",
            "8_dvi_kline_fenetre_coul": "DVI K-Line",
            "smart_plug_DD": "Delta Dore Easy Plug",
            "split_takao_type_1": "Atlantic Naviclim 875311",
            "split_takao_type_2": "Atlantic Naviclim 875311",
            "switch_tyxia2600_btn_a": "TYXIA 2600",
            "rcu_tyxia1410_btn_4": "TYXIA 1410",
            "tl2000_btn_2": "TL 2000 Tyxal+",
            "Tywatt_serie1000": "TYWATT 1000",
            "Volet_roulant_wellcom": "Well'com roller shutter",
        }

        for tutorial_id, expected_model in cases.items():
            with self.subTest(tutorial_id=tutorial_id):
                self.assertEqual(
                    resolve_device_model(tutorial_id, "unknown"), expected_model
                )

    def test_family_tutorials_do_not_become_models(self) -> None:
        """Family-only tutorial identifiers retain the existing fallback."""
        tutorials = {
            "14_TyxalPlus_high",
            "34_tywatt_54xx+",
            "1_Calybox_Tybox_serie100_1",
            "2_Calybox_TyboxRT_serie1000",
            "3_Calybox_TyboxRT_serie2000",
            "5_Tybox_serie5000",
            "6_RecepteurRF_serie6000_1",
            "6_RecepteurRF_serie6000_2_twc",
            "kline_vr",
            "42_novoferm_novoport_novomatic",
            "TA5555_Zigbee_DD",
            # This is an association flow shared by unrelated opening
            # detectors (including MDO TYXAL+), not a physical model.
            "5_detectouverture_kline",
        }

        for tutorial_id in tutorials:
            with self.subTest(tutorial_id=tutorial_id):
                self.assertIsNone(resolve_device_model(tutorial_id, "light"))

    def test_opening_association_tutorial_does_not_identify_dvi(self) -> None:
        """The shared K-Line flow cannot identify the physical detector."""
        for usage in ("windowFrench", "belmDoor", "klineDoor"):
            with self.subTest(usage=usage):
                self.assertIsNone(
                    resolve_device_model("5_detectouverture_kline", usage)
                )

    def test_legacy_tutorial_category_uses_the_endpoint_profile(self) -> None:
        """The legacy series-4000 tutorial name must not become the model."""
        self.assertEqual(
            resolve_device_model("7_Tyxia_serie4000", "gate"), "TYXIA 4620"
        )
        self.assertEqual(
            resolve_device_model("7_Tyxia_serie4000", "garage_door"),
            "TYXIA 4620",
        )
        self.assertIsNone(
            resolve_device_model("7_Tyxia_serie4000", "light", _binary_4900_metadata())
        )
        self.assertIsNone(resolve_device_model("7_Tyxia_serie4000", "shutter"))

    def test_binary_series_4900_profile_is_tyxia_4910(self) -> None:
        """Binary series-4900 metadata narrows the family to TYXIA 4910."""
        metadata = _binary_4900_metadata()

        self.assertTrue(is_binary_tyxia_receiver_profile(metadata))
        self.assertEqual(
            resolve_device_model("9_tyxia_modulaire_serie4900", "others", metadata),
            "TYXIA 4910",
        )

    def test_non_binary_series_4900_retains_fallback(self) -> None:
        """A different series-4900 profile must not become a model."""
        metadata = {
            "level": {"min": 0, "max": 100, "step": 1},
            "levelCmd": {"enum_values": ["OFF", "ON"]},
        }

        self.assertFalse(is_binary_tyxia_receiver_profile(metadata))
        self.assertIsNone(
            resolve_device_model("9_tyxia_modulaire_serie4900", "others", metadata)
        )

    def test_tyxia_dimmer_profile(self) -> None:
        """Dimmers stay generic unless a narrower tutorial identifies them."""
        metadata = {
            "level": {"min": 0, "max": 100, "step": 1},
            "levelCmd": {
                "enum_values": [
                    "ON",
                    "OFF",
                    "STOP",
                    "FAVORIT1",
                    "FAVORIT2",
                    "TOGGLE",
                    "ON_SLOW",
                    "OFF_SLOW",
                ]
            },
        }

        self.assertTrue(is_tyxia_dimmer_profile(metadata))
        self.assertIsNone(resolve_device_model(None, "light", metadata))
        self.assertIsNone(resolve_device_model("7_Tyxia_serie4000", "light", metadata))
        self.assertEqual(
            resolve_device_model("9_Tyxia_modulaire_serie4900", "light", metadata),
            "TYXIA 4940",
        )

    def test_unknown_or_missing_tutorial_is_not_guessed(self) -> None:
        """Unknown descriptors retain Home Assistant's existing fallback."""
        self.assertIsNone(resolve_device_model(None, "light"))
        self.assertIsNone(resolve_device_model("unknown_product", "light"))

    def test_tymoov_firmware_profile_identifies_the_confirmed_range(self) -> None:
        """The complete TYMOOV firmware tuple supplies its confirmed range."""
        data = {
            "softPlan0": "24.28.00.20",
            "softPlan1": "24.94.00.11",
            "softPlan2": "24.28.00.31",
            "softPlan3": "22.10.00.30",
        }

        self.assertTrue(is_tymoov_profile(data))
        self.assertEqual(resolve_device_model(None, "shutter", data=data), "TYMOOV")

    def test_partial_tymoov_firmware_profile_is_not_used(self) -> None:
        """An incomplete TYMOOV resemblance retains the existing fallback."""
        data = {
            "softPlan0": "24.28.00.20",
            "softPlan2": "different-product",
            "softPlan3": "22.10.00.30",
        }

        self.assertFalse(is_tymoov_profile(data))
        self.assertIsNone(resolve_device_model(None, "shutter", data=data))

    def test_trv_1_firmware_profile(self) -> None:
        """The firmware tuple reported for TRV 1.0 identifies the valve."""
        data = {
            "softPlan0": "24.22.00.14",
            "softPlan1": "24.22.00.30",
            "softPlan2": "24.22.00.20",
        }

        self.assertTrue(is_trv_1_profile(data))
        self.assertEqual(resolve_device_model(None, "sh_hvac", data=data), "TRV 1.0")
        self.assertFalse(is_trv_1_profile({"softPlan0": "24.22.00.14"}))

    def test_tybox_1137_metadata_profile(self) -> None:
        """The register set reported for TYBOX 1137 identifies the thermostat."""
        metadata = {
            "authorization": {"enum_values": ["STOP", "HEATING"]},
            "heatSetpoint": {},
            "overrideSetpoint": {},
            "overrideThermicLevel": {},
            "useMode": {"enum_values": ["SCHED", "OVERRIDE", "MANUAL"]},
            "antiSeizurePeriod": {},
            "invertOutput": {},
        }

        self.assertTrue(is_tybox_1137_profile(metadata))
        self.assertEqual(resolve_device_model(None, "boiler", metadata), "TYBOX 1137")
        metadata.pop("invertOutput")
        self.assertFalse(is_tybox_1137_profile(metadata))


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
