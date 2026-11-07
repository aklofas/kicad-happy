# tools/tests/test_stock_passive_symbol_type.py
"""A part on a stock Device R, C or L symbol keeps the symbol's type when its reference
prefix is unknown and starts with R or L. A C first letter is left as it is: C-prefixed
parts on a resistor symbol carry capacitor values."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.classify import classify_component  # noqa: E402


class StockPassiveSymbolOutranksPrefix(unittest.TestCase):
    def test_r_prefix_on_capacitor_symbol_is_capacitor(self):
        self.assertEqual(classify_component("RF-C10", "Device:C", "5pF"), "capacitor")
        self.assertEqual(classify_component("RFC3", "Device:C_Small", "100n"), "capacitor")

    def test_r_prefix_on_inductor_symbol_is_inductor(self):
        self.assertEqual(classify_component("RL1", "Device:L", "270nH"), "inductor")

    def test_l_prefix_on_resistor_symbol_is_resistor(self):
        self.assertEqual(classify_component("LEDRESISTOR1", "Device:R", "330"), "resistor")
        self.assertEqual(classify_component("LR2", "Device:R_US", "1k"), "resistor")

    def test_l_prefix_on_capacitor_symbol_is_capacitor(self):
        self.assertEqual(classify_component("LC1", "Device:C", "10p"), "capacitor")

    def test_legacy_lowercase_device_library(self):
        self.assertEqual(classify_component("RF-C11", "device:C", "22pF"), "capacitor")

    def test_c_prefix_on_resistor_symbol_is_unchanged(self):
        self.assertEqual(classify_component("CX1", "Device:R", "51pF"), "capacitor")

    def test_unknown_prefix_on_other_symbols_is_unchanged(self):
        self.assertEqual(classify_component("RF-C10", "MyLib:C", "5pF"), "resistor")
        self.assertEqual(classify_component("RX1", "Device:R_Pack04", "10k"), "resistor")
        self.assertEqual(classify_component("LX1", "Device:L", "10u"), "inductor")


if __name__ == "__main__":
    unittest.main()
