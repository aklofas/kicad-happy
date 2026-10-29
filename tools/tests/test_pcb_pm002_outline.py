# tools/tests/test_pcb_pm002_outline.py
"""PM-002 measures courtyards to the board outline KiCad builds from Edge.Cuts (curves, notches,
slots and cutouts); an outline that does not close is measured as its bounding box, with one
diagnostic."""
import contextlib, io, math, os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.pipeline import read_board  # noqa: E402
from pcb.assembly import analyze_placement  # noqa: E402
from pcb.geometry import outline_loops, point_in_outline  # noqa: E402


_dirs = []


def _fp(ref, x1, y1, x2, y2):
    """Footprint at the origin with a rectangular F.CrtYd courtyard (x1, y1)-(x2, y2)."""
    pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    lines = "".join(f'(fp_line (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (layer "F.CrtYd") (width 0.05))\n'
                    for a, b in zip(pts, pts[1:] + pts[:1]))
    return (f'(footprint "L:F" (layer "F.Cu") (at 0 0)\n'
            f'  (property "Reference" "{ref}")\n  (property "Value" "v")\n{lines})\n')


def _edges(*pts, close=True):
    pairs = list(zip(pts, pts[1:] + (pts[:1] if close else ())))
    return "".join(f'(gr_line (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (layer "Edge.Cuts") (width 0.1))\n'
                   for a, b in pairs)


def _read(*items):
    d = tempfile.TemporaryDirectory()
    _dirs.append(d)
    p = os.path.join(d.name, "b.kicad_pcb")
    with open(p, "w", encoding="utf-8") as f:
        f.write('(kicad_pcb (version 20221018) (generator pcbnew)\n' + "".join(items) + ')\n')
    with contextlib.redirect_stderr(io.StringIO()):
        return read_board(p)


def _pm002(board):
    res = analyze_placement(board.footprints, board.outline)
    return {w["component"]: w for w in res.get("edge_clearance_warnings", [])}


CIRCLE = '(gr_circle (center 50 50) (end 100 50) (layer "Edge.Cuts") (width 0.1))\n'
# L-shaped board: a 20 x 20 notch cut from the top-right corner of a 40 x 40 square
L_OUTLINE = _edges((0, 0), (40, 0), (40, 20), (20, 20), (20, 40), (0, 40))


class TestOutlineLoops(unittest.TestCase):
    def test_lines_chain_within_kicad_epsilon(self):
        # KiCad joins Edge.Cuts ends within DEFAULT_CHAINING_EPSILON_MM = 0.01 mm
        near = [{"type": "line", "start": [0, 0], "end": [10, 0]},
                {"type": "line", "start": [10.005, 0], "end": [10, 10]},
                {"type": "line", "start": [10, 10], "end": [0, 0]}]
        self.assertEqual(len(outline_loops(near)), 1)
        gap = [dict(e) for e in near]
        gap[1]["start"] = [10.02, 0]
        self.assertIsNone(outline_loops(gap))

    def test_cutout_is_off_board(self):
        loops = outline_loops([{"type": "rect", "start": [0, 0], "end": [30, 30]},
                               {"type": "rect", "start": [10, 10], "end": [20, 20]}])
        self.assertTrue(point_in_outline(5, 5, loops))
        self.assertFalse(point_in_outline(15, 15, loops))

    def test_circle_loop(self):
        loops = outline_loops([{"type": "circle", "center": [50, 50], "end": [100, 50]}])
        self.assertTrue(point_in_outline(84, 84, loops))     # 48.08 mm from the centre
        self.assertFalse(point_in_outline(86, 86, loops))    # 50.91 mm


class TestPm002Outline(unittest.TestCase):
    def test_circle_outline_part_off_board(self):
        # every courtyard corner is outside r = 50; the farthest, (91, 90.5), by
        # hypot(41, 40.5) - 50 = 7.63 mm. The bounding box (0..100) put it 9 mm inside.
        w = _pm002(_read(CIRCLE, _fp("U1", 89, 89.5, 91, 90.5)))["U1"]
        self.assertEqual(w["severity"], "warning")
        self.assertEqual(w["edge_clearance_mm"], round(-(math.hypot(41, 40.5) - 50), 2))
        self.assertIn("off-board", w["summary"])

    def test_circle_outline_overhang(self):
        # (84, 84) is inside, (86, 86) is hypot(36, 36) - 50 = 0.91 mm outside
        w = _pm002(_read(CIRCLE, _fp("U2", 84, 84, 86, 86)))["U2"]
        self.assertEqual(w["severity"], "error")
        self.assertEqual(w["edge_clearance_mm"], round(-(math.hypot(36, 36) - 50), 2))
        self.assertIn("overhangs", w["summary"])

    def test_l_notch_edge(self):
        # courtyard right side x = 19.7 is 0.3 mm from the notch edge x = 20 (y 20..40);
        # the bounding box (0..40) measured 10 mm
        w = _pm002(_read(L_OUTLINE, _fp("C12", 15, 25, 19.7, 30)))["C12"]
        self.assertEqual(w["severity"], "error")
        self.assertEqual(w["edge_clearance_mm"], 0.3)

    def test_part_by_the_notch_corner_not_reported(self):
        # (19, 19) is hypot(1, 1) = 1.41 mm from the notch's inner corner (20, 20): no finding
        self.assertNotIn("C13", _pm002(_read(L_OUTLINE, _fp("C13", 17, 17, 19, 19))))

    def test_part_in_the_notch_is_off_board(self):
        w = _pm002(_read(L_OUTLINE, _fp("C14", 25, 25, 30, 30)))["C14"]
        self.assertIn("off-board", w["summary"])

    def test_slot_is_board_edge(self):
        slot = '(gr_rect (start 10 10) (end 20 12) (layer "Edge.Cuts") (width 0.1))\n'
        board = '(gr_rect (start 0 0) (end 40 40) (layer "Edge.Cuts") (width 0.1))\n'
        # courtyard bottom y = 9.6 is 0.4 mm above the slot's top edge y = 10
        w = _pm002(_read(board, slot, _fp("R1", 12, 5, 18, 9.6)))["R1"]
        self.assertEqual(w["severity"], "error")
        self.assertEqual(w["edge_clearance_mm"], 0.4)

    def test_open_outline_keeps_the_bounding_box(self):
        # left side missing: KiCad cannot close the outline and uses its bounding box
        # (0..40 x 0..30); courtyard x = 0.4 is 0.4 mm from the box's left side
        st = _read(_edges((0, 0), (40, 0), (40, 30), (0, 30), close=False),
                   _fp("R2", 0.4, 10, 5, 12))
        w = _pm002(st)["R2"]
        self.assertEqual((w["severity"], w["edge_clearance_mm"]), ("error", 0.4))
        diags = [d for d in st.diagnostics if d["source"] == "pcb.pipeline.read_board"]
        self.assertEqual(len(diags), 1)
        self.assertIn("does not close", diags[0]["message"])

    def test_closed_outline_no_diagnostic(self):
        st = _read(L_OUTLINE, _fp("C13", 17, 17, 19, 19))
        self.assertEqual(st.diagnostics, [])

    def test_bounding_box_only_outline(self):
        # an outline dict without edges (as callers build it) keeps the bounding-box measure
        fps = [{"reference": "J1", "layer": "F.Cu", "x": 5, "y": 5,
                "courtyard": {"min_x": -1, "min_y": 3, "max_x": 2, "max_y": 7}}]
        outline = {"bounding_box": {"min_x": 0, "min_y": 0, "max_x": 50, "max_y": 50,
                                    "width": 50, "height": 50}}
        w = analyze_placement(fps, outline)["edge_clearance_warnings"][0]
        self.assertEqual(w["edge_clearance_mm"], -1)


if __name__ == "__main__":
    unittest.main()
