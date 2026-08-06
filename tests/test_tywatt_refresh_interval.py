"""Tests for the configured TYWATT cdata refresh interval."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock


def _load_refresh_cdata():
    """Load Hub.refresh_cdata without Home Assistant dependencies."""
    source_path = (
        Path(__file__).parents[1] / "custom_components" / "deltadore_tydom" / "hub.py"
    )
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    hub_class = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "Hub"
    )
    refresh_method = next(
        node
        for node in hub_class.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "refresh_cdata"
    )
    isolated_class = ast.ClassDef(
        name="RefreshCdataMixin",
        bases=[],
        keywords=[],
        body=[refresh_method],
        decorator_list=[],
    )
    isolated_module = ast.Module(body=[isolated_class], type_ignores=[])
    ast.fix_missing_locations(isolated_module)
    namespace = {"LOGGER": MagicMock()}
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return namespace["RefreshCdataMixin"]


RefreshCdataMixin = _load_refresh_cdata()


class TywattRefreshIntervalTests(IsolatedAsyncioTestCase):
    """Ensure TYWATT cdata follows the integration refresh option."""

    async def test_configured_interval_is_used_after_polling(self) -> None:
        """Poll immediately, then sleep for the configured number of seconds."""
        hub = RefreshCdataMixin()
        hub._shutting_down = False
        hub._refresh_interval = 1800
        hub._tydom_client = MagicMock()
        hub._tydom_client.poll_devices_data_5m = AsyncMock()

        async def sleep_once(interval: int) -> None:
            self.assertEqual(interval, 1800)
            hub._shutting_down = True

        hub._interruptible_sleep = sleep_once

        await hub.refresh_cdata()

        hub._tydom_client.poll_devices_data_5m.assert_awaited_once_with()

    def test_background_task_uses_frequency_neutral_name(self) -> None:
        """The integration setup must not describe cdata as fixed at five minutes."""
        init_path = (
            Path(__file__).parents[1]
            / "custom_components"
            / "deltadore_tydom"
            / "__init__.py"
        )
        source = init_path.read_text(encoding="utf-8")

        self.assertIn("target=tydom_hub.refresh_cdata()", source)
        self.assertIn('name="Tydom refresh cdata"', source)
        self.assertNotIn("refresh_data_5m", source)
