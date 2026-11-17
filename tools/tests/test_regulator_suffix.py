# tools/tests/test_regulator_suffix.py
"""A fixed-output voltage is read from a part-name suffix only where it is unambiguous."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_core.parts import (  # noqa: E402
    fixed_vout_is_explicit, lookup_regulator_vref, regulator_vref_key, vref_key_covers_part)


class FixedSuffix(unittest.TestCase):
    def test_unambiguous_decimal_suffixes(self):
        for name, volts in [("AMS1117-3.3_SOT-223", 3.3), ("LDK130-08_SOT23", 0.8),
                            ("TLV1117LV-33", 3.3), ("RT9013-18GV", 1.8),
                            ("APE8865-25", 2.5), ("AP1117-50", 5.0), ("LDO-3V3", 3.3)]:
            self.assertEqual(lookup_regulator_vref(name, ""), (volts, "fixed_suffix"), name)

    def test_library_ambiguous_suffixes_give_no_value(self):
        # KiCad's library reads these both ways: AP7361C-12E is 1.2 V, LM1085-12 is 12 V.
        for name in ["LM1085-12", "AP1117-15", "LM3480-15",
                     "LM341T-05", "RAC04-09", "NID30S48-24", "APE8865-24", "MCP1700-12"]:
            vref, source = lookup_regulator_vref(name, "")
            self.assertNotEqual(source, "fixed_suffix", name)
        self.assertEqual(lookup_regulator_vref("LM1085-12", ""), (None, ""))

    def test_family_data_sheet_gives_the_ambiguous_suffix(self):
        for name, volts in [("AP7361C-10E", 1.0), ("AP7361C-12E", 1.2), ("AP7361C-15E", 1.5),
                            ("LM2596S-12", 12.0), ("LM2596T-12", 12.0),
                            ("LM2576S-12", 12.0), ("LM2576T-15", 15.0),
                            ("LM2940IMPX-10/NOPB", 10.0), ("LM2940IMP-12/NOPB", 12.0),
                            ("LM2940-15", 15.0),
                            ("TL780-05KCS", 5.0), ("TL780-12", 12.0), ("TL780-15", 15.0),
                            ("NCP1117-12", 12.0), ("NCP1117-12_SOT223", 12.0), ("NCP1117-15", 1.5),
                            ("XL1509-12", 12.0)]:
            self.assertEqual(lookup_regulator_vref(name, ""), (volts, "fixed_suffix"), name)

    def test_fixed_part_of_unknown_voltage_has_no_adjustable_vref(self):
        # NCP1117 has a table Vref, but a -10 part is a fixed part the data sheet does not list.
        self.assertEqual(lookup_regulator_vref("NCP1117-10", ""), (None, ""))

    def test_suffix_inside_a_description_keeps_the_table_vref(self):
        self.assertEqual(lookup_regulator_vref("LM317 Regulator (VCC 7-12VDC)", ""), (1.25, "lookup"))

    def test_date_stamp_in_a_rescue_symbol_gives_no_value(self):
        self.assertEqual(lookup_regulator_vref(
            "MCP23008-E_SO", "Mezmerize_B1_Controller-rescue:MCP23008-E_SO-2019-12-07_08-25-49"),
            (None, ""))

    def test_suffix_below_half_a_volt_gives_no_value(self):
        # LC78_03-05 is a 3.3 V module, not 0.3 V.
        self.assertNotEqual(lookup_regulator_vref("LC78_03-05", "")[1], "fixed_suffix")
        self.assertEqual(lookup_regulator_vref("AP7361C-33E-13", ""), (3.3, "fixed_suffix"))

    def test_package_names_give_no_value(self):
        for name in ["LDO_SOT-23", "REG_SOT-89-10", "AXP209(QFN-48)", "LM2675-5-WSON-16",
                     "XYZ_TO-92", "REG_SOT-223"]:
            self.assertNotEqual(lookup_regulator_vref(name, "")[1], "fixed_suffix", name)

    def test_more_package_names_give_no_value(self):
        for name in ["REG_SO-08", "REG_MLP-33", "REG_WLCSP-25", "REG_PowerPAD-18", "REG_LFCSP-33"]:
            self.assertNotEqual(lookup_regulator_vref(name, "")[1], "fixed_suffix", name)

    def test_package_name_does_not_hide_a_real_suffix(self):
        self.assertEqual(lookup_regulator_vref("AMS1117-3.3_SOT-223", ""), (3.3, "fixed_suffix"))
        self.assertEqual(lookup_regulator_vref("XC6206P332MR(SOT-23)", ""), (None, ""))

    def test_lm2596_12_is_the_fixed_12v_part(self):
        self.assertEqual(lookup_regulator_vref("LM2596S-12", ""), (12.0, "fixed_suffix"))

    def test_lm78xx_unchanged(self):
        self.assertEqual(lookup_regulator_vref("LM7812", ""), (12.0, "fixed_suffix"))
        self.assertEqual(lookup_regulator_vref("LM78L05", ""), (5.0, "fixed_suffix"))

    def test_diodes_reel_code_is_not_a_voltage(self):
        # Diodes Inc. orders tape and reel as -7 / -13: AP64501SP-13 is the adjustable AP64501
        # (DS41980 Rev. 5-2, Ordering Information; VFB 0.8 V, Electrical Characteristics)
        for name in ["AP64501SP-13", "AP2152SG-13", "AL8861Y-13"]:
            self.assertNotEqual(lookup_regulator_vref(name, "")[1], "fixed_suffix", name)
        self.assertEqual(lookup_regulator_vref("AP64501SP-13", ""), (None, ""))
        # a voltage code ahead of the reel code is still read
        self.assertEqual(lookup_regulator_vref("AP7361C-33E-13", ""), (3.3, "fixed_suffix"))
        self.assertEqual(lookup_regulator_vref("AP1509-50SG-13", ""), (5.0, "fixed_suffix"))


class ExplicitFixedVoltage(unittest.TestCase):
    def test_explicit_forms_state_the_output_voltage(self):
        for value, lib_id, mpn in [("LM1117-3.3", "", ""), ("AMS1117-3.3_SOT-223", "", ""),
                                   ("LDO-3V3", "", ""), ("LM7805", "", ""), ("LM2596S-12", "", ""),
                                   ("XL1509-12", "", ""), ("MIC4680", "", "MIC4680-5.0YM"),
                                   ("LM2586S", "Regulator_Switching:LM2586S-5.0", "")]:
            self.assertEqual(lookup_regulator_vref(value, lib_id, mpn)[1], "fixed_suffix", value)
            self.assertTrue(fixed_vout_is_explicit(value, lib_id, mpn), value)

    def test_reel_code_states_no_output_voltage(self):
        # Diodes Inc. orders tape and reel as -7 / -13 (AP64501 DS41980 Rev. 5-2, Ordering Information)
        for name in ["AP64501SP-13", "AP66200FVBW-13", "AP64200SP-13"]:
            self.assertFalse(fixed_vout_is_explicit(name, ""), name)

    def test_bare_two_digit_suffix_is_read_but_not_explicit(self):
        for name in ["LP2985-33", "AP1117-33", "TLV1117LV-33"]:
            self.assertEqual(lookup_regulator_vref(name, ""), (3.3, "fixed_suffix"), name)
            self.assertFalse(fixed_vout_is_explicit(name, ""), name)

    def test_part_without_a_fixed_suffix_is_not_explicit(self):
        for name in ["LM317", "TPS54040", "LM2596S-ADJ"]:
            self.assertFalse(fixed_vout_is_explicit(name, ""), name)

    def test_explicit_form_elsewhere_does_not_vouch_for_a_bare_code(self):
        # the bare -33 in the value is what is read; the 5.0 in the symbol name is another voltage
        self.assertEqual(lookup_regulator_vref("AP1117-33", "Custom:LDO-5.0"), (3.3, "fixed_suffix"))
        self.assertFalse(fixed_vout_is_explicit("AP1117-33", "Custom:LDO-5.0"))


class FeedbackReference(unittest.TestCase):
    def test_tps61030_feedback_is_half_a_volt(self):
        self.assertEqual(lookup_regulator_vref("TPS61030PWPR", ""), (0.5, "lookup"))

    def test_fixed_output_member_does_not_take_the_adjustable_reference(self):
        # TPS61032 is the fixed 5 V member: the TPS61030 feedback voltage is not its Vref
        self.assertEqual(lookup_regulator_vref("TPS61032PWPR", ""), (None, ""))
        self.assertEqual(lookup_regulator_vref("TPS61025DRCR", ""), (None, ""))

    def test_tps6102x_members_have_their_own_reference(self):
        for part, vref in [("TPS61021ADSGR", 0.795), ("TPS61022RWUR", 0.6),
                           ("TPS61023DRLR", 0.595), ("TPS61020DRCR", 0.5)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (vref, "lookup"), part)

    def test_tps56x_members_have_their_own_reference(self):
        for part, vref in [("TPS561201DDCR", 0.768), ("TPS561243DRLR", 0.6),
                           ("TPS562212DRLR", 0.6), ("TPS562202SDRLR", 0.804),
                           ("TPS563200DDCR", 0.765), ("TPS563202SDRLR", 0.806),
                           ("TPS563240DDC", 0.6), ("TPS564247DRLR", 0.6)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (vref, "lookup"), part)

    def test_unlisted_family_member_takes_no_family_reference(self):
        # no member key: the divider estimate falls back to the heuristic sweep
        self.assertEqual(lookup_regulator_vref("TPS562231DRLR", ""), (None, ""))

    def test_lm2731_and_lmr33640_rows(self):
        for part, vref in [("LM27313XMFX/NOPB", 1.23), ("LM2731XMF", 1.23), ("LMR33640ADDAR", 1.0)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (vref, "lookup"), part)
            key, matched = regulator_vref_key(part, "")
            self.assertTrue(vref_key_covers_part(key, matched), part)

    def test_other_rows_unchanged(self):
        for part, vref in [("TPS62912", 0.8), ("TPS73601", 1.204), ("LM22676", 1.285),
                           ("LM317", 1.25), ("LT8606", 0.97)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (vref, "lookup"), part)

    def test_tps61023_reference_unchanged(self):
        self.assertEqual(lookup_regulator_vref("TPS61023DRLR", ""), (0.595, "lookup"))

    def test_ltc3558_feedback_is_0v8(self):
        self.assertEqual(lookup_regulator_vref("LTC3558", ""), (0.8, "lookup"))


class KeyCover(unittest.TestCase):
    def test_key_covers_its_own_part(self):
        self.assertTrue(vref_key_covers_part("NCP1117", "NCP1117DT"))
        self.assertTrue(vref_key_covers_part("LD1117", "LD1117S"))

    def test_fixed_voltage_code_after_the_key_names_another_part(self):
        for key, part in [("NCP1117", "NCP1117ST33T3G"), ("LD1117", "LD1117AV33"),
                          ("LD1117", "LD1117DT18TR")]:
            self.assertFalse(vref_key_covers_part(key, part), part)

    def test_wildcard_x_does_not_name_a_part(self):
        for part in ["LM259X", "LM259x", "LM259XX"]:
            self.assertFalse(vref_key_covers_part("LM259", part), part)

    def test_x_option_letter_is_part_of_the_order_code(self):
        for key, part in [("TPS560430", "TPS560430X"), ("TPS560430", "TPS560430XDBVR"),
                          ("LM2731", "LM2731XMF"), ("LM2731", "LM2731X"), ("LM27313", "LM27313X")]:
            self.assertTrue(vref_key_covers_part(key, part), part)

    def test_fixed_part_key_covers_nothing(self):
        self.assertFalse(vref_key_covers_part("LD33", "LD33"))
        self.assertEqual(lookup_regulator_vref("LD33", ""), (1.25, "lookup"))


class LongestKey(unittest.TestCase):
    def test_mpn_with_a_longer_key_beats_the_value_family_key(self):
        self.assertEqual(lookup_regulator_vref("RT6", ""), (0.6, "lookup"))
        self.assertEqual(lookup_regulator_vref("RT6", "", "RT6150AGQW"), (0.5, "lookup"))
        self.assertEqual(regulator_vref_key("RT6", "", "RT6150AGQW"), ("RT6150", "RT6150AGQW"))

    def test_value_key_wins_when_the_mpn_key_is_not_longer(self):
        self.assertEqual(lookup_regulator_vref("RT6150AGQW", "", "RT6"), (0.5, "lookup"))


if __name__ == "__main__":
    unittest.main()
