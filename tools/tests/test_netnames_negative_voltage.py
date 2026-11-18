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
                           ("-3V3", -3.3), ("+5V", 5.0), ("5V", 5.0), ("+3V3", 3.3),
                           ("(-)5V", -5.0), ("/Analog/(-)12V", -12.0)]:
            self.assertEqual(parse_voltage_from_net_name(name), want, name)

    def test_names_without_a_number_stay_none(self):
        for name in ["VNEG", "NEG", "VBAT", ""]:
            self.assertIsNone(parse_voltage_from_net_name(name), name)

    def test_voltage_inside_a_name_is_positive(self):
        self.assertEqual(parse_voltage_from_net_name("VCC_3V3"), 3.3)
        self.assertEqual(parse_voltage_from_net_name("VNEG_5V"), 5.0)


class SeparatorsDecimalsAndPinNames(unittest.TestCase):
    def test_separator_names_stay_positive(self):
        for name, want in [("USB-5V", 5.0), ("FTDI-3.3V", 3.3), ("CAMERA-2V8", 2.8), ("EURO-5V_F", 5.0),
                           ("DI-1-DSP-3.3V", 3.3), ("TPS-VOUT-3.3V", 3.3)]:
            self.assertEqual(parse_voltage_from_net_name(name), want, name)

    def test_comma_and_p_notation(self):
        for name, want in [("3,3V", 3.3), ("2,75V", 2.75), ("+3,3V-FAILURE", 3.3), ("AVDD1P2V", 1.2),
                           ("V1P8", 1.8), ("P1P8V_VCC", 1.8), ("VDD3P3", 3.3), ("PMU_RSTB_1P8V", 1.8),
                           ("VDDAR_0P85_CORE", 0.85), ("PWR_3,3-5V", 5.0)]:
            self.assertEqual(parse_voltage_from_net_name(name), want, name)
        for name in ["R39P1", "J1P2", "USB3P0", "A1P8"]:
            self.assertIsNone(parse_voltage_from_net_name(name), name)

    def test_names_read_before_keep_their_values(self):
        for name, want in [("+3V3", 3.3), ("-5V", -5.0), ("NEG12V", -12.0), ("(-)5V", -5.0),
                           ("VCC_3V3", 3.3)]:
            self.assertEqual(parse_voltage_from_net_name(name), want, name)

    def test_sign_after_space_or_underscore(self):
        self.assertEqual(parse_voltage_from_net_name("GENERATED -5V"), -5.0)
        self.assertEqual(parse_voltage_from_net_name("VEE_-12V"), -12.0)
        self.assertEqual(parse_voltage_from_net_name("/psu/VEE_-1V8"), -1.8)

    def test_valve_pin_net_is_no_rail(self):
        # a valve circuit names the net on pin 3 of V2 "V2P3": not a 2.3 V rail
        comps = [_part("V2", "other", "ECC83", "Valve:ECC83", [("3", "A")]),
                 _part("U1", "ic", "X", "X:X", [("5", "VDD")])]
        nets = {"V2P3": [("V2", "3", "passive")], "V1P8": [("U1", "5", "power_in")]}
        ctx = _ctx(comps, nets, {"V2P3", "V1P8"})
        rails = _rails(ctx, [])
        self.assertNotIn("V2P3", rails)
        self.assertEqual(rails["V1P8"], 1.8)
        self.assertIsNone(ctx.rail_voltage_or("V2P3", parse_voltage_from_net_name))
        self.assertEqual(ctx.rail_voltage_or("V1P8", parse_voltage_from_net_name), 1.8)
        stats = _stats_rails(comps, ctx.nets)
        self.assertIsNone(stats["V2P3"])
        self.assertEqual(stats["V1P8"], 1.8)

    def test_connector_and_ic_pin_nets_read_no_voltage(self):
        for name in ["Net-(J2-P3)", "U1P2", "J2P3"]:
            self.assertIsNone(parse_voltage_from_net_name(name), name)
        # a connector P2 names the net on its pin 3 "P2P3"
        comps = [_part("P2", "connector", "Conn_01x04", "Connector:Conn_01x04", [("2", "Pin_2"), ("3", "Pin_3")])]
        ctx = _ctx(comps, {"P2P3": [("P2", "3", "passive")], "U1P2": [("P2", "2", "passive")]},
                   {"P2P3", "U1P2"})
        rails = _rails(ctx, [])
        self.assertNotIn("P2P3", rails)
        self.assertNotIn("U1P2", rails)
        self.assertIsNone(ctx.rail_voltage_or("P2P3", parse_voltage_from_net_name))


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


def _pin(ref, num, name, pin_type):
    return dict(component=ref, pin_number=num, pin_name=name, pin_type=pin_type)


def _part(ref, typ, value, lib_id, pin_names):
    return {"reference": ref, "type": typ, "value": value, "lib_id": lib_id, "footprint": "",
            "properties": {}, "mpn": "", "dnp": False, "in_bom": True,
            "pins": [{"number": n, "name": nm} for n, nm in pin_names]}


def _split_supply(twin=True, divider=True):
    """An inverting charge pump (LM27761) from 5V5 onto 4V5_N, set by a feedback divider,
    beside a 4V5_P rail (the split supply's positive half) when *twin*."""
    comps = [_part("U1", "ic", "LM27761", "power-azonenberg:LM27761",
                   [("1", "VIN"), ("2", "GND"), ("3", "CPOUT"), ("4", "VOUT"), ("5", "VFB"),
                    ("6", "EN"), ("7", "C1-"), ("8", "C1+")]),
             _part("R1", "resistor", "255K", "device:R", [("1", "~"), ("2", "~")]),
             _part("R2", "resistor", "95.3K", "device:R", [("1", "~"), ("2", "~")]),
             _part("C5", "capacitor", "4.7u", "device:C", [("1", "~"), ("2", "~")]),
             _part("C6", "capacitor", "4.7u", "device:C", [("1", "~"), ("2", "~")])]
    nets = {
        "GND": [_pin("U1", "2", "GND", "power_in"), _pin("C5", "2", "~", "passive"),
                _pin("C6", "2", "~", "passive")],
        "5V5": [_pin("U1", "1", "VIN", "power_in"), _pin("U1", "6", "EN", "input")],
        "CP": [_pin("U1", "3", "CPOUT", "power_out")],
        "4V5_N": [_pin("U1", "4", "VOUT", "power_out"), _pin("C5", "1", "~", "passive")],
        "4V5_N_FB": [_pin("U1", "5", "VFB", "input")],
    }
    if divider:
        nets["4V5_N"].append(_pin("R1", "1", "~", "passive"))
        nets["4V5_N_FB"] += [_pin("R1", "2", "~", "passive"), _pin("R2", "1", "~", "passive")]
        nets["GND"].append(_pin("R2", "2", "~", "passive"))
    rails = {"GND", "5V5", "4V5_N"}
    if twin:
        nets["4V5_P"] = [_pin("C6", "1", "~", "passive")]
        rails.add("4V5_P")
    full = {n: {"name": n, "pins": ps, "point_count": 0, "no_connect": False,
                "has_pwr_flag": False, "labels": []} for n, ps in nets.items()}
    return comps, full, build_analysis_context(comps, full, {}, known_power_rails=rails)


def _regulators(ctx):
    from signal_detectors import detect_power_regulators, detect_voltage_dividers
    regs = detect_power_regulators(ctx, detect_voltage_dividers(ctx)["voltage_dividers"])
    return [r for r in regs if r["ref"] == "U1"]


def _rails(ctx, regs):
    from schematic.pipeline import build_rail_map, public_rail_voltages
    return public_rail_voltages(ctx, regs, build_rail_map(ctx, regs))


def _stats_rails(comps, nets):
    from schematic.bom_stats import compute_statistics
    stats = compute_statistics(comps, nets, [], [], [])
    return {r["name"]: r["voltage"] for r in stats["power_rails"]}


class SplitSupplyNegativeHalf(unittest.TestCase):
    def test_only_an_n_leaf_with_its_p_twin_is_the_negative_half(self):
        from kicad_core.netnames import negative_split_rails
        self.assertEqual(negative_split_rails(["4V5_N", "/psu/4V5_P", "GND"]), {"4V5_N"})
        self.assertEqual(negative_split_rails(["/afe/+5V0_N", "5V0_P"]), {"/afe/+5V0_N"})
        self.assertEqual(negative_split_rails(["4V5_P", "1V5_N", "7V0_N_1", "7V0_P", "V5N", "V5P"]),
                         {"7V0_N_1"})

    def test_split_rail_twins(self):
        from kicad_core.netnames import split_rail_voltages
        for names, want in [
                (["7V0_N_1", "7V0_N_2", "7V0_P", "7V0_P_1"], {"7V0_N_1": -7.0, "7V0_N_2": -7.0}),
                (["12V0_N_UNFUSED", "12V0_P"], {"12V0_N_UNFUSED": -12.0}),
                (["/afe/5V0_N", "5V0"], {"/afe/5V0_N": -5.0}),
                (["3V3N", "3V3P"], {"3V3N": -3.3}),
                (["V12N", "V12P"], {"V12N": -12.0, "V12P": 12.0}),
                (["F-15V", "F+15V"], {"F-15V": -15.0}),
                (["A-5V", "/psu/A+5V"], {"A-5V": -5.0})]:
            self.assertEqual(split_rail_voltages(names), want, names)

    def test_names_without_their_twin_are_not_split_rails(self):
        from kicad_core.netnames import split_rail_voltages
        for names in [["230V_N", "230V_L", "230V_PE"], ["1V5_N"], ["SNS5V0_N", "SNS5V0_P"],
                      ["PTT_3V3_N", "PTT_3V3"], ["1VN", "1V"], ["V1N", "V1P"], ["USB-5V"],
                      ["D-1", "D+1"], ["GND-5V", "GND+5V"], ["VSS-5V", "VSS+5V"],
                      # also a DC jack's return beside its supply pin
                      ["5V_NEG", "5V_POS"]]:
            self.assertEqual(split_rail_voltages(names), {}, names)

    def test_a_named_pair_keeps_both_halves(self):
        # over-reach: the 4V5_P / 4V5_N pair read before keeps -4.5 / +4.5
        from kicad_core.netnames import split_rail_voltages
        self.assertEqual(split_rail_voltages(["4V5_N", "4V5_P"]), {"4V5_N": -4.5})
        _, _, ctx = _split_supply()
        rails = _rails(ctx, [])
        self.assertEqual((rails["4V5_N"], rails["4V5_P"]), (-4.5, 4.5))

    def test_twins_in_rail_voltages_and_statistics(self):
        names = ["7V0_N_1", "7V0_P", "5V_NEG", "5V_POS", "V12N", "V12P", "A-5V", "A+5V", "230V_N", "230V_L"]
        comps = [_part("C1", "capacitor", "1u", "device:C", [("1", "~"), ("2", "~")])]
        comps += [_part(f"#PWR0{i}", "power_symbol", n, f"power:{n}", [("1", n)]) for i, n in enumerate(names)]
        nets = {n: {"name": n, "pins": [_pin("C1", "1", "~", "passive")], "point_count": 0,
                    "no_connect": False, "has_pwr_flag": False, "labels": []} for n in names}
        ctx = build_analysis_context(comps, nets, {}, known_power_rails=set(names))
        # 5V_NEG beside 5V_POS keeps the reading of its name
        want = {"7V0_N_1": -7.0, "7V0_P": 7.0, "5V_NEG": 5.0, "5V_POS": 5.0, "V12N": -12.0, "V12P": 12.0,
                "A-5V": -5.0, "A+5V": 5.0, "230V_N": 230.0, "230V_L": 230.0}
        rails = _rails(ctx, [])
        self.assertEqual({n: rails.get(n) for n in names}, want)
        stats = _stats_rails(comps, nets)
        self.assertEqual({n: stats.get(n) for n in names}, want)

    def test_regulator_on_the_negative_half_is_inverting_with_no_ldo_drop(self):
        _, _, ctx = _split_supply()
        [reg] = _regulators(ctx)
        self.assertTrue(reg.get("inverting"))
        self.assertLess(reg["estimated_vout"], 0)
        self.assertNotIn("power_dissipation", reg)

    def test_negative_half_reads_negative_in_rail_voltages_and_statistics(self):
        comps, nets, ctx = _split_supply()
        rails = _rails(ctx, _regulators(ctx))
        self.assertLess(rails["4V5_N"], 0)
        self.assertEqual(rails["4V5_P"], 4.5)
        stats = _stats_rails(comps, nets)
        self.assertEqual(stats["4V5_N"], -4.5)
        self.assertEqual(stats["4V5_P"], 4.5)

    def test_name_pass_reads_the_negative_half_without_a_regulator(self):
        _, _, ctx = _split_supply()
        self.assertEqual(_rails(ctx, [])["4V5_N"], -4.5)

    def test_inverting_regulator_without_an_estimate_gets_the_negative_name_voltage(self):
        _, _, ctx = _split_supply(divider=False)
        regs = _regulators(ctx)
        self.assertEqual([(r.get("inverting"), r.get("estimated_vout")) for r in regs], [(True, None)])
        self.assertEqual(_rails(ctx, regs)["4V5_N"], -4.5)

    def test_n_leaf_without_its_twin_stays_positive(self):
        comps, nets, ctx = _split_supply(twin=False)
        [reg] = _regulators(ctx)
        self.assertNotIn("inverting", reg)
        self.assertGreater(reg["estimated_vout"], 0)
        self.assertEqual(_stats_rails(comps, nets)["4V5_N"], 4.5)
        alone = {"1V5_N": [], "GND": []}
        full = {n: {"name": n, "pins": ps, "point_count": 0, "no_connect": False,
                    "has_pwr_flag": False, "labels": []} for n, ps in alone.items()}
        ctx = build_analysis_context([], full, {}, known_power_rails={"1V5_N", "GND"})
        self.assertEqual(_rails(ctx, [])["1V5_N"], 1.5)
        self.assertEqual(_stats_rails([], full)["1V5_N"], 1.5)


if __name__ == "__main__":
    unittest.main()
