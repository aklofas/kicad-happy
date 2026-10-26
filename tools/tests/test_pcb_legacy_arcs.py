# tools/tests/test_pcb_legacy_arcs.py
"""KiCad 5 arcs (start = centre, end = first point, angle = sweep) read as KiCad converts them."""
import math, os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.reader import _legacy_arc_points  # noqa: E402
from pcb.pipeline import read_board  # noqa: E402


def _board(body):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "b.kicad_pcb")
    with open(p, "w", encoding="utf-8") as f:
        f.write('(kicad_pcb (version 4) (host pcbnew 4.0.7)\n' + body + ')\n')
    return p


class TestLegacyArcs(unittest.TestCase):
    def test_helper_quarter_turn(self):
        s, m, e = _legacy_arc_points((100, 100), (110, 100), 90)
        c = 10 * math.cos(math.radians(45))
        self.assertEqual(s, (110.0, 100.0))
        self.assertEqual(m, (round(100 + c, 6), round(100 + c, 6)))
        self.assertEqual(e, (100.0, 110.0))

    def test_negative_half_turn(self):
        s, m, e = _legacy_arc_points((100, 100), (110, 100), -180)
        self.assertEqual((s, m, e), ((110.0, 100.0), (100.0, 90.0), (90.0, 100.0)))

    def test_two_arc_outline_bbox(self):
        body = ('(gr_arc (start 100 100) (end 110 100) (angle -180) (layer Edge.Cuts) (width 0.1))\n'
                '(gr_arc (start 100 100) (end 90 100) (angle -180) (layer Edge.Cuts) (width 0.1))\n')
        o = read_board(_board(body)).outline
        bb = o["bounding_box"]
        self.assertEqual((bb["min_x"], bb["min_y"], bb["max_x"], bb["max_y"]), (90.0, 90.0, 110.0, 110.0))
        self.assertAlmostEqual(o["width_mm"], 20.0)
        self.assertAlmostEqual(o["height_mm"], 20.0)

    def test_arc_with_mid_unchanged(self):
        body = '(gr_arc (start 0 0) (mid 1 1) (end 2 0) (layer Edge.Cuts) (width 0.1))\n'
        e = read_board(_board(body)).outline["edges"][0]
        self.assertEqual((e["start"], e["mid"], e["end"]), ([0.0, 0.0], [1.0, 1.0], [2.0, 0.0]))


if __name__ == "__main__":
    unittest.main()
