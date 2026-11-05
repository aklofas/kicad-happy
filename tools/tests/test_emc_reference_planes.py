"""SU-001, SU-002, CK-001 and DP-004 find reference planes by zone fill, then by KiCad layer type."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from emc_rules import check_clock_routing, check_diff_pair_layer, check_stackup  # noqa: E402

BOARD_AREA = 1000.0
PAIRS = {"design_analysis": {"differential_pairs": [
    {"positive": "USB_DP", "negative": "USB_DM", "type": "USB", "shared_ics": ["U1"]}]}}


def _copper(names, dielectrics):
    stack = []
    for i, name in enumerate(names):
        stack.append({"name": name, "type": "copper", "thickness": 0.035})
        if i < len(dielectrics):
            stack.append({"name": f"dielectric {i + 1}", "type": "core",
                          "thickness": dielectrics[i]})
    return stack


def _board(types, fills=None, dielectrics=None):
    """A board with copper layers typed *types* (name -> KiCad type) and one zone per
    entry of *fills* (layer -> (net, share of the board's bounding box))."""
    names = list(types)
    zones = [{"net_name": net, "layers": [layer], "filled_area_mm2": share * BOARD_AREA}
             for layer, (net, share) in (fills or {}).items()]
    outer = {"segments": 10}
    return {
        "layers": [{"name": n, "type": t} for n, t in types.items()],
        "setup": {"stackup": _copper(names, dielectrics or [0.2] * (len(names) - 1))},
        "statistics": {"board_area_mm2": BOARD_AREA},
        "zones": zones,
        "net_lengths": [{"net": net, "total_length_mm": 40, "layers": {"F.Cu": outer}}
                        for net in ("CLK", "USB_DP", "USB_DM")],
    }


FOUR = {"F.Cu": "signal", "In1.Cu": "signal", "In2.Cu": "signal", "B.Cu": "signal"}


def _rules(findings):
    return sorted((f["rule_id"], f["severity"]) for f in findings)


class FilledInnerLayersArePlanes(unittest.TestCase):
    def setUp(self):
        self.pcb = _board(FOUR, {"In1.Cu": ("GND", 0.93), "In2.Cu": ("+3V3", 0.89)})

    def test_no_adjacent_signal_layer_error(self):
        self.assertNotIn("SU-001", [f["rule_id"] for f in check_stackup(self.pcb)])

    def test_no_stripline_request_for_clocks(self):
        self.assertEqual(check_clock_routing(self.pcb), [])

    def test_no_stripline_request_for_diff_pairs(self):
        self.assertEqual(check_diff_pair_layer(self.pcb, PAIRS), [])

    def test_a_signal_net_pour_is_not_a_plane(self):
        pcb = _board(FOUR, {"In1.Cu": ("HSE_IN", 0.85), "In2.Cu": ("GND", 0.9)})
        self.assertEqual([r for r in _rules(check_stackup(pcb)) if r[0] == "SU-001"],
                         [("SU-001", "error")])
        self.assertEqual(len(check_clock_routing(pcb)), 1)

    def test_a_spaced_rail_name_is_a_power_plane(self):
        pcb = _board(FOUR, {"In1.Cu": ("3.3V OUT", 0.89), "In2.Cu": ("GND", 0.9)})
        self.assertNotIn("SU-001", [f["rule_id"] for f in check_stackup(pcb)])
        self.assertEqual(check_clock_routing(pcb), [])

    def test_a_filled_outer_layer_is_ignored(self):
        pcb = _board(FOUR, {"F.Cu": ("GND", 0.9), "B.Cu": ("GND", 0.9)})
        self.assertEqual([r for r in _rules(check_stackup(pcb)) if r[0] == "SU-001"],
                         [("SU-001", "error")] * 3)


class SmallPourOnInnerLayer(unittest.TestCase):
    def test_mixed_layer_with_16_percent_fill_is_a_signal_layer(self):
        types = dict(FOUR, **{"In1.Cu": "mixed", "In2.Cu": "mixed"})
        pcb = _board(types, {"In1.Cu": ("GND", 0.16), "In2.Cu": ("GND", 0.19)})
        self.assertEqual([r for r in _rules(check_stackup(pcb)) if r[0] == "SU-001"],
                         [("SU-001", "error")] * 3)
        self.assertEqual(len(check_clock_routing(pcb)), 1)
        self.assertEqual(len(check_diff_pair_layer(pcb, PAIRS)), 2)

    def test_threshold_is_a_quarter_of_the_bounding_box(self):
        def su001(share):
            pcb = _board(FOUR, {"In1.Cu": ("GND", share), "In2.Cu": ("GND", share)})
            return sum(f["rule_id"] == "SU-001" for f in check_stackup(pcb))
        self.assertEqual(su001(0.25), 0)
        self.assertEqual(su001(0.24), 3)

    def test_fill_is_summed_over_the_nets_on_a_layer(self):
        pcb = _board(FOUR, {"In2.Cu": ("+3V3", 0.9)})
        pcb["zones"] += [{"net_name": "GND", "layers": ["In1.Cu"], "filled_area_mm2": 150.0},
                         {"net_name": "+5V", "layers": ["In1.Cu"], "filled_area_mm2": 150.0}]
        self.assertNotIn("SU-001", [f["rule_id"] for f in check_stackup(pcb)])

    def test_keepout_and_netless_zones_do_not_count(self):
        pcb = _board(FOUR, {"In2.Cu": ("+3V3", 0.9)})
        pcb["zones"] += [{"net_name": "GND", "layers": ["In1.Cu"], "is_keepout": True,
                          "filled_area_mm2": 900.0},
                         {"net_name": "", "layers": ["In1.Cu"], "filled_area_mm2": 900.0}]
        self.assertIn(("SU-001", "error"), _rules(check_stackup(pcb)))


class LayerTypeFallback(unittest.TestCase):
    def test_unfilled_inner_layers_go_by_type(self):
        types = dict(FOUR, **{"In1.Cu": "power", "In2.Cu": "power"})
        pcb = _board(types)
        self.assertNotIn("SU-001", [f["rule_id"] for f in check_stackup(pcb)])
        self.assertEqual(check_clock_routing(pcb), [])
        self.assertEqual(check_diff_pair_layer(pcb, PAIRS), [])

    def test_unfilled_signal_inner_layers_are_signal_layers(self):
        pcb = _board(FOUR)
        self.assertEqual([r for r in _rules(check_stackup(pcb)) if r[0] == "SU-001"],
                         [("SU-001", "error")] * 3)
        self.assertEqual(len(check_clock_routing(pcb)), 1)
        self.assertEqual(len(check_diff_pair_layer(pcb, PAIRS)), 2)

    def test_poured_two_layer_board_unchanged(self):
        pcb = _board({"F.Cu": "signal", "B.Cu": "signal"},
                     {"F.Cu": ("GND", 0.8), "B.Cu": ("GND", 0.9)}, dielectrics=[1.5])
        self.assertEqual(_rules(check_stackup(pcb)), [("SU-001", "info")])
        self.assertEqual(check_clock_routing(pcb), [])
        self.assertEqual(check_diff_pair_layer(pcb, PAIRS), [])

    def test_jumper_layer_is_not_a_plane(self):
        pcb = _board({"F.Cu": "jumper", "B.Cu": "signal"},
                     {"F.Cu": ("GND", 0.8)}, dielectrics=[1.5])
        self.assertEqual(_rules(check_stackup(pcb)), [("SU-001", "info")])


def _square(x0, y0, side):
    pts = [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]
    return [{"type": "line", "start": list(a), "end": list(b)}
            for a, b in zip(pts, pts[1:] + pts[:1])]


class SeveralBoardsInOneFile(unittest.TestCase):
    """Two 40 mm boards side by side (bounding box 100 x 40 mm): planes covering 60 %
    of one board are planes, though they cover 24 % of the bounding box."""

    def _pcb(self, edges):
        pcb = _board(FOUR, {"In1.Cu": ("GND", 0.0), "In2.Cu": ("+3V3", 0.0)})
        pcb["statistics"]["board_area_mm2"] = 4000.0
        for zone in pcb["zones"]:
            zone["filled_area_mm2"] = 0.6 * 1600
        pcb["board_outline"] = {"edges": edges}
        return pcb

    def test_planes_on_one_of_two_boards_count(self):
        pcb = self._pcb(_square(0, 0, 40) + _square(60, 0, 40))
        self.assertNotIn("SU-001", [f["rule_id"] for f in check_stackup(pcb)])
        self.assertEqual(check_clock_routing(pcb), [])

    def test_one_board_keeps_the_bounding_box(self):
        outline = [{"type": "rect", "start": [0, 0], "end": [100, 40]}]
        pcb = self._pcb(outline + _square(5, 5, 10))  # a cutout, not a second board
        self.assertIn(("SU-001", "error"), _rules(check_stackup(pcb)))


class Su002UsesTheSamePlanes(unittest.TestCase):
    def test_signal_layer_far_from_a_filled_inner_plane(self):
        pcb = _board(FOUR, {"In1.Cu": ("GND", 0.9), "In2.Cu": ("GND", 0.9)},
                     dielectrics=[0.5, 0.6, 0.2])
        su002 = [f for f in check_stackup(pcb) if f["rule_id"] == "SU-002"]
        self.assertEqual(len(su002), 1)
        self.assertIn("F.Cu", su002[0]["summary"])
        self.assertIn("In1.Cu", su002[0]["description"])

    def test_small_pour_is_not_a_reference(self):
        pcb = _board(FOUR, {"In1.Cu": ("GND", 0.1), "In2.Cu": ("GND", 0.1)},
                     dielectrics=[0.5, 0.6, 0.2])
        self.assertNotIn("SU-002", [f["rule_id"] for f in check_stackup(pcb)])


if __name__ == "__main__":
    unittest.main()
