"""CK-001 and DP-004 measure the share routed on outer layers by track length."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from emc_rules import check_clock_routing, check_diff_pair_layer  # noqa: E402

PAIRS = {"design_analysis": {"differential_pairs": [
    {"positive": "USB_DP", "negative": "USB_DM", "type": "USB", "shared_ics": ["U1"]}]}}

# Six short F.Cu fanout segments (18 mm) and two long In1.Cu runs (80 mm):
# 75 % of the segments but 18 % of the length on an outer layer.
FANOUT = {"F.Cu": {"length_mm": 18.0, "segments": 6}, "In1.Cu": {"length_mm": 80.0, "segments": 2}}
# Two long F.Cu runs and six short In1.Cu pieces: 25 % of the segments, 82 % of the length.
OUTER_RUN = {"F.Cu": {"length_mm": 80.0, "segments": 2}, "In1.Cu": {"length_mm": 18.0, "segments": 6}}


def _board(layers_by_net):
    return {"layers": [{"name": n} for n in ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")], "zones": [],
            "net_lengths": [{"net": net, "total_length_mm": 98.0, "layers": layers}
                            for net, layers in layers_by_net.items()]}


def _rule(findings, rule_id):
    return [f for f in findings if f["rule_id"] == rule_id]


class ClockOuterShare(unittest.TestCase):
    def test_fanout_segments_do_not_make_an_outer_layer_clock(self):
        self.assertEqual(_rule(check_clock_routing(_board({"MCU_CLK": FANOUT})), "CK-001"), [])

    def test_long_outer_run_fires_with_the_length_share(self):
        (finding,) = _rule(check_clock_routing(_board({"MCU_CLK": OUTER_RUN})), "CK-001")
        self.assertIn("82% routed on outer layers", finding["description"])

    def test_segments_only_layers_fall_back_to_segment_counts(self):
        layers = {"F.Cu": {"segments": 3}, "In1.Cu": {"segments": 1}}
        (finding,) = _rule(check_clock_routing(_board({"MCU_CLK": layers})), "CK-001")
        self.assertIn("75% routed on outer layers", finding["description"])


class DiffPairOuterShare(unittest.TestCase):
    def test_fanout_segments_do_not_make_an_outer_layer_pair(self):
        pcb = _board({"USB_DP": FANOUT, "USB_DM": FANOUT})
        self.assertEqual(check_diff_pair_layer(pcb, PAIRS), [])

    def test_long_outer_run_fires_with_the_length_share(self):
        pcb = _board({"USB_DP": OUTER_RUN, "USB_DM": FANOUT})
        (finding,) = check_diff_pair_layer(pcb, PAIRS)
        self.assertEqual(finding["nets"], ["USB_DP"])
        self.assertIn("82% routed on outer layers", finding["description"])

    def test_segments_only_layers_fall_back_to_segment_counts(self):
        layers = {"F.Cu": {"segments": 3}, "In1.Cu": {"segments": 1}}
        pcb = _board({"USB_DP": layers, "USB_DM": layers})
        self.assertEqual(len(check_diff_pair_layer(pcb, PAIRS)), 2)

    def test_net_with_no_measured_routing_is_skipped(self):
        layers = {"F.Cu": {"length_mm": 0.0, "segments": 0}}
        pcb = _board({"USB_DP": layers, "USB_DM": layers})
        self.assertEqual(check_diff_pair_layer(pcb, PAIRS), [])


if __name__ == "__main__":
    unittest.main()
