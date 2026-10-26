# tools/tests/test_pcb_circle_courtyard.py
"""Circular and arc courtyards are polygons, so PM-001 judges the real shape."""
import os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.pipeline import read_board  # noqa: E402
from pcb.assembly import analyze_placement  # noqa: E402


_dirs = []


def _fp(ref, x, y, crtyd):
    return (f'(footprint "L:F" (layer "F.Cu") (at {x} {y})\n'
            f'  (property "Reference" "{ref}")\n  (property "Value" "v")\n{crtyd})\n')


def _board(*fps):
    d = tempfile.TemporaryDirectory()
    _dirs.append(d)
    p = os.path.join(d.name, "b.kicad_pcb")
    with open(p, "w", encoding="utf-8") as f:
        f.write('(kicad_pcb (version 20221018) (generator pcbnew)\n' + "".join(fps) + ')\n')
    return p


CIRCLE = '(fp_circle (center 0 0) (end 3 0) (layer "F.CrtYd") (width 0.05))'


def _placement(*fps):
    st = read_board(_board(*fps))
    return analyze_placement(st.footprints, st.outline).get("courtyard_overlaps", [])


class TestCircleCourtyard(unittest.TestCase):
    def tearDown(self):
        while _dirs:
            _dirs.pop().cleanup()

    def test_circle_bbox_and_polygon(self):
        fp = read_board(_board(_fp("C1", 110, 100, CIRCLE))).footprints[0]
        cy = fp["courtyard"]
        self.assertEqual((cy["min_x"], cy["min_y"], cy["max_x"], cy["max_y"]), (107.0, 97.0, 113.0, 103.0))
        self.assertEqual(len(fp["courtyard_poly"]), 1)
        self.assertEqual(len(fp["courtyard_poly"][0]), 32)

    def test_overlap_five_mm_apart(self):
        self.assertEqual(len(_placement(_fp("C1", 100, 100, CIRCLE), _fp("C2", 105, 100, CIRCLE))), 1)

    def test_no_overlap_seven_mm_apart(self):
        self.assertEqual(_placement(_fp("C1", 100, 100, CIRCLE), _fp("C2", 107, 100, CIRCLE)), [])

    def test_diagonal_boxes_overlap_circles_do_not(self):
        self.assertEqual(_placement(_fp("C1", 100, 100, CIRCLE), _fp("C2", 104.5, 104.5, CIRCLE)), [])

    def test_line_and_arc_chain_into_one_polygon(self):
        crtyd = ('(fp_line (start -2 0) (end 2 0) (layer "F.CrtYd") (width 0.05))\n'
                 '(fp_arc (start 2 0) (mid 0 2) (end -2 0) (layer "F.CrtYd") (width 0.05))\n')
        fp = read_board(_board(_fp("U1", 50, 50, crtyd))).footprints[0]
        self.assertEqual(len(fp["courtyard_poly"]), 1)
        cy = fp["courtyard"]
        self.assertEqual((cy["min_x"], cy["max_x"], cy["max_y"]), (48.0, 52.0, 52.0))

    def test_legacy_arc_and_line_chain(self):
        # centre (0,0), first point (2,0), sweep 180 -> ends at (-2,0) through (0,2)
        crtyd = ('(fp_line (start -2 0) (end 2 0) (layer F.CrtYd) (width 0.05))\n'
                 '(fp_arc (start 0 0) (end 2 0) (angle 180) (layer F.CrtYd) (width 0.05))\n')
        fp = read_board(_board(_fp("U1", 50, 50, crtyd))).footprints[0]
        self.assertEqual(len(fp["courtyard_poly"]), 1)
        cy = fp["courtyard"]
        self.assertEqual((cy["min_x"], cy["max_x"], cy["max_y"]), (48.0, 52.0, 52.0))

    def _square(self, extra_first="", extra_last=""):
        sides = ((-1, -1, 1, -1), (1, -1, 1, 1), (1, 1, -1, 1), (-1, 1, -1, -1))
        return extra_first + ''.join(
            f'(fp_line (start {a} {b}) (end {c} {d}) (layer F.CrtYd) (width 0.05))\n'
            for a, b, c, d in sides) + extra_last

    def _line(self, a, b, c, d):
        return f'(fp_line (start {a} {b}) (end {c} {d}) (layer F.CrtYd) (width 0.05))\n'

    def test_doubled_side_is_malformed_either_direction(self):
        for dup in (self._line(-1, -1, 1, -1), self._line(1, -1, -1, -1)):
            fp = read_board(_board(_fp("U1", 50, 50, self._square(extra_last=dup)))).footprints[0]
            self.assertNotIn("courtyard", fp)
            self.assertNotIn("courtyard_poly", fp)

    def test_malformed_courtyard_is_recorded(self):
        board = read_board(_board(_fp("U1", 50, 50, self._square(extra_last=self._line(-1, -1, 1, -1)))))
        self.assertEqual(board.diagnostics, [{
            "source": "pcb.reader.extract_footprints", "exception": "ValueError",
            "message": "U1: courtyard has a segment drawn twice",
            "effect": "courtyard not used for placement checks"}])

    def test_same_outline_on_front_and_back_is_not_malformed(self):
        # KiCad checks F.CrtYd and B.CrtYd as two courtyards: no malformed_courtyard here
        both = self._square() + self._square().replace("F.CrtYd", "B.CrtYd")
        board = read_board(_board(_fp("J2", 50, 50, both)))
        fp = board.footprints[0]
        self.assertEqual(board.diagnostics, [])
        cy = fp["courtyard"]
        self.assertEqual((cy["min_x"], cy["min_y"], cy["max_x"], cy["max_y"]), (49.0, 49.0, 51.0, 51.0))
        self.assertEqual(len(fp["courtyard_poly"]), 1)
        self.assertEqual(sorted(map(tuple, fp["courtyard_poly"][0])),
                         [(49.0, 49.0), (49.0, 51.0), (51.0, 49.0), (51.0, 51.0)])

    def test_same_outline_on_front_and_back_still_overlaps(self):
        both = self._square() + self._square().replace("F.CrtYd", "B.CrtYd")
        rect = '(fp_rect (start -1 -1) (end 1 1) (layer "F.CrtYd") (width 0.05))\n'
        # 2 x 2 squares 1.5 mm apart overlap by 0.5 x 2 = 1 mm2
        for a in (both, rect + rect.replace("F.CrtYd", "B.CrtYd")):
            ov = _placement(_fp("J2", 50, 50, a), _fp("U2", 51.5, 50, self._square()))
            self.assertEqual(len(ov), 1)
            self.assertAlmostEqual(ov[0]["overlap_mm2"], 1.0, delta=0.1)

    def test_zero_length_segment_is_harmless(self):
        for kw in ({"extra_first": self._line(1, 1, 1, 1)}, {"extra_last": self._line(0, 0, 0, 0)},
                   {"extra_last": self._line(-1, -1, -1, -1)}):
            sq = self._square(**kw)
            fps = (_fp("U1", 50, 50, sq), _fp("U2", 51.5, 50, self._square()))
            fp = read_board(_board(*fps)).footprints[0]
            self.assertEqual(len(fp["courtyard_poly"][0]), 4)
            self.assertEqual(len(_placement(*fps)), 1)

    def test_legacy_stadium_matches_kicad_conversion(self):
        # kicad-cli pcb upgrade writes these two arcs as mid (5.9 0) / (-5.9 0)
        legacy = ('(fp_line (start -1 -4.9) (end 1 -4.9) (layer F.CrtYd) (width 0.05))\n'
                  '(fp_line (start -1 4.9) (end 1 4.9) (layer F.CrtYd) (width 0.05))\n'
                  '(fp_arc (start -1 0) (end -1 4.9) (angle 180) (layer F.CrtYd) (width 0.05))\n'
                  '(fp_arc (start 1 0) (end 1 -4.9) (angle 180) (layer F.CrtYd) (width 0.05))\n')
        modern = ('(fp_line (start -1 -4.9) (end 1 -4.9) (layer "F.CrtYd") (width 0.05))\n'
                  '(fp_line (start -1 4.9) (end 1 4.9) (layer "F.CrtYd") (width 0.05))\n'
                  '(fp_arc (start -1 4.9) (mid -5.9 0) (end -1 -4.9) (layer "F.CrtYd") (width 0.05))\n'
                  '(fp_arc (start 1 -4.9) (mid 5.9 0) (end 1 4.9) (layer "F.CrtYd") (width 0.05))\n')
        a = read_board(_board(_fp("M1", 50, 50, legacy))).footprints[0]
        b = read_board(_board(_fp("M2", 50, 50, modern))).footprints[0]
        self.assertEqual(a["courtyard"], b["courtyard"])
        self.assertEqual(a["courtyard"]["min_x"], 44.1)
        self.assertEqual(a["courtyard"]["max_x"], 55.9)
        self.assertEqual(len(a["courtyard_poly"]), 1)


if __name__ == "__main__":
    unittest.main()
