"""With --full, an incompletely routed net that owns a zone saved without its fill says so: the
pads may join once the zones are refilled (kicad-cli pcb drc reports such nets as unconnected
until --refill-zones)."""
import contextlib, io, os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.pipeline import analyze_pcb  # noqa: E402

REFILL = "Its zones are not filled in the saved file: refill zones before trusting this count."


def _fp(ref, x):
    return (f'(footprint "t:X" (layer "F.Cu") (at {x} 10)\n'
            f' (property "Reference" "{ref}" (at 0 -3 0) (layer "F.SilkS"))\n (attr smd)\n'
            ' (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask") (net 1 "N")))\n')


def _zone(filled):
    pts = '(pts (xy 20 2) (xy 28 2) (xy 28 6) (xy 20 6))'
    fill = (' (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))'
            f' (polygon {pts}) (filled_polygon (layer "F.Cu") {pts})' if filled
            else f' (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon {pts})')
    return ('(zone (net 1) (net_name "N") (layer "F.Cu") (hatch edge 0.5)'
            ' (connect_pads yes (clearance 0.2)) (min_thickness 0.25)' + fill + ')\n')


def _board(filled):
    return ('(kicad_pcb (version 20240108) (generator "pcbnew")\n(general (thickness 1.6))\n'
            '(layers (0 "F.Cu" signal) (31 "B.Cu" signal) (39 "F.Mask" user) (44 "Edge.Cuts" user))\n'
            '(net 0 "")\n(net 1 "N")\n'
            '(gr_rect (start 0 0) (end 30 20) (stroke (width 0.05) (type default)) (fill none)'
            ' (layer "Edge.Cuts"))\n' + _fp("U1", 10) + _fp("U2", 14) + _zone(filled) + ')\n')


def _rt001(text, full=True):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "b.kicad_pcb"
        p.write_text(text, encoding="utf-8")
        cwd = os.getcwd()
        os.chdir(d)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                res = analyze_pcb(str(p), include_trace_segments=full)
        finally:
            os.chdir(cwd)
    return [f for f in res["findings"] if f.get("rule_id") == "RT-001"]


class UnfilledZoneNet(unittest.TestCase):
    def test_unfilled_zone_net_says_to_refill(self):
        (f,) = _rt001(_board(filled=False))
        self.assertIn("2 separate copper islands", f["description"])
        self.assertTrue(f["description"].endswith(" " + REFILL))

    def test_filled_zone_net_keeps_the_plain_description(self):
        (f,) = _rt001(_board(filled=True))
        self.assertEqual(f["description"], "Net N has 2 pads on 2 separate copper islands.")


if __name__ == "__main__":
    unittest.main()
