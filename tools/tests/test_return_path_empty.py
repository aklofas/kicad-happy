# tools/tests/test_return_path_empty.py
"""An empty return-path result means "ran, no gaps"; only an absent key means "not run".

One F.Cu track of net SIG runs x=2..18 at y=10 over a B.Cu GND fill covering x 0..20, y 5..15,
so every sample has a reference and the analyzer reports no gap."""
import os, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pcb.pipeline import analyze_pcb  # noqa: E402
from emc_rules import check_return_path_coverage  # noqa: E402
from test_pcb_return_path_reference import board, zone  # noqa: E402


def analyze(text, full=True):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "b.kicad_pcb"
        p.write_text(text, encoding="utf-8")
        cwd = os.getcwd()
        os.chdir(d)
        try:
            return analyze_pcb(str(p), include_trace_segments=full)
        finally:
            os.chdir(cwd)


def titles(pcb):
    return [f["summary"] for f in check_return_path_coverage(pcb)]


class EmptyResult(unittest.TestCase):
    def test_full_board_over_ground_keeps_empty_list_and_no_finding(self):
        out = analyze(board(zone("GND", "B.Cu")))
        self.assertEqual(out["return_path_continuity"], [])
        self.assertEqual(titles(out), [])

    def test_without_full_key_absent_and_run_full_text(self):
        out = analyze(board(zone("GND", "B.Cu")), full=False)
        self.assertNotIn("return_path_continuity", out)
        (f,) = check_return_path_coverage(out)
        self.assertIn("--full", f["recommendation"])
        self.assertEqual(f["summary"], "Return path analysis data not available")

    def test_full_board_without_any_fill_says_no_plane_fill(self):
        out = analyze(board(""))
        self.assertNotIn("return_path_continuity", out)
        (f,) = check_return_path_coverage(out)
        self.assertIn("no ground or power plane fill", f["summary"])
        self.assertNotIn("--full", f["recommendation"])

    def test_zone_flagged_filled_without_polygons_says_no_plane_fill(self):
        # (fill yes ...) but the file holds no filled_polygon: the pour was never filled/saved
        z = ('(zone (net 2) (net_name "GND") (layer "B.Cu") (hatch edge 0.5)'
             ' (connect_pads (clearance 0.2)) (min_thickness 0.25) (fill yes (thermal_gap 0.5)'
             ' (thermal_bridge_width 0.5)) (polygon (pts (xy 0 5) (xy 20 5) (xy 20 15) (xy 0 15))))\n')
        out = analyze(board(z))
        self.assertTrue(out["zones"][0]["is_filled"])
        self.assertNotIn("return_path_continuity", out)
        (f,) = check_return_path_coverage(out)
        self.assertIn("no ground or power plane fill", f["summary"])

    def test_fills_present_but_key_missing_points_at_older_analyzer(self):
        out = analyze(board(zone("GND", "B.Cu")))
        del out["return_path_continuity"]
        (f,) = check_return_path_coverage(out)
        self.assertIn("older analyzer", f["description"])
        self.assertEqual(f["summary"], "Return path analysis data not available")

    def test_a_real_gap_is_still_reported(self):
        out = analyze(board(zone("GND", "B.Cu", 40, 45, 40, 45)))
        (e,) = out["return_path_continuity"]
        self.assertEqual(e["net"], "SIG")
        self.assertLess(e["reference_plane_coverage_pct"], 95)
        self.assertTrue(titles(out))


if __name__ == "__main__":
    unittest.main()
