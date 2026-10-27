# tools/tests/test_pcb_polygon_arcs.py
"""Arcs inside (pts ...) lists of polygons are read whole, as KiCad's parseOutlinePoints does."""
import math, os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.sexp import parse as parse_sexp  # noqa: E402
from pcb.geometry import pts_coords, arc_points  # noqa: E402
from pcb.pipeline import read_board  # noqa: E402

PTS = ('(pts (arc (start 0 5) (mid 1.4645 1.4645) (end 5 0)) (xy 45 0) '
       '(arc (start 45 0) (mid 48.5355 1.4645) (end 50 5)) (xy 50 55) (xy 0 55))')


def _board(body):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "b.kicad_pcb")
    with open(p, "w", encoding="utf-8") as f:
        f.write('(kicad_pcb (version 20240108) (generator "pcbnew")\n'
                '(layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))\n'
                '(net 0 "")\n' + body + ')\n')
    return p


class TestPolygonArcs(unittest.TestCase):
    def test_pts_coords_expands_arcs_in_order(self):
        c = pts_coords(parse_sexp(PTS))
        self.assertEqual(c[0], (0.0, 5.0))
        self.assertIn((50.0, 55.0), c)
        self.assertEqual(c[-1], (0.0, 55.0))
        self.assertGreater(len(c), 8)
        xs = [p[0] for p in c]
        self.assertAlmostEqual(min(xs), 0.0, places=6)
        self.assertAlmostEqual(max(xs), 50.0, places=6)

    def test_duplicate_joint_dropped(self):
        c = pts_coords(parse_sexp('(pts (xy 5 0) (arc (start 5 0) (mid 6 1) (end 7 0)))'))
        self.assertEqual(c.count((5.0, 0.0)), 1)

    def test_arc_points_on_circle(self):
        for x, y in arc_points((10, 0), (0, 10), (-10, 0)):
            self.assertAlmostEqual(math.hypot(x, y), 10.0, places=6)

    def test_outline_gr_poly_with_arcs(self):
        body = '(gr_poly %s (stroke (width 0.1) (type solid)) (fill none) (layer "Edge.Cuts"))\n' % PTS
        o = read_board(_board(body)).outline
        self.assertTrue(o["edges"])
        bb = o["bounding_box"]
        self.assertAlmostEqual(bb["max_x"] - bb["min_x"], 50.0, places=2)
        self.assertAlmostEqual(bb["max_y"] - bb["min_y"], 55.0, places=2)

    def test_zone_outline_arc_corner_area(self):
        # 10 x 10 square whose (10,0) corner is rounded by a quarter circle of radius 4
        r = 4.0
        c = 6 + 0.0
        mx = 6 + r * math.sin(math.radians(45))
        my = 4 - r * math.cos(math.radians(45))
        body = ('(zone (net 0) (net_name "") (layer "F.Cu") (hatch edge 0.5)\n'
                '(polygon (pts (xy 0 0) (xy 6 0) (arc (start 6 0) (mid %.6f %.6f) (end 10 4)) '
                '(xy 10 10) (xy 0 10))))\n' % (mx, my))
        z = read_board(_board(body)).zones[0]
        expected = 100.0 - r * r * (1 - math.pi / 4)
        self.assertAlmostEqual(z["outline_area_mm2"], expected, delta=0.01)


if __name__ == "__main__":
    unittest.main()
