"""RP-002 / PS-002 plane-gap crossings: what the evidence supports."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import cross_analysis as ca  # noqa: E402

SCH = {"net_classifications": {"CLK": {"type": "clock"}}}
_ABSENT = object()


def _pcb(rpc=_ABSENT, crossing=True):
    # GND has two two-pad islands with a gap rectangle between them; CLK
    # runs across that rectangle (or well clear of it).
    y = 5 if crossing else 50
    pcb = {
        "nets": {"1": "GND", "2": "CLK"},
        "tracks": {"segments": [{"net": 2, "x1": 0, "y1": y, "x2": 20, "y2": y,
                                 "layer": "F.Cu", "width": 0.2}]},
        "connectivity_graph": {"GND": {
            "islands": 2,
            "gaps": [{"layer": "B.Cu", "bbox": [5, 0, 15, 10], "between_islands": [0, 1]}],
            "components": {"a": 0, "b": 0, "c": 1, "d": 1}}},
    }
    if rpc is not _ABSENT:
        pcb["return_path_continuity"] = rpc
    return pcb


FLAGGED = [{"net": "CLK", "reference_plane_coverage_pct": 60.0}]


class Rec:
    def __init__(self):
        self.rows = {}

    def record(self, check, ran, reason, items, n):
        self.rows[check] = (ran, reason, items, n)


def _rule(findings, rule_id):
    return [f for f in findings if f["rule_id"] == rule_id]


class ReturnPathCrossings(unittest.TestCase):
    def test_flagged_net_crossing_is_heuristic(self):
        rp = _rule(ca.check_return_path_enhanced(SCH, _pcb(FLAGGED)), "RP-002")
        self.assertEqual(len(rp), 1)
        self.assertEqual(rp[0]["confidence"], "heuristic")
        self.assertEqual(rp[0]["nets"], ["CLK", "GND"])

    def test_no_coverage_data_reports_no_crossing(self):
        self.assertEqual(ca.check_return_path_enhanced(SCH, _pcb()), [])

    def test_measured_clean_coverage_reports_no_crossing(self):
        self.assertEqual(ca.check_return_path_enhanced(SCH, _pcb([])), [])

    def test_unflagged_net_reports_no_crossing(self):
        clean = [{"net": "CLK", "reference_plane_coverage_pct": 99.0}]
        self.assertEqual(ca.check_return_path_enhanced(SCH, _pcb(clean)), [])


class ReturnPathAvailability(unittest.TestCase):
    def test_absent_coverage_records_not_run(self):
        rec = Rec()
        self.assertEqual(ca.check_return_path_enhanced(SCH, _pcb(), recorder=rec), [])
        self.assertEqual(rec.rows["RP-002"],
                         (False, "no return-path coverage in PCB analysis (zone fills unavailable)", 0, 0))

    def test_measured_clean_coverage_records_run(self):
        rec = Rec()
        ca.check_return_path_enhanced(SCH, _pcb([]), recorder=rec)
        self.assertEqual(rec.rows["RP-002"], (True, None, 1, 0))


class PlaneSplitCrossings(unittest.TestCase):
    def test_split_with_crossing_is_heuristic(self):
        ps = _rule(ca.check_plane_splits(SCH, _pcb(FLAGGED)), "PS-002")
        self.assertEqual(len(ps), 1)
        self.assertIn("1 signals crossing", ps[0]["summary"])
        self.assertEqual(ps[0]["confidence"], "heuristic")

    def test_island_count_only_stays_deterministic(self):
        ps = _rule(ca.check_plane_splits(SCH, _pcb(FLAGGED, crossing=False)), "PS-002")
        self.assertEqual(len(ps), 1)
        self.assertEqual(ps[0]["severity"], "info")
        self.assertEqual(ps[0]["confidence"], "deterministic")


if __name__ == "__main__":
    unittest.main()
