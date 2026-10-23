"""Tests for TYDOM metadata-based value validation."""

import importlib.util
from pathlib import Path
import unittest


_CONST_PATH = (
    Path(__file__).parents[1] / "custom_components" / "deltadore_tydom" / "const.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "deltadore_const_under_test", _CONST_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_CONST = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CONST)


class ValidateValueWithMetadataTests(unittest.TestCase):
    """Exercise metadata bounds and optional step validation."""

    def setUp(self) -> None:
        """Create a device with coarse cover position metadata."""
        self.device = type(
            "Device",
            (),
            {
                "_metadata": {
                    "position": {
                        "type": "numeric",
                        "min": 0,
                        "max": 100,
                        "step": 100,
                    }
                }
            },
        )()

    def test_step_is_enforced_by_default(self) -> None:
        """Other metadata-driven controls retain their step validation."""
        valid, error = _CONST.validate_value_with_metadata(self.device, "position", 25)

        self.assertFalse(valid)
        self.assertIn("step 100.0", error or "")

    def test_step_can_be_ignored_without_ignoring_bounds(self) -> None:
        """Cover callers can ignore step while still enforcing min/max."""
        valid, error = _CONST.validate_value_with_metadata(
            self.device, "position", 25, ignore_step=True
        )
        self.assertTrue(valid)
        self.assertIsNone(error)

        valid, error = _CONST.validate_value_with_metadata(
            self.device, "position", 101, ignore_step=True
        )
        self.assertFalse(valid)
        self.assertIn("maximum 100", error or "")


if __name__ == "__main__":
    unittest.main()
