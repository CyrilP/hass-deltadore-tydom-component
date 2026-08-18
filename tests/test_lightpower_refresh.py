"""Tests for dynamic lightPower refresh scheduling."""

from __future__ import annotations

import ast
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock


def _load_polling_mixin():
    """Load Hub polling methods without Home Assistant dependencies."""
    source_path = (
        Path(__file__).parents[1] / "custom_components" / "deltadore_tydom" / "hub.py"
    )
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    hub_class = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "Hub"
    )
    polling_methods = [
        node
        for node in hub_class.body
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in {"_rebuild_polling_cache", "refresh_data"}
        )
    ]
    isolated_class = ast.ClassDef(
        name="PollingCacheMixin",
        bases=[],
        keywords=[],
        body=polling_methods,
        decorator_list=[],
    )
    isolated_module = ast.Module(body=[isolated_class], type_ignores=[])
    ast.fix_missing_locations(isolated_module)

    intervals = {
        "ES_SUPERVISION": 300,
        "SENSOR_SUPERVISION": 60,
        "SYNCHRO_SUPERVISION": 30,
    }
    namespace = {
        "DYNAMIC_POLLING_FALLBACK_ATTRIBUTES": frozenset({"lightPower"}),
        "RADIO_REFRESH_SETTLE_SECONDS": 6,
        "LOGGER": MagicMock(),
        "time": time,
        "get_polling_interval_for_validity": lambda validity: intervals.get(
            str(validity).upper()
        ),
    }
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return namespace["PollingCacheMixin"]


PollingCacheMixin = _load_polling_mixin()


class LightPowerRefreshTests(TestCase):
    """Ensure changing irradiance values remain refreshable."""

    def _hub(
        self,
        metadata: dict | None,
        refresh_interval: int = 1800,
        **runtime_attributes,
    ):
        hub = PollingCacheMixin()
        hub.devices = {
            "7_42": SimpleNamespace(_metadata=metadata, **runtime_attributes),
        }
        hub._refresh_interval = refresh_interval
        hub._polling_cache = {}
        hub._radio_refresh_intervals = set()
        return hub

    def test_up_to_date_light_power_uses_configured_interval(self) -> None:
        """A stale upToDate marker must not suppress lightPower refreshes."""
        hub = self._hub({"lightPower": {"validity": "upToDate"}})

        hub._rebuild_polling_cache()

        self.assertEqual(hub._polling_cache, {("7_42", "lightPower"): 1800})
        self.assertEqual(hub._radio_refresh_intervals, {1800})

    def test_runtime_light_power_without_metadata_uses_configured_interval(
        self,
    ) -> None:
        """A data-only lightPower capability must remain refreshable."""
        hub = self._hub({}, refresh_interval=600, lightPower=23)

        hub._rebuild_polling_cache()

        self.assertEqual(hub._polling_cache, {("7_42", "lightPower"): 600})
        self.assertEqual(hub._radio_refresh_intervals, {600})

    def test_runtime_light_power_without_metadata_object_is_refreshable(self) -> None:
        """A missing metadata object must not suppress runtime capabilities."""
        hub = self._hub(None, refresh_interval=60, lightPower=23)

        hub._rebuild_polling_cache()

        self.assertEqual(hub._polling_cache, {("7_42", "lightPower"): 60})
        self.assertEqual(hub._radio_refresh_intervals, {60})

    def test_metadata_polling_interval_remains_preferred(self) -> None:
        """Valid supervision metadata must retain its faster interval."""
        hub = self._hub({"lightPower": {"validity": "SENSOR_SUPERVISION"}})

        hub._rebuild_polling_cache()

        self.assertEqual(hub._polling_cache, {("7_42", "lightPower"): 60})
        self.assertEqual(hub._radio_refresh_intervals, set())

    def test_other_up_to_date_attributes_are_not_polled(self) -> None:
        """The workaround must not turn all stable attributes into polling."""
        hub = self._hub({"position": {"validity": "upToDate"}})

        hub._rebuild_polling_cache()

        self.assertEqual(hub._polling_cache, {})
        self.assertEqual(hub._radio_refresh_intervals, set())


class LightPowerRefreshLoopTests(IsolatedAsyncioTestCase):
    """Ensure radio refreshes are batched per due polling interval."""

    async def test_one_global_refresh_serves_multiple_light_power_devices(self) -> None:
        """Do not send one global radio refresh for every shutter."""
        hub = PollingCacheMixin()
        client = SimpleNamespace(
            post_refresh=AsyncMock(),
            poll_device_data=AsyncMock(),
        )
        hub._tydom_client = client
        hub._shutting_down = False
        hub._polling_cache = {
            ("7_42", "lightPower"): 60,
            ("8_43", "lightPower"): 60,
        }
        hub._polling_cache_timestamp = time.monotonic()
        hub._polling_cache_ttl = 300
        hub._next_poll_due = {}
        hub._radio_refresh_intervals = {60}
        hub.devices = {
            "7_42": SimpleNamespace(
                _id="42", device_endpoint="7", _tydom_client=client
            ),
            "8_43": SimpleNamespace(
                _id="43", device_endpoint="8", _tydom_client=client
            ),
        }

        sleep_intervals = []

        async def sleep_once(interval: int) -> None:
            sleep_intervals.append(interval)
            if interval == 60:
                hub._shutting_down = True

        hub._interruptible_sleep = sleep_once

        await hub.refresh_data()

        client.post_refresh.assert_awaited_once_with(wait_for_acknowledgement=True)
        self.assertEqual(client.poll_device_data.await_count, 2)
        self.assertEqual(sleep_intervals, [6, 60])
