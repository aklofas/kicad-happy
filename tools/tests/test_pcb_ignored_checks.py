# tools/tests/test_pcb_ignored_checks.py
"""`unconnected_items` set to ignore drops RT-001 and `copper_edge_clearance` set to ignore drops
BV-001, while the routing facts stay as measured."""
import json, os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.pipeline import analyze_pcb  # noqa: E402

PAD = '(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask") (net 1 "A"))'
# A is a two-pad net with no copper between the pads; the via sits 0.2 mm from the board edge.
BOARD = f"""(kicad_pcb (version 20221018) (generator pcbnew)
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
  (net 0 "") (net 1 "A")
  (gr_rect (start 100 100) (end 130 130) (layer "Edge.Cuts") (width 0.1))
  (via (at 100.2 115) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1))
  (footprint "L:F" (layer "F.Cu") (at 110 110)
    (property "Reference" "R1") (property "Value" "v") {PAD})
  (footprint "L:F" (layer "F.Cu") (at 120 120)
    (property "Reference" "R2") (property "Value" "v") {PAD})
)
"""


def _run(severities):
    with tempfile.TemporaryDirectory() as tmp:
        board = os.path.join(tmp, "b.kicad_pcb")
        with open(board, "w", encoding="utf-8") as f:
            f.write(BOARD)
        with open(os.path.join(tmp, "b.kicad_pro"), "w", encoding="utf-8") as f:
            json.dump({"board": {"design_settings": {"rule_severities": severities}}}, f)
        return analyze_pcb(board, include_trace_segments=True)


def _rules(result):
    return {f["rule_id"] for f in result["findings"] if f["rule_id"] in ("RT-001", "BV-001")}


class TestIgnoredChecks(unittest.TestCase):
    def test_baseline_reports_both(self):
        self.assertEqual(_rules(_run({})), {"RT-001", "BV-001"})

    def test_unconnected_items_ignored_drops_only_rt001(self):
        r = _run({"unconnected_items": "ignore"})
        self.assertEqual(_rules(r), {"BV-001"})
        self.assertFalse(r["connectivity"]["routing_complete"])
        self.assertEqual(r["connectivity"]["unrouted_count"], 1)

    def test_copper_edge_clearance_ignored_drops_only_bv001(self):
        r = _run({"copper_edge_clearance": "ignore"})
        self.assertEqual(_rules(r), {"RT-001"})
        self.assertNotIn("board_edge_via_clearance", r)

    def test_error_severity_keeps_both(self):
        r = _run({"unconnected_items": "error", "copper_edge_clearance": "error"})
        self.assertEqual(_rules(r), {"RT-001", "BV-001"})


if __name__ == "__main__":
    unittest.main()
