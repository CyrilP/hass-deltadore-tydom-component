"""Tests for dedicated TYDOM remote-control support."""

import importlib.util
from pathlib import Path
import sys
import types
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock


_MISSING = object()
_original_modules: dict[str, object] = {}


def _module(name: str, **attributes) -> types.ModuleType:
    """Install a minimal module required to load the protocol code."""
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

logger = MagicMock()
_module(
    "custom_components.deltadore_tydom.const",
    LOGGER=logger,
    validate_value_with_metadata=MagicMock(return_value=(True, None)),
)

root = Path(__file__).parents[1]
devices_name = "custom_components.deltadore_tydom.tydom.tydom_devices"
devices_path = (
    root / "custom_components" / "deltadore_tydom" / "tydom" / "tydom_devices.py"
)
devices_spec = importlib.util.spec_from_file_location(devices_name, devices_path)
assert devices_spec is not None and devices_spec.loader is not None
devices_module = importlib.util.module_from_spec(devices_spec)
_original_modules.setdefault(devices_name, sys.modules.get(devices_name, _MISSING))
sys.modules[devices_name] = devices_module
devices_spec.loader.exec_module(devices_module)

handler_name = "custom_components.deltadore_tydom.tydom.MessageHandler"
handler_path = (
    root / "custom_components" / "deltadore_tydom" / "tydom" / "MessageHandler.py"
)
handler_spec = importlib.util.spec_from_file_location(handler_name, handler_path)
assert handler_spec is not None and handler_spec.loader is not None
handler_module = importlib.util.module_from_spec(handler_spec)
_original_modules.setdefault(handler_name, sys.modules.get(handler_name, _MISSING))
sys.modules[handler_name] = handler_module
handler_spec.loader.exec_module(handler_module)

MessageHandler = handler_module.MessageHandler
TydomRemoteControl = devices_module.TydomRemoteControl

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


class TestRemoteControl(IsolatedAsyncioTestCase):
    """Exercise physical remote and per-button discovery."""

    def setUp(self) -> None:
        """Reset global protocol metadata."""
        for mapping_name in (
            "device_name",
            "device_type",
            "device_metadata",
            "groups_metadata",
            "groups_data",
            "endpoint_config",
            "remote_control_info",
        ):
            getattr(handler_module, mapping_name).clear()
        logger.reset_mock()
        self.handler = MessageHandler(MagicMock(), b"")

    async def _configure_remote(
        self,
        *,
        device_id: int,
        group_id: int,
        group_name: str,
        tutorial_id: str,
        button_count: int,
    ) -> list[int]:
        """Apply configuration and related-endpoint group payloads."""
        endpoint_ids = [device_id + (index * 25) for index in range(button_count)]
        endpoints = [
            {
                "id_device": device_id,
                "id_endpoint": endpoint_id,
                "name": f"CG_DD_COMMON_BUTTON{index}",
                "first_usage": "remoteControl",
                "last_usage": "remoteControl",
                "widget_behavior": {
                    "action": "TOGGLE",
                    "tutorial_id": f"{tutorial_id}_btn_{index}",
                },
            }
            for index, endpoint_id in enumerate(endpoint_ids, start=1)
        ]
        await self.handler.parse_config_data(
            {
                "endpoints": endpoints,
                "groups": [
                    {
                        "id": group_id,
                        "name": group_name,
                        "usage": "remoteControl",
                        "type": "relatedendpoints",
                        "widget_behavior": {"tutorial_id": tutorial_id},
                    }
                ],
            },
            None,
        )

        group_devices = await self.handler.parse_groups_file(
            {
                "groups": [
                    {
                        "id": group_id,
                        "devices": [
                            {
                                "id": device_id,
                                "endpoints": [{"id": value} for value in endpoint_ids],
                            }
                        ],
                    }
                ]
            },
            None,
        )

        self.assertEqual(group_devices, [])
        return endpoint_ids

    async def test_tl2000_buttons_share_one_physical_remote(self) -> None:
        """Two TL 2000 endpoints retain button identity and physical grouping."""
        device_id = 1693549636
        endpoint_ids = await self._configure_remote(
            device_id=device_id,
            group_id=303212258,
            group_name="Télécommande Jo",
            tutorial_id="tl2000",
            button_count=2,
        )

        for endpoint_id in endpoint_ids:
            unique_id = f"{endpoint_id}_{device_id}"
            handler_module.device_metadata[unique_id] = {
                "battDefect": {"type": "boolean"},
                "action": {"type": "string"},
            }

        devices = await self.handler.parse_devices_data(
            [
                {
                    "id": device_id,
                    "endpoints": [
                        {
                            "id": endpoint_id,
                            "error": 0,
                            "data": [
                                {
                                    "name": "battDefect",
                                    "validity": "upToDate",
                                    "value": False,
                                },
                                {
                                    "name": "action",
                                    "validity": "upToDate",
                                    "value": "IDLE",
                                },
                            ],
                        }
                        for endpoint_id in endpoint_ids
                    ],
                }
            ],
            None,
        )

        self.assertEqual(len(devices), 2)
        self.assertTrue(all(isinstance(device, TydomRemoteControl) for device in devices))
        self.assertEqual([device.button_number for device in devices], [1, 2])
        self.assertEqual(
            {device.physical_device_id for device in devices}, {str(device_id)}
        )
        self.assertEqual(
            {device.remote_name for device in devices}, {"Télécommande Jo"}
        )
        self.assertEqual(
            {device.remote_model for device in devices}, {"TL 2000 TYXAL+"}
        )

    async def test_tyxia_1410_has_four_button_endpoints(self) -> None:
        """TYXIA 1410 discovery exposes four buttons under one remote."""
        device_id = 1693573310
        endpoint_ids = await self._configure_remote(
            device_id=device_id,
            group_id=1558462107,
            group_name="Télécommande C3",
            tutorial_id="rcu_tyxia1410",
            button_count=4,
        )

        self.assertEqual(
            [
                handler_module.remote_control_info[
                    f"{endpoint_id}_{device_id}"
                ]["button_number"]
                for endpoint_id in endpoint_ids
            ],
            [1, 2, 3, 4],
        )
        self.assertEqual(
            {
                handler_module.remote_control_info[
                    f"{endpoint_id}_{device_id}"
                ]["model"]
                for endpoint_id in endpoint_ids
            },
            {"TYXIA 1410"},
        )

    async def test_only_fresh_non_idle_action_advances_event_sequence(self) -> None:
        """Polling without a fresh action must not repeat the previous press."""
        device = TydomRemoteControl(
            MagicMock(),
            "endpoint_device",
            "device",
            "Button 1",
            "remoteControl",
            "endpoint",
            None,
            {"action": "IDLE"},
            {"physical_device_id": "device", "button_number": 1},
        )
        callback = MagicMock()
        device.register_callback(callback)

        pressed = TydomRemoteControl(
            MagicMock(),
            "endpoint_device",
            "device",
            "Button 1",
            "remoteControl",
            "endpoint",
            None,
            {"action": "TOGGLE"},
            {"physical_device_id": "device", "button_number": 1},
        )
        await device.update_device(pressed)

        self.assertEqual(device.event_sequence, 1)
        self.assertEqual(device.action, "TOGGLE")
        callback.assert_called_once_with()

        callback.reset_mock()
        expired = TydomRemoteControl(
            MagicMock(),
            "endpoint_device",
            "device",
            "Button 1",
            "remoteControl",
            "endpoint",
            None,
            None,
            {"physical_device_id": "device", "button_number": 1},
        )
        await device.update_device(expired)

        self.assertEqual(device.event_sequence, 1)
        callback.assert_called_once_with()


if __name__ == "__main__":
    import unittest

    unittest.main()
