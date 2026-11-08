"""A board file whose Edge.Cuts holds several boards reports their summed area, as KiCad's Board
Statistics does (a hole inside a board is not subtracted). The file below (two boards, 60 x 40
and 60 x 20, with a 3.2 mm mounting hole) gives Width 60, Height 65 and Area 3600.00 in
`kicad-cli pcb export stats` (10.0.8). Outlines KiCad reports as malformed (touching or crossing
loops, a zero-length line), a single outline and a footprint drawing on Edge.Cuts keep the
bounding box."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from kicad_core.sexp import parse  # noqa: E402
from pcb.geometry import outline_board_area  # noqa: E402
from pcb.pipeline import analyze_pcb  # noqa: E402
from pcb.reader import extract_board_outline, has_footprint_edge_cuts  # noqa: E402
from emc_rules import check_via_stitching  # noqa: E402


def rect(x0, y0, x1, y1):
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return "".join(f'  (gr_line (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (stroke (width 0.05) '
                   f'(type default)) (layer "Edge.Cuts"))\n' for a, b in zip(pts, pts[1:] + pts[:1]))


HOLE = ('  (gr_circle (center 105 55) (end 106.6 55) (stroke (width 0.05) (type default)) '
        '(fill no) (layer "Edge.Cuts"))\n')
TWO_BOARDS = rect(100, 50, 160, 90) + rect(100, 95, 160, 115) + HOLE
PART = ('  (footprint "R_0603" (layer "F.Cu") (at 110 60)\n'
        '    (property "Reference" "R1" (at 0 0 0) (layer "F.SilkS"))\n'
        '    (pad "1" smd rect (at 0 0) (size 0.8 0.9) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
        '{extra}  )\n')
EDGE_IN_PART = '    (fp_line (start 0 2) (end 2 2) (stroke (width 0.05)) (layer "Edge.Cuts"))\n'


def board_text(items):
    return ('(kicad_pcb (version 20260206) (generator "pcbnew") (generator_version "10.0")\n'
            '  (general (thickness 1.6))\n'
            '  (layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))\n'
            '  (setup (pad_to_mask_clearance 0))\n  (net 0 "")\n' + items + ')\n')


def area(items):
    return outline_board_area(extract_board_outline(parse(board_text(items)))["edges"])


def analyze(items):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "b.kicad_pcb")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(board_text(items))
        return analyze_pcb(path)


class OutlineBoardArea(unittest.TestCase):
    def test_two_boards_sum_to_kicads_area(self):
        self.assertAlmostEqual(area(TWO_BOARDS), 3600.0, places=6)

    def test_single_outline_has_no_summed_area(self):
        self.assertIsNone(area(rect(0, 0, 60, 40) + HOLE.replace("105 55", "5 5")
                               .replace("106.6 55", "6.6 5")))

    def test_touching_boards_keep_the_box(self):
        self.assertIsNone(area(rect(0, 0, 60, 40) + rect(60, 0, 100, 40)))
        self.assertIsNone(area(rect(0, 0, 60, 40) + rect(60, 40, 100, 80)))  # corner contact

    def test_crossing_boards_keep_the_box(self):
        self.assertIsNone(area(rect(0, 0, 60, 40) + rect(50, 10, 100, 30)))

    def test_zero_length_line_keeps_the_box(self):
        dot = ('  (gr_line (start 10 10) (end 10 10) (stroke (width 0.05) (type default)) '
               '(layer "Edge.Cuts"))\n')
        self.assertIsNone(area(TWO_BOARDS + dot))

    def test_open_outline_keeps_the_box(self):
        self.assertIsNone(area(TWO_BOARDS.split("\n", 1)[1]))


class FootprintEdgeCuts(unittest.TestCase):
    def test_footprint_and_module_drawing_on_edge_cuts(self):
        self.assertFalse(has_footprint_edge_cuts(parse(board_text(PART.format(extra="")))))
        self.assertTrue(has_footprint_edge_cuts(parse(board_text(PART.format(extra=EDGE_IN_PART)))))
        module = ('  (module R_0603 (layer F.Cu) (at 110 60)\n'
                  '    (fp_line (start 0 2) (end 2 2) (layer Edge.Cuts) (width 0.05)))\n')
        self.assertTrue(has_footprint_edge_cuts(parse(board_text(PART.format(extra="") + module))))


class AnalyzerBoardArea(unittest.TestCase):
    def test_statistics_and_density_use_the_summed_area(self):
        result = analyze(TWO_BOARDS + PART.format(extra=""))
        stats = result["statistics"]
        self.assertEqual((stats["board_width_mm"], stats["board_height_mm"]), (60.0, 65.0))
        self.assertEqual(stats["board_area_mm2"], 3600.0)
        density = result["placement_density"]
        self.assertEqual(density["board_area_cm2"], 36.0)
        self.assertEqual(density["front_density_per_cm2"], round(1 / 36.0, 1))

    def test_footprint_edge_cuts_keeps_the_box(self):
        result = analyze(TWO_BOARDS + PART.format(extra=EDGE_IN_PART))
        self.assertEqual(result["statistics"]["board_area_mm2"], 3900.0)
        self.assertEqual(result["placement_density"]["board_area_cm2"], 39.0)

    def test_single_board_keeps_the_box(self):
        self.assertEqual(analyze(rect(0, 0, 60, 40))["statistics"]["board_area_mm2"], 2400.0)

    def test_design_intent_board_area_signal_reads_the_summed_area(self):
        # 60 x 200 box (120 cm2) around two 60 x 60 boards (72 cm2)
        def signals(items):
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "b.kicad_pcb")
                out = os.path.join(tmp, "out.json")
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(board_text(items))
                r = subprocess.run([sys.executable, str(SCRIPTS / "analyze_pcb.py"), path,
                                    "--output", out], cwd=tmp, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                with open(out, encoding="utf-8") as f:
                    return json.load(f)["design_intent"]["detection_signals"]
        self.assertFalse([s for s in signals(rect(0, 0, 60, 60) + rect(0, 140, 60, 200))
                          if s.startswith("board area")])
        self.assertIn("board area 12000mm² (>100cm²)", signals(rect(0, 0, 60, 200)))


class ViaStitchingArea(unittest.TestCase):
    def _board(self, board_area_mm2):
        return {"nets": {"1": "GND"},
                "statistics": {"board_area_mm2": board_area_mm2},
                "board_outline": {"bounding_box": {"width": 50, "height": 50}},
                "vias": {"vias": [{"net": 1, "x": 10, "y": 10}]},
                "zones": [{"net_name": "GND", "layers": ["F.Cu"], "filled_area_mm2": 900},
                          {"net_name": "GND", "layers": ["B.Cu"], "filled_area_mm2": 900}]}

    def test_vs001_uses_the_summed_board_area(self):
        (finding,) = check_via_stitching(self._board(1200.0))
        self.assertIn("across 1200 mm²", finding["description"])

    def test_vs001_keeps_the_box_for_a_single_board(self):
        (finding,) = check_via_stitching(self._board(2500.0))
        self.assertIn("across 2500 mm²", finding["description"])


if __name__ == "__main__":
    unittest.main()
