"""BE-001 measures the distance to polygon and curve board outlines, not to the origin."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from emc_rules import _point_to_edges_min_distance, check_trace_near_board_edge  # noqa: E402

POLYGON = {"type": "polygon", "points": [[0, 0], [100, 0], [100, 50], [0, 50]]}
# A Bezier whose control points lie on y = 0, so the curve is the segment (0,0)-(100,0)
CURVE = {"type": "curve", "points": [[0, 0], [30, 0], [70, 0], [100, 0]]}


def _pcb(edge, mid_y):
    seg = {"layer": "F.Cu", "net": 1, "x1": 49.0, "y1": mid_y, "x2": 51.0, "y2": mid_y}
    return {"tracks": {"segments": [seg]}, "board_outline": {"edges": [edge]},
            "nets": {"1": "SIG"}}


def _be001(pcb):
    return [f["rule_id"] for f in check_trace_near_board_edge(pcb, net_id_map={1: "SIG"})]


class PolygonAndCurveOutlines(unittest.TestCase):
    def test_polygon_distance_is_to_its_nearest_side(self):
        self.assertAlmostEqual(_point_to_edges_min_distance(50, 1, [POLYGON]), 1.0)
        self.assertAlmostEqual(_point_to_edges_min_distance(98, 25, [POLYGON]), 2.0)

    def test_curve_distance_is_to_the_curve(self):
        self.assertAlmostEqual(_point_to_edges_min_distance(50, 1, [CURVE]), 1.0, places=6)

    def test_trace_beside_a_polygon_edge_is_reported(self):
        self.assertEqual(_be001(_pcb(POLYGON, 0.1)), ["BE-001"])
        self.assertEqual(_be001(_pcb(POLYGON, 25.0)), [])

    def test_trace_beside_a_curve_edge_is_reported(self):
        self.assertEqual(_be001(_pcb(CURVE, 0.1)), ["BE-001"])

    def test_edge_without_points_is_skipped(self):
        line = {"type": "line", "start": [0, 10], "end": [100, 10]}
        self.assertAlmostEqual(_point_to_edges_min_distance(50, 12, [{"type": "polygon"}, line]), 2.0)


if __name__ == "__main__":
    unittest.main()
