"""A part with an empty Value is named by its symbol in power-path and pull-up findings."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from detector_helpers import part_label  # noqa: E402
from domain_detectors import detect_power_path  # noqa: E402
from tools.tests.test_load_switch_not_regulator import _switch_ctx  # noqa: E402
from tools.tests.test_validation_w4 import ctx_of, ic, rule, vd  # noqa: E402


def _power_path_summary(value, lib_id):
    entries = detect_power_path(_switch_ctx(value, lib_id))
    return [e["summary"] for e in entries]


def _pu001(value, lib_id):
    comp = ic("U2", value)
    comp["lib_id"] = lib_id
    ctx = ctx_of([comp], {"SENSOR_IRQ": [("U2", "5", "INT", "bidirectional")]}, set())
    return rule(vd.validate_pullups(ctx), "PU-001")


class PartLabel(unittest.TestCase):
    def test_value_wins(self):
        self.assertEqual(part_label({"value": "TPS2065", "lib_id": "A:B"}), "TPS2065")

    def test_symbol_when_value_empty(self):
        self.assertEqual(part_label({"value": "", "lib_id": "Interface_USB_:HUSB238"}), "HUSB238")

    def test_nothing_readable_is_empty(self):
        self.assertEqual(part_label({"value": "", "lib_id": ""}), "")
        self.assertEqual(part_label({}), "")


class EmptyValueLabels(unittest.TestCase):
    def test_power_path_summary_names_the_symbol_when_value_is_empty(self):
        got = _power_path_summary("", "Interface_USB_:HUSB238")
        self.assertEqual(len(got), 1, got)
        self.assertIn("(HUSB238)", got[0])
        self.assertNotIn("()", got[0])

    def test_power_path_summary_keeps_a_value(self):
        got = _power_path_summary("HUSB238", "Interface_USB_:HUSB238")
        self.assertIn("U1 (HUSB238) [", got[0])

    def test_pu001_names_the_symbol_when_value_is_empty(self):
        got = _pu001("", "MCU_Test:STM32F4")
        self.assertEqual(len(got), 1)
        self.assertIn("on U2 (STM32F4)", got[0]["description"])
        self.assertNotIn("()", got[0]["description"])

    def test_pu001_keeps_a_value(self):
        got = _pu001("MCU", "MCU_Test:STM32F4")
        self.assertIn("on U2 (MCU)", got[0]["description"])


if __name__ == "__main__":
    unittest.main()
