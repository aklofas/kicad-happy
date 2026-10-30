# tools/tests/test_hash_seed_order.py
"""Output that iterates a set of strings must not depend on PYTHONHASHSEED.

Each case runs product code in a subprocess under several hash seeds, prints a JSON
projection of the result, and asserts every seed printed the same thing (and, where the
order is defined, the hand-computed order)."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_PATHS = [str(ROOT / "skills" / d / "scripts") for d in ("kicad", "emc", "datasheets")]

PRELUDE = f"""
import json, sys
sys.path[:0] = {_PATHS!r}
from kicad_types import build_analysis_context

def ctx_of(components, nets):
    full = {{n: {{"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                     for r, p, pn, t in pins],
                 "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}}
            for n, pins in nets.items()}}
    return build_analysis_context(components, full, {{}}, known_power_rails={{"+5V", "+3V3"}})
"""


def _under_seeds(code, seeds=("0", "1", "2", "3")):
    """stdout of PRELUDE + code run once per hash seed."""
    outs = []
    with tempfile.TemporaryDirectory() as tmp:
        for s in seeds:
            env = dict(os.environ, PYTHONHASHSEED=s, PYTHONDONTWRITEBYTECODE="1")
            r = subprocess.run([sys.executable, "-c", PRELUDE + code], env=env, cwd=tmp,
                               capture_output=True, text=True, encoding="utf-8", timeout=60)
            if r.returncode != 0:
                raise AssertionError(f"seed {s} exited {r.returncode}:\n{r.stderr}")
            outs.append(r.stdout)
    return outs


class SeedOrder(unittest.TestCase):
    def assertSeedsAgree(self, code, expected=None):
        outs = _under_seeds(code)
        self.assertEqual(len(set(outs)), 1, f"seeds disagree: {outs}")
        got = json.loads(outs[0])
        if expected is not None:
            self.assertEqual(got, expected)
        return got

    def test_trace_through_returns_sorted_nets(self):
        code = """
comps = [{"reference": "U1", "type": "ic", "value": "X"}]
names = ["N_H", "N_C", "N_F", "N_A", "N_G", "N_B", "N_E", "N_D"]
ctx = ctx_of(comps, {n: [("U1", str(i), "P%d" % i, "passive")] for i, n in enumerate(names, 1)})
print(json.dumps(ctx.nq.trace_through("N_E", "U1")))
"""
        self.assertSeedsAgree(code, ["N_A", "N_B", "N_C", "N_D", "N_F", "N_G", "N_H"])

    def test_regulator_inductor_found_through_the_ic(self):
        # SW carries no inductor; NET_A..NET_D each carry a different one. The str-smallest
        # other net with an inductor wins: NET_A -> L4, whose pin 1 (away from SW) is OUT_A.
        code = """
from signal_detectors import detect_power_regulators
comps = [{"reference": "U1", "type": "ic", "value": "BUCK1", "pins": [1]}]
nets = {"+5V": [("U1", "1", "VIN", "power_in")],
        "GND": [("U1", "2", "GND", "power_in")],
        "SWN": [("U1", "3", "SW", "output")]}
for i, (net, ind) in enumerate((("NET_B", "L1"), ("NET_D", "L2"), ("NET_C", "L3"), ("NET_A", "L4"))):
    comps.append({"reference": ind, "type": "inductor", "value": "10u"})
    nets[net] = [("U1", str(4 + i), "IO%d" % i, "passive"), (ind, "2", "~", "passive")]
    nets["OUT_" + net[-1]] = [(ind, "1", "~", "passive")]
regs = detect_power_regulators(ctx_of(comps, nets), [])
print(json.dumps([[r["ref"], r.get("inductor"), r.get("output_rail")] for r in regs]))
"""
        self.assertSeedsAgree(code, [["U1", "L4", "OUT_A"]])

    def test_clock_buffer_consumers_follow_output_net_order(self):
        code = """
from domain_detectors import _trace_clock_consumers
comps = [{"reference": "Y1", "type": "crystal", "value": "25MHz"},
         {"reference": "U1", "type": "ic", "value": "SI5351A"}]
nets = {"CLK_IN": [("Y1", "1", "~", "passive"), ("U1", "1", "XA", "input")],
        "+3V3": [("U1", "2", "VDD", "power_in")],
        "GND": [("U1", "3", "GND", "power_in")]}
for i in range(6):
    consumer = "U%d" % (15 - i)
    comps.append({"reference": consumer, "type": "ic", "value": "MCU"})
    nets["CK_%d" % i] = [("U1", str(4 + i), "CLK%d" % i, "output"), (consumer, "1", "CLKIN", "input")]
print(json.dumps(_trace_clock_consumers(ctx_of(comps, nets), "CLK_IN", "Y1")))
"""
        self.assertSeedsAgree(code, ["U15", "U14", "U13", "U12", "U11", "U10"])

    def test_opamp_parallel_feedback_parts_pick_the_smallest_ref(self):
        code = """
from signal_detectors import detect_opamp_circuits
comps = [{"reference": "U1", "type": "ic", "value": "OPA1"}]
for ref, typ, val in (("R1", "resistor", "100k"), ("R2", "resistor", "200k"),
                      ("R4", "resistor", "47k"), ("R5", "resistor", "330k"),
                      ("R3", "resistor", "10k"),
                      ("C1", "capacitor", "10p"), ("C2", "capacitor", "22p"),
                      ("C3", "capacitor", "47p")):
    comps.append({"reference": ref, "type": typ, "value": val})
fb = ("R1", "R2", "R4", "R5", "C1", "C2", "C3")
nets = {"OUT": [("U1", "1", "OUT", "output")] + [(r, "1", "~", "passive") for r in fb],
        "INN": [("U1", "2", "-IN", "input"), ("R3", "2", "~", "passive")]
               + [(r, "2", "~", "passive") for r in fb],
        "VREF": [("U1", "3", "+IN", "input")],
        "SIG": [("R3", "1", "~", "passive")]}
oa = detect_opamp_circuits(ctx_of(comps, nets))
print(json.dumps([[o["reference"], o.get("feedback_resistor", {}).get("ref"),
                   o.get("feedback_capacitor", {}).get("ref")] for o in oa]))
"""
        self.assertSeedsAgree(code, [["U1", "R1", "C1"]])

    def test_cp001_description_lists_foreign_nets_sorted(self):
        code = """
from pcb.copper import analyze_copper_presence
from pcb.geometry import ZoneFills
names = ["VB", "VE", "VA", "VD", "VC"]
zones = [{"net": i + 2, "net_name": n, "layer": "F.Cu"} for i, n in enumerate(names)]
fills = ZoneFills()
for i in range(len(zones)):
    fills.add(i, "F.Cu", [(-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0)])
fp = {"reference": "U1", "value": "X", "layer": "F.Cu", "x": 0.0, "y": 0.0,
      "pads": [{"number": "1", "abs_x": 0.0, "abs_y": 0.0, "net_number": 1, "net_name": "SIG"}]}
res = analyze_copper_presence([fp], zones, fills)
found = [f for f in res.get("same_layer_foreign_zones", []) if f.get("rule_id") == "CP-001"]
print(json.dumps([[f["description"], f["nets"]] for f in found]))
"""
        nets = ["VA", "VB", "VC", "VD", "VE"]
        self.assertSeedsAgree(code, [[
            "Component U1 has same-layer copper from foreign zone(s): VA, VB, VC, VD, VE.", nets]])

    def test_ml001_victims_in_ref_order(self):
        code = """
from emc_rules import check_inductor_leakage
from finding_schema import Det, assign_finding_ids
sch = {"findings": [{"detector": Det.POWER_REGULATORS, "ref": "U1", "topology": "switching",
                     "inductor": "L1"}]
                   + [{"detector": Det.CRYSTAL_CIRCUITS, "reference": r} for r in ("Y3", "Y1", "Y2", "Y4")]}
pos = {"L1": (0, 0), "Y1": (5, 0), "Y2": (0, 5), "Y3": (-5, 0), "Y4": (0, -5)}
pcb = {"footprints": [{"reference": r, "x": x, "y": y, "value": ""} for r, (x, y) in pos.items()]}
fs = check_inductor_leakage(pcb, sch)
assign_finding_ids(fs, "emc")
print(json.dumps([[f["finding_id"], f["summary"]] for f in fs]))
"""
        got = self.assertSeedsAgree(code)
        self.assertEqual([s.split("sensitive ")[1].split()[0] for _, s in got], ["Y1", "Y2", "Y3", "Y4"])

    def test_test_plan_takes_the_riskiest_protocol(self):
        # protocol_speeds ranks HDMI 9, USB 7 and an unlisted type ("differential") 4.
        code = """
from emc_rules import generate_test_plan
sch = {"design_analysis": {"differential_pairs": [
    {"positive": "USB_DP", "negative": "USB_DN", "type": "USB"},
    {"positive": "SS_TX_P", "negative": "SS_TX_N", "type": "differential"},
    {"positive": "HDMI_D0_P", "negative": "HDMI_D0_N", "type": "HDMI"}]}}
pad_nets = {str(i): {"net": n, "pin": str(i)} for i, n in enumerate(
    ("USB_DP", "USB_DN", "SS_TX_P", "SS_TX_N", "HDMI_D0_P", "HDMI_D0_N", "GND"), 1)}
pcb = {"footprints": [{"reference": "J1", "value": "USB_C", "pad_nets": pad_nets, "x": 1, "y": 1}]}
plan = generate_test_plan(sch, pcb, [])
print(json.dumps([[r["connector"], r["protocol"], r["risk_score"]] for r in plan["interface_risks"]]))
"""
        self.assertSeedsAgree(code, [["J1", "HDMI", 9]])

    def test_deep_merge_keeps_base_order_then_override_order(self):
        code = """
from project_config import DEFAULT_CONFIG, _deep_merge
m = _deep_merge(dict(DEFAULT_CONFIG), {"project": {"name": "x", "revision": "A",
                                                   "board_class": "c", "target_market": "m"}})
n = _deep_merge({"b": 1, "a": {"y": 1, "x": 2}, "c": 3},
                {"a": {"z": 1, "x": 5, "w": 0}, "d": 4, "e": 5})
print(json.dumps([list(m), list(m["project"]), list(n), list(n["a"])]))
"""
        self.assertSeedsAgree(code, [
            ["version", "project", "suppressions", "preferred_suppliers", "bom", "analysis"],
            ["name", "revision", "board_class", "target_market"],
            ["b", "a", "c", "d", "e"], ["y", "x", "z", "w"]])

    def test_lifecycle_sources_available_sorted(self):
        code = """
import lifecycle_audit as la
la.audit_component = lambda mpn, sources, project_dir=None, delay=0: {
    "status": "active", "sources": {"mouser": {}, "lcsc": {}, "element14": {}, "digikey": {}}}
r = la.audit_bom({"bom": [{"mpn": "LM358DR", "references": ["U1"], "type": "ic"}]}, delay=0)
print(json.dumps(r["sources_available"]))
"""
        self.assertSeedsAgree(code, ["digikey", "element14", "lcsc", "mouser"])

    def test_datasheet_decoupling_lists_caps_in_net_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext = {"pins": [{"number": str(i), "name": "VDD%d" % i, "type": "power",
                             "direction": "input"} for i in range(1, 6)],
                   "application_circuit": {"decoupling_cap": "10uF x9"}}
            with open(os.path.join(tmp, "TESTIC.json"), "w", encoding="utf-8") as fh:
                json.dump(ext, fh)
            code = f"""
from datasheet_verify import verify_decoupling
pin_nets = {{"1": "VE", "2": "VA", "3": "VD", "4": "VB", "5": "VC"}}
caps = {{"VA": "C5", "VB": "C3", "VC": "C1", "VD": "C4", "VE": "C2"}}
comps = [{{"reference": "U1", "type": "ic", "mpn": "TESTIC", "pin_nets": pin_nets}}]
comps += [{{"reference": c, "type": "capacitor", "value": "100n"}} for c in caps.values()]
nets = {{n: {{"pins": [{{"component": "U1"}}, {{"component": c}}]}} for n, c in caps.items()}}
fs = verify_decoupling(comps, nets, {tmp!r}, {{c["reference"]: c for c in comps}},
                       {{c: 1e-7 for c in caps.values()}})
print(json.dumps([[c["ref"] for c in f["actual_caps"]] for f in fs
                  if f.get("type") == "decoupling_insufficient"]))
"""
            self.assertSeedsAgree(code, [["C5", "C3", "C1", "C4", "C2"]])

    def test_what_if_parasitics_and_spice_delta_keys(self):
        code = """
import types
import what_if as wi
det = {k: {"ref": "R1", "ohms": 1000.0, "net": n}
       for k, n in (("a", "N3"), ("b", "N1"), ("c", "N4"), ("d", "N2"), ("e", "N5"))}
tracks = {n: [{"length_mm": 10.0 + i * 3.3, "width_mm": 0.15 + i * 0.07}]
          for i, n in enumerate(("N1", "N2", "N3", "N4"))}
par = wi._extract_parasitics({"tracks": tracks}, det, "rc_filters")

fake = types.ModuleType("simulate_subcircuits")
fake.simulate_subcircuits = lambda mini, **kw: {"simulation_results": [{"status": "pass",
    "simulated": {k: v * mini["findings"][0]["scale"]
                  for k, v in {"m_e": 1.0, "m_b": 2.0, "m_d": 3.0, "m_a": 4.0, "m_c": 5.0}.items()}}]}
sim = types.ModuleType("spice_simulator")
sim.detect_simulator = lambda name: "stub"
sys.modules["simulate_subcircuits"] = fake
sys.modules["spice_simulator"] = sim
res = wi._run_spice_comparison([("rc_filters", 0, {"scale": 1.0}, {})], [{"scale": 2.0}], {})
print(json.dumps([par, list(res[("rc_filters", 0)])]))
"""
        got = self.assertSeedsAgree(code)
        self.assertEqual(got[0]["R1"]["net"], "N4")
        self.assertEqual(got[1], ["m_a", "m_b", "m_c", "m_d", "m_e"])

    def test_current_sense_ics_in_ref_order(self):
        # Five ICs each with a pin on both sides of one shunt: one record per IC, sorted
        code = """
import signal_detectors as sd
ics = ["U5", "U3", "U1", "U4", "U2"]
comps = [{"reference": "R1", "type": "resistor", "value": "0.01"}]
comps += [{"reference": u, "type": "ic", "value": "SENSE"} for u in ics]
nets = {"VA": [("R1", "1", "~", "passive")] + [(u, "1", "INP", "input") for u in ics],
        "VB": [("R1", "2", "~", "passive")] + [(u, "2", "INN", "input") for u in ics]}
print(json.dumps([c["sense_ic"]["ref"] for c in sd.detect_current_sense(ctx_of(comps, nets))]))
"""
        self.assertSeedsAgree(code, ["U1", "U2", "U3", "U4", "U5"])


if __name__ == "__main__":
    unittest.main()
