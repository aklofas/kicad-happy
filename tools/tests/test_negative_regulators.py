"""An LM79xx is a negative fixed regulator, a rail name with a leading minus is negative,
and a boost whose divider tops out on a V-/VEE rail is inverting."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_core.parts import lookup_regulator_vref  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from schematic.system_analyses import analyze_inrush_current, analyze_power_budget  # noqa: E402
from signal_detectors import _infer_rail_voltage, detect_power_regulators  # noqa: E402

_TYPES = {"U": "ic", "L": "inductor", "R": "resistor", "C": "capacitor"}


def _ctx(parts):
    """A context from ``(ref, lib_id, value, {pin_num: (pin_name, net)})`` tuples."""
    components, nets = [], {}
    for ref, lib_id, value, pins in parts:
        components.append({"reference": ref, "lib_id": lib_id, "value": value,
                           "type": _TYPES[ref.rstrip("0123456789")],
                           "pins": [{"number": n, "name": name} for n, (name, _) in pins.items()]})
        for num, (name, net) in pins.items():
            nets.setdefault(net, {"name": net, "pins": []})["pins"].append(
                {"component": ref, "pin_number": num, "pin_name": name})
    return build_analysis_context(components, nets, {})


def _lm7905():
    return _ctx([("U1", "Regulator_Linear:LM7905_TO220", "LM7905_TO220",
                  {"1": ("GND", "GND"), "2": ("VI", "-12V"), "3": ("VO", "-5V")}),
                 ("C1", "Device:C", "10u", {"1": ("1", "-5V"), "2": ("2", "GND")})])


class Lm79FixedOutput(unittest.TestCase):
    def test_lm79_parts_read_negative(self):
        for name, volts in [("LM7905", -5.0), ("LM79L05", -5.0), ("LM7912CT", -12.0),
                            ("LM7915_TO220", -15.0)]:
            self.assertEqual(lookup_regulator_vref(name, ""), (volts, "fixed_suffix"), name)

    def test_lm78_parts_stay_positive(self):
        self.assertEqual(lookup_regulator_vref("LM7805", ""), (5.0, "fixed_suffix"))
        self.assertEqual(lookup_regulator_vref("LM78L12", ""), (12.0, "fixed_suffix"))

    def test_lm7905_estimates_minus_five_and_a_dissipation(self):
        reg = detect_power_regulators(_lm7905(), [])[0]
        self.assertEqual((reg["estimated_vout"], reg["input_rail"], reg["output_rail"]),
                         (-5.0, "-12V", "-5V"))
        pd = reg["power_dissipation"]
        # -12 V in, -5 V out: 7 V dropout at the 0.1 A cap proxy (10 uF), 0.7 W.
        self.assertEqual((pd["vin_estimated_V"], pd["dropout_V"], pd["estimated_pdiss_W"]),
                         (-12.0, 7.0, 0.7))

    def test_lm7905_keeps_its_inrush_record(self):
        ctx = _lm7905()
        inrush = analyze_inrush_current(ctx, {"power_regulators": detect_power_regulators(ctx, [])})
        row = inrush["rails"][0]
        self.assertEqual((row["regulator"], row["output_voltage"]), ("U1", 5.0))

    def test_negative_adjustable_gets_an_inrush_row(self):
        # LM337 at -15 V into 10 uF over the 0.5 ms LDO soft start: 10e-6 x 15 / 0.5e-3 = 0.3 A.
        ctx = _ctx([("U1", "Regulator_Linear:LM337_TO220", "LM337",
                     {"1": ("ADJ", "ADJ"), "2": ("VI", "-20V"), "3": ("VO", "-15V")}),
                    ("C1", "Device:C", "10u", {"1": ("1", "-15V"), "2": ("2", "GND")})])
        reg = {"ref": "U1", "value": "LM337", "topology": "LDO", "estimated_vout": -15.0,
               "input_rail": "-20V", "output_rail": "-15V"}
        row = analyze_inrush_current(ctx, {"power_regulators": [reg]})["rails"][0]
        self.assertEqual((row["regulator"], row["output_voltage"], row["estimated_inrush_A"]),
                         ("U1", 15.0, 0.3))


class RailNameSign(unittest.TestCase):
    def test_leading_minus_is_negative(self):
        self.assertEqual(_infer_rail_voltage("-VBAT"), -3.7)
        self.assertEqual(_infer_rail_voltage("/Analog/-5V"), -5.0)
        self.assertEqual(_infer_rail_voltage("-12V"), -12.0)

    def test_positive_and_data_names_unchanged(self):
        self.assertEqual(_infer_rail_voltage("+5V"), 5.0)
        self.assertEqual(_infer_rail_voltage("VBAT"), 3.7)
        self.assertIsNone(_infer_rail_voltage("USB_D-"))
        self.assertIsNone(_infer_rail_voltage("-FOO"))


class BoostDividerTop(unittest.TestCase):
    def _boost(self, top, twin=None):
        parts = [("U1", "Regulator_Switching:LT3581", "LT3581",
                  {"1": ("SW", "SW_NODE"), "2": ("FB", "FB"), "3": ("VIN", "+12V")}),
                 ("L1", "Device:L", "10uH", {"1": ("1", "SW_NODE"), "2": ("2", "+12V")})]
        if twin:
            # the output and its positive twin, each with a capacitor to ground
            parts += [("C1", "Device:C", "10u", {"1": ("1", twin), "2": ("2", "GND")}),
                      ("C2", "Device:C", "10u", {"1": ("1", top), "2": ("2", "GND")})]
        ctx = _ctx(parts)
        vd = {"r_top": {"ref": "R1", "ohms": 10000.0, "value": "10k"},
              "r_bottom": {"ref": "R2", "ohms": 10000.0, "value": "10k"},
              "top_net": top, "mid_net": "FB", "bottom_net": "GND", "ratio": 0.5}
        return detect_power_regulators(ctx, [vd])[0]

    def test_vee_or_v_minus_top_is_inverting(self):
        for top in ("VEE", "V-", "/Power/VEE_ANALOG"):
            reg = self._boost(top)
            self.assertEqual(reg["output_rail"], top)
            self.assertTrue(reg.get("inverting"), top)
            self.assertLess(reg["estimated_vout"], 0, top)

    def test_boost_with_negative_divider_top_is_inverting(self):
        for top, twin in [("-15V", None), ("F-15V", "F+15V"), ("7V0_N", "7V0_P"), ("5V_NEG", None)]:
            reg = self._boost(top, twin)
            self.assertEqual(reg["output_rail"], top)
            self.assertTrue(reg.get("inverting"), top)

    def test_word_dash_voltage_top_without_its_twin_is_not_inverting(self):
        self.assertNotIn("inverting", self._boost("F-15V"))

    def test_positive_top_is_not_inverting(self):
        for top in ("VCC-5V", "+24V", "VOUT"):
            self.assertNotIn("inverting", self._boost(top), top)


class InvertingOutputName(unittest.TestCase):
    def _reg(self, out, twin=None):
        parts = [("U1", "Regulator_Linear:LM337_TO220", "LM337",
                  {"1": ("ADJ", "ADJ"), "2": ("VI", "+12V"),
                   "3": ("VO", out)}),
                 ("C1", "Device:C", "10u", {"1": ("1", out), "2": ("2", "GND")})]
        if twin:
            parts.append(("C2", "Device:C", "10u", {"1": ("1", twin), "2": ("2", "GND")}))
        return detect_power_regulators(_ctx(parts), [])[0]

    def test_dash_between_words_is_not_inverting(self):
        for out in ("TPS-VOUT-3.3V", "5Vout-50V", "INJ-2-OUT", "USB-5V", "FTDI-3.3V"):
            self.assertNotIn("inverting", self._reg(out), out)

    def test_negative_names_stay_inverting(self):
        for out in ("-5V", "-VOUT", "AV-", "GENERATED -5V", "5V_NEG",
                    "V-5V", "VEE-12V", "AVEE-5V", "VSS-5V"):
            self.assertTrue(self._reg(out).get("inverting"), out)
        self.assertTrue(self._reg("F-15V", "F+15V").get("inverting"))


class LdoDissipationSign(unittest.TestCase):
    def _rail(self, v_in_net, v_out_net, vout):
        ctx = _ctx([("U1", "Regulator_Linear:LM337_TO220", "LM337",
                     {"1": ("ADJ", "ADJ"), "2": ("VI", v_in_net), "3": ("VO", v_out_net)}),
                    ("U2", "MCU:Part", "MCU", {"1": ("VDD", v_out_net), "2": ("GND", "GND")}),
                    ("C1", "Device:C", "10u", {"1": ("1", v_out_net), "2": ("2", "GND")})])
        reg = {"ref": "U1", "value": "LM337", "topology": "LDO", "estimated_vout": vout,
               "input_rail": v_in_net, "output_rail": v_out_net}
        return analyze_power_budget(ctx, {"power_regulators": [reg]})["rails"][v_out_net]

    def test_negative_ldo_on_a_negative_input_has_a_dissipation(self):
        rail = self._rail("-12V", "-5V", -5.0)
        self.assertEqual(rail["ldo_dissipation"]["dropout"], 7.0)

    def test_positive_input_to_a_negative_output_has_no_dissipation(self):
        self.assertNotIn("ldo_dissipation", self._rail("+15V", "-5V", -5.0))

    def test_positive_ldo_keeps_its_dissipation(self):
        self.assertEqual(self._rail("+12V", "+5V", 5.0)["ldo_dissipation"]["dropout"], 7.0)


class FixedPartOnANegativeInput(unittest.TestCase):
    """A negative regulator's part number writes its voltage without the sign: the input rail
    gives it."""

    def _reg(self, value, vin, twin=None):
        parts = [("U1", "Regulator_Linear:" + value, value,
                  {"1": ("GND", "GND"), "2": ("IN", vin), "3": ("OUT", "VOUT")}),
                 ("C1", "Device:C", "10u", {"1": ("1", "VOUT"), "2": ("2", "GND")})]
        if twin:
            parts.append(("C2", "Device:C", "10u", {"1": ("1", twin), "2": ("2", "GND")}))
        return detect_power_regulators(_ctx(parts), [])[0]

    def test_fixed_part_on_a_negative_input_is_negative(self):
        for value, vin, volts in [("LM2990SX-5.0", "-12V", -5.0), ("LT3015EQ-2.5", "-5VA", -2.5),
                                  ("LM2990S-5.0", "/Power/-12V", -5.0)]:
            reg = self._reg(value, vin)
            self.assertEqual((reg["input_rail"], reg["estimated_vout"]), (vin, volts), value)

    def test_negative_half_of_a_split_pair_is_a_negative_input(self):
        self.assertEqual(self._reg("LM2990S-5.0", "F-15V", twin="F+15V")["estimated_vout"], -5.0)

    def test_fixed_part_on_a_positive_input_stays_positive(self):
        for vin in ("+12V", "VIN-12V", "USB-5V", "F-15V"):
            self.assertEqual(self._reg("LM2990S-5.0", vin)["estimated_vout"], 5.0, vin)

    def test_positive_data_sheet_code_on_a_negative_input_gets_no_estimate(self):
        # an L78L33 or LM7805 fed from a negative rail is wired outside its data sheet
        for value, vin in [("L78L33_SO8", "-3V3"), ("LM7805", "-12V"), ("LM2596S-12", "-15V")]:
            self.assertNotIn("estimated_vout", self._reg(value, vin), value)
        self.assertEqual(self._reg("L78L33_SO8", "+5V")["estimated_vout"], 3.3)

    def test_unlisted_79l_series_code_reads_nothing(self):
        self.assertNotIn("estimated_vout", self._reg("uA79L05", "-12V"))

    def test_negative_code_is_not_negated_twice(self):
        self.assertEqual(self._reg("79L05", "-12V")["estimated_vout"], -5.0)
        self.assertEqual(self._reg("MC7912CTG", "-15V")["estimated_vout"], -12.0)


class InvertingWordInTheLibraryName(unittest.TestCase):
    def test_inverting_regulator_library_marks_the_part_inverting(self):
        ctx = _ctx([("U1", "Inverting_switching_regulator:LT1617", "LT1617",
                     {"1": ("SW", "SW_NODE"), "2": ("GND", "GND"), "3": ("FB", "FB"),
                      "4": ("~{SHDN}", "+5V"), "5": ("VIN", "+5V")}),
                    ("L1", "Device:L", "10uH", {"1": ("1", "+5V"), "2": ("2", "SW_NODE")})])
        reg = detect_power_regulators(ctx, [])[0]
        self.assertTrue(reg.get("inverting"))

    def test_project_library_named_for_an_inverter_does_not(self):
        ctx = _ctx([("U1", "inverter-altium-import:root_0_LM2675", "LM2675M-5.0",
                     {"1": ("CB", "BOOT"), "2": ("VIN", "+12V"), "3": ("ON/OFF", "+12V"),
                      "4": ("GND", "GND"), "5": ("FB", "+5V1"), "6": ("VOUT", "__unnamed_16")}),
                    ("L1", "Device:L", "33uH", {"1": ("1", "__unnamed_16"), "2": ("2", "+5V1")}),
                    ("C1", "Device:C", "68u", {"1": ("1", "+5V1"), "2": ("2", "GND")})])
        reg = detect_power_regulators(ctx, [])[0]
        self.assertNotIn("inverting", reg)
        self.assertEqual(reg["estimated_vout"], 5.0)

    def test_logic_inverter_library_does_not(self):
        ctx = _ctx([("U1", "74xx_Logic-Gates-and-Inverters:LM317", "LM317",
                     {"1": ("ADJ", "ADJ"), "2": ("VO", "+3V3"), "3": ("VI", "+5V")}),
                    ("C1", "Device:C", "10u", {"1": ("1", "+3V3"), "2": ("2", "GND")})])
        reg = detect_power_regulators(ctx, [])[0]
        self.assertNotIn("inverting", reg)


if __name__ == "__main__":
    unittest.main()
