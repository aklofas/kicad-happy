# tools/tests/test_divider_local_rail_node.py
"""A voltage divider continues through a node named like a rail (12V_FBM) when only
local labels name it, two resistors are its only parts and every IC in the design has
mapped pins. A global or hierarchical label, a power symbol or an IC without pins keeps
the node a chain end; a ground node always ends the chain."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
import signal_detectors as sd  # noqa: E402


def _p(ref, pin):
    return (ref, pin, "~", "passive")


def _r(ref, value):
    return {"reference": ref, "type": "resistor", "value": value, "lib_id": "Device:R"}


def _ctx(components, nets, labels):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False,
                "labels": labels.get(n, [])}
            for n, pins in nets.items()}
    for c in components:
        c.setdefault("lib_id", "")
        c.setdefault("pins", [])
        c.setdefault("footprint", "")
    return build_analysis_context(components, full, {})


def _mp2459(mid_label_type="label", extra_parts=(), mid_power_symbol=False,
            bottom_mid="FB"):
    """+12V - R220 100k - 12V_FBM - R221 47k - FB - R222 10k - GND, MP2459 (VFB 0.81 V).
    ``mid_label_type`` names the 12V_FBM label kinds, "+"-joined.
    ``bottom_mid`` other than FB puts a second 10k (R223) between FB and that node."""
    comps = [{"reference": "U220", "type": "ic", "value": "MP2459",
              "lib_id": "Regulator_Switching:MP2459"},
             _r("R220", "100k"), _r("R221", "47k"), _r("R222", "10k"),
             {"reference": "L220", "type": "inductor", "value": "10u"},
             *extra_parts]
    nets = {"+12V": [_p("L220", "2"), _p("R220", "1"), ("#PWR01", "1", "+12V", "power_in")],
            "SW": [("U220", "3", "SW", "output"), _p("L220", "1")],
            "IN": [("U220", "1", "IN", "power_in"), ("#PWR02", "1", "IN", "power_in")],
            "GND": [("U220", "2", "GND", "power_in"), ("#PWR03", "1", "GND", "power_in")],
            "12V_FBM": [_p("R220", "2"), _p("R221", "1")],
            "FB": [("U220", "4", "FB", "input"), _p("R221", "2"), _p("R222", "1")]}
    if bottom_mid == "FB":
        nets["GND"].append(_p("R222", "2"))
    else:
        comps.append(_r("R223", "10k"))
        nets[bottom_mid] = [_p("R222", "2"), _p("R223", "1")]
        nets["GND"].append(_p("R223", "2"))
    if mid_power_symbol:
        nets["12V_FBM"].append(("#PWR04", "1", "12V_FBM", "power_in"))
    labels = {"12V_FBM": [{"name": "12V_FBM", "type": t} for t in mid_label_type.split("+")]}
    if bottom_mid != "FB":
        labels[bottom_mid] = [{"name": bottom_mid, "type": "label"}]
    return _ctx(comps, nets, labels)


def _divider(ctx):
    d = sd.detect_voltage_dividers(ctx)
    vds = sd._merge_series_dividers(d["voltage_dividers"], ctx)
    fns = [fn for fn in d["feedback_networks"] if not fn.get("_closed_chain")]
    vds, fns = sd.postfilter_vd_and_dedup(vds, fns, [], ctx.nets)
    fb = [vd for vd in vds if vd["mid_net"] == "FB"]
    return fb, vds


class LocalRailNamedNode(unittest.TestCase):
    def test_local_label_node_joins_the_top_arm(self):
        ctx = _mp2459()
        fb, vds = _divider(ctx)
        self.assertEqual(len(fb), 1)
        vd = fb[0]
        self.assertEqual(vd["r_top"]["ohms"], 147000.0)
        self.assertEqual([c["ref"] for c in vd["r_top"]["chain_resistors"]], ["R221", "R220"])
        self.assertEqual(vd["top_net"], "+12V")
        regs = sd.detect_power_regulators(ctx, vds)
        u220 = [r for r in regs if r["ref"] == "U220"]
        self.assertEqual(len(u220), 1)
        self.assertAlmostEqual(u220[0]["estimated_vout"], 12.717, places=2)

    def _assert_unchanged(self, ctx):
        fb, _ = _divider(ctx)
        self.assertEqual(len(fb), 1)
        self.assertEqual(fb[0]["r_top"]["ohms"], 47000.0)
        self.assertNotIn("chain_resistors", fb[0]["r_top"])
        self.assertEqual(fb[0]["top_net"], "12V_FBM")

    def test_global_label_node_ends_the_chain(self):
        self._assert_unchanged(_mp2459(mid_label_type="global_label"))

    def test_local_and_global_label_node_ends_the_chain(self):
        self._assert_unchanged(_mp2459(mid_label_type="label+global_label"))

    def test_hierarchical_label_node_ends_the_chain(self):
        self._assert_unchanged(_mp2459(mid_label_type="hierarchical_label"))

    def test_power_symbol_node_ends_the_chain(self):
        ctx = _mp2459(mid_power_symbol=True)
        self.assertIn("12V_FBM", ctx.known_power_rails)
        self._assert_unchanged(ctx)

    def test_an_ic_without_mapped_pins_keeps_the_node_a_chain_end(self):
        unresolved = {"reference": "U9", "type": "ic", "value": "LM358",
                      "lib_id": "Amplifier_Operational:LM358"}
        self._assert_unchanged(_mp2459(extra_parts=(unresolved,)))

    def test_local_label_ground_node_ends_the_chain(self):
        ctx = _mp2459(bottom_mid="AGND")
        self.assertTrue(ctx.is_ground("AGND"))
        fb, _ = _divider(ctx)
        self.assertEqual(len(fb), 1)
        self.assertEqual(fb[0]["r_bottom"]["ohms"], 10000.0)
        self.assertEqual(fb[0]["bottom_net"], "AGND")


if __name__ == "__main__":
    unittest.main()
