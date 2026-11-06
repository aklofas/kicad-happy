"""DP-005 measures pair lengths with arcs included."""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import cross_analysis as ca  # noqa: E402

SCH = {"net_classifications": {"USB_DP": {"type": "usb", "differential": True},
                               "USB_DM": {"type": "usb", "differential": True}}}
# Quarter arc of radius 20/pi mm: 10 mm long.
ARC_LEN = math.pi * (20 / math.pi) / 2


def _pcb(dm_arc_mm):
    dm_len = round(10 + dm_arc_mm, 3)
    return {
        "nets": {"3": "USB_DP", "4": "USB_DM"},
        "tracks": {"segments": [
            {"net": 3, "x1": 0, "y1": 0, "x2": 20, "y2": 0, "layer": "F.Cu"},
            {"net": 4, "x1": 0, "y1": 1, "x2": 10, "y2": 1, "layer": "F.Cu"}]},
        "net_lengths": [
            {"net": "USB_DP", "total_length_mm": 20.0, "via_count": 0,
             "layers": {"F.Cu": {"length_mm": 20.0, "segments": 1}}},
            {"net": "USB_DM", "total_length_mm": dm_len, "via_count": 0,
             "layers": {"F.Cu": {"length_mm": dm_len, "segments": 2 if dm_arc_mm else 1}}}],
    }


class Dp005Lengths(unittest.TestCase):
    def test_segment_and_arc_pair_of_equal_length(self):
        self.assertEqual(ca.check_diff_pair_quality(SCH, _pcb(ARC_LEN)), [])

    def test_real_mismatch_still_fires(self):
        out = ca.check_diff_pair_quality(SCH, _pcb(0))
        self.assertEqual([f["rule_id"] for f in out], ["DP-005"])
        self.assertIn("length mismatch 10.0mm (67%)", out[0]["summary"])


if __name__ == "__main__":
    unittest.main()
