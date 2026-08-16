"""Tests for dynamic lightPower refresh scheduling."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock


def _load_rebuild_polling_cache():
    """Load Hub._rebuild_polling_cache without Home Assistant dependencies."""
    source_path = (
        Path(__file__).parents[1] / "custom_components" / "deltadore_tydom" / "hub.py"
    )
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    hub_class = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "Hub"
    )
    rebuild_method = next(
        node
        for node in hub_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "_rebuild_polling_cache"
    )
    isolated_class = ast.ClassDef(
        name="PollingCacheMixin",
        bases=[],
        keywords=[],
        body=[rebuild_method],
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
        "LOGGER": MagicMock(),
        "get_polling_interval_for_validity": lambda validity: intervals.get(
            str(validity).upper()
        ),
    }
    exec(compile(isolated_module, source_path, "exec"), namespace)
    return namespace["PollingCacheMixin"]


PollingCacheMixin = _load_rebuild_polling_cache()


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
        return hub

    def test_up_to_date_light_power_uses_configured_interval(self) -> None:
        """A stale upToDate marker must not suppress lightPower refreshes."""
        hub = self._hub({"lightPower": {"validity": "upToDate"}})

        hub._rebuild_polling_cache()

        self.assertEqual(hub._polling_cache, {("7_42", "lightPower"): 1800})

    def test_runtime_light_power_without_metadata_uses_configured_interval(
        self,
    ) -> None:
        """A data-only lightPower capability must remain refreshable."""
        hub = self._hub({}, refresh_interval=600, lightPower=23)

        hub._rebuild_polling_cache()

        self.assertEqual(hub._polling_cache, {("7_42", "lightPower"): 600})

    def test_runtime_light_power_without_metadata_object_is_refreshable(self) -> None:
        """A missing metadata object must not suppress runtime capabilities."""
        hub = self._hub(None, refresh_interval=60, lightPower=23)

        hub._rebuild_polling_cache()

        self.assertEqual(hub._polling_cache, {("7_42", "lightPower"): 60})

    def test_metadata_polling_interval_remains_preferred(self) -> None:
        """Valid supervision metadata must retain its faster interval."""
        hub = self._hub({"lightPower": {"validity": "SENSOR_SUPERVISION"}})

        hub._rebuild_polling_cache()

        self.assertEqual(hub._polling_cache, {("7_42", "lightPower"): 60})

    def test_other_up_to_date_attributes_are_not_polled(self) -> None:
        """The workaround must not turn all stable attributes into polling."""
        hub = self._hub({"position": {"validity": "upToDate"}})

        hub._rebuild_polling_cache()

        self.assertEqual(hub._polling_cache, {})
