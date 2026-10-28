# tools/tests/test_regulator_phases.py
"""Pins detect_power_regulators behaviour across its screen/build phases and post-loop passes."""
import copy, hashlib, json, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.parts import lookup_regulator_vref  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from schematic.pipeline import build_rail_map  # noqa: E402
from signal_detectors import detect_power_regulators  # noqa: E402
from what_if import _scan_fixable  # noqa: E402

EXAMPLE_EXTRACTION = SCRIPTS.parents[1] / "datasheets" / "examples" / "lm2596-adj.json"

_TYPES = {"U": "ic", "L": "inductor", "R": "resistor", "RV": "resistor", "C": "capacitor", "D": "diode"}


def _ctx(parts, mpn=None, cache_dir=None):
    """Build a context from ``(ref, lib_id, value, {pin_num: (pin_name, net)})`` tuples."""
    components, nets = [], {}
    for ref, lib_id, value, pins in parts:
        components.append({
            "reference": ref, "lib_id": lib_id, "value": value,
            "type": _TYPES[ref.rstrip("0123456789")],
            "pins": [{"number": n, "name": name} for n, (name, _) in pins.items()],
        })
        if mpn and ref.startswith("U"):
            components[-1]["mpn"] = mpn
        for num, (name, net) in pins.items():
            nets.setdefault(net, {"pins": []})["pins"].append(
                {"component": ref, "pin_number": num, "pin_name": name})
    return build_analysis_context(components, nets, {}, cache_dir=cache_dir)


def _fb_divider(top, r_top, r_bottom, mid="FB", refs=("R1", "R2")):
    return {"r_top": {"ref": refs[0], "ohms": r_top, "value": str(r_top)},
            "r_bottom": {"ref": refs[1], "ohms": r_bottom, "value": str(r_bottom)},
            "top_net": top, "mid_net": mid, "bottom_net": "GND",
            "ratio": r_bottom / (r_top + r_bottom)}


def _adj_ldo(value, out, lib_id="Custom:Adjustable"):
    return ("U1", lib_id, value,
            {"1": ("VIN", "+12V"), "2": ("VOUT", out), "3": ("FB", "FB"), "4": ("GND", "GND")})


def _extraction_cache(root, mpn, vref, with_pdf):
    """A v1.4 extraction cache for *mpn* whose feedback reference is *vref*; untrusted without its PDF."""
    data = json.loads(EXAMPLE_EXTRACTION.read_text(encoding="utf-8"))
    data["source"]["mpn"] = mpn
    data["source"]["local_path"] = mpn + ".pdf"
    data["regulator"]["reference_voltage"][0].update(typ=vref, min=None, max=None)
    pdf = b"%PDF-1.4 test"
    data["source"]["sha256"] = "sha256:" + hashlib.sha256(pdf).hexdigest()
    cache = Path(root) / "datasheets" / "extracted"
    cache.mkdir(parents=True)
    (cache / (mpn + ".json")).write_text(json.dumps(data), encoding="utf-8")
    if with_pdf:
        (cache.parent / (mpn + ".pdf")).write_bytes(pdf)
    return cache


def _divider(top, mid, bottom):
    return {"r_top": {"ref": "R1", "ohms": 10000.0, "value": "10k"},
            "r_bottom": {"ref": "R2", "ohms": 10000.0, "value": "10k"},
            "top_net": top, "mid_net": mid, "bottom_net": bottom, "ratio": 0.5}


def _three_terminal(value, out, vin="VIN_RAW"):
    """An LM317-style adjustable: ADJ, VO, VI and no ground pin."""
    return ("U1", "Regulator_Linear:" + value, value,
            {"1": ("ADJ", "ADJ"), "2": ("VO", out), "3": ("VI", vin)})


_BUCK_PINS = {"1": ("SW", "SW_NODE"), "2": ("FB", "FB"), "3": ("VIN", "+12V")}
_INDUCTOR = ("L1", "Device:L", "10uH", {"1": ("1", "SW_NODE")})


class RegulatorPhases(unittest.TestCase):
    def test_keyword_pmic_without_pins_yields_keyword_only_record(self):
        ctx = _ctx([("U1", "Regulator_Linear:AMS1117-3.3", "LDO PMIC", {})])
        regs = detect_power_regulators(ctx, [])
        self.assertEqual([r["ref"] for r in regs], ["U1"])
        self.assertEqual(regs[0]["detector"], "detect_power_regulators")
        self.assertEqual(regs[0]["rule_id"], "PR-DET")
        self.assertEqual(regs[0]["topology"], "unknown")
        self.assertNotIn("vref_source", regs[0])

    def test_fixed_suffix_ldo_estimates_vout_and_ldo_topology(self):
        ctx = _ctx([("U2", "Regulator_Linear:AMS1117-3.3", "AMS1117-3.3",
                     {"1": ("GND", "GND"), "2": ("VOUT", "+3V3"), "3": ("VIN", "+5V")})])
        r = detect_power_regulators(ctx, [])[0]
        self.assertEqual(r["topology"], "LDO")
        self.assertEqual(r["estimated_vout"], 3.3)
        self.assertEqual(r["vref_source"], "fixed_suffix")
        self.assertEqual(r["input_rail"], "+5V")
        self.assertEqual(r["output_rail"], "+3V3")

    def test_inverting_regulator_negates_vout_and_fb_at_top_cross_reference(self):
        ctx = _ctx([("U3", "Regulator_Switching:LT3581", "LT3581", _BUCK_PINS), _INDUCTOR])
        r = detect_power_regulators(ctx, [_divider("FB", "X", "GND")])[0]
        self.assertEqual(r["topology"], "switching")
        self.assertEqual(r["inductor"], "L1")
        self.assertEqual(r["feedback_divider"]["topology"], "fb_at_top")
        self.assertEqual(r["output_rail"], "FB")

        ctx = _ctx([("U3", "Regulator_Switching:LT3581", "LT3581 inverting", _BUCK_PINS), _INDUCTOR])
        r = detect_power_regulators(ctx, [_divider("OUT", "FB", "GND")])[0]
        self.assertTrue(r["inverting"])
        self.assertLess(r["estimated_vout"], 0)

    def test_uuid_sheet_path_does_not_make_an_output_inverting(self):
        # TPS54040 Vref 0.8 V: 0.8 x (31.6k + 10k) / 10k = 3.328 V
        out = "/1b2c3d4e-5f60-4a1b-9c2d-3e4f5a6b7c8d/+3V3"
        r = detect_power_regulators(_ctx([_adj_ldo("TPS54040", out)]), [_fb_divider(out, 31600.0, 10000.0)])[0]
        self.assertNotIn("inverting", r)
        self.assertEqual(r["estimated_vout"], 3.328)

    def test_output_named_v_minus_is_inverting(self):
        ctx = _ctx([("U1", "Regulator_SwitchedCapacitor:TC7660", "TC7660",
                     {"1": ("V+", "+5V"), "2": ("CAP+", "CP"), "3": ("GND", "GND"),
                      "4": ("CAP-", "CN"), "5": ("VOUT", "V-")})])
        r = detect_power_regulators(ctx, [])[0]
        self.assertTrue(r.get("inverting"))

    def test_table_vref_for_tps82085(self):
        # SLVSCN4D eq. 3: VOUT = 0.8 V x (1 + R1/R2) = 0.8 x 673/162 = 3.323 V
        r = detect_power_regulators(_ctx([_adj_ldo("TPS82085SILR", "3V3")]),
                                    [_fb_divider("3V3", 511000.0, 162000.0)])[0]
        self.assertEqual(r["estimated_vout"], 3.323)
        self.assertEqual(r["vref_source"], "lookup")
        self.assertEqual(r["_estimated_vout_provenance"]["source"], "divider_plus_lookup")

    def test_unknown_part_vref_chosen_by_rail_name(self):
        # 0.6 V would give 2.493 V; 0.8 V gives 3.323 V, within 10 % of the 3V3 name
        r = detect_power_regulators(_ctx([_adj_ldo("MYBUCK", "3V3")]),
                                    [_fb_divider("3V3", 511000.0, 162000.0)])[0]
        self.assertEqual(r["estimated_vout"], 3.323)
        self.assertEqual(r["assumed_vref"], 0.8)
        self.assertEqual(r["vref_source"], "heuristic")
        self.assertEqual(r["_estimated_vout_provenance"],
                         {"source": "divider_plus_rail_name", "confidence": "heuristic"})

    def test_unknown_part_without_rail_voltage_keeps_first_fit(self):
        r = detect_power_regulators(_ctx([_adj_ldo("MYBUCK", "VOUT")]),
                                    [_fb_divider("VOUT", 511000.0, 162000.0)])[0]
        self.assertEqual(r["assumed_vref"], 0.6)
        self.assertEqual(r["estimated_vout"], 2.493)
        self.assertEqual(r["_estimated_vout_provenance"]["source"], "divider_plus_heuristic")

    def test_mpn_gives_vref(self):
        # TPS54040 Vref 0.8 V, equal divider: 1.6 V
        r = detect_power_regulators(_ctx([_adj_ldo("BUCK", "VOUT_ADJ")], mpn="TPS54040"),
                                    [_fb_divider("VOUT_ADJ", 10000.0, 10000.0)])[0]
        self.assertEqual(r["estimated_vout"], 1.6)
        self.assertEqual(r["vref_source"], "lookup")

    def test_table_vref_beats_a_disagreeing_rail_name(self):
        # A divider that does not make the named voltage is the design's problem, not the Vref's.
        r = detect_power_regulators(_ctx([_adj_ldo("BUCK", "+3V3")], mpn="TPS54040"),
                                    [_fb_divider("+3V3", 10000.0, 10000.0)])[0]
        self.assertEqual(r["estimated_vout"], 1.6)
        self.assertEqual(r["assumed_vref"], 0.8)

    def test_trusted_extraction_vref_wins_over_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = _extraction_cache(tmp, "TPS54040", 0.765, with_pdf=True)
            r = detect_power_regulators(_ctx([_adj_ldo("BUCK", "VOUT_ADJ")], mpn="TPS54040", cache_dir=cache),
                                        [_fb_divider("VOUT_ADJ", 10000.0, 10000.0)])[0]
        self.assertEqual(r["estimated_vout"], 1.53)
        self.assertEqual(r["vref_source"], "datasheet")
        self.assertEqual(r["_estimated_vout_provenance"],
                         {"source": "divider_plus_datasheet", "confidence": "deterministic"})

    def test_untrusted_extraction_falls_back_to_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = _extraction_cache(tmp, "TPS54040", 0.765, with_pdf=False)
            r = detect_power_regulators(_ctx([_adj_ldo("BUCK", "VOUT_ADJ")], mpn="TPS54040", cache_dir=cache),
                                        [_fb_divider("VOUT_ADJ", 10000.0, 10000.0)])[0]
        self.assertEqual(r["estimated_vout"], 1.6)
        self.assertEqual(r["vref_source"], "lookup")

    def test_fixed_output_from_mpn(self):
        ctx = _ctx([("U1", "Custom:LDO", "AP7313",
                     {"1": ("VIN", "+5V"), "2": ("VOUT", "+3V3"), "3": ("GND", "GND")})], mpn="AP7313-33SAG-7")
        r = detect_power_regulators(ctx, [])[0]
        self.assertEqual(r["estimated_vout"], 3.3)
        self.assertEqual(r["vref_source"], "fixed_suffix")

    def test_lookup_table_entries(self):
        self.assertEqual(lookup_regulator_vref("TPS63020DSJR", ""), (0.5, "lookup"))
        self.assertEqual(lookup_regulator_vref("TPS82084SILR", ""), (0.8, "lookup"))
        # value keeps precedence over the MPN
        self.assertEqual(lookup_regulator_vref("TPS54040", "", "AP7313-33SAG-7"), (0.8, "lookup"))

    def test_regulator_output_takes_its_sheet_voltage_without_an_estimate(self):
        # TPS630701 with FB strapped to VOUT: no divider, no estimate; the sheet is "5V_regulator".
        ctx = _ctx([("U1", "Custom:TPS630701", "TPS630701RNMR",
                     {"1": ("VIN", "/5V_regulator/VIN_PROT"), "2": ("VOUT", "/5V_regulator/VOUT_SEN"),
                      "3": ("L1", "/5V_regulator/L1"), "4": ("L2", "/5V_regulator/L2"), "5": ("GND", "GND")}),
                    ("U2", "Custom:TPS630701", "TPS630701RNMR",
                     {"1": ("VIN", "/5V_regulator#2/VIN_PROT"), "2": ("VOUT", "/3V3_sheet/+5V"),
                      "5": ("GND", "GND")})])
        regs = [{"ref": "U1", "input_rail": "/5V_regulator/VIN_PROT", "output_rail": "/5V_regulator/VOUT_SEN"},
                {"ref": "U2", "input_rail": "/5V_regulator#2/VIN_PROT", "output_rail": "/3V3_sheet/+5V"},
                {"ref": "U3", "input_rail": "/5V_regulator#3/VOUT", "output_rail": "/5V_regulator#3/VOUT"},
                {"ref": "U4", "topology": "switching", "sw_net": "/3v3_buck/SW", "output_rail": "/3v3_buck/L"},
                # an MCU read as a regulator whose "output" is the buck's switch node, and a core-voltage pin
                {"ref": "U5", "topology": "ic_with_internal_regulator", "output_rail": "/3v3_buck/SW"},
                {"ref": "U6", "topology": "ic_with_internal_regulator", "output_rail": "/3v3_mcu/VCAP"}]
        by_net = build_rail_map(ctx, regs)
        self.assertEqual(by_net.get("/5V_regulator/VOUT_SEN"), 5.0)
        self.assertNotIn("/5V_regulator/VIN_PROT", by_net)
        self.assertNotIn("/5V_regulator/L1", by_net)
        self.assertEqual(by_net.get("/3V3_sheet/+5V"), 5.0)       # the rail's own name wins
        self.assertNotIn("/5V_regulator#3/VOUT", by_net)          # an input is never an output
        self.assertNotIn("/3v3_buck/SW", by_net)
        self.assertNotIn("/3v3_mcu/VCAP", by_net)
        self.assertEqual(by_net.get("/3v3_buck/L"), 3.3)
        self.assertEqual(regs[0]["_output_rail_voltage_provenance"], {"source": "sheet name", "voltage": 5.0})
        self.assertNotIn("_output_rail_voltage_provenance", regs[1])

    def test_boost_output_is_the_divider_top_not_the_input(self):
        # MT3608: L1 from +5V to SW, D1 SW -> +12V, 19k/1k feedback; Vref 0.6 V: 0.6 x 20 = 12.0 V
        ctx = _ctx([("U1", "Regulator_Switching:MT3608", "MT3608",
                     {"1": ("SW", "SW"), "2": ("GND", "GND"), "3": ("FB", "FB"),
                      "4": ("EN", "+5V"), "5": ("IN", "+5V")}),
                    ("L1", "Device:L", "22uH", {"1": ("1", "+5V"), "2": ("2", "SW")}),
                    ("D1", "Device:D_Schottky", "SS34", {"1": ("K", "+12V"), "2": ("A", "SW")})])
        regs = detect_power_regulators(ctx, [_fb_divider("+12V", 19000.0, 1000.0)])
        r = regs[0]
        self.assertEqual(r["input_rail"], "+5V")
        self.assertEqual(r["output_rail"], "+12V")
        self.assertEqual(r["estimated_vout"], 12.0)
        by_net = build_rail_map(ctx, regs)
        self.assertEqual(by_net.get("+5V"), 5.0)
        self.assertEqual(by_net.get("+12V"), 12.0)

    def test_inverting_stage_with_inductor_on_the_input_has_no_output_rail(self):
        # LT1617: L1 from +5V to SW, the negative output sits behind a coupling cap; NFB is not an FB pin
        ctx = _ctx([("U1", "Regulator_Switching:LT1617", "LT1617",
                     {"1": ("SW", "SW"), "2": ("GND", "GND"), "3": ("NFB", "NFB"),
                      "4": ("~{SHDN}", "+5V"), "5": ("VIN", "+5V")}),
                    ("L1", "Device:L", "10uH", {"1": ("1", "+5V"), "2": ("2", "SW")})])
        r = detect_power_regulators(ctx, [])[0]
        self.assertEqual(r["input_rail"], "+5V")
        self.assertFalse(r.get("output_rail"))

    def test_led_boost_sense_node_is_not_an_output_rail(self):
        # CAT4139: L1 from +5V to SW; FB is the LED string's current-sense node (FB-at-top divider)
        ctx = _ctx([("U1", "Driver_LED:CAT4139", "CAT4139",
                     {"1": ("SW", "SW"), "2": ("GND", "GND"), "3": ("FB", "FB"),
                      "4": ("SHDN", "+5V"), "5": ("VIN", "+5V")}),
                    ("L1", "Device:L", "22uH", {"1": ("1", "+5V"), "2": ("2", "SW")})])
        r = detect_power_regulators(ctx, [_divider("FB", "X", "GND")])[0]
        self.assertEqual(r["feedback_divider"]["topology"], "fb_at_top")
        self.assertFalse(r.get("output_rail"))
        self.assertNotIn("_far_side_is_input", r)

    def test_three_terminal_adjustable_uses_the_out_adj_resistor(self):
        # LM317 datasheet: Vout = 1.25 V x (1 + R2/R1), R1 between OUT and ADJ
        r = detect_power_regulators(_ctx([_three_terminal("LM317", "+15V")]),
                                    [_fb_divider("+15V", 249.0, 2730.0, mid="ADJ")])[0]
        self.assertEqual(r["estimated_vout"], 14.955)        # 1.25 x 2979 / 249
        self.assertEqual(r["feedback_divider"]["reference"], "out_adj")
        r = detect_power_regulators(_ctx([_three_terminal("LM337", "-12V")]),
                                    [_fb_divider("-12V", 124.0, 1070.0, mid="ADJ")])[0]
        self.assertEqual(r["estimated_vout"], -12.036)       # -1.25 x 1194 / 124
        r = detect_power_regulators(_ctx([_three_terminal("LM317L", "+3V3_ISO")]),
                                    [_fb_divider("+3V3_ISO", 240.0, 390.0, mid="ADJ")])[0]
        self.assertEqual(r["estimated_vout"], 3.281)         # 1.25 x 630 / 240

    def test_three_terminal_adjustable_with_a_potentiometer_has_no_estimate(self):
        r = detect_power_regulators(_ctx([_three_terminal("LM317", "+12V")]),
                                    [_fb_divider("+12V", 560.0, 10000.0, mid="ADJ", refs=("R2", "RV1"))])[0]
        self.assertNotIn("estimated_vout", r)
        self.assertEqual(r["output_rail"], "+12V")
        ctx = _ctx([_three_terminal("LM317", "+12V"),
                    ("R5", "Device:R_Potentiometer_Trim", "10k", {"1": ("1", "ADJ"), "2": ("2", "GND")})])
        r = detect_power_regulators(ctx, [_fb_divider("+12V", 560.0, 10000.0, mid="ADJ", refs=("R2", "R5"))])[0]
        self.assertNotIn("estimated_vout", r)
        self.assertEqual(build_rail_map(ctx, [r]).get("+12V"), 12.0)

    def test_adj_pin_with_a_ground_pin_keeps_the_feedback_formula(self):
        # MIC29302: ADJ is a ground-referenced feedback input, Vout = 1.24 V x (1 + R1/R2)
        ctx = _ctx([("U1", "Regulator_Linear:MIC29302", "MIC29302",
                     {"1": ("EN", "+5V"), "2": ("IN", "+5V"), "3": ("GND", "GND"),
                      "4": ("OUT", "+3V3"), "5": ("ADJ", "ADJ")})])
        r = detect_power_regulators(ctx, [_fb_divider("+3V3", 16900.0, 10000.0, mid="ADJ")])[0]
        self.assertEqual(r["estimated_vout"], 3.336)         # 1.24 x 26.9 / 10
        self.assertNotIn("reference", r["feedback_divider"])

    def test_what_if_targets_the_out_adj_ratio(self):
        # 1.25 V x (Rtop + Rbot) / Rtop = 15 V  =>  Rbot / (Rtop + Rbot) = 1 - 1.25 / 15
        vd = _fb_divider("+15V", 249.0, 2500.0, mid="ADJ")
        reg = {"ref": "U1", "output_rail": "+15V", "estimated_vout": 13.8, "assumed_vref": 1.25,
               "vref_source": "lookup",
               "feedback_divider": {"r_top": vd["r_top"], "r_bottom": vd["r_bottom"],
                                    "ratio": vd["ratio"], "reference": "out_adj"}}
        issues = _scan_fixable({"power_regulators": [reg], "voltage_dividers": [vd]})
        self.assertAlmostEqual(issues[0]["target_value"], 1 - 1.25 / 15)

    def test_phase_functions_are_the_only_mutators(self):
        ctx = _ctx([("U2", "Regulator_Linear:AMS1117-3.3", "AMS1117-3.3",
                     {"1": ("GND", "GND"), "2": ("VOUT", "+3V3"), "3": ("VIN", "+5V")})])
        components, nets = copy.deepcopy(ctx.components), copy.deepcopy(ctx.nets)
        detect_power_regulators(ctx, [])
        self.assertEqual(ctx.components, components)
        self.assertEqual(ctx.nets, nets)


if __name__ == "__main__":
    unittest.main()
