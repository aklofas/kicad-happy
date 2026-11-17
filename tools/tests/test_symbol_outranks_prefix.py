# tools/tests/test_symbol_outranks_prefix.py
"""A part whose reference prefix does not name its type takes the type its library symbol
names: a switching regulator on a Regulator_Switching symbol is an IC, not a switch."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.classify import classify_component  # noqa: E402


class SwitchingRegulatorLibrary(unittest.TestCase):
    def test_regulator_switching_symbol_is_ic(self):
        for ref in ("REG1", "PS1", "VREG1", "DC1", "VR1", "POW1"):
            self.assertEqual(classify_component(ref, "Regulator_Switching:LM2596S-5", "LM2596S-5"), "ic", ref)

    def test_switch_libraries_stay_switches(self):
        self.assertEqual(classify_component("SW1", "Switch:SW_Push", ""), "switch")
        self.assertEqual(classify_component("KEY1", "Switch:SW_Push", ""), "switch")


if __name__ == "__main__":
    unittest.main()
