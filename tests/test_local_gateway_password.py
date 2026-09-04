"""Tests for direct-LAN gateway password changes from a cloud configuration."""

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, skipIf
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parents[1]))

try:
    from custom_components.deltadore_tydom.hub import Hub
except ModuleNotFoundError:
    # The lightweight protocol-test environment deliberately has no Home
    # Assistant dependency. The test runs in the integration test environment.
    Hub = None


@skipIf(Hub is None, "Home Assistant integration dependencies are unavailable")
class LocalGatewayPasswordTests(IsolatedAsyncioTestCase):
    """Ensure a cloud entry can make one safe direct LAN request."""

    async def test_cloud_configuration_uses_the_supplied_local_host(self) -> None:
        """The password request itself must bypass cloud mediation."""
        hub = object.__new__(Hub)
        hub._hass = MagicMock()
        hub._id = "Tydom-123456"
        hub._mac = "001A25123456"
        hub._pass = "stored-gateway-password"
        hub._zone_home = ""
        hub._zone_away = ""
        hub._zone_night = ""
        hub._pin = ""
        hub._tydom_client = SimpleNamespace(_remote_mode=True)

        connection = MagicMock()
        local_client = MagicMock()
        local_client._shutting_down = False
        local_client.async_connect = AsyncMock(return_value=connection)
        local_client.async_set_local_gateway_password = AsyncMock()
        local_client.async_disconnect = AsyncMock()

        async def wait_for_cancellation() -> None:
            await asyncio.Event().wait()

        local_client.consume_messages = wait_for_cancellation

        with patch(
            "custom_components.deltadore_tydom.hub.TydomClient",
            return_value=local_client,
        ) as client_class:
            await hub.async_set_local_gateway_password("NewPassword1", "192.168.2.50")

        client_class.assert_called_once_with(
            hass=hub._hass,
            id="Tydom-123456",
            mac="001A25123456",
            host="192.168.2.50",
            password="stored-gateway-password",
            zone_home="",
            zone_away="",
            zone_night="",
            alarm_pin="",
        )
        local_client.async_connect.assert_awaited_once()
        local_client.async_set_local_gateway_password.assert_awaited_once_with(
            "NewPassword1"
        )
        local_client.async_disconnect.assert_awaited_once()
        self.assertEqual(hub._pass, "NewPassword1")
