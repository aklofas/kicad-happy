# tools/tests/test_decoupling_census.py
"""Decoupling, regulator-capacitor and inrush census: only fitted parts count. A capacitor
marked DNP or excluded from the board is not decoupling or inrush load, and an unfitted IC or
regulator needs no capacitors."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "spice" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import detect_decoupling, detect_design_observations  # noqa: E402
from schematic.system_analyses import analyze_inrush_current  # noqa: E402


def _ctx(comps, wiring, rails=("+3V3", "+5V")):
    by_ref = {c["reference"]: dict({"lib_id": "", "dnp": False, "on_board": True}, **c, pins=[]) for c in comps}
    nets = {}
    for net, pins in wiring:
        entry = nets.setdefault(net, {"name": net, "pins": [], "point_count": 0, "no_connect": False,
                                      "has_pwr_flag": False, "labels": []})
        for ref, num, name, ptype in pins:
            entry["pins"].append({"component": ref, "pin_number": num, "pin_name": name, "pin_type": ptype})
            by_ref[ref]["pins"].append({"number": num, "name": name})
    return build_analysis_context(list(by_ref.values()), nets, {}, known_power_rails=set(rails))


def _ic_with_caps(caps, ic=None):
    """IC U1 (VCC on +3V3, GND) and capacitors from +3V3 to GND, one per entry of *caps*."""
    comps = [dict({"reference": "U1", "type": "ic", "value": "ATTINY25"}, **(ic or {}))]
    rail = [("U1", "8", "VCC", "power_in")]
    gnd = [("U1", "4", "GND", "power_in")]
    for i, cap in enumerate(caps, 1):
        comps.append(dict({"reference": f"C{i}", "type": "capacitor", "value": "100n"}, **cap))
        rail.append((f"C{i}", "1", "", "passive"))
        gnd.append((f"C{i}", "2", "", "passive"))
    ctx = _ctx(comps, [("+3V3", rail), ("GND", gnd)])
    dc = detect_decoupling(ctx)
    obs = detect_design_observations(ctx, {"decoupling_analysis": dc})
    return dc, [o["rails_without_caps"] for o in obs if o["category"] == "decoupling"]


class FittedCapacitorsOnly(unittest.TestCase):
    def test_dnp_cap_is_not_decoupling_and_the_rail_reads_missing(self):
        dc, missing = _ic_with_caps([{"dnp": True}])
        self.assertEqual(dc, [])
        self.assertEqual(missing, [["+3V3"]])

    def test_cap_excluded_from_the_board_is_not_decoupling(self):
        dc, missing = _ic_with_caps([{"on_board": False}])
        self.assertEqual(dc, [])
        self.assertEqual(missing, [["+3V3"]])

    def test_rail_total_counts_only_its_fitted_caps(self):
        dc, missing = _ic_with_caps([{}, {"value": "10u", "dnp": True}])
        self.assertEqual([(d["components"], d["cap_count"], d["total_capacitance_uF"]) for d in dc],
                         [(["C1"], 1, 0.1)])
        self.assertEqual(missing, [])

    def test_fitted_cap_keeps_its_record(self):
        dc, missing = _ic_with_caps([{}])
        self.assertEqual([d["components"] for d in dc], [["C1"]])
        self.assertEqual(missing, [])

    def test_an_unfitted_ic_needs_no_decoupling(self):
        for ic in ({"dnp": True}, {"on_board": False}):
            with self.subTest(ic=ic):
                self.assertEqual(_ic_with_caps([], ic=ic)[1], [])
                self.assertEqual(_ic_with_caps([{"dnp": True}], ic=ic)[1], [])


def _regulator(in_net="+5V", in_cap=None, out_cap=None, reg=None, out_net="+3V3"):
    """LDO U1 (input on *in_net*, output on *out_net*) with C1 from the input and C2 from the
    output to GND; *in_cap* / *out_cap* = None leaves that capacitor out."""
    comps = [dict({"reference": "U1", "type": "ic", "value": "AMS1117-3.3"}, **(reg or {}))]
    wiring = {in_net: [("U1", "3", "VI", "power_in")], out_net: [("U1", "2", "VO", "power_out")],
              "GND": [("U1", "1", "GND", "power_in")]}
    for ref, net, cap, value in (("C1", in_net, in_cap, "10uF"), ("C2", out_net, out_cap, "22uF")):
        if cap is None:
            continue
        comps.append(dict({"reference": ref, "type": "capacitor", "value": value}, **cap))
        wiring[net].append((ref, "1", "", "passive"))
        wiring["GND"].append((ref, "2", "", "passive"))
    ctx = _ctx(comps, list(wiring.items()))
    regs = [{"ref": "U1", "value": "AMS1117-3.3", "topology": "LDO", "input_rail": in_net, "output_rail": out_net}]
    obs = detect_design_observations(ctx, {"power_regulators": regs, "decoupling_analysis": detect_decoupling(ctx)})
    return ctx, regs, [o["missing_caps"] for o in obs if o["category"] == "regulator_caps"]


class RegulatorCapacitors(unittest.TestCase):
    def test_fitted_caps_satisfy_the_regulator(self):
        self.assertEqual(_regulator(in_cap={}, out_cap={})[2], [])

    def test_dnp_input_cap_does_not_count(self):
        self.assertEqual(_regulator(in_cap={"dnp": True}, out_cap={})[2], [{"input": "+5V"}])

    def test_off_board_output_cap_on_an_unnamed_net_does_not_count(self):
        self.assertEqual(_regulator(in_cap={}, out_cap={"on_board": False}, out_net="__unnamed_4")[2],
                         [{"output": "__unnamed_4"}])

    def test_an_unfitted_regulator_gets_no_capacitor_observation(self):
        for reg in ({"dnp": True}, {"on_board": False}):
            with self.subTest(reg=reg):
                self.assertEqual(_regulator(reg=reg)[2], [])
                self.assertEqual(_regulator(in_cap={"dnp": True}, out_cap={"dnp": True}, reg=reg)[2], [])


class InrushFittedCapsOnly(unittest.TestCase):
    def test_dnp_output_cap_is_left_out_of_the_inrush_total(self):
        ctx, regs, _ = _regulator(in_cap={}, out_cap={"value": "100uF", "dnp": True})
        self.assertEqual(analyze_inrush_current(ctx, {"power_regulators": regs}), {})

    def test_fitted_output_cap_is_the_inrush_total(self):
        ctx, regs, _ = _regulator(in_cap={}, out_cap={})
        rails = analyze_inrush_current(ctx, {"power_regulators": regs})["rails"]
        self.assertEqual(rails[0]["total_output_capacitance_uF"], 22.0)


class DecouplingBenchModelNote(unittest.TestCase):
    def _note(self, pdn_refs):
        from spice_templates import generate_decoupling
        det = {"rail": "+3V3", "capacitors": [{"ref": "C1", "farads": 1e-7}, {"ref": "C2", "farads": 1e-5}]}
        ctx = {"pdn_impedance": {"rails": {"+3V3": {"capacitors": [
            {"ref": r, "esr_ohm": 0.02, "esl_nH": 0.5} for r in pdn_refs]}}}}
        cir = generate_decoupling(det, "out.txt", context=ctx).circuit
        return next(line for line in cir.splitlines() if line.startswith("* Model:"))

    def test_note_names_a_mixed_model(self):
        self.assertEqual(self._note(["C1"]),
                         "* Model: ESR/ESL from pdn_impedance for 1 of 2 capacitors, "
                         "estimated ESR + parasitic L from SRF for the rest")

    def test_note_for_a_single_model(self):
        self.assertEqual(self._note(["C1", "C2"]), "* Model: ESR/ESL from pdn_impedance (package-based)")
        self.assertEqual(self._note([]), "* Model: estimated ESR + parasitic L from SRF")


if __name__ == "__main__":
    unittest.main()
