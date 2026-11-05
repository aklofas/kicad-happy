# tools/tests/test_regulator_suffix.py
"""A fixed-output voltage is read from a part-name suffix only where it is unambiguous."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_core.parts import lookup_regulator_vref, regulator_vref_key  # noqa: E402


class FixedSuffix(unittest.TestCase):
    def test_unambiguous_decimal_suffixes(self):
        for name, volts in [("AMS1117-3.3_SOT-223", 3.3), ("LDK130-08_SOT23", 0.8),
                            ("TLV1117LV-33", 3.3), ("RT9013-18GV", 1.8),
                            ("APE8865-25", 2.5), ("AP1117-50", 5.0), ("LDO-3V3", 3.3)]:
            self.assertEqual(lookup_regulator_vref(name, ""), (volts, "fixed_suffix"), name)

    def test_library_ambiguous_suffixes_give_no_value(self):
        # KiCad's library reads these both ways: AP7361C-12E is 1.2 V, LM1085-12 is 12 V.
        for name in ["AP7361C-12E", "LM1085-12", "AP1117-15", "LM3480-15", "AP7361C-10E",
                     "LM341T-05", "RAC04-09", "NID30S48-24", "APE8865-24", "MCP1700-12"]:
            vref, source = lookup_regulator_vref(name, "")
            self.assertNotEqual(source, "fixed_suffix", name)

    def test_suffix_below_half_a_volt_gives_no_value(self):
        # LC78_03-05 is a 3.3 V module, not 0.3 V.
        self.assertNotEqual(lookup_regulator_vref("LC78_03-05", "")[1], "fixed_suffix")
        self.assertEqual(lookup_regulator_vref("AP7361C-33E-13", ""), (3.3, "fixed_suffix"))

    def test_package_names_give_no_value(self):
        for name in ["LDO_SOT-23", "REG_SOT-89-10", "AXP209(QFN-48)", "LM2675-5-WSON-16",
                     "XYZ_TO-92", "REG_SOT-223"]:
            self.assertNotEqual(lookup_regulator_vref(name, "")[1], "fixed_suffix", name)

    def test_package_name_does_not_hide_a_real_suffix(self):
        self.assertEqual(lookup_regulator_vref("AMS1117-3.3_SOT-223", ""), (3.3, "fixed_suffix"))
        self.assertEqual(lookup_regulator_vref("XC6206P332MR(SOT-23)", ""), (None, ""))

    def test_ambiguous_suffix_falls_through_to_the_table(self):
        self.assertEqual(lookup_regulator_vref("LM2596S-12", ""), (1.23, "lookup"))

    def test_lm78xx_unchanged(self):
        self.assertEqual(lookup_regulator_vref("LM7812", ""), (12.0, "fixed_suffix"))
        self.assertEqual(lookup_regulator_vref("LM78L05", ""), (5.0, "fixed_suffix"))


class LongestKey(unittest.TestCase):
    def test_mpn_with_a_longer_key_beats_the_value_family_key(self):
        self.assertEqual(lookup_regulator_vref("RT6", ""), (0.6, "lookup"))
        self.assertEqual(lookup_regulator_vref("RT6", "", "RT6150AGQW"), (0.5, "lookup"))
        self.assertEqual(regulator_vref_key("RT6", "", "RT6150AGQW"), ("RT6150", "RT6150AGQW"))

    def test_value_key_wins_when_the_mpn_key_is_not_longer(self):
        self.assertEqual(lookup_regulator_vref("RT6150AGQW", "", "RT6"), (0.5, "lookup"))


if __name__ == "__main__":
    unittest.main()
