"""FS-001 compensation and divider impedance, VM-001 regulator enable pins, PS-001 cycle key.

Expected values come from the datasheets and the arithmetic:
- LM2596 is internally compensated and has no COMP pin (LM2596 datasheet, pinout: VIN, OUTPUT,
  GND, FEEDBACK, ON/OFF); UC3843 has a COMP pin for the error-amplifier network.
- LM317 needs >= 3.5-10 mA minimum load, so its datasheet divider is R1 = 240 ohm (OUT-ADJ);
  240 || 720 = 180 ohm is the intended value, not a wasteful divider.
- 100 || 100 = 50 ohm < 1 kohm on a part without that requirement is still worth an info.
- VM-001 threshold table (validation_detectors._VOLTAGE_THRESHOLDS): a 3.3 V-class input has a
  3.6 V absolute maximum, a 1.8 V-class input 2.0 V, so 5.0 V into 3.3 V and 3.3 V into 1.8 V are errors.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import validation_detectors as vd  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402


def ctx_of(components, nets, rails, power_rails_config=None):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    for c in components:
        c.setdefault("lib_id", "")
        c.setdefault("pins", [])
        c.setdefault("footprint", "")
    return build_analysis_context(components, full, {}, known_power_rails=set(rails),
                                  power_rails_config=power_rails_config)


def ic(ref, value):
    return {"reference": ref, "type": "ic", "value": value}


def res(ref, value):
    return {"reference": ref, "type": "resistor", "value": value}


def rule(findings, rule_id):
    return [f for f in findings if f.get("rule_id") == rule_id]


def regulator(ref, r_top, r_bottom, reference=None):
    fb = {"r_top": {"ref": r_top[0], "ohms": r_top[1], "value": str(r_top[1])},
          "r_bottom": {"ref": r_bottom[0], "ohms": r_bottom[1], "value": str(r_bottom[1])},
          "ratio": r_bottom[1] / (r_top[1] + r_bottom[1])}
    if reference:
        fb["reference"] = reference
    return {"ref": ref, "output_rail": "VOUT", "feedback_divider": fb}


class FeedbackCompensation(unittest.TestCase):
    def test_lm2596_feedback_node_gets_no_compensation_finding(self):
        # LM2596-ADJ: divider 10k / 3.3k on FB (2.48 kohm, inside the window), no capacitor.
        comps = [ic("U1", "LM2596S-ADJ"), res("R1", "10k"), res("R2", "3.3k")]
        nets = {"VOUT": [("U1", "2", "OUTPUT", "output"), ("R1", "1", "~", "passive")],
                "FB": [("U1", "4", "FB", "input"), ("R1", "2", "~", "passive"), ("R2", "1", "~", "passive")],
                "GND": [("U1", "3", "GND", "power_in"), ("R2", "2", "~", "passive")]}
        got = vd.validate_feedback_stability(ctx_of(comps, nets, {"VOUT", "GND"}),
                                             [regulator("U1", ("R1", 10000), ("R2", 3300))])
        self.assertEqual(rule(got, "FS-001"), [])

    def test_uc3843_bare_comp_pin_is_reported_on_the_comp_net(self):
        comps = [ic("U1", "UC3843"), res("R1", "10k"), res("R2", "2.5k")]
        nets = {"VOUT": [("R1", "1", "~", "passive")],
                "FB": [("U1", "2", "VFB", "input"), ("R1", "2", "~", "passive"), ("R2", "1", "~", "passive")],
                "COMP": [("U1", "1", "COMP", "output")],
                "GND": [("U1", "5", "GND", "power_in"), ("R2", "2", "~", "passive")]}
        (f,) = rule(vd.validate_feedback_stability(ctx_of(comps, nets, {"VOUT", "GND"}),
                                                   [regulator("U1", ("R1", 10000), ("R2", 2500))]), "FS-001")
        self.assertEqual(f["summary"], "Regulator U1: missing compensation capacitor")
        self.assertEqual(f["nets"], ["COMP"])

    def test_uc3843_comp_with_capacitor_is_silent(self):
        comps = [ic("U1", "UC3843"), res("R1", "10k"), res("R2", "2.5k"),
                 {"reference": "C1", "type": "capacitor", "value": "100n"}]
        nets = {"VOUT": [("R1", "1", "~", "passive")],
                "FB": [("U1", "2", "VFB", "input"), ("R1", "2", "~", "passive"), ("R2", "1", "~", "passive")],
                "COMP": [("U1", "1", "COMP", "output"), ("C1", "1", "~", "passive")],
                "GND": [("U1", "5", "GND", "power_in"), ("R2", "2", "~", "passive"), ("C1", "2", "~", "passive")]}
        got = vd.validate_feedback_stability(ctx_of(comps, nets, {"VOUT", "GND"}),
                                             [regulator("U1", ("R1", 10000), ("R2", 2500))])
        self.assertEqual(rule(got, "FS-001"), [])


class FeedbackImpedance(unittest.TestCase):
    def _run(self, value, reference=None):
        comps = [ic("U1", value), res("R1", "240"), res("R2", "720")]
        nets = {"VOUT": [("U1", "2", "VO", "output"), ("R1", "1", "~", "passive")],
                "ADJ": [("U1", "1", "ADJ", "input"), ("R1", "2", "~", "passive"), ("R2", "1", "~", "passive")],
                "GND": [("R2", "2", "~", "passive")]}
        return rule(vd.validate_feedback_stability(
            ctx_of(comps, nets, {"VOUT", "GND"}),
            [regulator("U1", ("R1", 240), ("R2", 720), reference)]), "FS-001")

    def test_lm317_240_720_gets_no_low_impedance_info(self):
        self.assertEqual(self._run("LM317", "out_adj"), [])

    def test_min_load_keyword_alone_exempts(self):
        self.assertEqual(self._run("AMS1117-ADJ"), [])

    def test_out_adj_marker_alone_exempts(self):
        self.assertEqual(self._run("LT1585-ADJ", "out_adj"), [])

    def test_generic_100_100_divider_still_gets_info(self):
        comps = [ic("U1", "AP3012"), res("R1", "100"), res("R2", "100")]
        nets = {"VOUT": [("R1", "1", "~", "passive")],
                "FB": [("U1", "3", "FB", "input"), ("R1", "2", "~", "passive"), ("R2", "1", "~", "passive")],
                "GND": [("R2", "2", "~", "passive")]}
        (f,) = rule(vd.validate_feedback_stability(ctx_of(comps, nets, {"VOUT", "GND"}),
                                                   [regulator("U1", ("R1", 100), ("R2", 100))]), "FS-001")
        self.assertEqual(f["summary"], "Regulator U1: feedback divider impedance too low (50R)")


VM_NETS_POWER = {"+5V": [("U5", "1", "VDD", "power_in")],
                 "+3V3": [("U6", "1", "VDD", "power_in"), ("U7", "1", "VIN", "power_in")],
                 "GND": [("U5", "2", "GND", "power_in"), ("U6", "2", "GND", "power_in"),
                         ("U7", "2", "GND", "power_in")]}


def vm001(ctx):
    with patch.object(vd, "get_regulator_features", return_value=None):
        return rule(vd.validate_voltage_levels(ctx), "VM-001")


class EnableEndpoints(unittest.TestCase):
    def test_en_endpoint_drops_out_and_the_other_pair_is_checked(self):
        comps = [ic("U5", "MCU5V"), ic("U6", "MCU3V3"), ic("U7", "TPS62130")]
        nets = dict(VM_NETS_POWER, SIG=[("U5", "3", "PA0", "output"), ("U6", "3", "PB0", "input"),
                                        ("U7", "3", "EN", "input")])
        (f,) = vm001(ctx_of(comps, nets, {"+5V", "+3V3", "GND"}))
        self.assertEqual(f["summary"], "Net SIG: 5.0V / 3.3V domain crossing without level shifter")
        self.assertEqual(f["components"], ["U5", "U6"])
        self.assertEqual(f["severity"], "error")

    def test_remaining_endpoints_in_one_domain_stay_silent(self):
        # A 3.3 V GPIO drives a 5 V-supplied regulator's EN and a second 3.3 V IC.
        comps = [ic("U5", "TPS62130"), ic("U6", "MCU3V3"), ic("U7", "SENSOR3V3")]
        nets = {"+5V": [("U5", "1", "VIN", "power_in")],
                "+3V3": [("U6", "1", "VDD", "power_in"), ("U7", "1", "VDD", "power_in")],
                "SIG": [("U5", "3", "EN", "input"), ("U6", "3", "PB0", "output"),
                        ("U7", "3", "INT", "input")]}
        self.assertEqual(vm001(ctx_of(comps, nets, {"+5V", "+3V3"})), [])

    def test_two_pin_enable_net_stays_silent(self):
        # 3.3 V MCU IO on a TPS61023 boost EN, the boost supplied from +5V: one endpoint remains.
        comps = [ic("U1", "ESP32-S3"), ic("U2", "TPS61023DRLR"), res("R12", "10k")]
        nets = {"+3V3": [("U1", "1", "3V3", "power_in")], "+BATT": [("U2", "3", "VIN", "power_in")],
                "+5V": [("U2", "6", "VOUT", "power_out")],
                "GND": [("U1", "2", "GND", "power_in"), ("U2", "1", "GND", "power_in"),
                        ("R12", "2", "~", "passive")],
                "EN_5V": [("U1", "3", "IO8", "bidirectional"), ("U2", "2", "EN", "input"),
                          ("R12", "1", "~", "passive")]}
        self.assertEqual(vm001(ctx_of(comps, nets, {"+3V3", "+BATT", "+5V", "GND"})), [])


class RegulatorStatusPins(unittest.TestCase):
    # A 5 V-supplied regulator's open-drain power-good output and its active-low shutdown input
    # on a 3.3 V MCU net: the pull-up sets PG's level, and nSHDN is an enable input.
    def _vm(self, reg_value, pin):
        comps = [ic("U7", reg_value), ic("U6", "MCU3V3")]
        nets = {"+5V": [("U7", "1", "VIN", "power_in")], "+3V3": [("U6", "1", "VDD", "power_in")],
                "SIG": [("U7", "3", pin, "open_collector"), ("U6", "3", "PB0", "input")]}
        return vm001(ctx_of(comps, nets, {"+5V", "+3V3"}))

    def test_power_good_pin_is_a_compatible_endpoint(self):
        for pin in ("PG", "PGOOD", "PWRGD", "nPG"):
            self.assertEqual(self._vm("TPS62130", pin), [], pin)

    def test_active_low_shutdown_pin_is_a_compatible_endpoint(self):
        self.assertEqual(self._vm("TPS62130", "nSHDN"), [])

    def test_pg_named_pin_on_a_non_regulator_is_still_checked(self):
        (f,) = self._vm("MCU5V", "PG")
        self.assertEqual(f["severity"], "error")


class MinLoadAdjustable(unittest.TestCase):
    # Minimum-load adjustable linears whose datasheet OUT-ADJ resistor is 120-240 ohm, as the
    # LM317's, so 240 || 720 = 180 ohm is intended.
    def test_min_load_adjustables_get_no_low_impedance_info(self):
        for value in ("LM1084IT-ADJ", "LM1085IS-ADJ", "LT1117CST", "LT317AT", "LM117K",
                      "LM217T", "LD1085V", "LD1086D2T"):
            self.assertEqual(FeedbackImpedance._run(self, value), [], value)


class UsbDataNets(unittest.TestCase):
    # USB D+/D- swing at most 3.6 V whatever the device supply (USB 2.0, 7.1.1), so a 5 V-
    # supplied device and a 3.3 V device on D+/D- are no domain crossing.
    def _nets(self, name):
        return dict(VM_NETS_POWER, **{name: [("U5", "3", "D+", "bidirectional"),
                                             ("U6", "3", "USB_DP", "bidirectional")]})

    def test_usb_data_net_is_not_a_domain_crossing(self):
        comps = [ic("U5", "MCU5V"), ic("U6", "MCU3V3")]
        for name in ("USB_D+", "/USB/D-", "USBDP"):
            self.assertEqual(vm001(ctx_of(comps, self._nets(name), {"+5V", "+3V3", "GND"})), [],
                             name)

    def test_non_usb_net_between_the_same_ics_is_still_an_error(self):
        comps = [ic("U5", "MCU5V"), ic("U6", "MCU3V3")]
        (f,) = vm001(ctx_of(comps, self._nets("DATA"), {"+5V", "+3V3", "GND"}))
        self.assertEqual(f["severity"], "error")


class IgnoredSupply(unittest.TestCase):
    def test_ic_with_a_supply_on_an_ignored_rail_has_no_domain(self):
        # U1 VDD on +5V (ignored) and VIO on +3V3; U2 on +1V8. Without the rule U1 would read
        # 3.3 V from VIO and 3.3 V into a 1.8 V input (2.0 V abs max) would be an error.
        comps = [ic("U1", "MCU"), ic("U2", "SENSOR")]
        nets = {"+5V": [("U1", "1", "VDD", "power_in")], "+3V3": [("U1", "2", "VIO", "power_in")],
                "+1V8": [("U2", "1", "VDD", "power_in")],
                "SIG": [("U1", "3", "IO", "bidirectional"), ("U2", "3", "IO", "bidirectional")]}
        rails = {"+5V", "+3V3", "+1V8"}
        self.assertEqual(len(vm001(ctx_of(comps, nets, rails))), 1)
        self.assertEqual(vm001(ctx_of(comps, nets, rails, {"ignore": ["+5V"]})), [])


def _regs(*pairs):
    return [{"ref": r, "output_rail": out} for r, out in pairs]


class EnableCycle(unittest.TestCase):
    def test_two_regulators_enabling_each_other_are_one_cycle(self):
        comps = [ic("U1", "REGA"), ic("U2", "REGB")]
        nets = {"RAIL_A": [("U1", "2", "VOUT", "output"), ("U2", "3", "EN", "input")],
                "RAIL_B": [("U2", "2", "VOUT", "output"), ("U1", "3", "EN", "input")]}
        got = vd.validate_power_sequencing(ctx_of(comps, nets, set()),
                                           _regs(("U1", "RAIL_A"), ("U2", "RAIL_B")))
        cycles = [f for f in rule(got, "PS-001") if f["summary"].startswith("Circular")]
        self.assertEqual([f["components"] for f in cycles], [["U1", "U2"]])

    def test_two_separate_cycles_are_two_findings(self):
        comps = [ic(r, "REG") for r in ("U1", "U2", "U3", "U4")]
        nets = {"RAIL_A": [("U1", "2", "VOUT", "output"), ("U2", "3", "EN", "input")],
                "RAIL_B": [("U2", "2", "VOUT", "output"), ("U1", "3", "EN", "input")],
                "RAIL_C": [("U3", "2", "VOUT", "output"), ("U4", "3", "EN", "input")],
                "RAIL_D": [("U4", "2", "VOUT", "output"), ("U3", "3", "EN", "input")]}
        got = vd.validate_power_sequencing(
            ctx_of(comps, nets, set()),
            _regs(("U1", "RAIL_A"), ("U2", "RAIL_B"), ("U3", "RAIL_C"), ("U4", "RAIL_D")))
        cycles = [f for f in rule(got, "PS-001") if f["summary"].startswith("Circular")]
        self.assertEqual([f["components"] for f in cycles], [["U1", "U2"], ["U3", "U4"]])


if __name__ == "__main__":
    unittest.main()
