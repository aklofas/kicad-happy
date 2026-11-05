"""DP-003 grades a differential pair's layer change by RP-001's ground-via stitching."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from emc_rules import check_diff_pair_reference_plane  # noqa: E402

SCHEMATIC = {"design_analysis": {"differential_pairs": [
    {"positive": "USB_DP", "negative": "USB_DM", "type": "USB", "shared_ics": ["U1"]}]}}


def _transition(net, positions):
    return {"net": net, "via_count": len(positions), "copper_layers": ["F.Cu", "B.Cu"],
            "via_positions": [{"x": x, "y": y} for x, y in positions]}


def _severities(signal_vias, ground_vias, with_via_list=True):
    pcb = {"nets": {"1": "GND"},
           "layer_transitions": [_transition("USB_DP", signal_vias)]}
    if with_via_list:
        pcb["vias"] = {"vias": [{"x": x, "y": y, "net_name": "GND"} for x, y in ground_vias]}
    return [f["severity"] for f in check_diff_pair_reference_plane(pcb, SCHEMATIC)]


class Dp003Stitching(unittest.TestCase):
    def test_every_transition_stitched_is_info(self):
        self.assertEqual(_severities([(0, 0), (10, 0)], [(0.5, 0), (10, 0.8)]), ["info"])

    def test_one_unstitched_via_is_a_warning(self):
        self.assertEqual(_severities([(0, 0), (10, 0)], [(0.5, 0), (14, 0)]), ["warning"])

    def test_no_ground_vias_is_a_warning(self):
        self.assertEqual(_severities([(0, 0)], []), ["warning"])

    def test_no_via_list_is_a_warning(self):
        self.assertEqual(_severities([(0, 0)], [], with_via_list=False), ["warning"])

    def test_transition_without_positions_is_a_warning(self):
        pcb = {"layer_transitions": [{"net": "USB_DP", "via_count": 1,
                                      "copper_layers": ["F.Cu", "B.Cu"]}],
               "vias": {"vias": [{"x": 0, "y": 0, "net_name": "GND"}]}}
        self.assertEqual([f["severity"] for f in check_diff_pair_reference_plane(pcb, SCHEMATIC)],
                         ["warning"])

    def test_description_names_the_radius(self):
        pcb = {"layer_transitions": [_transition("USB_DP", [(0, 0)])],
               "vias": {"vias": [{"x": 0.5, "y": 0, "net_name": "GND"}]}}
        (finding,) = check_diff_pair_reference_plane(pcb, SCHEMATIC)
        self.assertIn("within 1mm", finding["description"])

    def test_without_a_via_list_the_description_says_stitching_was_not_checked(self):
        pcb = {"layer_transitions": [_transition("USB_DP", [(0, 0)])]}
        (finding,) = check_diff_pair_reference_plane(pcb, SCHEMATIC)
        self.assertIn("No via list", finding["description"])
        self.assertIn("--full", finding["description"])
        self.assertNotIn("not all with a ground via", finding["description"])

    def test_unstitched_description_with_a_via_list_names_the_radius(self):
        pcb = {"layer_transitions": [_transition("USB_DP", [(0, 0)])],
               "vias": {"vias": [{"x": 20, "y": 0, "net_name": "GND"}]}}
        (finding,) = check_diff_pair_reference_plane(pcb, SCHEMATIC)
        self.assertIn("not all with a ground via within 1mm", finding["description"])

    def test_one_ground_via_can_stitch_both_signal_vias(self):
        self.assertEqual(_severities([(0, 0), (1.5, 0)], [(0.75, 0)]), ["info"])

    def test_the_radius_is_inclusive(self):
        self.assertEqual(_severities([(0, 0)], [(1.0, 0)]), ["info"])
        self.assertEqual(_severities([(0, 0)], [(1.01, 0)]), ["warning"])

    def test_the_stated_radius_is_the_one_used(self):
        pcb = {"setup": {"stackup": [{"type": "core", "thickness": 1.51}]},
               "layer_transitions": [_transition("USB_DP", [(0, 0)])],
               "vias": {"vias": [{"x": 3.0, "y": 0, "net_name": "GND"}]}}
        (finding,) = check_diff_pair_reference_plane(pcb, SCHEMATIC)
        self.assertEqual(finding["severity"], "info")
        self.assertIn("within 3.02mm", finding["description"])


if __name__ == "__main__":
    unittest.main()
