# tools/tests/test_pcb_courtyard_per_side.py
"""PM-001 tests F.CrtYd against F.CrtYd and B.CrtYd against B.CrtYd, whichever side each part
is mounted on, as kicad-cli DRC (courtyards_overlap) does."""
import contextlib, io, os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.pipeline import analyze_pcb, read_board  # noqa: E402
from pcb.assembly import analyze_placement  # noqa: E402


def _rect(x1, y1, x2, y2, layer):
    return (f'(fp_rect (start {x1} {y1}) (end {x2} {y2}) (stroke (width 0.05) (type solid)) '
            f'(fill none) (layer "{layer}"))')


def _poly(pts, layer):
    xy = " ".join(f"(xy {x} {y})" for x, y in pts)
    return f'(fp_poly (pts {xy}) (stroke (width 0.05) (type solid)) (fill none) (layer "{layer}"))'


def _fp(ref, mount, x, y, *shapes):
    return (f'(footprint "T:{ref}" (layer "{mount}") (at {x} {y})\n'
            f'  (property "Reference" "{ref}")\n  (property "Value" "v")\n  {" ".join(shapes)})\n')


class _Board(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def _write(self, *fps):
        p = os.path.join(self._dir.name, "b.kicad_pcb")
        edge = "".join(f'(gr_line (start {a}) (end {b}) (stroke (width 0.1) (type solid)) (layer "Edge.Cuts"))'
                       for a, b in (("0 0", "100 0"), ("100 0", "100 40"),
                                    ("100 40", "0 40"), ("0 40", "0 0")))
        with open(p, "w", encoding="utf-8") as f:
            f.write('(kicad_pcb (version 20240108) (generator "pcbnew")\n' + "".join(fps) + edge + ')\n')
        return p

    def _pairs(self, *fps):
        with contextlib.redirect_stderr(io.StringIO()):
            st = read_board(self._write(*fps))
        ov = analyze_placement(st.footprints, st.outline).get("courtyard_overlaps", [])
        return {(o["component_a"], o["component_b"]): o for o in ov}


# kicad-cli 10.0.8 DRC on this board reports courtyards_overlap for A-B and E-F only.
C1 = (
    # front through-hole part with courtyards on both layers over a back-mounted part
    _fp("A", "F.Cu", 20, 20, _rect(-2, -2, 2, 2, "F.CrtYd"), _rect(-2, -2, 2, 2, "B.CrtYd")),
    _fp("B", "B.Cu", 21, 20, _rect(-1, -1, 1, 1, "B.CrtYd")),
    # same mounting side, courtyards on different layers
    _fp("C", "F.Cu", 40, 20, _rect(-2, -2, 2, 2, "B.CrtYd")),
    _fp("D", "F.Cu", 41, 20, _rect(-1, -1, 1, 1, "F.CrtYd")),
    # control: front against front
    _fp("E", "F.Cu", 60, 20, _rect(-2, -2, 2, 2, "F.CrtYd")),
    _fp("F", "F.Cu", 61, 20, _rect(-1, -1, 1, 1, "F.CrtYd")),
    # opposite sides, each courtyard on its own side
    _fp("G", "F.Cu", 80, 20, _rect(-2, -2, 2, 2, "F.CrtYd")),
    _fp("H", "B.Cu", 81, 20, _rect(-1, -1, 1, 1, "B.CrtYd")),
)


class TestCourtyardLayers(_Board):
    def test_pairs_match_drc(self):
        self.assertEqual(sorted(self._pairs(*C1)), [("A", "B"), ("E", "F")])

    def test_layer_is_the_courtyard_layer(self):
        pairs = self._pairs(*C1)
        self.assertEqual(pairs[("A", "B")]["layer"], "B.Cu")
        self.assertIn("on B.Cu", pairs[("A", "B")]["description"])
        self.assertEqual(pairs[("E", "F")]["layer"], "F.Cu")

    def test_one_finding_when_both_layers_collide(self):
        both = (_rect(-2, -2, 2, 2, "F.CrtYd"), _rect(-2, -2, 2, 2, "B.CrtYd"))
        pairs = self._pairs(_fp("J1", "F.Cu", 20, 20, *both), _fp("J2", "F.Cu", 21, 20, *both))
        self.assertEqual(list(pairs), [("J1", "J2")])
        self.assertEqual(pairs[("J1", "J2")]["overlap_mm2"], 12.0)

    def test_per_layer_data_not_in_output(self):
        with contextlib.redirect_stderr(io.StringIO()):
            res = analyze_pcb(self._write(*C1))
        self.assertTrue(res["footprints"])
        for fp in res["footprints"]:
            self.assertNotIn("_courtyard_sides", fp)
        self.assertEqual(sorted(tuple(f["components"]) for f in res["findings"]
                                if f.get("rule_id") == "PM-001"), [("A", "B"), ("E", "F")])


# U1: front through-hole part, an L-shaped courtyard on each layer with the notch in a
# different corner: F.CrtYd lacks [5,10]x[5,10], B.CrtYd lacks [0,5]x[5,10].
# kicad-cli 10.0.8 DRC with R1-R4 on one board reports U1-R3 and U1-R4 only.
U1 = _fp("U1", "F.Cu", 20, 20,
         _poly([(0, 0), (10, 0), (10, 5), (5, 5), (5, 10), (0, 10)], "F.CrtYd"),
         _poly([(0, 0), (10, 0), (10, 10), (5, 10), (5, 5), (0, 5)], "B.CrtYd"))


class TestNotchedBothLayers(_Board):
    def test_front_part_in_front_notch(self):
        # inside the B.CrtYd outline only: no F.CrtYd collision
        self.assertEqual(self._pairs(U1, _fp("R1", "F.Cu", 20, 20, _rect(6, 6, 9, 9, "F.CrtYd"))), {})

    def test_back_part_in_back_notch(self):
        self.assertEqual(self._pairs(U1, _fp("R2", "B.Cu", 20, 20, _rect(1, 6, 4, 9, "B.CrtYd"))), {})

    def test_back_part_on_back_outline(self):
        pairs = self._pairs(U1, _fp("R3", "B.Cu", 20, 20, _rect(6, 6, 9, 9, "B.CrtYd")))
        self.assertEqual(list(pairs), [("U1", "R3")])
        self.assertEqual(pairs[("U1", "R3")]["layer"], "B.Cu")
        self.assertEqual(pairs[("U1", "R3")]["overlap_mm2"], 9.0)

    def test_front_part_where_both_outlines_cover(self):
        # the two layers' outlines overlap here; each layer is filled on its own
        pairs = self._pairs(U1, _fp("R4", "F.Cu", 20, 20, _rect(1, 1, 4, 4, "F.CrtYd")))
        self.assertEqual(list(pairs), [("U1", "R4")])
        self.assertEqual(pairs[("U1", "R4")]["layer"], "F.Cu")
        self.assertEqual(pairs[("U1", "R4")]["overlap_mm2"], 9.0)


def _dict_fp(ref, layer, box):
    x1, y1, x2, y2 = box
    return {"reference": ref, "layer": layer,
            "courtyard": {"min_x": x1, "min_y": y1, "max_x": x2, "max_y": y2},
            "courtyard_poly": [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]}


class TestFootprintsWithoutPerLayerData(unittest.TestCase):
    """A footprint dict with only the merged courtyard is tested on its mounting side."""

    def _pairs(self, *fps):
        return [(o["component_a"], o["component_b"], o["layer"], o["overlap_mm2"])
                for o in analyze_placement(list(fps), {}).get("courtyard_overlaps", [])]

    def test_same_side(self):
        self.assertEqual(self._pairs(_dict_fp("R1", "F.Cu", (0, 0, 2, 2)),
                                     _dict_fp("R2", "F.Cu", (1, 0, 3, 2))),
                         [("R1", "R2", "F.Cu", 2.0)])
        self.assertEqual(self._pairs(_dict_fp("R1", "B.Cu", (0, 0, 2, 2)),
                                     _dict_fp("R2", "B.Cu", (1, 0, 3, 2))),
                         [("R1", "R2", "B.Cu", 2.0)])

    def test_opposite_sides(self):
        self.assertEqual(self._pairs(_dict_fp("R1", "F.Cu", (0, 0, 2, 2)),
                                     _dict_fp("R2", "B.Cu", (1, 0, 3, 2))), [])

    def test_bbox_only(self):
        a = _dict_fp("R1", "F.Cu", (0, 0, 2, 2))
        b = _dict_fp("R2", "F.Cu", (1, 0, 3, 2))
        del a["courtyard_poly"], b["courtyard_poly"]
        self.assertEqual(self._pairs(a, b), [("R1", "R2", "F.Cu", 2.0)])


if __name__ == "__main__":
    unittest.main()
