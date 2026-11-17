# tools/tests/test_load_switch_not_regulator.py
"""Power switches and load switches are not recorded as regulators; real LDOs and chargers still are."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from kicad_core.parts import is_load_switch_part  # noqa: E402
from domain_detectors import detect_power_path  # noqa: E402
from signal_detectors import audit_rail_sources, detect_power_regulators  # noqa: E402
from validation_detectors import _is_regulator_like  # noqa: E402


def _regulators(value, lib_id, pins, description=""):
    comp = {"reference": "U1", "lib_id": lib_id, "value": value, "type": "ic", "description": description,
            "pins": [{"number": n, "name": name} for n, (name, _) in pins.items()]}
    nets = {}
    for num, (name, net) in pins.items():
        nets.setdefault(net, {"pins": []})["pins"].append(
            {"component": "U1", "pin_number": num, "pin_name": name})
    return detect_power_regulators(build_analysis_context([comp], nets, {}), [])


_SWITCH_PINS = {"1": ("VIN", "+5V"), "2": ("VOUT", "VBUS_OUT"), "3": ("GND", "GND"), "4": ("EN", "EN")}


class LoadSwitchesAreNotRegulators(unittest.TestCase):
    def test_load_and_usb_power_switches_are_not_regulators(self):
        for value in ("RT9742", "TPS2061", "TPS2065C", "AP2171W", "AP2191", "MT9700", "SY6280",
                      "AP2281-1", "RT9701"):
            self.assertEqual(_regulators(value, "Power_Management:" + value, _SWITCH_PINS), [], value)

    def test_real_linear_regulators_stay(self):
        ldo = {"1": ("GND", "GND"), "2": ("VOUT", "+3V3"), "3": ("VIN", "+5V")}
        for value in ("NJM2870", "LP3874", "AMS1117-3.3"):
            regs = _regulators(value, "Regulator_Linear:" + value, ldo)
            self.assertEqual([r["ref"] for r in regs], ["U1"], value)

    def test_chargers_stay(self):
        pins = {"1": ("IN", "+5V"), "2": ("OUT", "VBAT"), "3": ("GND", "GND"), "4": ("FB", "FB")}
        for value in ("BQ25170", "BQ24074"):
            regs = _regulators(value, "Battery_Management:" + value, pins)
            self.assertEqual([r["ref"] for r in regs], ["U1"], value)


_BUCK_PINS = {"1": ("VIN", "+5V"), "2": ("EN", "+3V3"), "3": ("SW", "SW"), "4": ("SNS", "+3V3"),
              "5": ("GND", "GND")}


class LoadSwitchWordsInDescription(unittest.TestCase):
    def _refs(self, description):
        return [r["ref"] for r in _regulators("XYZ2305", "Custom:XYZ2305", _BUCK_PINS, description)]

    def test_a_buck_describing_light_load_switching_is_a_regulator(self):
        self.assertEqual(self._refs("4MHz PWM Buck Regulator with HyperLight Load Switching Scheme, "
                                    "3.3V Fixed Output Voltage"), ["U1"])

    def test_a_part_described_as_a_load_or_power_switch_is_not(self):
        for description in ("Current-limited load switch", "USB Power Switches",
                            "Single-channel power distribution switch"):
            self.assertEqual(self._refs(description), [], description)

    def test_names_load_switch_matches_whole_words(self):
        from kicad_core.parts import names_load_switch
        self.assertTrue(names_load_switch("Power Distribution Switch, 2 channel"))
        self.assertTrue(names_load_switch("dual LOAD SWITCHES"))
        self.assertFalse(names_load_switch("HyperLight Load Switching Scheme"))
        self.assertFalse(names_load_switch("overload switch"))
        self.assertFalse(names_load_switch(""))


def _switch_sources(value, vin_pin_type, vin_net="+5V"):
    """RS-001 nets for a switch fed from *vin_net*, with a 5 V rail pin on it of *vin_pin_type*."""
    comps = [{"reference": "U1", "type": "ic", "value": value, "lib_id": "Power_Management:" + value},
             {"reference": "J1", "type": "connector", "value": "Conn"},
             {"reference": "U2", "type": "ic", "value": "MCU"}]
    pins = {vin_net: [("J1", "1", "J1", vin_pin_type), ("U1", "1", "VIN", "power_in")],
            "+5V_SW": [("U1", "2", "VOUT", "output"), ("U2", "1", "VDD", "power_in")],
            "GND": [("U1", "3", "GND", "power_in")]}
    nets = {n: {"name": n, "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": [],
                "pins": [dict(component=r, pin_number=num, pin_name=name, pin_type=t) for r, num, name, t in ps]}
            for n, ps in pins.items()}
    ctx = build_analysis_context(comps, nets, {})
    return [f["nets"][0] for f in audit_rail_sources(ctx) if f["rule_id"] == "RS-001"]


class SwitchOutputIsSourced(unittest.TestCase):
    def test_output_of_a_switch_fed_from_a_sourced_rail_is_sourced(self):
        self.assertEqual(_switch_sources("MT9700", "power_out"), [])

    def test_output_of_a_switch_with_an_unsourced_input_is_not(self):
        self.assertEqual(_switch_sources("MT9700", "passive"), ["+5V", "+5V_SW"])

    def test_output_of_a_part_that_is_not_a_switch_is_not(self):
        self.assertEqual(_switch_sources("XYZ123", "power_out"), ["+5V_SW"])


def _switch_behind_jumper(state):
    """(rule, net) findings for a load switch fed from +5V_IN, which reaches the flagged VBUS through JP1."""
    comps = [{"reference": "U1", "type": "ic", "value": "MT9700", "lib_id": "Power_Management:MT9700"},
             {"reference": "U2", "type": "ic", "value": "MCU"},
             {"reference": "JP1", "type": "jumper", "value": "SJ"}]
    pins = {"VBUS": [("JP1", "2", "", "passive")],
            "+5V_IN": [("JP1", "1", "", "passive"), ("U1", "1", "VIN", "power_in")],
            "+5V_SW": [("U1", "2", "VOUT", "output"), ("U2", "1", "VDD", "power_in")],
            "GND": [("U1", "3", "GND", "power_in")]}
    nets = {n: {"name": n, "point_count": 0, "no_connect": False, "has_pwr_flag": n == "VBUS", "labels": [],
                "pins": [dict(component=r, pin_number=num, pin_name=name, pin_type=t) for r, num, name, t in ps]}
            for n, ps in pins.items()}
    ctx = build_analysis_context(comps, nets, {})
    found = audit_rail_sources(ctx, solder_jumpers=[
        {"reference": "JP1", "default_state": state, "nets": ["+5V_IN", "VBUS"]}])
    return sorted((f["rule_id"], f["nets"][0]) for f in found)


class SwitchBehindJumper(unittest.TestCase):
    def test_bridged_jumper_sources_the_switch_input_and_output(self):
        self.assertEqual(_switch_behind_jumper("bridged"), [("RS-003", "+5V_IN")])

    def test_open_jumper_leaves_both_nets_unsourced(self):
        self.assertEqual(_switch_behind_jumper("open"),
                         [("RS-001", "+5V_SW"), ("RS-002", "+5V_IN")])



def _dual_switch_sources(vin2_pin_type):
    """RS-001 nets for a TPS22966 whose VIN1 is fed from a sourced 3V3 and VIN2 from 1V8."""
    comps = [{"reference": "U1", "type": "ic", "value": "TPS22966", "lib_id": "Power_Management:TPS22966"},
             {"reference": "J1", "type": "connector", "value": "Conn"},
             {"reference": "U2", "type": "ic", "value": "MCU"}]
    pins = {"+3V3": [("J1", "1", "J1", "power_out"), ("U1", "1", "VIN1", "power_in")],
            "+1V8": [("J1", "2", "J2", vin2_pin_type), ("U1", "9", "VIN2", "power_in")],
            "+3V3_SW": [("U1", "13", "VOUT1", "output"), ("U2", "1", "VDD", "power_in")],
            "+1V8_SW": [("U1", "7", "VOUT2", "output"), ("U2", "2", "VDDIO", "power_in")],
            "GND": [("U1", "11", "GND", "power_in")]}
    nets = {n: {"name": n, "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": [],
                "pins": [dict(component=r, pin_number=num, pin_name=name, pin_type=t) for r, num, name, t in ps]}
            for n, ps in pins.items()}
    ctx = build_analysis_context(comps, nets, {})
    return sorted(f["nets"][0] for f in audit_rail_sources(ctx) if f["rule_id"] == "RS-001")


class DualSwitchChannels(unittest.TestCase):
    def test_each_output_is_sourced_from_its_own_channel_input(self):
        self.assertEqual(_dual_switch_sources("passive"), ["+1V8", "+1V8_SW"])

    def test_both_channels_sourced_report_nothing(self):
        self.assertEqual(_dual_switch_sources("power_out"), [])


# A load switch and an LDO share this pinout: VIN, VOUT, EN, GND.
_PINS = (("1", "VIN", "+5V"), ("2", "GND", "GND"), ("3", "EN", "EN_SW"), ("4", "VOUT", "+5V_SW"))


def _switch_ctx(value, lib_id, mpn=""):
    comp = {"reference": "U1", "type": "ic", "value": value, "lib_id": lib_id,
            "pins": [{"number": n, "name": name} for n, name, _ in _PINS]}
    if mpn:
        comp["mpn"] = mpn
    nets = {net: {"name": net, "pins": [{"component": "U1", "pin_number": n, "pin_name": name}]}
            for n, name, net in _PINS}
    return build_analysis_context([comp], nets, {}, known_power_rails={"+5V", "+5V_SW", "GND"})


def _regulator_refs(value, lib_id, mpn=""):
    return [r["ref"] for r in detect_power_regulators(_switch_ctx(value, lib_id, mpn), [])]


def _power_path_types(value, lib_id, mpn=""):
    return [(e["ref"], e["type"]) for e in detect_power_path(_switch_ctx(value, lib_id, mpn))]


class LoadSwitchFamilies(unittest.TestCase):
    def test_vm001_families_are_load_switches(self):
        for value in ("AP22653W6-7", "SiP32509", "MIC2025-1YMM", "AP22802AW5-7",
                      "AP22615AWU-7", "FPF2123", "TPS2051BDBVR"):
            with self.subTest(value=value):
                self.assertEqual(_regulator_refs(value, "Power_Management:LoadSwitch"), [])
                self.assertEqual(_power_path_types(value, "Power_Management:LoadSwitch"),
                                 [("U1", "load_switch")])

    def test_an_ldo_with_the_same_pinout_stays_a_regulator(self):
        self.assertEqual(_regulator_refs("AP2112K-3.3", "Regulator_Linear:AP2112K-3.3"), ["U1"])
        self.assertEqual(_power_path_types("AP2112K-3.3", "Regulator_Linear:AP2112K-3.3"), [])


class ValueDecidesOverTheSymbol(unittest.TestCase):
    def test_value_names_the_part_not_the_symbol(self):
        self.assertEqual(_regulator_refs("LP5907MFX-1.2/NOPB", "X:MIC20XX"), ["U1"])
        self.assertEqual(_power_path_types("LP5907MFX-1.2/NOPB", "X:MIC20XX"), [])
        self.assertFalse(_is_regulator_like(_switch_ctx("TDA2002", "Power_Management:FPF2002"), "U1"))

    def test_mpn_names_the_part_when_the_value_does_not(self):
        self.assertTrue(is_load_switch_part("LOADSW", "LoadSwitch", "TPS22918DBVR"))
        self.assertFalse(is_load_switch_part("~", "FPF2195", "LM1117-3.3"))

    def test_family_prefix_needs_a_boundary(self):
        self.assertFalse(is_load_switch_part("SAP2171", ""))
        self.assertTrue(is_load_switch_part("U_MIC2025", ""))

    def test_symbol_name_decides_for_an_empty_or_label_value(self):
        self.assertTrue(is_load_switch_part("~", "MIC2025-1YM"))
        self.assertTrue(is_load_switch_part("", "MIC2025-1YM"))
        self.assertTrue(is_load_switch_part("LDO1", "FPF2195"))
        self.assertEqual(_power_path_types("~", "Power_Management:MIC2025-1YM"), [("U1", "load_switch")])
        self.assertEqual(_power_path_types("LDO1", "lib:FPF2195"), [("U1", "load_switch")])

    def test_value_naming_a_regulator_is_not_a_switch_on_a_switch_symbol(self):
        self.assertFalse(is_load_switch_part("LM1117", "TPS2051"))
        self.assertEqual(_power_path_types("LM1117", "lib:TPS2051"), [])
        self.assertEqual(_regulator_refs("LM1117", "lib:TPS2051"), ["U1"])

    def test_switch_output_from_a_sourced_rail_is_sourced_for_every_family(self):
        for value in ("AP22653W6-7", "SiP32509", "MIC2025-1YMM", "FPF2123", "TPS2051BDBVR"):
            self.assertEqual(_switch_sources(value, "power_out"), [], value)

    def test_library_nickname_is_not_the_symbol(self):
        self.assertEqual(_power_path_types("~", "fpf_parts:Generic_IC"), [])


if __name__ == "__main__":
    unittest.main()
