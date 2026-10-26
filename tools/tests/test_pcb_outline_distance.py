# tools/tests/test_pcb_outline_distance.py
"""Distance from a point to a board outline of lines, rects, arcs, circles, polygons and curves."""
import math, sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.geometry import outline_edge_distance  # noqa: E402
from pcb.copper import analyze_board_edge_via_clearance  # noqa: E402

CIRCLE = {"type": "circle", "center": [0, 0], "end": [10, 0]}
ARC = {"type": "arc", "start": [0, 10], "mid": [7.0711, 7.0711], "end": [10, 0]}


class TestOutlineDistance(unittest.TestCase):
    def test_no_edges(self):
        self.assertIsNone(outline_edge_distance(0, 0, []))

    def test_line(self):
        e = {"type": "line", "start": [0, 0], "end": [10, 0]}
        self.assertAlmostEqual(outline_edge_distance(5, 3, [e]), 3.0)
        self.assertAlmostEqual(outline_edge_distance(13, 4, [e]), 5.0)

    def test_rect_nearest_side(self):
        e = {"type": "rect", "start": [0, 0], "end": [10, 20]}
        self.assertAlmostEqual(outline_edge_distance(9.8, 10, [e]), 0.2)
        self.assertAlmostEqual(outline_edge_distance(5, 1, [e]), 1.0)

    def test_circle(self):
        self.assertAlmostEqual(outline_edge_distance(9.8, 0, [CIRCLE]), 0.2)
        self.assertAlmostEqual(outline_edge_distance(0, 0, [CIRCLE]), 10.0)

    def test_arc_inside_sweep(self):
        self.assertAlmostEqual(outline_edge_distance(7, 7, [ARC]), 0.1005, delta=1e-3)

    def test_arc_outside_sweep_uses_endpoint(self):
        self.assertAlmostEqual(outline_edge_distance(0, -5, [ARC]), math.hypot(10, 5), places=3)

    def test_arc_clockwise(self):
        cw = {"type": "arc", "start": [10, 0], "mid": [7.0711, 7.0711], "end": [0, 10]}
        self.assertAlmostEqual(outline_edge_distance(7, 7, [cw]), 0.1005, delta=1e-3)
        self.assertAlmostEqual(outline_edge_distance(0, -5, [cw]), math.hypot(10, 5), places=3)

    def test_polygon_ring_closes(self):
        e = {"type": "polygon", "points": [[0, 0], [10, 0], [10, 10]]}
        self.assertAlmostEqual(outline_edge_distance(4, 5, [e]), 1 / math.sqrt(2) * 1.0, places=6)

    def test_curve_sampled(self):
        pts = [[0, 0], [0, 10], [10, 10], [10, 0]]
        e = {"type": "curve", "points": pts}
        # Bezier midpoint (t = 0.5) is (5, 7.5); the 32-step sample hits it exactly.
        self.assertAlmostEqual(outline_edge_distance(5, 7.5, [e]), 0.0, places=9)
        self.assertAlmostEqual(outline_edge_distance(5, 8.5, [e]), 1.0, places=2)

    def test_full_circle_arc_does_not_raise(self):
        e = {"type": "arc", "start": [10, 0], "mid": [-10, 0], "end": [10, 0]}
        self.assertAlmostEqual(outline_edge_distance(9.8, 0, [e]), 0.2)

    def test_collinear_arc_does_not_raise(self):
        e = {"type": "arc", "start": [0, 0], "mid": [5, 0], "end": [10, 0]}
        self.assertAlmostEqual(outline_edge_distance(5, 2, [e]), 2.0)

    def test_arc_without_mid_is_skipped(self):
        # its chord may run well inside the board, so it is not an edge to measure
        e = {"type": "arc", "start": [0, 0], "mid": None, "end": [10, 0]}
        self.assertIsNone(outline_edge_distance(5, 2, [e]))
        line = {"type": "line", "start": [0, 10], "end": [10, 10]}
        self.assertAlmostEqual(outline_edge_distance(5, 2, [e, line]), 8.0)


class TestBv001(unittest.TestCase):
    def test_circle_outline_flags_near_via(self):
        out = analyze_board_edge_via_clearance(
            {"vias": [{"x": 9.8, "y": 0}, {"x": 0, "y": 0}]}, {"edges": [CIRCLE]})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["edge_clearance_mm"], 0.2)

    def test_arc_outline_flags_near_via(self):
        out = analyze_board_edge_via_clearance({"vias": [{"x": 7, "y": 7}]}, {"edges": [ARC]})
        self.assertEqual([f["edge_clearance_mm"] for f in out], [0.101])


if __name__ == "__main__":
    unittest.main()
