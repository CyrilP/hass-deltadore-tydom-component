"""Tests for capability-driven device association commands."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from custom_components.deltadore_tydom.hub import (
    ASSOCIATION_COMMAND,
    IDENTIFY_COMMAND,
    start_command,
    supports_command,
)
from custom_components.deltadore_tydom.hub import HADeviceAssociationButton


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object, str, str]] = []

    async def put_devices_data(self, device_id, endpoint_id, name, value) -> None:
        self.calls.append((device_id, endpoint_id, name, value))


class DeviceAssociationTests(IsolatedAsyncioTestCase):
    """Validate only capabilities explicitly advertised by the gateway."""

    def _device(self, metadata: dict | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            _id="42",
            _endpoint="43",
            device_id="43_42",
            _metadata=metadata or {},
            _tydom_client=_Client(),
        )

    def test_supports_writable_start_command(self) -> None:
        """Accept a command explicitly advertised as writable and startable."""
        device = self._device(
            {ASSOCIATION_COMMAND: {"permission": "w", "enum_values": ["START"]}}
        )

        self.assertTrue(supports_command(device, ASSOCIATION_COMMAND))

    def test_rejects_read_only_or_unknown_commands(self) -> None:
        """Reject commands that cannot safely be sent to this endpoint."""
        device = self._device(
            {
                ASSOCIATION_COMMAND: {"permission": "r", "enum_values": ["START"]},
                IDENTIFY_COMMAND: {"permission": "w", "enum_values": ["STOP"]},
            }
        )

        self.assertFalse(supports_command(device, ASSOCIATION_COMMAND))
        self.assertFalse(supports_command(device, IDENTIFY_COMMAND))

    async def test_start_command_uses_the_physical_device_and_endpoint(self) -> None:
        """Send the command to the physical TYDOM identifier and endpoint."""
        device = self._device(
            {IDENTIFY_COMMAND: {"permission": "rw", "enum_values": ["START"]}}
        )

        await start_command(device, IDENTIFY_COMMAND)

        self.assertEqual(
            device._tydom_client.calls,
            [("42", "43", IDENTIFY_COMMAND, "START")],
        )

    async def test_start_command_rejects_unsupported_device(self) -> None:
        """Avoid a write when the gateway does not advertise the command."""
        with self.assertRaisesRegex(ValueError, "does not support"):
            await start_command(self._device(), ASSOCIATION_COMMAND)

    async def test_association_button_uses_the_advertised_start_command(self) -> None:
        """The device-page button sends START instead of a generic ON command."""
        device = self._device(
            {ASSOCIATION_COMMAND: {"permission": "w", "enum_values": ["START"]}}
        )
        button = HADeviceAssociationButton(device, None, ASSOCIATION_COMMAND)

        await button.async_press()

        self.assertEqual(
            device._tydom_client.calls,
            [("42", "43", ASSOCIATION_COMMAND, "START")],
        )
