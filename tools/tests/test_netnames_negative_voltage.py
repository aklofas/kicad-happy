import json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_core.netnames import parse_voltage_from_net_name  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402


def _ctx(components, nets, rails=()):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name="", pin_type=t) for r, p, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    return build_analysis_context(components, full, {}, known_power_rails=set(rails))


class ParseSign(unittest.TestCase):
    def test_negative_rails_keep_their_sign(self):
        for name, want in [("-5V", -5.0), ("NEG5V", -5.0), ("-12V", -12.0), ("Neg6v", -6.0),
                           ("-3V3", -3.3), ("+5V", 5.0), ("5V", 5.0), ("+3V3", 3.3)]:
            self.assertEqual(parse_voltage_from_net_name(name), want, name)

    def test_names_without_a_number_stay_none(self):
        for name in ["VNEG", "NEG", "VBAT", ""]:
            self.assertIsNone(parse_voltage_from_net_name(name), name)

    def test_voltage_inside_a_name_is_positive(self):
        self.assertEqual(parse_voltage_from_net_name("VCC_3V3"), 3.3)
        self.assertEqual(parse_voltage_from_net_name("VNEG_5V"), 5.0)


class Callers(unittest.TestCase):
    def test_opposite_polarity_rails_are_not_compatible(self):
        from schematic.net_analysis import _rails_voltage_compatible
        self.assertFalse(_rails_voltage_compatible({"+5V"}, {"-5V"}))
        self.assertTrue(_rails_voltage_compatible({"-5V"}, {"-5V_A"}))

    def test_regulator_mismatch_denominator_is_the_magnitude(self):
        from signal_detectors import detect_design_observations
        reg = {"ref": "U1", "value": "X", "estimated_vout": 3.0, "output_rail": "-5V",
               "feedback_divider": {}, "assumed_vref": 0.8, "topology": "LDO"}
        ctx = _ctx([{"reference": "U1", "type": "ic", "value": "X"}], {"-5V": [("U1", "1", "power_out")]}, {"-5V"})
        obs = detect_design_observations(ctx, {"power_regulators": [reg]})
        mm = [o["vout_net_mismatch"] for o in obs if "vout_net_mismatch" in o]
        # |3.0 - 5| / 5 = 40 %
        self.assertEqual([m["percent_diff"] for m in mm], [40.0])

    def test_regulator_magnitude_matching_a_negative_rail_is_not_a_mismatch(self):
        from signal_detectors import detect_design_observations
        reg = {"ref": "U1", "value": "X", "estimated_vout": 12.0, "output_rail": "-12V",
               "feedback_divider": {}, "assumed_vref": 1.25, "topology": "LDO"}
        ctx = _ctx([{"reference": "U1", "type": "ic", "value": "X"}], {"-12V": [("U1", "1", "power_out")]}, {"-12V"})
        obs = detect_design_observations(ctx, {"power_regulators": [reg]})
        self.assertEqual([o for o in obs if "vout_net_mismatch" in o], [])

    def test_regulator_on_a_rail_named_0v_is_no_mismatch_and_no_crash(self):
        from signal_detectors import detect_design_observations
        reg = {"ref": "U1", "value": "X", "estimated_vout": 3.3, "output_rail": "0V",
               "feedback_divider": {}, "assumed_vref": 0.8, "topology": "LDO"}
        ctx = _ctx([{"reference": "U1", "type": "ic", "value": "X"}], {"0V": [("U1", "1", "power_out")]}, {"0V"})
        obs = detect_design_observations(ctx, {"power_regulators": [reg]})
        self.assertEqual([o for o in obs if "vout_net_mismatch" in o], [])
        self.assertEqual([o["estimated_vout"] for o in obs if o.get("category") == "regulator_voltage"], [3.3])

    def test_sleep_current_uses_the_rail_magnitude(self):
        from schematic.system_analyses import analyze_sleep_current
        ctx = _ctx([{"reference": "R1", "type": "resistor", "value": "10k"}],
                   {"-5V": [("R1", "1", "passive")], "GND": [("R1", "2", "passive")]}, {"-5V"})
        out = analyze_sleep_current(ctx, {})
        # 5 V / 10 kOhm = 500 uA
        self.assertEqual(out["rails"]["-5V"]["total_uA"], 500.0)

    def test_level_shifter_voltage_is_the_magnitude(self):
        from domain_detectors import _infer_voltage
        self.assertEqual(_infer_voltage(None, "-5V"), 5.0)
        self.assertEqual(_infer_voltage(None, "+3V3"), 3.3)

    def test_ic_rail_estimate_is_the_magnitude(self):
        from validation_detectors import _estimate_rail_voltage_for_ic
        ctx = _ctx([{"reference": "U1", "type": "ic", "value": "OPA"}],
                   {"-5V": [("U1", "4", "power_in")]}, {"-5V"})
        self.assertEqual(_estimate_rail_voltage_for_ic(ctx, "U1"), 5.0)

    def test_i2c_device_on_a_negative_supply_is_not_a_logic_level_mismatch(self):
        from schematic.system_analyses import analyze_protocol_compliance
        pu = {"ref": "R1", "value": "4.7k", "ohms": 4700.0, "to_rail": "+5V"}
        bus = lambda line, net: {"line": line, "net": net, "devices": ["U1"], "pull_ups": [dict(pu)]}
        design = {"bus_analysis": {"i2c": [bus("SDA", "SDA"), bus("SCL", "SCL")]},
                  "power_domains": {"ic_power_rails": {"U1": {"power_rails": ["+5V", "-5V"]}}}}
        out = analyze_protocol_compliance([], {}, design, {}, {})
        text = json.dumps(out)
        self.assertNotIn("voltage mismatch", text)

    def test_led_current_uses_the_rail_magnitude(self):
        from domain_detectors import audit_led_circuits
        comps = [{"reference": "D1", "type": "led", "value": "LED_RED"},
                 {"reference": "R1", "type": "resistor", "value": "1k"}]
        ctx = _ctx(comps, {"-5V": [("R1", "1", "passive")],
                           "N1": [("R1", "2", "passive"), ("D1", "2", "passive")],
                           "GND": [("D1", "1", "passive")]}, {"-5V"})
        out = audit_led_circuits(ctx, [])
        cur = [f.get("estimated_current_mA") for f in out if f.get("estimated_current_mA") is not None]
        # (5 V - 2.0 V red Vf) / 1 kOhm = 3.0 mA
        self.assertEqual(cur, [3.0])

    def test_led_on_a_negative_rail_has_no_forward_bias_floor_finding(self):
        from domain_detectors import audit_led_circuits
        comps = [{"reference": "D1", "type": "led", "value": "LED_RED"},
                 {"reference": "R1", "type": "resistor", "value": "1k"}]
        ctx = _ctx(comps, {"-5V": [("R1", "1", "passive")],
                           "N1": [("R1", "2", "passive"), ("D1", "2", "passive")],
                           "GND": [("D1", "1", "passive")]}, {"-5V"})
        out = audit_led_circuits(ctx, [])
        self.assertNotIn("LA-004", [f.get("rule_id") for f in out])

    def test_supervisor_threshold_compares_against_the_magnitude(self):
        from domain_detectors import build_power_sequencing_graph
        ctx = _ctx([{"reference": "U2", "type": "ic", "value": "SUP"}],
                   {"-5V": [("U2", "1", "power_in")]}, {"-5V"})
        sup = {"ref": "U2", "type": "voltage_supervisor", "monitored_rail": "-5V",
               "threshold_voltage": 4.5}
        out = build_power_sequencing_graph(ctx, [], [], [sup])
        self.assertEqual([i for i in out.get("issues", []) if i["type"] == "supervisor_threshold_above_nominal"], [])


if __name__ == "__main__":
    unittest.main()
