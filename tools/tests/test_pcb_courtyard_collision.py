# tools/tests/test_pcb_courtyard_collision.py
"""PM-001 decides courtyard collision as KiCad's DRC does: each courtyard shrunk by 0.005 mm
(touching courtyards are legal), thin crossings are found, open outlines are not courtyards."""
import contextlib, io, os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.pipeline import read_board  # noqa: E402
from pcb.assembly import analyze_placement  # noqa: E402
from pcb.geometry import courtyards_collide  # noqa: E402


_dirs = []


def _fp(ref, crtyd, x=100, y=100, layer="F.Cu"):
    return (f'(footprint "L:F" (layer "{layer}") (at {x} {y})\n'
            f'  (property "Reference" "{ref}")\n  (property "Value" "v")\n{crtyd})\n')


def _lines(*pts, layer="F.CrtYd"):
    """Closed outline through ``pts`` as fp_line segments."""
    return "".join(f'(fp_line (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (layer "{layer}") (width 0.05))\n'
                   for a, b in zip(pts, pts[1:] + pts[:1]))


def _rect(x1, y1, x2, y2):
    return _lines((x1, y1), (x2, y1), (x2, y2), (x1, y2))


def _read(*fps):
    d = tempfile.TemporaryDirectory()
    _dirs.append(d)
    p = os.path.join(d.name, "b.kicad_pcb")
    with open(p, "w", encoding="utf-8") as f:
        f.write('(kicad_pcb (version 20221018) (generator pcbnew)\n' + "".join(fps) + ')\n')
    with contextlib.redirect_stderr(io.StringIO()):
        return read_board(p)


def _overlaps(*fps):
    st = _read(*fps)
    return analyze_placement(st.footprints, st.outline).get("courtyard_overlaps", [])


def _sq(x1, y1, x2, y2):
    return [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]


# Producer output of 22060/2025/kicad/ESC_v1 (kicad-cli 10.0.7 DRC reports no courtyards_overlap
# for these pairs; the shapes overlap by 0.001-0.002 mm).
ESC_V1 = [
    {"reference": "J9", "layer": "F.Cu",
     "courtyard": {"min_x": 205.689, "min_y": 77.584, "max_x": 221.539, "max_y": 91.884},
     "courtyard_poly": [[[221.539, 91.884], [205.689, 91.884], [205.689, 77.584], [221.539, 77.584]]]},
    {"reference": "J17", "layer": "F.Cu",
     "courtyard": {"min_x": 212.921, "min_y": 91.883, "max_x": 221.521, "max_y": 102.783},
     "courtyard_poly": [[[221.521, 102.783], [221.521, 91.883], [212.921, 91.883], [212.921, 102.783]]]},
    {"reference": "R42", "layer": "B.Cu",
     "courtyard": {"min_x": 173.895, "min_y": 83.694, "max_x": 175.355, "max_y": 86.994},
     "courtyard_poly": [[[175.355, 86.994], [175.355, 83.694], [173.895, 83.694], [173.895, 86.994]]]},
    {"reference": "Q10", "layer": "B.Cu",
     "courtyard": {"min_x": 175.353, "min_y": 86.792, "max_x": 186.241, "max_y": 93.142},
     "courtyard_poly": [[[186.241, 93.142], [175.353, 93.142], [175.353, 86.792], [186.241, 86.792],
                         [186.241, 88.892], [182.253, 88.892], [182.253, 91.092], [186.241, 91.092]]]},
    {"reference": "R41", "layer": "B.Cu",
     "courtyard": {"min_x": 173.895, "min_y": 90.044, "max_x": 175.355, "max_y": 93.344},
     "courtyard_poly": [[[175.355, 93.344], [175.355, 90.044], [173.895, 90.044], [173.895, 93.344]]]},
]

# Two strips of width 0.25*sqrt(2) along the diagonals of a 10 mm square: they cross in a
# rhombus of area 0.125 mm^2 at (5, 5) that the 24x24 sample over the 10.25 mm window misses.
STRIP_A = _lines((-0.125, 0.125), (9.875, 10.125), (10.125, 9.875), (0.125, -0.125))
STRIP_B = _lines((0.125, 10.125), (10.125, 0.125), (9.875, -0.125), (-0.125, 9.875))


class TestCourtyardsCollide(unittest.TestCase):
    def test_shared_edge(self):
        self.assertFalse(courtyards_collide(_sq(0, 0, 2, 2), _sq(2, 0, 4, 2)))

    def test_overlap_within_tolerance(self):
        # each side shrinks 0.005 mm: a 0.004 mm overlap leaves a gap
        self.assertFalse(courtyards_collide(_sq(0, 0, 2, 2), _sq(1.996, 0, 4, 2)))

    def test_overlap_past_tolerance(self):
        self.assertTrue(courtyards_collide(_sq(0, 0, 2, 2), _sq(1.98, 0, 4, 2)))

    def test_disjoint(self):
        self.assertFalse(courtyards_collide(_sq(0, 0, 2, 2), _sq(3, 3, 4, 4)))

    def test_contained(self):
        self.assertTrue(courtyards_collide(_sq(0, 0, 4, 4), _sq(1, 1, 2, 2)))

    def test_square_in_an_l_notch(self):
        # kicad-cli 10.0.7: no courtyards_overlap at 0.0095 mm into both arms, one at 0.01 mm
        ell = [[[0, 0], [10, 0], [10, 3], [3, 3], [3, 10], [0, 10]]]
        self.assertFalse(courtyards_collide(ell, _sq(2.9905, 2.9905, 8, 8)))
        self.assertTrue(courtyards_collide(ell, _sq(2.99, 2.99, 8, 8)))

    def test_inside_a_hole(self):
        ring = _sq(0, 0, 10, 10) + _sq(2, 2, 8, 8)
        self.assertFalse(courtyards_collide(ring, _sq(3, 3, 7, 7)))
        self.assertTrue(courtyards_collide(ring, _sq(1, 3, 7, 7)))


class TestPlacementTolerance(unittest.TestCase):
    def tearDown(self):
        while _dirs:
            _dirs.pop().cleanup()

    def test_shared_edge_no_pm001(self):
        self.assertEqual(_overlaps(_fp("R1", _rect(0, 0, 2, 2)), _fp("R2", _rect(2, 0, 4, 2))), [])

    def test_overlap_0_004_no_pm001(self):
        self.assertEqual(_overlaps(_fp("R1", _rect(0, 0, 2, 2)), _fp("R2", _rect(1.996, 0, 4, 2))), [])

    def test_overlap_0_02_keeps_pm001_and_area(self):
        # a true pair must survive the tolerance with its measured area: 0.02 mm x 2 mm
        ov = _overlaps(_fp("R1", _rect(0, 0, 2, 2)), _fp("R2", _rect(1.98, 0, 4, 2)))
        self.assertEqual([(o["component_a"], o["component_b"], o["overlap_mm2"], o["severity"])
                          for o in ov], [("R1", "R2", 0.04, "warning")])

    def test_esc_v1_touching_pairs(self):
        self.assertEqual(analyze_placement(ESC_V1, {}).get("courtyard_overlaps", []), [])

    def test_crossing_slivers(self):
        ov = _overlaps(_fp("U1", STRIP_A), _fp("U2", STRIP_B))
        self.assertEqual(len(ov), 1)
        self.assertEqual(ov[0]["rule_id"], "PM-001")
        self.assertAlmostEqual(ov[0]["overlap_mm2"], 0.125, delta=0.01)


class TestOpenCourtyard(unittest.TestCase):
    def tearDown(self):
        while _dirs:
            _dirs.pop().cleanup()

    def test_t_junction(self):
        t = ('(fp_line (start 0 0) (end 2 0) (layer "F.CrtYd") (width 0.05))\n'
             '(fp_line (start 0 0) (end -2 0) (layer "F.CrtYd") (width 0.05))\n'
             '(fp_line (start 0 0) (end 0 2) (layer "F.CrtYd") (width 0.05))\n' + _rect(5, 5, 7, 7))
        st = _read(_fp("U1", t), _fp("R1", _rect(5.5, 5.5, 8, 8)))
        u1 = next(f for f in st.footprints if f["reference"] == "U1")
        self.assertNotIn("courtyard", u1)
        self.assertEqual(analyze_placement(st.footprints, st.outline).get("courtyard_overlaps", []), [])
        self.assertEqual([(d["message"], d["effect"]) for d in st.diagnostics],
                         [("U1: courtyard outline is not closed", "courtyard not used for placement checks")])

    def test_gap_within_chaining_epsilon_closes(self):
        # KiCad chains outline ends up to 0.02 mm apart
        sq = _lines((0, 0), (2, 0), (2, 2), (0, 2)).replace("(start 0 2)", "(start 0.015 2)")
        st = _read(_fp("U1", sq))
        self.assertEqual(st.diagnostics, [])
        self.assertEqual(len(st.footprints[0]["courtyard_poly"]), 1)


if __name__ == "__main__":
    unittest.main()
