"""RP-001 and VS-001 on a PCB whose via list has no ground via."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from emc_rules import check_layer_transition_stitching, check_via_stitching  # noqa: E402

GND_POURS = [{"net_name": "GND", "layers": ["F.Cu"], "filled_area_mm2": 2000},
             {"net_name": "GND", "layers": ["B.Cu"], "filled_area_mm2": 2400}]


def _board(zones, ground_vias=(), signal=((10, 10), (30, 30))):
    vias = [{"net": 2, "x": x, "y": y} for x, y in signal]
    vias += [{"net": 1, "x": x, "y": y} for x, y in ground_vias]
    return {"nets": {"1": "GND", "2": "SIG"},
            "board_outline": {"bounding_box": {"width": 50, "height": 50}},
            "vias": {"vias": vias},
            "layer_transitions": [{"net": "SIG", "copper_layers": ["F.Cu", "B.Cu"],
                                   "via_positions": [{"x": x, "y": y} for x, y in signal]}],
            "zones": zones}


class TwoGroundPoursNoGroundVia(unittest.TestCase):
    def test_rp001_reports_the_unstitched_transition(self):
        findings = check_layer_transition_stitching(_board(GND_POURS))
        self.assertEqual([(f["rule_id"], f["severity"]) for f in findings], [("RP-001", "warning")])

    def test_vs001_counts_zero_ground_vias(self):
        (finding,) = check_via_stitching(_board(GND_POURS))
        self.assertEqual(finding["rule_id"], "VS-001")
        self.assertIn("Board has 0 ground vias", finding["description"])
        self.assertIn("no ground vias detected", finding["description"])

    def test_one_ground_pour_is_not_a_plane_pair(self):
        self.assertEqual(check_layer_transition_stitching(_board(GND_POURS[:1])), [])


class NoGroundFill(unittest.TestCase):
    def test_neither_rule_fires(self):
        self.assertEqual(check_layer_transition_stitching(_board([])), [])
        self.assertEqual(check_via_stitching(_board([])), [])

    def test_single_signal_via_is_not_reported_as_sparse_stitching(self):
        self.assertEqual(check_via_stitching(_board([], signal=[(10, 10)])), [])

    def test_unfilled_ground_zone_is_not_fill(self):
        zones = [{"net_name": "GND", "layers": ["F.Cu"]}, {"net_name": "GND", "layers": ["B.Cu"]}]
        self.assertEqual(check_layer_transition_stitching(_board(zones)), [])
        self.assertEqual(check_via_stitching(_board(zones)), [])


class WithGroundVias(unittest.TestCase):
    def test_stitched_transitions_stay_silent(self):
        board = _board(GND_POURS, ground_vias=[(10.5, 10), (30.5, 30)])
        self.assertEqual(check_layer_transition_stitching(board), [])

    def test_unstitched_transition_still_fires(self):
        board = _board([], ground_vias=[(10.5, 10)])
        findings = check_layer_transition_stitching(board)
        self.assertEqual([(f["rule_id"], f["severity"]) for f in findings], [("RP-001", "info")])

    def test_vs001_counts_the_ground_vias(self):
        board = _board([], ground_vias=[(10.5, 10)])
        (finding,) = check_via_stitching(board)
        self.assertIn("Board has 1 ground vias", finding["description"])

    def test_dense_ground_vias_stay_silent(self):
        board = _board(GND_POURS, ground_vias=[(10.5, 10), (30.5, 30)])
        self.assertEqual(check_via_stitching(board), [])


if __name__ == "__main__":
    unittest.main()
