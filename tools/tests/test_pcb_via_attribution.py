# tools/tests/test_pcb_via_attribution.py
"""Which vias belong to a thermal pad, and which pads via-in-pad checks.

A via joins a pad's thermal path only when it is the pad's copper: a via of another net
inside the pad is a short (KiCad DRC `shorting_items`), not a thermal via. Inside the pad
means inside its real outline (a circle pad does not own its bounding-box corners). A via
is open to solder on the side the pad opens: tenting on the other side does not cover it,
and a negative pad solder_mask_margin that closes the opening leaves the via under mask.
Via-in-pad exempts only the thermal pad TV-001 already reports, not the footprint's
signal pads."""
import sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.sexp import parse  # noqa: E402
from pcb.copper import analyze_thermal_pad_vias  # noqa: E402
from pcb.pipeline import analyze_pcb  # noqa: E402
from pcb.reader import extract_footprints, extract_vias, extract_zones  # noqa: E402


def board_text(items, setup=""):
    return (
        '(kicad_pcb (version 20171130) (host pcbnew 5.1.9)\n'
        ' (general (thickness 1.6))\n'
        ' (layers (0 F.Cu signal) (31 B.Cu signal) (34 B.Paste user) (35 F.Paste user)\n'
        '  (36 B.SilkS user) (37 F.SilkS user) (38 B.Mask user) (39 F.Mask user)\n'
        '  (44 Edge.Cuts user))\n'
        f' (setup {setup})\n'
        ' (net 0 "") (net 1 GND) (net 3 SIG) (net 99 OTHER)\n'
        ' (gr_line (start 0 0) (end 30 0) (layer Edge.Cuts) (width 0.1))\n'
        ' (gr_line (start 30 0) (end 30 30) (layer Edge.Cuts) (width 0.1))\n'
        ' (gr_line (start 30 30) (end 0 30) (layer Edge.Cuts) (width 0.1))\n'
        ' (gr_line (start 0 30) (end 0 0) (layer Edge.Cuts) (width 0.1))\n'
        f' {items})\n')


def qfn(ep="(size 3 3)", ep_shape="rect", ep_layers="F.Cu F.Paste F.Mask", side="F",
        ep_extra=""):
    """U1 at (15, 10): four 0.3 x 0.8 signal pads and an exposed pad 5 on GND."""
    pads = "".join(
        f' (pad {n} smd rect (at {dx} -2.5) (size 0.3 0.8) (layers {side}.Cu {side}.Paste'
        f' {side}.Mask) (net 3 SIG))'
        for n, dx in ((1, -0.75), (2, -0.25), (3, 0.25), (4, 0.75)))
    pads += f' (pad 5 smd {ep_shape} (at 0 0) {ep} (layers {ep_layers}) (net 1 GND){ep_extra})'
    return (f'(module Test:QFN (layer {side}.Cu) (at 15 10) (fp_text reference U1 (at 0 4)'
            f' (layer {side}.SilkS)){pads})')


def via(x, y=10, net=1, extra=""):
    return f'(via (at {x} {y}) (size 0.6) (drill 0.3) {extra} (layers F.Cu B.Cu) (net {net}))'


def tv001(items, setup=""):
    root = parse(board_text(items, setup))
    zones, fills = extract_zones(root)
    return analyze_thermal_pad_vias(extract_footprints(root), extract_vias(root), zones, fills)


class ThermalPadViaNet(unittest.TestCase):
    # 2 x 2 mm pad: the Tier-1 window reaches 1.5 mm from the centre, so x = 1.3 is inside it.
    EP = "(size 2 2)"
    OTHER = "".join(via(16.3, 10 + dy, net=99) for dy in (-0.8, -0.4, 0, 0.4, 0.8))

    def test_vias_of_another_net_are_not_thermal_vias(self):
        tv = tv001(qfn(self.EP) + self.OTHER)
        self.assertEqual((tv[0]["via_count"], tv[0]["adequacy"], tv[0]["severity"]),
                         (0, "none", "warning"))

    def test_a_via_on_the_pad_net_counts(self):
        tv = tv001(qfn(self.EP) + self.OTHER + via(15.3))
        self.assertEqual(tv[0]["via_count"], 1)


class ThermalPadViaExposure(unittest.TestCase):
    def test_circle_pad_does_not_own_its_bbox_corner(self):
        # Circle of radius 1.5 mm; (1.2, 1.2) is 1.70 mm from its centre: in the bounding box
        # and the Tier-1 window, outside the copper and its mask opening. The via is tented.
        tv = tv001(qfn(ep_shape="circle") + via(16.2, 11.2))
        self.assertEqual(tv[0]["via_count"], 1)
        self.assertNotIn("tenting_note", tv[0])

    def test_front_tenting_does_not_cover_a_via_at_a_back_pad(self):
        # 1.8 mm from the centre: beside the B-side pad, not under it; open on B.
        tv = tv001(qfn(ep_layers="B.Cu B.Paste B.Mask", side="B")
                   + via(16.8, extra="(tenting front)"), setup="(tenting none)")
        self.assertEqual(tv[0]["via_count"], 1)
        self.assertIn("tenting_note", tv[0])

    def test_back_tenting_still_covers_a_via_at_a_back_pad(self):
        tv = tv001(qfn(ep_layers="B.Cu B.Paste B.Mask", side="B")
                   + via(16.8, extra="(tenting back)"), setup="(tenting none)")
        self.assertNotIn("tenting_note", tv[0])

    def test_negative_mask_margin_that_closes_the_opening_covers_the_via(self):
        # A 3 x 3 pad shrunk by 1.6 mm per side has no opening left; the via is tented.
        tv = tv001(qfn(ep_extra=" (solder_mask_margin -1.6)") + via(15.5))
        self.assertNotIn("tenting_note", tv[0])

    def test_negative_mask_margin_leaving_an_opening_over_the_via_exposes_it(self):
        # Shrunk by 0.5 mm per side the opening is 2 x 2 mm; 0.5 mm from the centre is in it.
        tv = tv001(qfn(ep_extra=" (solder_mask_margin -0.5)") + via(15.5))
        self.assertIn("tenting_note", tv[0])


class ViaInPadExemption(unittest.TestCase):
    def _vp001(self, items):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "b.kicad_pcb")
            p.write_text(board_text(items, "(pcbplotparams (viasonmask true))"),
                         encoding="utf-8")
            res = analyze_pcb(str(p), include_trace_segments=True)
        tv = [f for f in res["findings"] if f.get("rule_id") == "TV-001"]
        vp = [f["summary"] for f in res["findings"] if f.get("rule_id") == "VP-001"]
        return tv, vp

    def test_signal_pad_of_a_footprint_with_a_thermal_pad_is_checked(self):
        # Untented via in signal pad 1 at (14.25, 7.5); two thermal vias in the exposed pad.
        tv, vp = self._vp001(qfn() + via(14.25, 7.5, net=3) + via(14.5) + via(15.5))
        self.assertEqual(len(tv), 1)
        self.assertEqual(vp, ["Via in pad: U1:1 (exposed by the pad's mask opening)"])

    def test_vias_in_the_thermal_pad_are_left_to_tv001(self):
        tv, vp = self._vp001(qfn() + via(14.5) + via(15.5))
        self.assertEqual(tv[0]["via_count"], 2)
        self.assertEqual(vp, [])

    def test_vias_in_a_heatsink_pad_are_intentional(self):
        # A second, small GND pad with KiCad's heatsink property beside the exposed pad: too
        # small for TV-001, its via is still a deliberate thermal via.
        fp = qfn().replace(
            '(net 1 GND))', '(net 1 GND)) (pad 6 smd rect (at 0 2.5) (size 1 0.8)'
            ' (layers F.Cu F.Paste F.Mask) (net 1 GND) (property pad_prop_heatsink))', 1)
        tv, vp = self._vp001(fp + via(14.5) + via(15.5) + via(15, 12.5))
        self.assertEqual([e["pad_number"] for e in tv], ["5"])
        self.assertEqual(vp, [])


if __name__ == "__main__":
    unittest.main()
