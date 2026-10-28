# tools/tests/test_parallel_parts.py
"""Parts of one kind between the same two nets act as one equivalent part (1/sum(1/R),
sum(C)) in voltage dividers, regulator feedback, current-sense shunts and crystal load legs.
The record names the first ref in sorted order and lists every member in ``parallel_refs``;
a DNP part beside a fitted one is left out; a 3-pin potentiometer never joins a group."""
import json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
from detector_helpers import group_value, parallel_groups  # noqa: E402
import signal_detectors as sd  # noqa: E402


def _ctx(components, nets, rails=("+5V", "+3V3", "VOUT", "+12V")):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    for c in components:
        c.setdefault("lib_id", "")
        c.setdefault("pins", [])
        c.setdefault("footprint", "")
    return build_analysis_context(components, full, {}, known_power_rails=set(rails))


def _r(ref, value, dnp=False, lib_id="Device:R"):
    return {"reference": ref, "type": "resistor", "value": value, "dnp": dnp, "lib_id": lib_id}


def _c(ref, value):
    return {"reference": ref, "type": "capacitor", "value": value}


def _p(ref, pin="1"):
    return (ref, pin, "~", "passive")


def _dividers(ctx):
    d = sd.detect_voltage_dividers(ctx)
    vds = sd._merge_series_dividers(d["voltage_dividers"], ctx)
    # as schematic/pipeline.py: a chain that closed on itself leaves feedback_networks too
    fns = [fn for fn in d["feedback_networks"] if not fn.get("_closed_chain")]
    return sd.postfilter_vd_and_dedup(vds, fns, [], ctx.nets)


def _divider_ctx(top, bottoms, top_net="+3V3"):
    """``top`` from ``top_net`` to MID; every part in ``bottoms`` from MID to GND."""
    nets = {top_net: [_p(top["reference"], "1")],
            "MID": [_p(top["reference"], "2")] + [_p(b["reference"], "1") for b in bottoms],
            "GND": [_p(b["reference"], "2") for b in bottoms]}
    return _ctx([top] + bottoms, nets)


class Divider(unittest.TestCase):
    def test_tps54040_parallel_bottom_arm(self):
        # 10k / (10k || 10k = 5k): ratio 5/15, Vout = 0.8 V / (1/3) = 2.4 V (TPS54040 Vref 0.8 V)
        comps = [{"reference": "U1", "type": "ic", "value": "TPS54040",
                  "lib_id": "Regulator_Switching:TPS54040"},
                 _r("R1", "10k"), _r("R2", "10k"), _r("R3", "10k"),
                 {"reference": "L1", "type": "inductor", "value": "10u"}]
        nets = {"+12V": [("U1", "1", "VIN", "power_in")],
                "GND": [("U1", "2", "GND", "power_in"), _p("R2", "2"), _p("R3", "2")],
                "SW": [("U1", "3", "PH", "output"), _p("L1", "1")],
                "VOUT": [_p("L1", "2"), _p("R1", "1")],
                "FB": [("U1", "4", "FB", "input"), _p("R1", "2"), _p("R2", "1"), _p("R3", "1")]}
        ctx = _ctx(comps, nets)
        vds, fns = _dividers(ctx)
        self.assertEqual(len(vds), 1)
        vd = vds[0]
        self.assertEqual(vd["ratio"], 0.333333)
        self.assertEqual(vd["r_bottom"], {"ref": "R2", "value": "2 resistors parallel", "ohms": 5000.0,
                                          "parallel_refs": ["R2", "R3"]})
        self.assertEqual(vd["r_top"], {"ref": "R1", "value": "10k", "ohms": 10000.0})
        self.assertEqual(vd["components"], ["R1", "R2", "R3"])
        self.assertNotIn("parallel_count", vd)
        self.assertEqual([f["ratio"] for f in fns], [0.333333])
        regs = sd.detect_power_regulators(ctx, vds)
        self.assertEqual([r["estimated_vout"] for r in regs], [2.4])
        self.assertEqual(regs[0]["feedback_divider"]["r_bottom"]["parallel_refs"], ["R2", "R3"])
        self.assertEqual(regs[0]["feedback_divider"]["r_bottom"]["ohms"], 5000.0)

    def test_dnp_alternate_is_left_out(self):
        # R14 10k fitted, R15 1k DNP beside it: the arm is R14 alone, ratio 0.5
        ctx = _divider_ctx(_r("R13", "10k"), [_r("R14", "10k"), _r("R15", "1k", dnp=True)])
        vds, _ = _dividers(ctx)
        self.assertEqual([(v["r_top"]["ref"], v["r_bottom"]["ref"], v["ratio"]) for v in vds],
                         [("R13", "R14", 0.5)])
        self.assertNotIn("parallel_count", vds[0])
        self.assertNotIn("parallel_refs", vds[0]["r_bottom"])
        self.assertNotIn("R15", json.dumps(vds))

    def test_fitted_variant_alternates_are_grouped(self):
        # Two fitted 100k alternates on one arm (a variant tool rewrites DNP per variant);
        # KiCad netlists both, so they are one 50k arm: ratio 50/(100+50)
        ctx = _divider_ctx(_r("R33", "100k"), [_r("R34", "100k"), _r("R35", "100k")])
        vds, _ = _dividers(ctx)
        self.assertEqual(len(vds), 1)
        self.assertEqual(vds[0]["ratio"], 0.333333)
        self.assertEqual(vds[0]["r_bottom"]["parallel_refs"], ["R34", "R35"])

    def test_three_pin_potentiometer_never_joins(self):
        pot = {"reference": "RV1", "type": "resistor", "value": "10k",
               "lib_id": "Device:R_Potentiometer"}
        comps = [_r("R1", "10k"), _r("R2", "10k"), pot]
        nets = {"+3V3": [_p("R1", "1")],
                "MID": [_p("R1", "2"), _p("R2", "1"), _p("RV1", "1")],
                "GND": [_p("R2", "2"), _p("RV1", "2")],
                "WIPER": [_p("RV1", "3")]}
        ctx = _ctx(comps, nets)
        self.assertNotIn("RV1", parallel_groups(ctx, "resistor"))
        self.assertEqual(parallel_groups(ctx, "resistor")["R2"]["refs"], ["R2"])
        vds, _ = _dividers(ctx)
        self.assertFalse(any("parallel_refs" in v[arm] for v in vds for arm in ("r_top", "r_bottom")))

    def test_unparsed_member_makes_the_group_unknown(self):
        ctx = _divider_ctx(_r("R1", "10k"), [_r("R2", "10k"), _r("R3", "R_ALT")])
        self.assertIsNone(group_value(ctx, "R2"))
        vds, _ = _dividers(ctx)
        self.assertEqual(vds, [])

    def test_zero_ohm_member_makes_the_group_zero(self):
        ctx = _divider_ctx(_r("R1", "10k"), [_r("R2", "10k"), _r("R3", "0")])
        self.assertEqual(group_value(ctx, "R2"), 0.0)
        vds, _ = _dividers(ctx)
        self.assertEqual(vds, [])

    def test_chain_back_to_ground_is_not_a_divider(self):
        # FB node: R14 680k from VDD, R17 150k to GND, and R18 10M + R24 2M2 in series to GND.
        # R18/R17 extended through R24 runs GND -> FB -> GND: no divider. The regulator takes
        # R14/R17: TLV62569 Vref 0.6 V, ratio 150/830, Vout = 0.6 * 830/150 = 3.32 V.
        comps = [{"reference": "U1", "type": "ic", "value": "TLV62569",
                  "lib_id": "Regulator_Switching:TLV62569DBV"},
                 _r("R14", "680k"), _r("R17", "150k"), _r("R18", "10M"), _r("R24", "2M2"),
                 {"reference": "L1", "type": "inductor", "value": "2u2"}]
        nets = {"+5V": [("U1", "1", "VIN", "power_in")],
                "GND": [("U1", "2", "GND", "power_in"), _p("R17", "2"), _p("R24", "2")],
                "SW": [("U1", "3", "SW", "output"), _p("L1", "1")],
                "VDD": [_p("L1", "2"), _p("R14", "1")],
                "FB": [("U1", "4", "FB", "input"), _p("R14", "2"), _p("R17", "1"), _p("R18", "1")],
                "LEG": [_p("R18", "2"), _p("R24", "1")]}
        ctx = _ctx(comps, nets, rails=("+5V", "VDD"))
        vds, fns = _dividers(ctx)
        self.assertFalse(any(v["top_net"] == v["bottom_net"] for v in vds), vds)
        for records in (vds, fns):
            self.assertNotIn(("R18", "R17"), [(v["r_top"]["ref"], v["r_bottom"]["ref"]) for v in records])
        self.assertEqual([(f["r_top"]["ref"], f["r_bottom"]["ref"]) for f in fns], [("R14", "R17")])
        regs = sd.detect_power_regulators(ctx, vds)
        self.assertEqual([(r["feedback_divider"]["r_top"]["ref"], r["feedback_divider"]["r_bottom"]["ref"],
                           r["estimated_vout"]) for r in regs], [("R14", "R17", 3.32)])

    def test_both_ends_on_ground_is_not_a_divider(self):
        comps = [_r("R1", "10k"), _r("R2", "10k")]
        nets = {"GND": [_p("R1", "1")], "MID": [_p("R1", "2"), _p("R2", "1")], "AGND": [_p("R2", "2")]}
        vds, _ = _dividers(_ctx(comps, nets))
        self.assertEqual(vds, [])

    def test_single_member_keeps_its_value_bit_exact(self):
        # 1/(1/6800.0) != 6800.0 in floating point
        self.assertNotEqual(1 / (1 / 6800.0), 6800.0)
        ctx = _divider_ctx(_r("R1", "10k"), [_r("R2", "6.8k")])
        vds, _ = _dividers(ctx)
        self.assertEqual(vds[0]["r_bottom"], {"ref": "R2", "value": "6.8k", "ohms": 6800.0})
        self.assertEqual(vds[0]["ratio"], round(6800.0 / 16800.0, 6))


class CurrentSense(unittest.TestCase):
    COMPS = [{"reference": "U4", "type": "ic", "value": "INA219", "lib_id": "Analog_ADC:INA219"}]

    def _cs(self, n1, n2, rails):
        comps = [dict(c) for c in self.COMPS] + [_r("R11", "0.1"), _r("R12", "0.1")]
        nets = {n1: [_p("R11", "1"), _p("R12", "1"), ("U4", "1", "IN+", "input")],
                n2: [_p("R11", "2"), _p("R12", "2"), ("U4", "2", "IN-", "input")]}
        return sd.detect_current_sense(_ctx(comps, nets, rails=rails))

    def test_two_parallel_shunts_are_one_at_half_the_resistance(self):
        for n1, n2, rails in (("+12V", "LOAD", ("+12V",)), ("VA", "VB", ())):
            cs = self._cs(n1, n2, rails)
            self.assertEqual([(c["shunt"]["ref"], c["shunt"]["ohms"], c["shunt"].get("parallel_refs"),
                               c["sense_ic"]["ref"]) for c in cs],
                             [("R11", 0.05, ["R11", "R12"], "U4")], (n1, n2))
            self.assertEqual(cs[0]["max_current_50mV_A"], 1.0)
            self.assertEqual(cs[0]["components"], ["R11", "R12", "U4"])


class CrystalLegs(unittest.TestCase):
    def _xtal(self, legs):
        comps = [{"reference": "Y1", "type": "crystal", "value": "16MHz",
                  "pins": [{"number": "1", "name": "1"}, {"number": "2", "name": "2"}]}]
        nets = {"OSC_IN": [("Y1", "1", "1", "passive")], "OSC_OUT": [("Y1", "2", "2", "passive")],
                "GND": []}
        for net, caps in legs.items():
            for ref, val in caps:
                comps.append(_c(ref, val))
                nets[net].append(_p(ref, "1"))
                nets["GND"].append(_p(ref, "2"))
        return sd.detect_crystal_circuits(_ctx(comps, nets))

    def test_load_capacitance_sums_each_leg(self):
        # (22p + 5p) on one leg, 27p on the other: 27*27/54 + 3 pF stray = 16.5 pF
        xc = self._xtal({"OSC_IN": [("C2", "22p"), ("C3", "5p")], "OSC_OUT": [("C4", "27p")]})
        self.assertEqual([x["effective_load_pF"] for x in xc], [16.5])
        self.assertIn("summed per leg", xc[0]["note"])

    def test_one_cap_per_leg_keeps_the_note(self):
        xc = self._xtal({"OSC_IN": [("C2", "22p")], "OSC_OUT": [("C4", "22p")]})
        self.assertEqual(xc[0]["effective_load_pF"], 14.0)
        self.assertEqual(xc[0]["note"], "CL_eff = (22p * 22p) / (22p + 22p) + ~3pF stray")

    def test_both_caps_on_one_leg_have_no_series_load(self):
        xc = self._xtal({"OSC_IN": [("C2", "22p"), ("C3", "22p")], "OSC_OUT": []})
        self.assertNotIn("effective_load_pF", xc[0])

    def test_ic_crystal_pins_sum_each_leg(self):
        comps = [{"reference": "U1", "type": "ic", "value": "MCU",
                  "pins": [{"number": "1", "name": "OSC_IN"}, {"number": "2", "name": "OSC_OUT"}]},
                 _c("C2", "22p"), _c("C3", "5p"), _c("C4", "27p")]
        nets = {"XI": [("U1", "1", "OSC_IN", "input"), _p("C2", "1"), _p("C3", "1")],
                "XO": [("U1", "2", "OSC_OUT", "output"), _p("C4", "1")],
                "GND": [_p("C2", "2"), _p("C3", "2"), _p("C4", "2")]}
        xc = sd.detect_crystal_circuits(_ctx(comps, nets))
        self.assertEqual([x["effective_load_pF"] for x in xc], [16.5])

    def test_what_if_recompute_sums_each_leg(self):
        from detection_schema import _recalc_crystal_load
        det = {"load_caps": [{"ref": "C2", "farads": 22e-12, "net": "OSC_IN"},
                             {"ref": "C3", "farads": 5e-12, "net": "OSC_IN"},
                             {"ref": "C4", "farads": 27e-12, "net": "OSC_OUT"}]}
        _recalc_crystal_load(det)
        self.assertEqual(det["effective_load_pF"], 16.5)
        det = {"load_caps": [{"ref": "C1", "farads": 22e-12}, {"ref": "C2", "farads": 22e-12}]}
        _recalc_crystal_load(det)
        self.assertEqual(det["effective_load_pF"], 14.0)
        # the IC-pin path can list one cap twice (two XTAL pins on one net): counted once
        det = {"load_caps": [{"ref": "C2", "farads": 22e-12, "net": "XI"},
                             {"ref": "C2", "farads": 22e-12, "net": "XI"},
                             {"ref": "C4", "farads": 22e-12, "net": "XO"}]}
        _recalc_crystal_load(det)
        self.assertEqual(det["effective_load_pF"], 14.0)


if __name__ == "__main__":
    unittest.main()
