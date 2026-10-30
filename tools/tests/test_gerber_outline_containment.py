"""GR-002 reports copper that lies outside the board outline.

Every layer of one KiCad export is registered by construction, so layers of
different sizes (copper that does not reach the board edge) are not a defect.
What a fab rejects is copper outside the board profile. Extents are compared in
millimetres per file (``%MOIN*%`` / ``%MOMM*%``), arcs add the axis extremes
they sweep (Gerber spec 4.7: ``G75`` multi-quadrant, start == end is a full
circle), and drill files are not compared.
"""
import os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
import analyze_gerbers as ag  # noqa: E402

HEAD_MM = "%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.100000*%\nD10*\n"


def _square(func, x0, y0, x1, y1, head=HEAD_MM, scale=1_000_000):
    """A closed rectangle drawn on a layer with the given X2 FileFunction."""
    def c(x, y):
        return f"X{round(x * scale)}Y{round(y * scale)}"
    return (f"%TF.FileFunction,{func}*%\n{head}"
            f"{c(x0, y0)}D02*\n{c(x1, y0)}D01*\n{c(x1, y1)}D01*\n"
            f"{c(x0, y1)}D01*\n{c(x0, y0)}D01*\nM02*\n")


EDGE = _square("Profile,NP", 0, 0, 10, 10)


def _write(d, name, text):
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        f.write(text)


def _run(files):
    with tempfile.TemporaryDirectory() as d:
        for name, text in files.items():
            _write(d, name, text)
        return ag.analyze_gerbers(d)


def _gr002(r):
    return [f["summary"] for f in r["findings"] if f["rule_id"] == "GR-002"]


def _parse(text):
    with tempfile.TemporaryDirectory() as d:
        _write(d, "x.gbr", text)
        return ag.parse_gerber(os.path.join(d, "x.gbr"))


class OutlineContainmentTest(unittest.TestCase):
    def test_registered_layers_are_aligned(self):
        r = _run({"b-F_Cu.gtl": _square("Copper,L1,Top", 0, 0, 10, 10),
                  "b-B_Cu.gbl": _square("Copper,L2,Bot", 0, 0, 10, 10),
                  "b-Edge_Cuts.gm1": EDGE})
        self.assertTrue(r["alignment"]["aligned"])
        self.assertEqual(r["alignment"]["issues"], [])
        self.assertEqual(_gr002(r), [])

    def test_copper_shifted_past_the_outline_is_reported(self):
        r = _run({"b-F_Cu.gtl": _square("Copper,L1,Top", 5, 0, 15, 10),
                  "b-B_Cu.gbl": _square("Copper,L2,Bot", 0, 0, 10, 10),
                  "b-Edge_Cuts.gm1": EDGE})
        self.assertFalse(r["alignment"]["aligned"])
        # 15 - 10 = 5 mm past the right edge; tolerance max(2, 5 % of 10) = 2 mm.
        self.assertEqual(r["alignment"]["issues"],
                         ["F.Cu extends 5.0mm outside the board outline"])
        self.assertEqual(len(_gr002(r)), 1)
        self.assertIn("F.Cu", _gr002(r)[0])

    def test_copper_inside_the_outline_is_aligned(self):
        # Copper 2..8 inside a 0..10 outline: a narrower layer, not a defect.
        r = _run({"b-F_Cu.gtl": _square("Copper,L1,Top", 2, 2, 8, 8),
                  "b-B_Cu.gbl": _square("Copper,L2,Bot", 2, 2, 8, 8),
                  "b-Edge_Cuts.gm1": EDGE})
        self.assertTrue(r["alignment"]["aligned"])
        self.assertEqual(_gr002(r), [])
        self.assertEqual(r["alignment"]["layer_extents"]["F.Cu"], {"width": 6.0, "height": 6.0})

    def test_inch_outline_with_mm_copper(self):
        edge_in = _square("Profile,NP", 0, 0, 0.4, 0.4,
                          head="%FSLAX46Y46*%\n%MOIN*%\n%ADD10C,0.004000*%\nD10*\n")
        r = _run({"b-F_Cu.gtl": _square("Copper,L1,Top", 0, 0, 10, 10),
                  "b-Edge_Cuts.gm1": edge_in})
        self.assertTrue(r["alignment"]["aligned"])
        # 0.4 in = 10.16 mm.
        self.assertEqual(r["alignment"]["layer_extents"]["Edge.Cuts"], {"width": 10.16, "height": 10.16})
        self.assertEqual(r["board_dimensions"]["width_mm"], 10.16)

    def test_drill_holes_are_not_compared(self):
        # Holes 100 mm away (a drill file in another origin or unit) are not copper.
        exc = "M48\nMETRIC\nT1C0.800\n%\nG90\nG05\nT1\nX110.0Y110.0\nX115.0Y115.0\nM30\n"
        r = _run({"b-F_Cu.gtl": _square("Copper,L1,Top", 0, 0, 10, 10),
                  "b-Edge_Cuts.gm1": EDGE, "b.drl": exc})
        self.assertTrue(r["alignment"]["aligned"])
        self.assertIn("drill_unknown", r["alignment"]["layer_extents"])

    def test_two_outline_files_both_bound_the_board(self):
        # An older 0..6 outline left beside the 0..10 one: copper 0..10 is inside the board.
        r = _run({"b-F_Cu.gtl": _square("Copper,L1,Top", 0, 0, 10, 10),
                  "b-Edge_Cuts.gbr": EDGE,
                  "b-Edge_Cuts.gko": _square("Profile,NP", 0, 0, 6, 10)})
        self.assertTrue(r["alignment"]["aligned"])

    def test_no_outline_no_gr002(self):
        r = _run({"b-F_Cu.gtl": _square("Copper,L1,Top", 0, 0, 10, 10),
                  "b-B_Cu.gbl": _square("Copper,L2,Bot", 50, 50, 90, 90)})
        self.assertTrue(r["alignment"]["aligned"])

    def test_g75_arc_bulge_counts(self):
        # Start (75, -75.5), centre = start + (I, J) = (71, -75.5), r = 4; the CCW
        # half-turn to (67, -75.5) passes the top of the circle at y = -71.5.
        g = _parse("%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.100000*%\nD10*\n"
                   "X75000000Y-75500000D02*\nG75*\nG03*\nX67000000Y-75500000I-4000000J0D01*\nM02*\n")
        cr = g["coordinate_range"]
        self.assertEqual((cr["x_min"], cr["x_max"], cr["y_min"], cr["y_max"]),
                         (67.0, 75.0, -75.5, -71.5))

    def test_g75_full_circle(self):
        # Centre (5, 10), r 5, start == end: a full circle covers x 0..10, y 5..15.
        g = _parse("%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.100000*%\nD10*\nG75*\n"
                   "X10000000Y10000000D02*\nG02X10000000Y10000000I-5000000J0D01*\nM02*\n")
        cr = g["coordinate_range"]
        self.assertEqual((cr["x_min"], cr["x_max"], cr["y_min"], cr["y_max"]),
                         (0.0, 10.0, 5.0, 15.0))

    def test_semicircle_outline_end_is_inside(self):
        # A rounded outline end bulges past its chord; copper under the bulge is inside.
        edge = ("%TF.FileFunction,Profile,NP*%\n" + HEAD_MM + "G75*\n"
                "X0Y0D02*\nX10000000Y0D01*\nG03X10000000Y10000000I0J5000000D01*\n"
                "G01X0Y10000000D01*\nX0Y0D01*\nM02*\n")
        r = _run({"b-F_Cu.gtl": _square("Copper,L1,Top", 0, 0, 14, 10),
                  "b-Edge_Cuts.gm1": edge})
        self.assertEqual(r["alignment"]["layer_extents"]["Edge.Cuts"], {"width": 15.0, "height": 10.0})
        self.assertTrue(r["alignment"]["aligned"])

    def test_inch_coordinates_are_millimetres(self):
        g = _parse("%FSLAX24Y24*%\n%MOIN*%\n%ADD10C,0.0100*%\nD10*\nX10000Y5000D03*\nM02*\n")
        cr = g["coordinate_range"]
        self.assertEqual((cr["x_min"], cr["y_min"]), (25.4, 12.7))


class ExcellonHeaderTest(unittest.TestCase):
    def _is(self, text):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "p.nc", text)
            return ag._is_excellon_file(Path(d) / "p.nc")

    def test_m48_header_line_is_excellon(self):
        self.assertTrue(self._is("M48\nMETRIC\nT1C0.800\n%\nT1\nX1.0Y1.0\nM30\n"))

    def test_m48_inside_a_cnc_line_is_not_excellon(self):
        # A LinuxCNC program enabling feed overrides (M48) is not a drill file.
        self.assertFalse(self._is("%\n(mill pocket)\nG21 G90 G17\nG0 Z5 M48\nG1 X10 Y10 F300\nM2\n%\n"))


if __name__ == "__main__":
    unittest.main()
