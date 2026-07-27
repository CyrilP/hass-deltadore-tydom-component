"""Tests for dedicated TYDOM wall-switch support."""

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
TydomInterrupter = devices_module.TydomInterrupter

for name, original in _original_modules.items():
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


class TestInterrupter(IsolatedAsyncioTestCase):
    """Exercise physical wall-switch and button discovery."""

    def setUp(self) -> None:
        """Reset global protocol metadata."""
        for mapping_name in (
            "device_name",
            "device_type",
            "device_metadata",
            "groups_metadata",
            "groups_data",
            "interrupter_endpoint_config",
            "interrupter_info",
        ):
            getattr(handler_module, mapping_name).clear()
        logger.reset_mock()
        self.handler = MessageHandler(MagicMock(), b"")

    async def _configure_switch(
        self,
        *,
        device_id: int,
        endpoint_ids: list[int],
        endpoint_buttons: list[str],
        group_id: int,
        group_name: str,
    ) -> None:
        """Apply configuration matching a captured TYXIA 2600."""
        await self.handler.parse_config_data(
            {
                "endpoints": [
                    {
                        "id_device": device_id,
                        "id_endpoint": endpoint_id,
                        "name": f"CG_DD_COMMON_BUTTON{button}",
                        "first_usage": "interrupter",
                        "last_usage": "interrupter",
                        "widget_behavior": {
                            "action": "TOGGLE",
                            "tutorial_id": f"switch_tyxia2600_btn_{button.lower()}",
                        },
                    }
                    for endpoint_id, button in zip(
                        endpoint_ids, endpoint_buttons, strict=True
                    )
                ],
                "groups": [
                    {
                        "id": group_id,
                        "name": group_name,
                        "usage": "interrupter",
                        "type": "relatedendpoints",
                        "widget_behavior": {"tutorial_id": "switch_tyxia2600"},
                    }
                ],
            },
            None,
        )

        groups = await self.handler.parse_groups_file(
            {
                "groups": [
                    {
                        "id": group_id,
                        "devices": [
                            {
                                "id": device_id,
                                "endpoints": [
                                    {"id": endpoint_id}
                                    for endpoint_id in endpoint_ids
                                ],
                            }
                        ],
                    }
                ]
            },
            None,
        )
        self.assertEqual(groups, [])

    async def test_tyxia_2600_buttons_share_named_physical_device(self) -> None:
        """Both endpoints are grouped and retain their A/B button identity."""
        device_id = 1759742040
        endpoint_ids = [1759742040, 1759742338]
        await self._configure_switch(
            device_id=device_id,
            endpoint_ids=endpoint_ids,
            endpoint_buttons=["B", "A"],
            group_id=845782971,
            group_name="Portillon/Portail",
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
        self.assertTrue(all(isinstance(device, TydomInterrupter) for device in devices))
        self.assertEqual([device.button for device in devices], ["B", "A"])
        self.assertEqual(
            {device.physical_device_id for device in devices}, {str(device_id)}
        )
        self.assertEqual(
            {device.interrupter_name for device in devices}, {"Portillon/Portail"}
        )
        self.assertEqual(
            {device.interrupter_model for device in devices}, {"TYXIA 2600"}
        )

    async def test_all_three_captured_switch_names_are_retained(self) -> None:
        """The group names configured in the Delta Dore app remain available."""
        captures = (
            (1759742040, [1759742040, 1759742338], 845782971, "Portillon/Portail"),
            (
                1759742530,
                [1759742530, 1759742560],
                1886000055,
                "S à Manger/Esc Haut",
            ),
            (
                1759743287,
                [1759743287, 1759743998],
                1896078259,
                "Cuisine / Esc Bas",
            ),
        )

        for device_id, endpoints, group_id, name in captures:
            await self._configure_switch(
                device_id=device_id,
                endpoint_ids=endpoints,
                endpoint_buttons=["A", "B"],
                group_id=group_id,
                group_name=name,
            )

        self.assertEqual(
            {
                info["name"]
                for info in handler_module.interrupter_info.values()
            },
            {"Portillon/Portail", "S à Manger/Esc Haut", "Cuisine / Esc Bas"},
        )

    async def test_expired_action_does_not_repeat_last_press(self) -> None:
        """Polling without a fresh action must not emit the previous press again."""
        device = TydomInterrupter(
            MagicMock(),
            "endpoint_device",
            "device",
            "Button A",
            "interrupter",
            "endpoint",
            None,
            {"action": "IDLE"},
            {"physical_device_id": "device", "button": "A"},
        )
        callback = MagicMock()
        device.register_callback(callback)

        pressed = TydomInterrupter(
            MagicMock(),
            "endpoint_device",
            "device",
            "Button A",
            "interrupter",
            "endpoint",
            None,
            {"action": "TOGGLE"},
            {"physical_device_id": "device", "button": "A"},
        )
        await device.update_device(pressed)

        self.assertEqual(device.event_sequence, 1)
        callback.assert_called_once_with()

        callback.reset_mock()
        expired = TydomInterrupter(
            MagicMock(),
            "endpoint_device",
            "device",
            "Button A",
            "interrupter",
            "endpoint",
            None,
            None,
            {"physical_device_id": "device", "button": "A"},
        )
        await device.update_device(expired)

        self.assertEqual(device.event_sequence, 1)
        callback.assert_called_once_with()


if __name__ == "__main__":
    import unittest

    unittest.main()
