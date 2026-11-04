# tools/tests/test_touch_pad_not_test_point.py
"""A capacitive touch electrode with a TP reference is not a test point: TE-001, the schematic
test coverage and CP-003 read it through one classifier (kicad_core.classify.is_touch_pad)."""
import sys, unittest
from pathlib import Path
from types import SimpleNamespace
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.classify import is_touch_pad  # noqa: E402
from kicad_core.sexp import parse  # noqa: E402
from pcb.assembly import analyze_test_point_coverage  # noqa: E402
from pcb.reader import extract_footprints  # noqa: E402
from schematic.system_analyses import analyze_test_coverage  # noqa: E402

PAD = '(pad "1" smd circle (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask") (net 1 "SIG"))'


def pcb_cov(ref, lib_fp, value):
    fp = (f'(footprint "{lib_fp}" (layer "F.Cu") (at 10 10) (attr smd)'
          f' (property "Reference" "{ref}") (property "Value" "{value}") {PAD})')
    board = parse(f'(kicad_pcb (version 20240108) (generator "pcbnew") (net 0 "") (net 1 "SIG") {fp})')
    return analyze_test_point_coverage(extract_footprints(board), {0: "", 1: "SIG"})


def sch_cov(ref, footprint, value):
    comp = {"reference": ref, "footprint": footprint, "value": value, "type": "test_point"}
    ctx = SimpleNamespace(components=[comp], nets={"SIG": {"pins": []}}, pin_net={},
                          comp_lookup={ref: comp}, ref_pins={ref: {"1": ("SIG", None)}},
                          is_power_net=lambda n: False, is_ground=lambda n: False)
    return analyze_test_coverage(ctx)


class TouchPadClassifier(unittest.TestCase):
    def test_touch_footprint_value_or_reference(self):
        self.assertTrue(is_touch_pad("TP1", "x", "sacmap:Touch"))
        self.assertTrue(is_touch_pad("TP1", "TouchPad", "Lib:FP"))
        self.assertTrue(is_touch_pad("TCH2", "x", ""))

    def test_test_point_footprint_wins_over_value(self):
        self.assertFalse(is_touch_pad("TP1", "TouchPad", "TestPoint:TestPoint_Pad_D1.0mm"))


class TouchPadIsNotATestPoint(unittest.TestCase):
    def test_pcb_test_point_counts(self):
        cov = pcb_cov("TP1", "TestPoint:TestPoint_Pad_D1.0mm", "TP_SWCLK")
        self.assertEqual((cov["nets_with_test_points"], cov["test_point_count"]), (1, 1))

    def test_pcb_touch_pad_does_not(self):
        cov = pcb_cov("TP1", "sacmap:Touch", "TouchPad")
        self.assertEqual((cov["nets_with_test_points"], cov["test_point_count"]), (0, 0))

    def test_schematic_test_point_counts(self):
        cov = sch_cov("TP1", "TestPoint:TestPoint_Pad_D1.0mm", "TP_SWCLK")
        self.assertEqual(cov["test_point_count"], 1)

    def test_schematic_touch_pad_does_not(self):
        cov = sch_cov("TP1", "sacmap:Touch", "TouchPad")
        self.assertEqual(cov["test_point_count"], 0)


if __name__ == "__main__":
    unittest.main()
