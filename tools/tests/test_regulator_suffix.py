# tools/tests/test_regulator_suffix.py
"""A fixed-output voltage is read from a part-name suffix only where it is unambiguous."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_core.parts import (  # noqa: E402
    fixed_vout_is_explicit, is_r78_module, lookup_regulator_vref, regulator_vref_key, vref_key_covers_part)


class FixedSuffix(unittest.TestCase):
    def test_unambiguous_decimal_suffixes(self):
        for name, volts in [("AMS1117-3.3_SOT-223", 3.3), ("LDK130-08_SOT23", 0.8),
                            ("TLV1117LV-33", 3.3), ("RT9013-18GV", 1.8),
                            ("APE8865-25", 2.5), ("AP1117-50", 5.0), ("LDO-3V3", 3.3)]:
            self.assertEqual(lookup_regulator_vref(name, ""), (volts, "fixed_suffix"), name)

    def test_library_ambiguous_suffixes_give_no_value(self):
        # KiCad's library reads these both ways: AP7361C-12E is 1.2 V, LM1085-12 is 12 V.
        for name in ["AP1117-15", "LM3480-15",
                     "LM341T-05", "RAC04-09", "NID30S48-24", "APE8865-24", "MCP1700-12"]:
            vref, source = lookup_regulator_vref(name, "")
            self.assertNotEqual(source, "fixed_suffix", name)
        self.assertEqual(lookup_regulator_vref("LM3480-15", ""), (None, ""))

    def test_family_data_sheet_gives_the_ambiguous_suffix(self):
        for name, volts in [("AP7361C-10E", 1.0), ("AP7361C-12E", 1.2), ("AP7361C-15E", 1.5),
                            ("LM2596S-12", 12.0), ("LM2596T-12", 12.0),
                            ("LM2576S-12", 12.0), ("LM2576T-15", 15.0),
                            ("LM2940IMPX-10/NOPB", 10.0), ("LM2940IMP-12/NOPB", 12.0),
                            ("LM2940-15", 15.0),
                            ("TL780-05KCS", 5.0), ("TL780-12", 12.0), ("TL780-15", 15.0),
                            ("NCP1117-12", 12.0), ("NCP1117-12_SOT223", 12.0), ("NCP1117-15", 1.5),
                            ("XL1509-12", 12.0),
                            # LM2678 SNVS029L p1, LM2676 SNVS031N p1, LM2575/LM2575HV SNVS106E p1,
                            # LM1085 SNVS038H p1, LM340 SNOSBT0L p1
                            ("LM2678S-12", 12.0), ("LM2676SX-12/NOPB", 12.0),
                            ("LM2575HVS-12_C347430", 12.0), ("LM2575T-15", 15.0),
                            ("LM1085-12", 12.0), ("LM1085-12V", 12.0),
                            ("LM340-12", 12.0), ("LM340T-15", 15.0)]:
            self.assertEqual(lookup_regulator_vref(name, ""), (volts, "fixed_suffix"), name)

    def test_family_suffix_needs_the_whole_family_number(self):
        # LM3405 is an LED driver, not an LM340 regulator
        self.assertEqual(lookup_regulator_vref("LM3405-12", ""), (None, ""))

    def test_integer_volts_in_a_name_or_range_give_no_value(self):
        for name in ["Boost-converter-9-48V", "POE-RT5400-12V"]:
            self.assertEqual(lookup_regulator_vref(name, ""), (None, ""), name)

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
        for name in ["LDO_SOT-23", "REG_SOT-89-10", "AXP209(QFN-48)", "XYZ_TO-92", "REG_SOT-223"]:
            self.assertNotEqual(lookup_regulator_vref(name, "")[1], "fixed_suffix", name)

    def test_more_package_names_give_no_value(self):
        for name in ["REG_SO-08", "REG_MLP-33", "REG_WLCSP-25", "REG_PowerPAD-18", "REG_LFCSP-33"]:
            self.assertNotEqual(lookup_regulator_vref(name, "")[1], "fixed_suffix", name)

    def test_package_name_does_not_hide_a_real_suffix(self):
        self.assertEqual(lookup_regulator_vref("AMS1117-3.3_SOT-223", ""), (3.3, "fixed_suffix"))
        self.assertEqual(lookup_regulator_vref("XC6206P332MR(SOT-23)", ""), (None, ""))

    def test_one_digit_family_codes(self):
        # each data sheet lists the 5 V version: LM2596 SNVS124G p1, LM2576 SNVS107G p1, LM2575 SNVS106E p1,
        # LM2595 SNVS122C p1, LM2574 SNVS104F p1, LM2675 SNVS129G p1, LM22676 SNVS587L p1, LM22678 SNVS585M p1
        for name in ["LM2596S-5", "LM2596T-5", "LM2576HVS-5", "LM2575-5", "LM2595S-5", "LM2574N-5",
                     "LM2675M-5", "LM2675-5-WSON-16", "LM22676MR-5", "LM22678TJ-5"]:
            self.assertEqual(lookup_regulator_vref(name, ""), (5.0, "fixed_suffix"), name)
            self.assertTrue(fixed_vout_is_explicit(name, ""), name)
        # a one-digit code outside these families is not a voltage
        for name in ["LT8640EUDC-1#PBF", "AOZ1282CI-1", "LM3405-5", "LM2596S-ADJ", "LM2940-5",
                     "LM2596 Buck 12V-5V"]:
            self.assertNotEqual(lookup_regulator_vref(name, "")[0], 5.0, name)
        self.assertEqual(lookup_regulator_vref("LM2596S-ADJ", ""), (1.23, "lookup"))
        self.assertEqual(lookup_regulator_vref("LT8640EUDC-1#PBF", ""), (0.97, "lookup"))

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
        # the fixed members give their output voltage, not the adjustable members' feedback voltage
        # (TPS6102x SLVS451G p3 ordering table; TPS6103x SLUS534G p3 device comparison table)
        for part, volts in [("TPS61024DRCR", 3.0), ("TPS61025DRCR", 3.3), ("TPS61026DRCR", 5.0),
                            ("TPS61027DRCT", 5.0), ("TPS61031PWPR", 3.3), ("TPS61032PWPR", 5.0),
                            ("TPS61032RSAR", 5.0)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (volts, "fixed_suffix"), part)
            self.assertTrue(fixed_vout_is_explicit(part, ""), part)

    def test_fixed_member_symbol_under_a_label_value(self):
        self.assertEqual(lookup_regulator_vref("3.3V-Regulator", "Regulator_Switching:TPS61025DRCR"),
                         (3.3, "fixed_suffix"))

    def test_fixed_member_prefix_needs_the_whole_part_number(self):
        # TPS610333 is not a TPS61033x relative of the TPS61031/32 table rows
        self.assertEqual(lookup_regulator_vref("TPS610333DRLR", ""), (None, ""))

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

    def test_tps56520x_members_have_their_own_reference(self):
        # VFBTH = 760 mV (TPS565201 SLVSE71 p5, TPS565208 SLVSE72B p5); TPS565242 VREF = 600 mV (SLUSEN1A p5)
        for part, vref in [("TPS565201DDCR", 0.76), ("TPS565208DDC", 0.76), ("TPS565242DRLR", 0.6)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (vref, "lookup"), part)

    def test_unlisted_family_member_takes_no_family_reference(self):
        # no member key: the divider estimate falls back to the heuristic sweep
        self.assertEqual(lookup_regulator_vref("TPS562231DRLR", ""), (None, ""))

    def test_lm2731_and_lmr33640_rows(self):
        for part, vref in [("LM27313XMFX/NOPB", 1.23), ("LM2731XMF", 1.23), ("LMR33640ADDAR", 1.0)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (vref, "lookup"), part)
            key, matched = regulator_vref_key(part, "")
            self.assertTrue(vref_key_covers_part(key, matched), part)

    def test_lmr5161x_reference_is_0v8_for_every_order_option(self):
        # TI "LMR516xx SIMPLE SWITCHER Power Converter, 4-V to 65-V, 0.6-A/1-A Buck Converter in a
        # SOT-23 Package", SLUSEY1B (Dec 2023): Vfb 0.8 V typ (6.5, p5); X = 400 kHz, Y = 1.1 MHz,
        # F = FPWM, every orderable adjustable (4, p3)
        for part in ["LMR51610", "LMR51610X", "LMR51610XDBVR", "LMR51610YFDBVR", "LMR51606X",
                     "LMR51606YDBVR"]:
            self.assertEqual(lookup_regulator_vref(part, ""), (0.8, "lookup"), part)
            key, matched = regulator_vref_key(part, "")
            self.assertTrue(vref_key_covers_part(key, matched), part)

    def test_other_rows_unchanged(self):
        for part, vref in [("TPS62912", 0.8), ("TPS73601", 1.204), ("LM22676", 1.285),
                           ("LM317", 1.25)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (vref, "lookup"), part)

    def test_lt860x_members_have_their_own_reference(self):
        # LT8606/LT8606B Rev. D p3, LT8607/LT8607B Rev. D p3, LT8608/LT8608B Rev. D p3, LT8608S Rev. 0 p2,
        # LT8609/LT8609A/LT8609B Rev. J p4, LT8609S Rev. D p3 (Feedback Reference Voltage, typ.)
        for part, vref in [("LT8606EMSE", 0.778), ("LT8607", 0.778), ("LT8608.MSE", 0.778),
                           ("LT8608S", 0.774), ("LT8609AIMSE_PBF", 0.782), ("LT8609SEV", 0.774)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (vref, "lookup"), part)
            key, matched = regulator_vref_key(part, "")
            self.assertTrue(vref_key_covers_part(key, matched), part)

    def test_lt860x_parts_without_a_row_take_no_reference(self):
        for part in ["LT8601.UJ", "LT8602.UJ"]:
            self.assertEqual(lookup_regulator_vref(part, ""), (None, ""), part)

    def test_reference_rows_name_the_parts_they_cover(self):
        # LT8610 Rev. A p2 and LT8610A/LT8610AB Rev. C p3, LT8614 Rev. H p3, LT8640/LT8640-1 Rev. F p3,
        # LTC3610 Rev. F p2, LTC3620 Rev. A p2
        for part, vref in [("LT8610", 0.97), ("LT8610AB.MSE", 0.97), ("LT8614EUDC", 0.97),
                           ("LT8640.UDC", 0.97), ("LTC3610EWP", 0.6), ("LTC3620EDC", 0.6)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (vref, "lookup"), part)
            key, matched = regulator_vref_key(part, "")
            self.assertTrue(vref_key_covers_part(key, matched), part)

    def test_adjustable_ldo_and_boost_controller_rows(self):
        # TPS731 SBVS034P p5, TPS793 SLVS348L p6, LM5122 SNVS954H p8
        for part, vref in [("TPS73101DBV", 1.204), ("TPS79301-EP", 1.225), ("LM5122MHX/NOPB", 1.2)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (vref, "lookup"), part)
            key, matched = regulator_vref_key(part, "")
            self.assertTrue(vref_key_covers_part(key, matched), part)

    def test_fixed_members_of_the_new_rows_give_their_output_voltage(self):
        # one-digit fixed-output codes: LT8607 Rev. D p2 order information (LT8607EMSE-5), LT8609 Rev. J
        # p3 (LT8609AEDDM-5), LT8610A/LT8610AB Rev. C p2 (LT8610ABEMSE-5), LTC3620 Rev. A p1 (LTC3620-1
        # is programmed to 1.1 V); a -3.3 code reads as written
        for part, volts in [("LT8607EMSE-5#PBF", 5.0), ("LT8609AEDDM-5#PBF", 5.0),
                            ("LT8610ABEMSE-5_TRPBF", 5.0), ("LT8610AB.MSE-5", 5.0),
                            ("LTC3620EDC-1#TRMPBF", 1.1), ("LT8609AEDDM-3.3#PBF", 3.3)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (volts, "fixed_suffix"), part)
        # LT8640-1 is an adjustable part (LT8640/LT8640-1 Rev. F p3)
        self.assertEqual(lookup_regulator_vref("LT8640EUDC-1#PBF", ""), (0.97, "lookup"))

    def test_fixed_ldo_members_take_no_adjustable_reference(self):
        for part in ["TPS79333DBVRG4Q1", "TPS79318-EP", "TPS73133DBVR"]:
            self.assertEqual(lookup_regulator_vref(part, ""), (None, ""), part)

    def test_tps61023_reference_unchanged(self):
        self.assertEqual(lookup_regulator_vref("TPS61023DRLR", ""), (0.595, "lookup"))

    def test_rows_take_their_datasheet_reference(self):
        # typ column of each Electrical Characteristics table: TPS54202 SLVSD26C p5 and TPS54202H
        # SLVSDG7A p5 VFB 0.596; TPS54560 SLVSBN0A p5 / TPS54560B SLVSF00 p5 0.8; LM338 SNVS771D p7
        # VREF 1.24; LM350 SNVS772B p2 1.25; SPX1117 Rev. 2.2.0 p2 1.25; LMR50410 SLUSDW3A p5 VFB 1.0;
        # LMR51625 SLUSF64B p5 0.8
        for part, vref in [("TPS54202DDCR", 0.596), ("TPS54202HDDCR", 0.596),
                           ("TPS54560BDDAR", 0.8), ("TPS54560DDA", 0.8), ("LM338T", 1.24),
                           ("LM350T", 1.25), ("SPX1117M3-L/TR", 1.25), ("LMR50410XDBVR", 1.0),
                           ("LMR51625YDDCR", 0.8), ("LMR51635YDDCR", 0.8)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (vref, "lookup"), part)

    def test_fixed_members_of_the_new_rows(self):
        # SPX1117 Rev. 2.2.0 p3 ordering table; LMR50410-Q1 SLUSDW4A p3 device comparison table
        for part, volts in [("SPX1117M3-L-1-5/TR", 1.5), ("SPX1117M3-L-1-8/TR", 1.8),
                            ("SPX1117M3-L-2-5/TR", 2.5), ("SPX1117M3-L-3-3/TR", 3.3),
                            ("SPX1117M3-L-5-0/TR", 5.0), ("LMR50410Y3FQDBVRQ1", 3.3),
                            ("LMR50410Y5FQDBVRQ1", 5.0)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (volts, "fixed_suffix"), part)
        self.assertEqual(lookup_regulator_vref("LMR50410YFQDBVRQ1", ""), (1.0, "lookup"))
        # a code the ordering table does not list is not read as a voltage
        self.assertEqual(lookup_regulator_vref("SPX1117M3-L-1-2/TR", ""), (None, ""))

    def test_keys_do_not_reach_other_parts(self):
        # LM3509 / LM35000 are not LM350; LMR51620 / LMR51630 / LMR51640 / LMR51660 have no data sheet
        for part in ["LM3509", "LM35000", "LM3380", "LMR51620", "LMR51630", "LMR51640", "LMR51660"]:
            self.assertEqual(lookup_regulator_vref(part, ""), (None, ""), part)
        self.assertEqual(lookup_regulator_vref("LMR51430", ""), (0.6, "lookup"))

    def test_ltc3558_feedback_is_0v8(self):
        self.assertEqual(lookup_regulator_vref("LTC3558", ""), (0.8, "lookup"))


class OrderCodes(unittest.TestCase):
    def test_onsemi_ncp1117_order_codes(self):
        # NCP1117/D Rev. 31 p12 (NCP1117) and p13 (NCV1117) ordering tables;
        # NCP1117LP/D Rev. 6 p1 marking (xx = 15, 18, 25, 33, 50, AD) and p12 ordering table
        for part, volts in [("NCP1117ST33T3G", 3.3), ("NCP1117DT33RKG", 3.3),
                            ("NCP1117ST12T3G", 12.0), ("NCP1117ST15T3G", 1.5),
                            ("NCP1117DT285RKG", 2.85), ("NCP1117DT19RKG", 1.9),
                            ("NCP1117DT15G_MountingTab", 1.5), ("NCV1117ST50T3G", 5.0),
                            ("NCP1117LPST33T3G", 3.3), ("NCP1117LPDT18RKG", 1.8)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (volts, "fixed_suffix"), part)
            self.assertTrue(fixed_vout_is_explicit(part, ""), part)

    def test_ncp1117_adjustable_order_codes_keep_the_reference(self):
        for part in ["NCP1117STAT3G", "NCP1117DTARKG", "NCP1117LPSTADT3G", "NCP1117-ADJ_SOT223"]:
            self.assertEqual(lookup_regulator_vref(part, ""), (1.25, "lookup"), part)

    def test_borrowed_order_code_symbol_says_nothing_about_another_part(self):
        self.assertEqual(lookup_regulator_vref("TC2117", "X:NCP1117ST33T3G"), (None, ""))
        self.assertEqual(lookup_regulator_vref("LDL1117S30R", "X:NCP1117ST33T3G"), (3.0, "fixed_suffix"))

    def test_lmr36506_fixed_order_codes(self):
        # LMR36506-Q1 SNVSB91C p3 Device Comparison Table: MSC5 5-V fixed, MSC3 3.3-V fixed, MSCQ adjustable
        for part, volts in [("LMR36506MSC5RPERQ1", 5.0), ("LMR36506MSC3RPERQ1", 3.3)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (volts, "fixed_suffix"), part)
            self.assertTrue(fixed_vout_is_explicit(part, ""), part)
        self.assertEqual(lookup_regulator_vref("LMR36506MSCQRPERQ1", ""), (None, ""))

    def test_lmr36506_codes(self):
        # LMR36506-Q1 SNVSB91C p3 and LMR36506 SNVSBB6C p3 device comparison tables
        for part, volts in [("LMR36506RS3QRPERQ1", 3.3), ("LMR36506R3RPER", 3.3), ("LMR36506RF3RPER", 3.3),
                            ("LMR36506R5RPER", 5.0)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (volts, "fixed_suffix"), part)
            self.assertTrue(fixed_vout_is_explicit(part, ""), part)
        for part in ["LMR36506RRPER", "LMR36506RFRPER"]:
            self.assertNotEqual(lookup_regulator_vref(part, "")[1], "fixed_suffix", part)

    def test_st_ld1117_order_codes(self):
        # LD1117 DocID2572 Rev 38 Table 26 p44; LD1117A DocID7194 Rev 26 Table 1 p1
        for part, volts in [("LD1117S33TR", 3.3), ("LD1117DT18TR", 1.8), ("LD1117V33C", 3.3),
                            ("LD1117D33TR", 3.3), ("LD1117S50CTR", 5.0), ("LD1117S25TR_SOT223", 2.5),
                            ("LD1117AS12TR", 1.2), ("LD1117ADT33TR", 3.3), ("LD1117AV33", 3.3)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (volts, "fixed_suffix"), part)
            self.assertTrue(fixed_vout_is_explicit(part, ""), part)
        # the adjustable versions keep the 1.25 V reference (DocID2572 Rev 38 Table 8 p14)
        for part in ["LD1117STR", "LD1117DTTR", "LD1117V", "LD1117SC-R", "LD1117ADT-TR", "LD1117ASTR"]:
            self.assertEqual(lookup_regulator_vref(part, ""), (1.25, "lookup"), part)

    def test_ldl1117_has_fixed_members_only(self):
        # DS12022 Rev 7 Table 7 p18: fixed members only, S12R is 1.185 V
        for part, volts in [("LDL1117S12R", 1.185), ("LDL1117S15R", 1.5), ("LDL1117S30R", 3.0),
                            ("LDL1117S33R", 3.3), ("LDL1117S50R", 5.0)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (volts, "fixed_suffix"), part)
        self.assertEqual(lookup_regulator_vref("LDL1117", ""), (None, ""))
        self.assertIsNone(regulator_vref_key("LDL1117", ""))

    def test_ncp1117i_codes(self):
        # NCP1117/D Rev. 31 p12, ordering information (NCP1117I)
        for part, volts in [("NCP1117IST18T3G", 1.8), ("NCP1117IST33T3G", 3.3), ("NCP1117IST50T3G", 5.0),
                            ("NCP1117IDT33T4G", 3.3), ("NCP1117IDT50T4G", 5.0)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (volts, "fixed_suffix"), part)
        for part in ["NCP1117ISTAT3G", "NCP1117IDTAT4G"]:
            self.assertEqual(lookup_regulator_vref(part, ""), (1.25, "lookup"), part)

    def test_mic23050_codes(self):
        # M9999-092211-E p2 ordering information
        for part, volts in [("MIC23050-CYML", 1.0), ("MIC23050-4YML", 1.2), ("MIC23050_GYML", 1.8),
                            ("MIC23050-SYML-TR", 3.3)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (volts, "fixed_suffix"), part)
            self.assertTrue(fixed_vout_is_explicit(part, ""), part)
        self.assertEqual(lookup_regulator_vref("MIC23050", ""), (None, ""))

    def test_invisible_marks_around_a_part_number(self):
        self.assertEqual(lookup_regulator_vref("\u200f\u200eNCV1117ST25T3G", ""), (2.5, "fixed_suffix"))
        self.assertEqual(lookup_regulator_vref("LINEAR_LDO", "X:LINEAR_LDO", "LD1117AS12TR\u200e\u200f"),
                         (1.2, "fixed_suffix"))

    def test_reg_label_text_is_not_read(self):
        self.assertEqual(lookup_regulator_vref("Reg.3.3V 1A", "lsts-regul:REG_Recom"), (None, ""))

    def test_st_l78_l79_codes(self):
        # ST order codes: L78 DS0422 Rev 38 Table 27 p50; L78L DS0424 Rev 30 Table 29 p34; L78M DocID2147
        # Rev 9 Table 14 p27; L78S DocID2148 Rev 8 Table 1 p1; L79 DocID2149 Rev 21 Table 1 p1; L79L
        # DocID2511 Rev 18 Table 14 p22
        for part, volts in [("L7805CV", 5.0), ("L7885CV", 8.5), ("L7824ABD2T-TR", 24.0),
                            ("L78L33ACZ", 3.3), ("L78L10ACUTR", 10.0), ("L78M05CDT", 5.0),
                            ("L78M10ABDT-TR", 10.0), ("L78S75CV", 7.5), ("L78S05CV_TO220", 5.0),
                            ("L7912CV", -12.0), ("L7908CV", -8.0), ("L79L05", -5.0), ("L79L15ACUTR", -15.0)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (volts, "fixed_suffix"), part)
            self.assertTrue(fixed_vout_is_explicit(part, ""), part)
        # L7987 and L7983 are ST step-down converters; L7833, L78M33 and L79L09 are not in the tables
        for part in ["L7987", "L7983", "L7833", "L78M33", "L78S33CV", "L79L09"]:
            self.assertNotEqual(lookup_regulator_vref(part, "")[1], "fixed_suffix", part)

    def test_st_order_code_on_a_generic_78xx_symbol_reads_its_own_code(self):
        for value, lib_id, volts in [("L7808CV", "Regulator_Linear:LM7808_TO220", 8.0),
                                     ("L78M05ABDT-TR", "Regulator_Linear:LM78M05_TO252", 5.0),
                                     ("L7805CV", "rti-rescue:LM7805CT-regul", 5.0),
                                     ("L7805", "Regulator_Linear:LM7812_TO220", 5.0),
                                     ("", "Regulator_Linear:L7805", 5.0)]:
            self.assertEqual(lookup_regulator_vref(value, lib_id), (volts, "fixed_suffix"), value)
        # an MC, uA or AIP 78xx code is not an ST order code
        for value in ["MC7809CTG", "UA7805UC", "AIP78M05"]:
            self.assertEqual(lookup_regulator_vref(value, "Regulator_Linear:LM7805_TO220"), (None, ""), value)

    def test_other_makers_79xx_codes_read_negative(self):
        # onsemi MC7900/D Rev. 21 pp2-7, MC79L00/D Rev. 12 pp2-4, MC79M00/D Rev. 16 p1; TI uA7900
        # SLVS058H p1, uA79M SLVS060K p1; a bare code is any maker's part with that code
        for part, volts in [("L7905CV", -5.0), ("MC7912", -12.0), ("MC7912CTG", -12.0),
                            ("MC7924BTG", -24.0), ("MC79L05ACPG", -5.0), ("MC79L15ACDR", -15.0),
                            ("MC79M05CDTG", -5.0), ("MC79M12_TO252", -12.0), ("UA7905CKCS", -5.0),
                            ("UA79M08CKTPR", -8.0), ("79L05", -5.0), ("79L05_SOT89", -5.0),
                            ("7912", -12.0), ("7915", -15.0), ("79M12", -12.0)]:
            self.assertEqual(lookup_regulator_vref(part, ""), (volts, "fixed_suffix"), part)
            self.assertTrue(fixed_vout_is_explicit(part, ""), part)
        # L7987 is an ST buck; MC7905.2 is -5.2 V; MC79L08, MC79M24 and uA79M12 are not in their tables
        for part in ["L7987", "MC7905.2CT", "MC79L08", "MC79M24", "UA79M12", "79L09", "7987", "790512"]:
            self.assertNotEqual(lookup_regulator_vref(part, "")[1], "fixed_suffix", part)

    def test_79xx_value_on_another_parts_symbol_reads_its_own_code(self):
        self.assertEqual(lookup_regulator_vref("79L05", "Regulator_Linear:L79L05_SO8"),
                         (-5.0, "fixed_suffix"))
        self.assertEqual(lookup_regulator_vref("7915", "Regulator_Linear:LM7915_TO220", "MC7915CTG"),
                         (-15.0, "fixed_suffix"))
        # a value naming another part takes nothing from a 79xx symbol
        self.assertEqual(lookup_regulator_vref("TA7900S", "Custom:MC7905"), (None, ""))


class BorrowedSymbol(unittest.TestCase):
    def test_value_naming_another_part_does_not_take_the_symbol_reference(self):
        for value, lib_id in [
                ("TPS54331", "MidiLedController-rescue:TPS563200-Regulator_Switching-MidiDrumTeacherModule-rescue"),
                ("TPS564208DDCT", "Custom_Parts:TPS54308DDC"),
                ("LT1085CT", "Regulator_Linear:LM337_TO220")]:
            self.assertEqual(lookup_regulator_vref(value, lib_id), (None, ""), value)
            self.assertIsNone(regulator_vref_key(value, lib_id), value)

    def test_value_with_its_own_row_keeps_it_on_a_borrowed_symbol(self):
        self.assertEqual(lookup_regulator_vref(
            "TPS54202", "MidiLedController-rescue:TPS563200-Regulator_Switching-MidiDrumTeacherModule-rescue"),
            (0.596, "lookup"))

    def test_value_naming_no_part_takes_the_symbol_reference(self):
        for value, lib_id, vref in [("", "Regulator_Switching:TPS54308", 0.596),
                                    ("LDO1", "Regulator_Linear:LM317_TO220", 1.25),
                                    ("DNP/TPS54302", "Regulator_Switching:TPS54302", 0.596)]:
            self.assertEqual(lookup_regulator_vref(value, lib_id), (vref, "lookup"), value)

    def test_own_reference_still_wins_over_the_symbol(self):
        self.assertEqual(lookup_regulator_vref("TPS564247DRLR", "Regulator_Switching:TPS562202"),
                         (0.6, "lookup"))

    def test_mpn_still_gives_the_reference_when_the_value_has_none(self):
        self.assertEqual(lookup_regulator_vref("TPS54202", "X:TPS563200", "TPS54308DDCR"),
                         (0.596, "lookup"))

    def test_voltage_in_a_label_value_outranks_a_borrowed_order_code_symbol(self):
        for value, lib_id, volts in [("DCDC_3V3", "Regulator_Switching:R-78E5.0-0.5", 3.3),
                                     ("LDO_3V3", "Regulator_Switching:R-78E5.0-0.5", 3.3),
                                     ("REG-3.3", "X:NCP1117ST50T3G", 3.3),
                                     ("LDO_5V0", "X:NCP1117ST33T3G", 5.0),
                                     ("BUCK-12V0", "Converter_DCDC:R-78B5.0-2.0", 12.0),
                                     ("DCDC_3V3", "X:TPS61032PWPR", 3.3)]:
            self.assertEqual(lookup_regulator_vref(value, lib_id), (volts, "fixed_suffix"), value)

    def test_fixed_voltage_of_a_borrowed_symbol_is_not_read(self):
        for value, lib_id in [("LF33CV", "Regulator_Linear:LM7805_TO220"),
                              ("CJ78M09", "Regulator_Linear:LM78M05_TO252"),
                              ("AMS1117-5", "Regulator_Linear:AMS1117-3.3"),
                              ("LM323-K", "Regulator_Linear:LM7812_TO220"),
                              ("TPS7A0309", "Regulator_Linear:MIC5365-1.8YC5"),
                              ("CL9293A33", "Regulator_Linear:AP2127K-1.2"),
                              ("AMS1117", "X:SPX1117M3-L-3-3")]:
            self.assertNotEqual(lookup_regulator_vref(value, lib_id)[1], "fixed_suffix", value)
            self.assertFalse(fixed_vout_is_explicit(value, lib_id), value)

    def test_divider_sets_vout_under_a_borrowed_fixed_symbol(self):
        self.assertEqual(lookup_regulator_vref("LM2596S-ADJ", "Regulator_Switching:LM2596S-12"), (1.23, "lookup"))

    def test_own_fixed_voltage_beats_a_borrowed_lm78xx_symbol(self):
        self.assertEqual(lookup_regulator_vref("LP2950CZ-3.3G", "Regulator_Linear:LM78L05_TO92"),
                         (3.3, "fixed_suffix"))

    def test_value_naming_no_part_still_takes_the_symbol_voltage(self):
        for value in ("", "7805", "LDO1"):
            self.assertEqual(lookup_regulator_vref(value, "Regulator_Linear:LM7805_TO220"), (5.0, "fixed_suffix"),
                             value)

    def test_value_the_symbol_name_starts_with_names_the_same_part(self):
        for value, lib_id, expected in [("LM2586S", "X:LM2586S-5.0", (5.0, "fixed_suffix")),
                                        ("AMS1117", "Regulator_Linear:AMS1117-3.3", (3.3, "fixed_suffix")),
                                        ("SPX1117", "X:SPX1117M3-L-3-3", (3.3, "fixed_suffix")),
                                        ("LD1117", "Regulator_Linear:LD1117S33TR_SOT223", None)]:
            got = lookup_regulator_vref(value, lib_id)
            self.assertEqual(got, lookup_regulator_vref("", lib_id), value)
            if expected:
                self.assertEqual(got, expected, value)


class RecomR78(unittest.TestCase):
    # RECOM model numbering R-78<series><Vout>-<Iout>: R-78xx-0.5 REV 6/2023 p1, R-78xx-1.0 REV 5/2023 p1,
    # R-78B-1.5 REV 5/2020 p1, R-78B-2.0 REV 5/2021 p1, R-78C-1.0 REV 3/2019 p1, R-78CK-0.5 Rev 1-2025 p1,
    # R-78E-0.5 REV 9/2025 p1, R-78E-1.0 REV 9/2024 p1, R-78HB-0.5 REV 5/2019 p1, R-78K-1.0 Rev 6-2025 p2
    def test_r78_name_gives_the_output_voltage_not_the_current(self):
        for name, volts in [("R-78E3.3-1.0", 3.3), ("R-78E5.0-0.5", 5.0), ("R-78E12-1.0/X9", 12.0),
                            ("R-78K3.3-1.0", 3.3), ("R-78B12-2.0", 12.0), ("R-78B3.3-1.5L", 3.3),
                            ("R-78C5.0-1.0", 5.0), ("R-78CK3.3-0.5", 3.3), ("R-78HB6.5-0.5", 6.5),
                            ("R-783.3-0.5", 3.3), ("R-7812-0.5", 12.0), ("R-785.0-1.0", 5.0),
                            ("R-78E5", 5.0), ("R-78B3.3-1.0 (Recom)", 3.3)]:
            self.assertEqual(lookup_regulator_vref(name, ""), (volts, "fixed_suffix"), name)
            self.assertTrue(fixed_vout_is_explicit(name, ""), name)

    def test_r78_symbol_under_a_label_value(self):
        self.assertEqual(lookup_regulator_vref("U2", "Regulator_Switching:R-78E5.0-0.5"), (5.0, "fixed_suffix"))

    def test_r78_current_suffix_is_never_read_as_a_voltage(self):
        # a series outside the cited data sheets, and R-78 symbols borrowed for other parts
        for value, lib_id in [("R-78S3.3-0.1", ""), ("VXO7803-1000", "X:R-78C3.3-1.0"),
                              ("BP5293-5", "X:R-78E5")]:
            self.assertNotEqual(lookup_regulator_vref(value, lib_id)[1], "fixed_suffix", value)
        # an ST order code on an R-78 symbol gives its own voltage, not the module's
        self.assertEqual(lookup_regulator_vref("L7812CV", "X:R-78B5.0-2.0"), (12.0, "fixed_suffix"))

    def test_r78aa_and_underscore_spelling(self):
        # R-78AA-0.5 REV.: 5/2019 p1 selection guide and model numbering; some libraries write R_78
        for name, volts in [("R-78AA5.0-0.5SMD", 5.0), ("R-78AA3.3-0.5SMD-R", 3.3), ("R_783.3-0.5", 3.3),
                            ("R_78E5.0-0.5", 5.0)]:
            self.assertEqual(lookup_regulator_vref(name, ""), (volts, "fixed_suffix"), name)
        self.assertTrue(is_r78_module("R_783.3-0.5", ""))
        self.assertEqual(lookup_regulator_vref("R-78S3.3-0.1", ""), (None, ""))

    def test_voltage_written_outside_the_model_number_is_still_read(self):
        self.assertEqual(lookup_regulator_vref("R-78B_9.0V-1.0A", ""), (9.0, "fixed_suffix"))

    def test_r78_module_is_recognised_by_value_or_symbol(self):
        self.assertTrue(is_r78_module("R-78C3.3-1.0", "lsts-regul:REG_Recom"))
        self.assertTrue(is_r78_module("U2", "Regulator_Switching:R-78E5.0-0.5"))
        # a symbol borrowed for another part says nothing
        self.assertFalse(is_r78_module("L7805CV", "Regulator_Switching:R-78B5.0-2.0"))
        self.assertFalse(is_r78_module("AMS1117-3.3", "Regulator_Linear:AMS1117-3.3"))


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
                          ("LM2731", "LM2731XMF"), ("LM2731", "LM2731X"), ("LM27313", "LM27313X"),
                          ("LMR51610", "LMR51610X"), ("LMR51606", "LMR51606X")]:
            self.assertTrue(vref_key_covers_part(key, part), part)

    def test_ld33_takes_no_reference(self):
        # no cited data sheet names an LD33 part (LD1117 DocID2572 Rev 38 Table 26 lists no LD33 code)
        for part in ["LD33", "LD33CV", "LD33V"]:
            self.assertEqual(lookup_regulator_vref(part, ""), (None, ""), part)
            self.assertIsNone(regulator_vref_key(part, ""), part)


class LongestKey(unittest.TestCase):
    def test_mpn_with_a_longer_key_beats_the_value_family_key(self):
        self.assertEqual(lookup_regulator_vref("RT6", ""), (0.6, "lookup"))
        self.assertEqual(lookup_regulator_vref("RT6", "", "RT6150AGQW"), (0.5, "lookup"))
        self.assertEqual(regulator_vref_key("RT6", "", "RT6150AGQW"), ("RT6150", "RT6150AGQW"))

    def test_value_key_wins_when_the_mpn_key_is_not_longer(self):
        self.assertEqual(lookup_regulator_vref("RT6150AGQW", "", "RT6"), (0.5, "lookup"))


if __name__ == "__main__":
    unittest.main()
