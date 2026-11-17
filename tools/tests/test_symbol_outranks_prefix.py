# tools/tests/test_symbol_outranks_prefix.py
"""A part whose reference prefix does not name its type takes the type its library symbol
names: a switching regulator on a Regulator_Switching symbol is an IC, not a switch, and a
part whose type would come only from its first letter takes the type its symbol's name
stands for (PD1 on R_Small is a resistor, LD4 on Device:LED an LED)."""
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


class LetterFallback(unittest.TestCase):
    def test_p_prefix_on_passive_and_led_symbols(self):
        self.assertEqual(classify_component("PD1", "Device:R_Small", "10K"), "resistor")
        self.assertEqual(classify_component("PWR1", "Device:LED", "RED"), "led")
        self.assertEqual(classify_component("PC1", "Device:C", "1u"), "capacitor")
        self.assertEqual(classify_component("POT1", "Device:R_Potentiometer", "10k"), "resistor")
        self.assertEqual(classify_component("PS.C1", "Device:C_Small", "10u"), "capacitor")

    def test_led_symbol_outranks_l_and_d_letters(self):
        self.assertEqual(classify_component("LD4", "Device:LED", ""), "led")
        self.assertEqual(classify_component("DS1", "Device:LED", "RED"), "led")
        self.assertEqual(classify_component("DL1", "Device:LED_Small", "GREEN"), "led")
        self.assertEqual(classify_component("TX1", "Device:LED", "TX"), "led")

    def test_diode_and_transistor_symbols_outrank_other_letters(self):
        self.assertEqual(classify_component("RF-D2", "Device:D", "1N4148"), "diode")
        self.assertEqual(classify_component("RF-Q1", "Device:Q_NPN_BEC", "BC847"), "transistor")
        self.assertEqual(classify_component("SQ1", "MyLib:BJT_NPN", "2N3904"), "transistor")

    def test_force_sensing_resistor_on_f_letter_is_resistor(self):
        self.assertEqual(classify_component("FSR1", "Device:R_Variable", "FSR"), "resistor")

    def test_combined_resistor_led_symbol_stays_resistor(self):
        self.assertEqual(classify_component("RL1", "Device:R_Led", "1k"), "resistor")

    def test_ferrite_core_inductor_on_r_letter_matches_l_reference(self):
        self.assertEqual(classify_component("RF-L10", "Device:L_Core_Ferrite", "22uH"),
                         classify_component("L10", "Device:L_Core_Ferrite", "22uH"))

    def test_symbols_that_name_no_designator_keep_the_letter(self):
        self.assertEqual(classify_component("RT1", "Device:Thermistor_NTC", "10k"), "thermistor")
        self.assertEqual(classify_component("FX1", "MyLib:Fuse_Small", "1A"), "fuse")

    def test_c_letter_on_resistor_symbol_is_unchanged(self):
        self.assertEqual(classify_component("CX1", "Device:R", "51pF"), "capacitor")

    def test_v_letter_pot_stays_resistor(self):
        self.assertEqual(classify_component("VR1", "Device:R_Potentiometer", "10k"), "resistor")

    def test_mapped_prefixes_are_unchanged(self):
        self.assertEqual(classify_component("P1", "Device:R", "10k"), "connector")
        self.assertEqual(classify_component("J1", "Connector:Conn_01x02", ""), "connector")
        self.assertEqual(classify_component("RX1", "Device:R_Pack04", "10k"), "resistor")
        self.assertEqual(classify_component("LX1", "Device:L", "10u"), "inductor")


if __name__ == "__main__":
    unittest.main()
