# tools/tests/test_ko001_outline.py
"""KO-001 judges an item against the rule area's outline, holes included, as KiCad does.

Expected items are kicad-cli 10.0.8 DRC ("Items not allowed") on the same boards.
"""
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.assembly import analyze_keepout_violations  # noqa: E402
from pcb.pipeline import analyze_pcb  # noqa: E402


def _pts(ring):
    return "(pts " + " ".join(f"(xy {x:.4f} {y:.4f})" for x, y in ring) + ")"


def _circle(cx, cy, r, n=64):
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n))
            for k in range(n)]


def _square(x1, y1, x2, y2):
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def _at45(r):
    return (100 + r * math.cos(math.pi / 4), 100 + r * math.sin(math.pi / 4))


def _board(rings, vias, layers='"F.Cu" "B.Cu"'):
    polygons = " ".join(f"(polygon {_pts(ring)})" for ring in rings)
    via_text = "\n".join(f'  (via (at {x:.4f} {y:.4f}) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1))'
                         for x, y in vias)
    return f'''(kicad_pcb (version 20240108) (generator "pcbnew")
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user) (47 "F.CrtYd" user))
  (net 0 "")
  (net 1 "GND")
  (gr_rect (start 70 70) (end 130 130) (stroke (width 0.1) (type default)) (fill none) (layer "Edge.Cuts"))
  (zone (net 0) (net_name "") (layers {layers}) (name "ko") (hatch edge 0.5)
    (keepout (tracks allowed) (vias not_allowed) (pads allowed) (copperpour allowed) (footprints allowed))
    {polygons})
{via_text}
)
'''


def _analyze(board_text):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "b.kicad_pcb")
        with open(p, "w", encoding="utf-8") as f:
            f.write(board_text)
        return analyze_pcb(p)


def _ko001(result):
    return [f for f in result.get("findings", []) if f.get("rule_id") == "KO-001"]


def _flagged(rings, vias):
    """The subset of ``vias`` KO-001 reports, as rounded (x, y)."""
    got = {(f["via_x"], f["via_y"]) for f in _ko001(_analyze(_board(rings, vias)))}
    return [v for v in vias if (round(v[0], 2), round(v[1], 2)) in got]


CIRCLE = [_circle(100, 100, 4.4)]
RING = [_square(90, 90, 110, 110), _square(95, 95, 105, 105)]


class TestViaAgainstRoundArea(unittest.TestCase):
    # GitHub #70: a round area of radius 4.4 mm; vias of 0.6 mm (copper radius 0.3)

    def test_via_inside_the_circle_is_reported(self):
        v = (103.0, 100.0)
        self.assertEqual(_flagged(CIRCLE, [v]), [v])

    def test_vias_in_the_box_corner_but_outside_the_circle_are_not_reported(self):
        vias = [_at45(4.7), _at45(5.2), _at45(5.7)]
        self.assertEqual(_flagged(CIRCLE, vias), [])

    def test_via_whose_copper_crosses_the_edge_is_reported(self):
        vias = [_at45(4.6), (104.65, 100.0)]
        self.assertEqual(_flagged(CIRCLE, vias), vias)

    def test_via_whose_copper_stays_clear_of_the_edge_is_not_reported(self):
        self.assertEqual(_flagged(CIRCLE, [_at45(4.75)]), [])


class TestViaAgainstAreaWithHole(unittest.TestCase):
    # a 20 mm square with a 10 mm square hole

    def test_via_in_the_hole_is_not_reported(self):
        self.assertEqual(_flagged(RING, [(100.0, 100.0), (104.5, 101.0)]), [])

    def test_via_in_the_ring_is_reported(self):
        self.assertEqual(_flagged(RING, [(92.0, 100.0)]), [(92.0, 100.0)])

    def test_via_straddling_the_hole_edge_is_reported(self):
        self.assertEqual(_flagged(RING, [(104.8, 100.0)]), [(104.8, 100.0)])


class TestKeepoutOutlineOutput(unittest.TestCase):

    def test_area_without_an_outline_is_skipped(self):
        kz = {"name": "ko", "layers": ["F.Cu", "B.Cu"], "restrictions": {"vias": "not_allowed"},
              "bounding_box": [90, 90, 110, 110]}
        vias = {"vias": [{"x": 100.0, "y": 100.0, "size": 0.6, "type": "through"}]}
        self.assertEqual(analyze_keepout_violations([], vias, [kz]), [])

    def test_outline_contours_stay_out_of_the_output(self):
        result = _analyze(_board(RING, [(92.0, 100.0)]))
        self.assertTrue(result["keepout_zones"])
        for z in result["zones"] + result["keepout_zones"]:
            self.assertNotIn("_outline_polys", z)

    def test_description_names_no_bbox_check(self):
        found = _ko001(_analyze(_board(RING, [(92.0, 100.0)])))
        self.assertEqual(len(found), 1)
        self.assertNotIn("bbox", found[0]["description"])


if __name__ == "__main__":
    unittest.main()
