"""Switching hot loop from pad positions: input-cap supply pad -> regulator supply pad, SW pad -> inductor SW pad,
regulator ground pad -> input-cap ground pad (PCB loop record + EMC SW-003)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from emc_rules import check_input_cap_loop_area  # noqa: E402
from kicad_core.hotloop import polygon_area, triangle_loop_area  # noqa: E402
from pcb.assembly import _compute_switching_loop_areas  # noqa: E402


def _fp(ref, x, y, pads):
    return {"reference": ref, "x": x, "y": y,
            "pads": [{"number": n, "net_name": net, "abs_x": px, "abs_y": py} for n, net, px, py in pads]}


def _schematic(ref="U2", inductor="L1", caps=("C3",), value="BUCK_2MHz", sw_net="SW", sw_pins=None):
    if sw_pins is None:
        sw_pins = ((inductor, "2"),)
    return {"findings": [{
                "detector": "detect_power_regulators", "rule_id": "PR-DET", "ref": ref, "value": value,
                "topology": "buck", "inductor": inductor, "sw_net": sw_net,
                "input_capacitors": [{"ref": c} for c in caps],
                "severity": "info", "confidence": "deterministic", "evidence_source": "topology",
                "summary": "", "description": "", "components": [ref], "nets": [], "pins": [],
                "recommendation": "", "report_context": {}}],
            "nets": {sw_net: {"pins": [{"component": r, "pin_number": p} for r, p in sw_pins]}}}


# GitHub #62 board (KiCad 10.0.7): pad centres as KiCad's IPC-D-356 export gives them.
# The C3, U2 and L1 centres all lie at y = 131 mm.
U2 = _fp("U2", 138.0, 131.0, [("1", "/SW", 136.8625, 130.05), ("2", "GND", 136.8625, 131.0),
                              ("3", "/FB", 136.8625, 131.95), ("4", "+5V", 139.1375, 131.95),
                              ("5", "+5V", 139.1375, 131.0)])
C3 = _fp("C3", 143.0, 131.0, [("1", "+5V", 142.2, 131.0), ("2", "GND", 143.8, 131.0)])
L1 = _fp("L1", 131.0, 131.0, [("1", "+3V3", 129.5, 131.0), ("2", "/SW", 132.5, 131.0)])
REPORTER = [U2, C3, L1]
REPORTER_SCH = _schematic(sw_net="/SW")


class PadLoopTest(unittest.TestCase):
    def test_reporter_board_gets_a_pad_loop(self):
        loop = _compute_switching_loop_areas(REPORTER, REPORTER_SCH)[0]
        self.assertEqual(loop["method"], "pad")
        self.assertEqual(loop["cap_ref"], "C3")
        self.assertEqual(loop["loop_pads"], ["C3.1", "U2.5", "U2.1", "L1.2", "U2.2", "C3.2"])
        # Only U2.1 is off y = 131: triangle U2.5 (139.1375), U2.1 (136.8625, 130.05), L1.2 (132.5):
        # 0.5 × (139.1375 - 132.5) × 0.95 = 3.15 mm².
        self.assertEqual(loop["area_mm2"], 3.2)
        self.assertEqual(loop["vertices_mm"][3], [132.5, 131.0])
        self.assertNotIn("estimate", loop)

    def test_unresolved_pads_give_no_area(self):
        cap = _fp("C3", 143.0, 131.0, [("1", "+5V", 142.2, 131.0), ("2", "+5V", 143.8, 131.0)])
        loop = _compute_switching_loop_areas([U2, cap, L1], REPORTER_SCH)[0]
        self.assertEqual(loop["method"], "pad")
        self.assertIsNone(loop["area_mm2"])
        self.assertEqual(loop["estimate"], "pads_unresolved")
        self.assertNotIn("vertices_mm", loop)
        self.assertNotIn("loop_pads", loop)

    def test_padless_footprints_give_no_area(self):
        fps = [{"reference": fp["reference"], "x": fp["x"], "y": fp["y"], "pads": []} for fp in REPORTER]
        loop = _compute_switching_loop_areas(fps, REPORTER_SCH)[0]
        self.assertIsNone(loop["area_mm2"])
        self.assertEqual(loop["estimate"], "pads_unresolved")
        self.assertEqual(loop["cap_ref"], "C3")

    def test_pads_in_a_line_are_degenerate(self):
        # Every pad on y = 10, 14 mm apart end to end: area 0 with a span over 2 mm.
        u1 = _fp("U1", 10.0, 10.0, [("1", "VIN", 10.0, 10.0), ("2", "SW", 11.0, 10.0), ("3", "GND", 9.0, 10.0)])
        l1 = _fp("L1", 20.0, 10.0, [("1", "SW", 19.0, 10.0), ("2", "VOUT", 21.0, 10.0)])
        c1 = _fp("C1", 3.0, 10.0, [("1", "VIN", 2.0, 10.0), ("2", "GND", 4.0, 10.0)])
        loop = _compute_switching_loop_areas([u1, l1, c1], _schematic("U1", "L1", ("C1",), "TPS54331"))[0]
        self.assertIsNone(loop["area_mm2"])
        self.assertEqual(loop["estimate"], "degenerate")
        self.assertEqual(len(loop["vertices_mm"]), 6)

    def test_self_crossing_loop_whose_lobes_cancel_is_degenerate(self):
        # ButterStick r1.0 U9 (TLV62569DRL), C77, L5: the pads are compact (C77 about 1.3 mm from U9.3) but edge
        # U9.2 -> C77.2 crosses edge U9.3 -> U9.4, so the two lobes net to 0.03 mm² across a 3.6 mm reach.
        u9 = _fp("U9", 176.55, 97.55, [("2", "GND", 177.3, 97.55), ("3", "+5V", 177.3, 97.05),
                                       ("4", "SW", 175.8, 97.05)])
        l5 = _fp("L5", 174.02, 97.97, [("1", "SW", 174.02, 97.0325), ("2", "+1V1", 174.02, 98.9075)])
        c77 = _fp("C77", 177.1, 95.8, [("1", "+5V", 177.585, 95.8), ("2", "GND", 176.615, 95.8)])
        loop = _compute_switching_loop_areas([u9, l5, c77], _schematic("U9", "L5", ("C77",), "TLV62569DRL",
                                                                       sw_pins=(("L5", "1"),)))[0]
        self.assertEqual(loop["loop_pads"], ["C77.1", "U9.3", "U9.4", "L5.1", "U9.2", "C77.2"])
        self.assertAlmostEqual(polygon_area([tuple(v) for v in loop["vertices_mm"]]), 0.029375, places=6)
        self.assertIsNone(loop["area_mm2"])
        self.assertEqual(loop["estimate"], "degenerate")

    def test_nearest_input_cap_closes_the_loop(self):
        far = _fp("C9", 160.0, 150.0, [("1", "+5V", 159.2, 150.0), ("2", "GND", 160.8, 150.0)])
        loop = _compute_switching_loop_areas(REPORTER + [far], _schematic(caps=("C9", "C3"), sw_net="/SW"))[0]
        self.assertEqual(loop["cap_ref"], "C3")
        self.assertEqual(loop["area_mm2"], 3.2)

    def test_schematic_sw_pin_picks_the_sw_net(self):
        # The inductor's output side also reaches the regulator (a VOS pin): the schematic SW net decides.
        u2 = _fp("U2", 138.0, 131.0, [("1", "/SW", 136.8625, 130.05), ("2", "GND", 136.8625, 131.0),
                                      ("3", "+3V3", 136.8625, 131.95), ("5", "+5V", 139.1375, 131.0)])
        loop = _compute_switching_loop_areas([u2, C3, L1], REPORTER_SCH)[0]
        self.assertEqual(loop["loop_pads"][2:4], ["U2.1", "L1.2"])
        no_pins = _compute_switching_loop_areas([u2, C3, L1], _schematic(sw_net="/SW", sw_pins=()))[0]
        self.assertEqual(no_pins["estimate"], "pads_unresolved")


class TriangleTest(unittest.TestCase):
    """The centre triangle EMC SW-003 falls back to without pad positions."""

    def test_real_triangle(self):
        # (1,1), (11,1), (1,11): 0.5 × 10 × 10 = 50 mm².
        self.assertEqual(triangle_loop_area([(1.0, 1.0), (11.0, 1.0), (1.0, 11.0)]), 50.0)

    def test_near_collinear_long_line_is_degenerate(self):
        # Base 20 mm, apex 0.05 mm off it: 0.5 × 20 × 0.05 = 0.5 mm² < 1 with a 20 mm side.
        self.assertIsNone(triangle_loop_area([(100.0, 100.0), (110.0, 100.05), (120.0, 100.0)]))

    def test_coincident_centres_are_degenerate(self):
        self.assertIsNone(triangle_loop_area([(10.0, 10.0), (10.0, 10.0), (20.0, 15.0)]))

    def test_compact_small_triangle_keeps_its_area(self):
        # (10,10), (11,10), (10,11.2): 0.5 × 1 × 1.2 = 0.6 mm², longest side √(1 + 1.44) = 1.56 mm < 2.
        self.assertAlmostEqual(triangle_loop_area([(10.0, 10.0), (11.0, 10.0), (10.0, 11.2)]), 0.6)


# Centres (5,5), (30,5), (5,30): centre triangle 0.5 × 25 × 25 = 312.5 mm².
# Pad loop (5,30) -> (5,5) -> (6,5) -> (30,5) -> (6,10) -> (8,30): triangle (5,5), (30,5), (6,10) = 0.5 × 25 × 5
# = 62.5, plus (5,5), (6,10), (8,30), (5,30) = 0.5 × 1 × 5 + 20 × (1 + 3) / 2 = 42.5; 105 mm² > 100.
LARGE = [_fp("U1", 5.0, 5.0, [("1", "VIN", 5.0, 5.0), ("2", "SW", 6.0, 5.0), ("3", "GND", 6.0, 10.0)]),
         _fp("L1", 30.0, 5.0, [("1", "SW", 30.0, 5.0), ("2", "VOUT", 32.0, 5.0)]),
         _fp("C1", 5.0, 30.0, [("1", "VIN", 5.0, 30.0), ("2", "GND", 8.0, 30.0)])]
# Centres (10,10), (13,10), (10,14): centre triangle 0.5 × 3 × 4 = 6 mm².
# Pad loop (10,13) -> (10,10) -> (11,10) -> (13,10) -> (11,11) -> (11,13): triangle (10,10), (13,10), (11,11)
# = 1.5, plus (10,10), (11,11), (11,13), (10,13) = 0.5 + 2 = 2.5; 4 mm² < 25.
COMPACT = [_fp("C1", 10.0, 10.0, [("1", "VIN", 10.0, 13.0), ("2", "GND", 11.0, 13.0)]),
           _fp("U1", 13.0, 10.0, [("1", "VIN", 10.0, 10.0), ("2", "SW", 11.0, 10.0), ("3", "GND", 11.0, 11.0)]),
           _fp("L1", 10.0, 14.0, [("1", "SW", 13.0, 10.0), ("2", "VOUT", 14.0, 10.0)])]
SYNTH_SCH = _schematic("U1", "L1", ("C1",), "TPS54331", sw_pins=(("L1", "1"),))


class SW003Test(unittest.TestCase):
    def _assert_not_estimated(self, findings):
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual((f["rule_id"], f["severity"]), ("SW-003", "info"))
        self.assertIn("not estimated", f["summary"])
        self.assertEqual(sorted(f["components"]), ["C3", "L1", "U2"])
        self.assertNotIn("0mm", f["description"])

    def test_precomputed_null_area_is_info_not_acceptable(self):
        fps = [{"reference": fp["reference"], "x": fp["x"], "y": fp["y"], "pads": []} for fp in REPORTER]
        pcb = {"footprints": fps, "switching_loop_areas": _compute_switching_loop_areas(fps, REPORTER_SCH)}
        self._assert_not_estimated(check_input_cap_loop_area(pcb, REPORTER_SCH))

    def test_fallback_collinear_is_info_not_acceptable(self):
        self._assert_not_estimated(check_input_cap_loop_area({"footprints": REPORTER}, REPORTER_SCH))

    def test_reporter_pad_loop_has_no_finding(self):
        pcb = {"footprints": REPORTER,
               "switching_loop_areas": _compute_switching_loop_areas(REPORTER, REPORTER_SCH)}
        self.assertEqual(check_input_cap_loop_area(pcb, REPORTER_SCH), [])

    def test_compact_loop_still_has_no_finding(self):
        self.assertEqual(_compute_switching_loop_areas(COMPACT, SYNTH_SCH)[0]["area_mm2"], 4.0)
        self.assertEqual(check_input_cap_loop_area({"footprints": COMPACT}, SYNTH_SCH), [])
        pcb = {"footprints": COMPACT, "switching_loop_areas": _compute_switching_loop_areas(COMPACT, SYNTH_SCH)}
        self.assertEqual(check_input_cap_loop_area(pcb, SYNTH_SCH), [])

    def test_pad_loop_not_estimated_names_the_pad_reason(self):
        u1 = _fp("U1", 10.0, 10.0, [("1", "VIN", 10.0, 10.0), ("2", "SW", 11.0, 10.0), ("3", "GND", 9.0, 10.0)])
        l1 = _fp("L1", 20.0, 10.0, [("1", "SW", 19.0, 10.0), ("2", "VOUT", 21.0, 10.0)])
        c1 = _fp("C1", 3.0, 10.0, [("1", "VIN", 2.0, 10.0), ("2", "GND", 4.0, 10.0)])
        sch = _schematic("U1", "L1", ("C1",), "TPS54331")
        pcb = {"footprints": [u1, l1, c1], "switching_loop_areas": _compute_switching_loop_areas([u1, l1, c1], sch)}
        f, = check_input_cap_loop_area(pcb, sch)
        self.assertEqual((f["severity"], f["summary"]), ("info", "Hot loop for U1 not estimated"))
        self.assertIn("area under 1 mm² across 2 mm or more: pads in a line or crossing lobes that cancel",
                      f["description"])
        self.assertNotIn("centre", f["description"])

    def test_unresolved_pads_say_the_pads_were_not_matched(self):
        fps = [{"reference": fp["reference"], "x": fp["x"], "y": fp["y"], "pads": []} for fp in REPORTER]
        pcb = {"footprints": fps, "switching_loop_areas": _compute_switching_loop_areas(fps, REPORTER_SCH)}
        f, = check_input_cap_loop_area(pcb, REPORTER_SCH)
        self.assertIn("could not be matched", f["description"])
        self.assertNotIn("centre", f["description"])
        self.assertNotIn("1 mm²", f["description"])

    def test_fallback_collinear_keeps_the_centre_text(self):
        f, = check_input_cap_loop_area({"footprints": REPORTER}, REPORTER_SCH)
        self.assertIn("lie in a line", f["description"])

    def test_large_centre_triangle_is_an_info_estimate(self):
        f, = check_input_cap_loop_area({"footprints": LARGE}, SYNTH_SCH)
        self.assertEqual((f["rule_id"], f["severity"]), ("SW-003", "info"))
        self.assertEqual(f["summary"], "Hot loop for U1 not graded: estimated from part centres")
        self.assertIn("312mm²", f["description"])
        self.assertIn("analyze_pcb.py", f["description"])
        self.assertIn("--schematic", f["description"])
        self.assertIn("not graded", f["description"])
        self.assertEqual(f["nets"], ["SW"])
        self.assertEqual(f["detector"], "emc_switching_emc")

    def test_precomputed_record_without_method_is_an_info_estimate(self):
        pcb = {"footprints": [], "switching_loop_areas": [
            {"regulator_ref": "U1", "regulator_value": "TPS54331", "inductor_ref": "L1", "cap_ref": "C1",
             "area_mm2": 150.0, "vertices_mm": [[10, 0], [0, 0], [0, 10]]}]}
        f, = check_input_cap_loop_area(pcb, SYNTH_SCH)
        self.assertEqual((f["severity"], f["summary"]), ("info", "Hot loop for U1 not graded: estimated from part centres"))
        self.assertIn("150mm²", f["description"])
        self.assertIn("--schematic", f["description"])

    def test_small_centre_triangle_still_has_no_finding(self):
        pcb = {"footprints": [], "switching_loop_areas": [
            {"regulator_ref": "U1", "regulator_value": "TPS54331", "inductor_ref": "L1", "cap_ref": "C1",
             "area_mm2": 24.9}]}
        self.assertEqual(check_input_cap_loop_area(pcb, SYNTH_SCH), [])

    def test_pad_loop_is_graded(self):
        for area, severity in ((40.0, "warning"), (150.0, "error"), (24.9, None)):
            pcb = {"footprints": [], "switching_loop_areas": [
                {"regulator_ref": "U1", "regulator_value": "TPS54331", "inductor_ref": "L1", "cap_ref": "C1",
                 "method": "pad", "area_mm2": area}]}
            findings = check_input_cap_loop_area(pcb, SYNTH_SCH)
            if severity is None:
                self.assertEqual(findings, [])
                continue
            f, = findings
            self.assertEqual((f["rule_id"], f["severity"], f["summary"]), ("SW-003", severity, "Large hot loop for U1"))
            self.assertIn(f"{area:.0f}mm²", f["description"])
            self.assertIn("pads", f["description"])
            self.assertNotIn("triangle", f["description"] + f["recommendation"])

    def test_large_pad_loop_still_reported(self):
        self.assertEqual(_compute_switching_loop_areas(LARGE, SYNTH_SCH)[0]["area_mm2"], 105.0)
        pcb = {"footprints": LARGE, "switching_loop_areas": _compute_switching_loop_areas(LARGE, SYNTH_SCH)}
        findings = check_input_cap_loop_area(pcb, SYNTH_SCH)
        self.assertEqual([(f["rule_id"], f["severity"]) for f in findings], [("SW-003", "error")])

if __name__ == "__main__":
    unittest.main()
