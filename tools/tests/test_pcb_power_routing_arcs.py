"""Power-net routing statistics count arc tracks."""
import math, sys, unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.routing import analyze_power_nets  # noqa: E402


class PowerRoutingArcs(unittest.TestCase):
    def test_narrow_arc_counts(self):
        tracks = {
            "segments": [{"net": 1, "width": 1.0, "x1": 0, "y1": 0, "x2": 1, "y2": 0,
                          "layer": "F.Cu"}],
            "arcs": [{"net": 1, "width": 0.25, "start": (1, 0), "mid": (6, 5),
                      "end": (11, 0), "layer": "F.Cu"}],
        }
        res = analyze_power_nets([], tracks, {1: "GND"})
        self.assertEqual(len(res), 1)
        r = res[0]
        self.assertEqual(r["track_count"], 2)
        self.assertAlmostEqual(r["total_length_mm"], round(1 + 5 * math.pi, 2), places=2)
        self.assertEqual(r["min_width_mm"], 0.25)
        self.assertEqual(r["widths_used"], [0.25, 1.0])

    def test_arc_only_net_and_missing_mid(self):
        tracks = {"segments": [], "arcs": [
            {"net": 1, "width": 0.5, "start": (0, 0), "end": (3, 4), "layer": "F.Cu"}]}
        r = analyze_power_nets([], tracks, {1: "+5V"})[0]
        self.assertEqual(r["track_count"], 1)
        self.assertAlmostEqual(r["total_length_mm"], 5.0)


if __name__ == "__main__":
    unittest.main()
