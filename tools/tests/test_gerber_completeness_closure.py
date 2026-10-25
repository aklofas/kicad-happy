"""Gerber completeness follows the stackup, GR-005 tests outline closure, X2 pins carry their own net."""
import os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
import analyze_gerbers as ag  # noqa: E402

LINE = "X0Y0D02*\nX1000000Y0D01*\n"
DRILL_PTH = "M48\n;TYPE=PLATED\nMETRIC\nT1C0.3\n%\nT1\nX1.0Y1.0\nM30\n"


def _gbr(d, name, ff, body=LINE, units="%MOMM*%"):
    head = f"%TF.FileFunction,{ff}*%\n" if ff else ""
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        f.write(f"{head}%FSLAX46Y46*%\n{units}\n%ADD10C,0.1*%\nD10*\n{body}M02*\n")


def _drill(d, name="b.drl", text=DRILL_PTH):
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        f.write(text)


def _stack(d, copper):
    """copper: [(filename, FileFunction)]; adds masks, a closed Edge.Cuts square and a PTH drill."""
    for name, ff in copper:
        _gbr(d, name, ff)
    _gbr(d, "b-F_Mask.gts", "Soldermask,Top")
    _gbr(d, "b-B_Mask.gbs", "Soldermask,Bot")
    _gbr(d, "b-Edge_Cuts.gm1", "Profile,NP", SQUARE)
    _drill(d)


# 10 mm square, every corner shared by two draws.
SQUARE = ("X0Y0D02*\nX10000000Y0D01*\nX10000000Y10000000D01*\n"
          "X0Y10000000D01*\nX0Y0D01*\n")


def _gr(result, rule):
    return [f for f in result["findings"] if f["rule_id"] == rule]


class StackupCompletenessTest(unittest.TestCase):
    def _run(self, copper, **kw):
        with tempfile.TemporaryDirectory() as d:
            _stack(d, copper)
            return ag.analyze_gerbers(d, **kw)

    def test_four_layer_missing_inner(self):
        r = self._run([("b-F_Cu.gtl", "Copper,L1,Top"), ("b-In1_Cu.g2", "Copper,L2,Inr"),
                       ("b-B_Cu.gbl", "Copper,L4,Bot")])
        c = r["completeness"]
        # L4 bottom => four copper layers => In1.Cu and In2.Cu; L2 is In1.Cu, so In2.Cu is absent.
        self.assertIn("In2.Cu", c["missing_required"])
        self.assertNotIn("In1.Cu", c["missing_required"])
        self.assertIs(c["complete"], False)
        gr001 = [f for f in _gr(r, "GR-001") if "In2.Cu" in f["summary"]]
        self.assertEqual(len(gr001), 1)

    def test_four_layer_complete(self):
        r = self._run([("b-F_Cu.gtl", "Copper,L1,Top"), ("b-In1_Cu.g2", "Copper,L2,Inr"),
                       ("b-In2_Cu.g3", "Copper,L3,Inr"), ("b-B_Cu.gbl", "Copper,L4,Bot")])
        self.assertEqual(r["completeness"]["missing_required"], [])

    def test_uppercase_gl_inner_found(self):
        r = self._run([("board.GTL", "Copper,L1,Top"), ("board.GL2", "Copper,L2,Inr"),
                       ("board.GL3", "Copper,L3,Inr"), ("board.GBL", "Copper,L4,Bot")])
        c = r["completeness"]
        self.assertIn("board.GL2", [g["filename"] for g in r["gerbers"]])
        self.assertIn("In1.Cu", c["found_layers"])
        self.assertIn("In2.Cu", c["found_layers"])
        self.assertEqual(c["missing_required"], [])

    def test_two_layer_unchanged(self):
        r = self._run([("b-F_Cu.gtl", "Copper,L1,Top"), ("b-B_Cu.gbl", "Copper,L2,Bot")])
        c = r["completeness"]
        # Defaults: F.Cu, B.Cu, F.Mask, B.Mask, Edge.Cuts required (all written);
        # F.SilkS and F.Paste recommended (none written).
        self.assertEqual(c["missing_required"], [])
        self.assertEqual(c["missing_recommended"], ["F.Paste", "F.SilkS"])
        self.assertIs(c["complete"], True)

    def test_filename_only_inner_not_inferred(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("board.GTL", "board.G2L", "board.G3L", "board.GBL",
                         "board.GTS", "board.GBS"):
                _gbr(d, name, None)
            _gbr(d, "board.GKO", None, SQUARE)
            _drill(d, "board.TXT", "M48\nMETRIC\nT1C0.3\n%\nT1\nX1.0Y1.0\nM30\n")
            c = ag.analyze_gerbers(d)["completeness"]
        # Eagle names map .G2L/.G3L to In2.Cu/In3.Cu; with no positional evidence
        # nothing beyond the found layers is required, so In1.Cu is not invented.
        self.assertEqual(c["missing_required"], [])


class OutlineClosureTest(unittest.TestCase):
    def _gr005(self, body, units="%MOMM*%"):
        with tempfile.TemporaryDirectory() as d:
            _gbr(d, "b-F_Cu.gtl", "Copper,L1,Top")
            _gbr(d, "b-B_Cu.gbl", "Copper,L2,Bot")
            _gbr(d, "b-Edge_Cuts.gm1", "Profile,NP", body, units)
            return _gr(ag.analyze_gerbers(d), "GR-005")

    def test_round_outline_closed(self):
        # One full circle: radius 10 mm, start == end, G75 multi-quadrant.
        self.assertEqual(self._gr005("X10000000Y0D02*\nG75*\nG03X10000000Y0I-10000000J0D01*\n"), [])

    def test_round_outline_inch(self):
        # The same circle in inches (FS 4.6): radius 1 in.
        self.assertEqual(self._gr005("X1000000Y0D02*\nG75*\nG03X1000000Y0I-1000000J0D01*\n",
                                     "%MOIN*%"), [])

    def test_triangle_closed(self):
        self.assertEqual(self._gr005("X0Y0D02*\nX10000000Y0D01*\nX5000000Y8000000D01*\nX0Y0D01*\n"), [])

    def test_modal_rectangle_closed(self):
        # Only the first draw names D01; the rest repeat the modal operation.
        body = ("X0Y0D02*\nX10000000Y0D01*\nY10000000*\nX0*\nY0*\n")
        self.assertEqual(self._gr005(body), [])

    def test_open_polyline(self):
        # Four draws (0,0)->(10,0)->(10,10)->(0,10)->(0,1): the last corner misses the start by 1 mm.
        body = ("X0Y0D02*\nX10000000Y0D01*\nX10000000Y10000000D01*\n"
                "X0Y10000000D01*\nX0Y1000000D01*\n")
        found = self._gr005(body)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "error")

    def test_loop_plus_stray_no_finding(self):
        body = SQUARE + "X20000000Y0D02*\nX30000000Y0D01*\n"
        self.assertEqual(self._gr005(body), [])

    def test_gap_within_tolerance_closed(self):
        # A 50 nm gap at the closing corner is inside the 0.025 mm endpoint tolerance.
        body = ("X0Y0D02*\nX10000000Y0D01*\nX10000000Y10000000D01*\n"
                "X0Y10000000D01*\nX50Y0D01*\n")
        self.assertEqual(self._gr005(body), [])


class X2PinNetTest(unittest.TestCase):
    def test_x2_pin_net_after_p(self):
        body = ("%TO.C,R1*%\n%TO.P,R1,1*%\n%TO.N,GND*%\nX0Y0D03*\n%TD*%\n"
                "%TO.P,R1,2*%\n%TO.N,VCC*%\nX2000000Y0D03*\n%TD*%\n")
        with tempfile.TemporaryDirectory() as d:
            _gbr(d, "b-F_Cu.gtl", "Copper,L1,Top", body)
            _gbr(d, "b-B_Cu.gbl", "Copper,L2,Bot")
            r = ag.analyze_gerbers(d, full=True)
        self.assertEqual(r["connectivity"],
                         [{"ref": "R1", "pin": "1", "pin_name": "", "net": "GND"},
                          {"ref": "R1", "pin": "2", "pin_name": "", "net": "VCC"}])


if __name__ == "__main__":
    unittest.main()
