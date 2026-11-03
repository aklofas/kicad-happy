# tools/tests/test_pcb_orientation_rounding.py
"""OR-001 treats angles that round to the same multiple of 180 degrees as one orientation."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.assembly import analyze_orientation_consistency  # noqa: E402


def _passives(base, odd, prefix="R"):
    fps = [{"reference": f"{prefix}{i}", "pads": [1, 2], "layer": "F.Cu", "angle": base}
           for i in range(1, 7)]
    fps.append({"reference": f"{prefix}7", "pads": [1, 2], "layer": "F.Cu", "angle": odd})
    return fps


class OrientationRounding(unittest.TestCase):
    def test_same_orientation_is_not_flagged(self):
        for odd in (179.6, 359.6, -0.4, -180.4, 180, 360, -5.7e-15):
            with self.subTest(odd=odd):
                self.assertEqual(analyze_orientation_consistency(_passives(0, odd)), [])

    def test_quarter_turn_variants(self):
        for odd in (90.4, 269.6, -90.4):
            with self.subTest(odd=odd):
                self.assertEqual(analyze_orientation_consistency(_passives(90, odd)), [])

    def test_real_deviator_is_still_flagged(self):
        f = analyze_orientation_consistency(_passives(0, 90))
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["majority_angle"], 0)
        self.assertEqual(f[0]["deviator_count"], 1)

    def test_buckets_stay_in_range(self):
        for a in (179.6, 359.6, -0.4, -180.4, 90.4, 180):
            f = analyze_orientation_consistency(_passives(45, a))
            self.assertEqual(len(f), 1)
            self.assertTrue(0 <= f[0]["majority_angle"] < 180)


if __name__ == "__main__":
    unittest.main()
