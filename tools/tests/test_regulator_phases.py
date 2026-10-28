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

EXAMPLE_EXTRACTION = SCRIPTS.parents[1] / "datasheets" / "examples" / "lm2596-adj.json"

_TYPES = {"U": "ic", "L": "inductor", "R": "resistor", "C": "capacitor"}


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


def _fb_divider(top, r_top, r_bottom):
    return {"r_top": {"ref": "R1", "ohms": r_top, "value": str(r_top)},
            "r_bottom": {"ref": "R2", "ohms": r_bottom, "value": str(r_bottom)},
            "top_net": top, "mid_net": "FB", "bottom_net": "GND",
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

    def test_phase_functions_are_the_only_mutators(self):
        ctx = _ctx([("U2", "Regulator_Linear:AMS1117-3.3", "AMS1117-3.3",
                     {"1": ("GND", "GND"), "2": ("VOUT", "+3V3"), "3": ("VIN", "+5V")})])
        components, nets = copy.deepcopy(ctx.components), copy.deepcopy(ctx.nets)
        detect_power_regulators(ctx, [])
        self.assertEqual(ctx.components, components)
        self.assertEqual(ctx.nets, nets)


if __name__ == "__main__":
    unittest.main()
