"""SW-002 sizes switching-node zone copper from the fill; a zone with no fill counts its outline."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from emc_rules import check_switching_node_area  # noqa: E402
from finding_schema import Det  # noqa: E402


def _areas(zone):
    pcb = {"zones": [dict(zone, net_name="SW")], "tracks": {"segments": []}}
    schematic = {"findings": [{"detector": Det.POWER_REGULATORS, "ref": "U1", "value": "TPS54331",
                               "topology": "buck", "sw_net": "SW"}]}
    return [f["description"] for f in check_switching_node_area(pcb, schematic)]


class SwitchingNodeArea(unittest.TestCase):
    def test_fill_smaller_than_outline_is_the_copper(self):
        self.assertEqual(_areas({"outline_area_mm2": 100, "filled_area_mm2": 30})[0].count("30mm² zone"), 1)

    def test_fill_under_threshold_is_no_finding(self):
        self.assertEqual(_areas({"outline_area_mm2": 100, "filled_area_mm2": 10}), [])

    def test_unfilled_zone_counts_its_outline(self):
        self.assertIn("100mm² zone", _areas({"outline_area_mm2": 100})[0])
