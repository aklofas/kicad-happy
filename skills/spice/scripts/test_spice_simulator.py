#!/usr/bin/env python3
"""Unit tests for SPICE simulator selection and external-deck execution."""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import spice_simulator


class TestExistingBackendSelection(unittest.TestCase):
    """Guard the generated-testbench simulator selection contract."""

    def test_registry_excludes_pspice(self):
        self.assertEqual(
            list(spice_simulator.BACKENDS),
            ["ngspice", "ltspice", "xyce"],
        )
        self.assertNotIn("pspice", spice_simulator.BACKENDS)

    def test_explicit_pspice_is_not_available_through_existing_detector(self):
        with patch.dict(os.environ, {"PSPICE_PATH": __file__}, clear=False):
            self.assertIsNone(spice_simulator.detect_simulator("pspice"))

    def test_auto_detection_order_is_unchanged(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(
                spice_simulator.NgspiceBackend,
                "find",
                return_value=None,
            ) as ng_find,
            patch.object(
                spice_simulator.LtspiceBackend,
                "find",
                return_value=None,
            ) as lt_find,
            patch.object(
                spice_simulator.XyceBackend,
                "find",
                return_value="/bin/Xyce",
            ) as xyce_find,
        ):
            backend = spice_simulator.detect_simulator("auto")

        self.assertIsInstance(backend, spice_simulator.XyceBackend)
        ng_find.assert_called_once_with()
        lt_find.assert_called_once_with()
        xyce_find.assert_called_once_with()


if __name__ == "__main__":
    unittest.main(verbosity=2)
