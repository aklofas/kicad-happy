# tools/tests/test_load_switch_not_regulator.py
"""Power switches and load switches are not recorded as regulators; real LDOs and chargers still are."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import audit_rail_sources, detect_power_regulators  # noqa: E402


def _regulators(value, lib_id, pins):
    comp = {"reference": "U1", "lib_id": lib_id, "value": value, "type": "ic",
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


if __name__ == "__main__":
    unittest.main()
