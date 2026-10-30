"""Switching-loop centre triangle: parts in a line are not estimated, not 0 mm² (PCB loop record + EMC SW-003)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from emc_rules import check_input_cap_loop_area  # noqa: E402
from pcb.assembly import _compute_switching_loop_areas  # noqa: E402


def _footprints(*placed):
    return [{"reference": ref, "x": x, "y": y, "pads": []} for ref, x, y in placed]


def _schematic(ref="U1", inductor="L1", cap="C1", value="TPS54331"):
    return {"findings": [{
        "detector": "detect_power_regulators", "rule_id": "PR-DET", "ref": ref, "value": value,
        "topology": "buck", "inductor": inductor, "input_capacitors": [{"ref": cap}],
        "severity": "info", "confidence": "deterministic", "evidence_source": "topology",
        "summary": "", "description": "", "components": [ref], "nets": [], "pins": [],
        "recommendation": "", "report_context": {}}]}


# GitHub #62 board: C3, U2 and L1 centres all at y = 131 mm. Shoelace area 0, longest side 143 - 131 = 12 mm.
REPORTER = _footprints(("C3", 143.0, 131.0), ("U2", 138.0, 131.0), ("L1", 131.0, 131.0))
REPORTER_SCH = _schematic("U2", "L1", "C3", "BUCK_2MHz")


class LoopRecordTest(unittest.TestCase):
    def test_reporter_collinear_centres_are_not_estimated(self):
        loops = _compute_switching_loop_areas(REPORTER, REPORTER_SCH)
        self.assertEqual(len(loops), 1)
        self.assertIsNone(loops[0]["area_mm2"])
        self.assertEqual(loops[0]["estimate"], "degenerate")
        self.assertEqual(loops[0]["vertices_mm"], [[143.0, 131.0], [138.0, 131.0], [131.0, 131.0]])

    def test_near_collinear_long_line_is_not_estimated(self):
        # Base 20 mm, apex 0.05 mm off it: area 0.5 × 20 × 0.05 = 0.5 mm² < 1 with a 20 mm side.
        fps = _footprints(("C1", 100.0, 100.0), ("U1", 110.0, 100.05), ("L1", 120.0, 100.0))
        self.assertIsNone(_compute_switching_loop_areas(fps, _schematic())[0]["area_mm2"])

    def test_coincident_centres_are_not_estimated(self):
        fps = _footprints(("C1", 10.0, 10.0), ("U1", 10.0, 10.0), ("L1", 20.0, 15.0))
        self.assertIsNone(_compute_switching_loop_areas(fps, _schematic())[0]["area_mm2"])

    def test_real_triangle_unchanged(self):
        # (1,1), (11,1), (1,11): 0.5 × 10 × 10 = 50 mm².
        fps = _footprints(("U1", 1.0, 1.0), ("L1", 1.0, 11.0), ("C1", 11.0, 1.0))
        loop = _compute_switching_loop_areas(fps, _schematic())[0]
        self.assertEqual(loop["area_mm2"], 50.0)
        self.assertNotIn("estimate", loop)

    def test_compact_small_loop_keeps_its_area(self):
        # (10,10), (11,10), (10,11.2): area 0.5 × 1 × 1.2 = 0.6 mm², longest side √(1 + 1.44) = 1.56 mm < 2.
        fps = _footprints(("C1", 10.0, 10.0), ("U1", 11.0, 10.0), ("L1", 10.0, 11.2))
        loop = _compute_switching_loop_areas(fps, _schematic())[0]
        self.assertEqual(loop["area_mm2"], 0.6)
        self.assertNotIn("estimate", loop)


class SW003Test(unittest.TestCase):
    def _assert_not_estimated(self, findings):
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual((f["rule_id"], f["severity"]), ("SW-003", "info"))
        self.assertIn("not estimated", f["summary"])
        self.assertEqual(sorted(f["components"]), ["C3", "L1", "U2"])
        self.assertNotIn("0mm", f["description"])

    def test_precomputed_null_area_is_info_not_acceptable(self):
        pcb = {"footprints": REPORTER,
               "switching_loop_areas": _compute_switching_loop_areas(REPORTER, REPORTER_SCH)}
        self._assert_not_estimated(check_input_cap_loop_area(pcb, REPORTER_SCH))

    def test_fallback_collinear_is_info_not_acceptable(self):
        self._assert_not_estimated(check_input_cap_loop_area({"footprints": REPORTER}, REPORTER_SCH))

    def test_compact_loop_still_has_no_finding(self):
        # (10,10), (13,10), (10,14): 0.5 × 3 × 4 = 6 mm² < 25.
        fps = _footprints(("C1", 10.0, 10.0), ("U1", 13.0, 10.0), ("L1", 10.0, 14.0))
        sch = _schematic()
        self.assertEqual(check_input_cap_loop_area({"footprints": fps}, sch), [])
        pcb = {"footprints": fps, "switching_loop_areas": _compute_switching_loop_areas(fps, sch)}
        self.assertEqual(check_input_cap_loop_area(pcb, sch), [])

    def test_large_loop_still_reported(self):
        # (5,5), (30,5), (5,30): 0.5 × 25 × 25 = 312.5 mm² > 100.
        fps = _footprints(("U1", 5.0, 5.0), ("L1", 30.0, 5.0), ("C1", 5.0, 30.0))
        sch = _schematic()
        for pcb in ({"footprints": fps},
                    {"footprints": fps, "switching_loop_areas": _compute_switching_loop_areas(fps, sch)}):
            findings = check_input_cap_loop_area(pcb, sch)
            self.assertEqual([(f["rule_id"], f["severity"]) for f in findings], [("SW-003", "error")])


if __name__ == "__main__":
    unittest.main()
