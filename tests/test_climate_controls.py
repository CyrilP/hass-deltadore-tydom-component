"""Run native HA climate-control tests separately from the suite's global module stubs."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from unittest import TestCase


class NativeClimateControlTests(TestCase):
    """Avoid sharing Home Assistant module mocks with tests of actual HA entities."""

    def test_native_climate_controls(self):
        """Run thermostat bounds, confirmation and diagnostic regressions in a clean interpreter."""
        root = Path(__file__).parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            filter(None, (str(root), env.get("PYTHONPATH")))
        )
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, str(root / "tests/climate_controls_native.py"), "-v"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
