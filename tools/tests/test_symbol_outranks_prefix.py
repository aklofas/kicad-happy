# tools/tests/test_symbol_outranks_prefix.py
"""A part whose reference prefix does not name its type takes the type its library symbol
names: a switching regulator on a Regulator_Switching symbol is an IC, not a switch, and a
part whose type would come only from its first letter takes the type its symbol's name
stands for (PD1 on R_Small is a resistor, LD4 on Device:LED an LED). A bare V letter is not a
varistor on its own: a SPICE source is "other", a diode, transistor, LED or logic IC keeps that
type, and only a varistor word keeps varistor."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.classify import classify_component  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
import signal_detectors as sd  # noqa: E402

PINS = lambda n: [{"name": ""}] * n  # noqa: E731


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


class VLetter(unittest.TestCase):
    def test_spice_sources_are_not_varistors(self):
        for lib in ("Simulation_SPICE:VDC", "Simulation_SPICE:VSIN", "Simulation_SPICE:VPULSE",
                    "pspice:VSOURCE", "VDC_PSPICE", "VSOURCE-RESCUE-sallen_key"):
            self.assertEqual(classify_component("V1", lib, "5"), "other", lib)
        self.assertEqual(classify_component("VIN1", "Simulation_SPICE:VSIN", "SIN(0 1 1k)"), "other")

    def test_symbol_names_the_part(self):
        self.assertEqual(classify_component("VD100", "Device:D_Bridge_+-AA", "DB107"), "diode")
        self.assertEqual(classify_component("VD1", "Device:D", "1N4148"), "diode")
        self.assertEqual(classify_component("VD4", "Device:LED_RGBA", "LTST"), "led")
        self.assertEqual(classify_component("VT1", "Device:Q_NPN_BEC", "BC847"), "transistor")
        self.assertEqual(classify_component("VT1", "gost_common:VT_NPN_EBC", "KT315"), "transistor")
        self.assertEqual(classify_component("V7", "Transistor_FET:BSP89", "NCE0115K"), "transistor")
        self.assertEqual(classify_component("VR3", "Device:R", "10k"), "resistor")

    def test_v_reference_on_logic_symbol_is_ic(self):
        self.assertEqual(classify_component("VD21", "jt74:74LS74", "74LS74", pins=PINS(14)), "ic")
        self.assertEqual(classify_component("VIC64", "74xx:74LS86", "74LS86"), "ic")
        self.assertEqual(classify_component("V3", "Reference_Voltage:REF3025", "REF3025"), "ic")

    def test_gost_letters_need_a_diode_or_transistor_pin_count(self):
        self.assertEqual(classify_component("VD3", "MyLib:KD522", "KD522", pins=PINS(2)), "diode")
        self.assertEqual(classify_component("VD5", "MyLib:KC405", "KC405", pins=PINS(4)), "diode")
        self.assertEqual(classify_component("VT2", "NTE2984", "FQP30N06", pins=PINS(3)), "transistor")
        self.assertEqual(classify_component("VT4", "MyLib:BC847S", "BC847S", pins=PINS(6)), "transistor")
        self.assertEqual(classify_component("VD16", "arcade:HM6116P-3", "HM6116P-3", pins=PINS(24)), "other")
        self.assertEqual(classify_component("VT9", "MyLib:ULN2003", "ULN2003", pins=PINS(16)), "other")

    def test_gost_letters_without_pin_data_are_permissive(self):
        self.assertEqual(classify_component("VD3", "MyLib:KD522", "KD522"), "diode")
        self.assertEqual(classify_component("VT2", "NTE2984", "FQP30N06"), "transistor")

    def test_varistor_words_keep_varistor(self):
        self.assertEqual(classify_component("V1", "Device:Varistor", "S14K275"), "varistor")
        self.assertEqual(classify_component("V1", "MyLib:X", "07D471K"), "varistor")
        self.assertEqual(classify_component("VR1", "VR", "VR"), "varistor")  # KiCad 4 varistor symbol
        self.assertEqual(classify_component("VR4", "MyLib:X", "TVR10471", description="VDR 470 V"),
                         "varistor")
        self.assertEqual(classify_component("RV1", "Device:Varistor", "275V"), "varistor")
        self.assertEqual(classify_component("MOV1", "TMOV20RP300E:TMOV20RP300E", "TMOV20"), "varistor")

    def test_varistor_part_numbers_keep_varistor(self):
        for val in ("S14K275", "B72214S0271K101", "ERZ-V14D471", "TVR10471", "ZNR",
                    "V275LA20AP", "CG0603MLC-05E", "7D471K"):
            self.assertEqual(classify_component("V1", "MyLib:X", val), "varistor", val)

    def test_v_reference_esd_array_is_ic(self):
        self.assertEqual(classify_component("VD1", "USB_ESD_Protection:USBLC6-2", "USBLC6-2",
                                            pins=PINS(6)), "ic")
        self.assertEqual(classify_component("VD1", "Power_Protection:TPD4E05U06", "TPD4E05U06",
                                            pins=PINS(6)), "ic")
        self.assertEqual(classify_component("VD2", "MyLib:ESD9B", "ESD9B5.0ST5G", pins=PINS(2)), "diode")

    def test_varistor_on_custom_symbol_named_only_by_its_description(self):
        comp = {"reference": "V1", "value": "S14K275", "lib_id": "MyParts:S14K275",
                "footprint": "", "pins": []}
        comp["type"] = classify_component("V1", comp["lib_id"], comp["value"],
                                          description="Metal oxide varistor 275 V")
        self.assertEqual(comp["type"], "varistor")
        nets = {n: {"name": n, "pins": [dict(component="V1", pin_number=p, pin_name="~",
                                             pin_type="passive")],
                    "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
                for n, p in (("AC_L", "1"), ("AC_N", "2"))}
        ctx = build_analysis_context([comp], nets, {}, known_power_rails=set())
        pds = [p for p in sd.detect_protection_devices(ctx) if p["ref"] == "V1"]
        self.assertEqual([(p["rule_id"], p["type"]) for p in pds], [("PD-DET", "varistor")])

    def test_vr_keeps_pot_and_regulator_overrides(self):
        self.assertEqual(classify_component("VR1", "Device:R_Potentiometer", "10k"), "resistor")
        self.assertEqual(classify_component("VR1", "Regulator_Linear:LM7805_TO220", "7805"), "ic")
        self.assertEqual(classify_component("VR2", "T93YA104KT20:T93YA104KT20", "T93YA104KT20"), "other")

    def test_unnamed_v_parts_are_other(self):
        self.assertEqual(classify_component("V1", "Valve:ECC83", "ECC83"), "other")
        self.assertEqual(classify_component("VMH1", "KCL:VIRTUAL_MOUNTING-HOLE", "X"), "other")


if __name__ == "__main__":
    unittest.main()
