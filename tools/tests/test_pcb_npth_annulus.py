# tools/tests/test_pcb_npth_annulus.py
"""An NPTH pad whose copper is larger than its hole carries copper and joins the --full
graph, as in KiCad 10 (pad.cpp PAD::IsOnCopperLayer). Every expected value below is what
`kicad-cli 10.0.6 pcb drc` reports for the same board: two N pads joined only through the
NPTH pad's annulus are one cluster (no unconnected item) or two."""
import os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.connectivity import build_connectivity_graph  # noqa: E402
import pcb.geometry as geo  # noqa: E402
from pcb.pipeline import analyze_pcb, read_board  # noqa: E402

CIRCLE_3 = '(pad "" np_thru_hole circle (at 0 0) (size 3 3) (drill 2.5) (layers "*.Cu" "*.Mask")'


def _board(npth_pad, layer="F.Cu", left_end=98.6, right_start=101.4):
    """Pads A1 (x 90) and B1 (x 110) on net N, an NPTH pad of net N at x 100, and two tracks
    that end inside the NPTH pad's copper but not in each other."""
    def fp(ref, x, pad):
        return (f'  (footprint "L:{ref}" (layer "F.Cu") (at {x} 100)\n'
                f'    (property "Reference" "{ref}") (property "Value" "v")\n'
                f'    {pad})\n')
    smd = '(pad "1" smd rect (at 0 0) (size 1 1) (layers "{}") (net 1 "N"))'.format(layer)
    return ('(kicad_pcb (version 20240108) (generator "pcbnew")\n'
            '  (general (thickness 1.6))\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (38 "B.Mask" user) (39 "F.Mask" user)'
            ' (44 "Edge.Cuts" user))\n'
            '  (net 0 "")\n  (net 1 "N")\n'
            + fp("A1", 90, smd) + fp("B1", 110, smd)
            + fp("H1", 100, npth_pad + ' (net 1 "N"))')
            + f'  (segment (start 90 100) (end {left_end} 100) (width 0.2) (layer "{layer}") (net 1))\n'
            f'  (segment (start {right_start} 100) (end 110 100) (width 0.2) (layer "{layer}") (net 1))\n'
            '  (gr_rect (start 80 90) (end 120 110) (stroke (width 0.1) (type solid)) (fill none)'
            ' (layer "Edge.Cuts"))\n)\n')


# name -> (pad text, track layer, KiCad joins A1 and B1 through the NPTH pad)
KICAD_CASES = {
    "circle_annulus": (CIRCLE_3, "F.Cu", True),
    "circle_hole_equals_pad": (CIRCLE_3.replace("(drill 2.5)", "(drill 3)"), "F.Cu", False),
    "circle_hole_larger": (CIRCLE_3.replace("(drill 2.5)", "(drill 3.2)"), "F.Cu", False),
    # KiCad keeps an NPTH pad's connectivity item on the first copper layer of its stack only.
    "annulus_back_tracks": (CIRCLE_3, "B.Cu", False),
    "annulus_layers_listed_back_first": (
        CIRCLE_3.replace('"*.Cu"', '"B.Cu" "F.Cu"'), "F.Cu", True),
    "no_drill": (CIRCLE_3.replace(" (drill 2.5)", ""), "F.Cu", True),
    "rect_hole_larger": (CIRCLE_3.replace("circle", "rect").replace("(drill 2.5)", "(drill 3.2)"),
                         "F.Cu", True),
    "oval_round_hole_covers": ('(pad "" np_thru_hole oval (at 0 0) (size 3 2) (drill 3)'
                               ' (layers "*.Cu" "*.Mask")', "F.Cu", False),
    "oval_oblong_hole_equal": ('(pad "" np_thru_hole oval (at 0 0) (size 3 2) (drill oval 3 2)'
                               ' (layers "*.Cu" "*.Mask")', "F.Cu", False),
    "circle_oblong_hole_as_wide": ('(pad "" np_thru_hole circle (at 0 0) (size 3 3)'
                                   ' (drill oval 3 2) (layers "*.Cu" "*.Mask")', "F.Cu", False),
    "padstack_back_layer_no_ring": (
        CIRCLE_3 + ' (padstack (mode custom) (layer "B.Cu" (shape circle) (size 2.5 2.5)))',
        "F.Cu", False),
    "padstack_back_layer_rect": (
        CIRCLE_3 + ' (padstack (mode custom) (layer "B.Cu" (shape rect) (size 2 2)))',
        "F.Cu", True),
    "padstack_front_no_ring_back_ring": (
        CIRCLE_3.replace("(size 3 3)", "(size 2.5 2.5)")
        + ' (padstack (mode custom) (layer "B.Cu" (shape circle) (size 3 3)))', "F.Cu", False),
}


class TestNpthFlashesCopper(unittest.TestCase):
    def test_kicad_rule(self):
        # (pad dict as the reader keeps it, has copper) per pad.cpp PAD::IsOnCopperLayer
        cases = [
            ({"shape": "circle", "width": 3, "height": 3, "drill": 2.5}, True),
            ({"shape": "circle", "width": 3, "height": 3, "drill": 3}, False),
            ({"shape": "circle", "width": 3, "height": 3, "drill": 3.2}, False),
            ({"shape": "circle", "width": 3, "height": 3}, True),
            ({"shape": "circle", "width": 3, "height": 3, "drill": 3, "_drill_offset": True}, True),
            ({"shape": "oval", "width": 3, "height": 2, "drill": 3}, False),
            ({"shape": "oval", "width": 3, "height": 2, "drill": 2.5, "drill_shape": "oval",
              "drill_h": 2}, True),
            ({"shape": "oval", "width": 3, "height": 2, "drill": 3, "drill_shape": "oval",
              "drill_h": 2}, False),
            ({"shape": "rect", "width": 3, "height": 3, "drill": 3.2}, True),
            ({"shape": "roundrect", "width": 3, "height": 3, "drill": 3.2}, True),
        ]
        for pad, want in cases:
            pad = dict(pad, type="np_thru_hole", layers=["*.Cu", "*.Mask"])
            with self.subTest(pad=pad):
                self.assertIs(geo.npth_flashes_copper(pad), want)

    def test_copper_layers_of_an_npth_pad(self):
        cu = ["F.Cu", "In1.Cu", "B.Cu"]
        ring = {"type": "np_thru_hole", "shape": "circle", "width": 3, "height": 3,
                "drill": 2.5, "layers": ["*.Cu", "*.Mask"]}
        self.assertEqual(geo.pad_copper_layers(ring, cu), ["F.Cu"])
        self.assertEqual(geo.pad_copper_layers(dict(ring, layers=["B.Cu", "In1.Cu"]), cu),
                         ["In1.Cu"])
        self.assertEqual(geo.pad_copper_layers(dict(ring, drill=3), cu), [])

    def test_pad_on_layer(self):
        ring = {"type": "np_thru_hole", "shape": "circle", "width": 3, "height": 3,
                "drill": 2.5, "layers": ["*.Cu", "*.Mask"]}
        self.assertTrue(geo._pad_on_layer(ring, "B.Cu", "F.Cu"))
        self.assertFalse(geo._pad_on_layer(dict(ring, drill=3), "F.Cu", "F.Cu"))
        self.assertFalse(geo._pad_on_layer(dict(ring, drill=3), "B.Cu", "F.Cu"))


class TestNpthGraph(unittest.TestCase):
    def _graph(self, drill, layer="F.Cu"):
        def pad(ref, x, w, typ="smd", shape="rect", layers=(layer,), num="1", **kw):
            d = {"number": num, "abs_x": x, "abs_y": 100, "width": w, "height": w,
                 "layers": list(layers), "shape": shape, "type": typ, "net_name": "N", **kw}
            return {"reference": ref, "pads": [d]}
        fps = [pad("A", 90, 1), pad("B", 110, 1),
               pad("H", 100, 3, typ="np_thru_hole", shape="circle", layers=("*.Cu", "*.Mask"),
                   num="", drill=drill)]
        segs = [{"x1": 90, "y1": 100, "x2": 98.6, "y2": 100, "width": 0.2, "layer": layer,
                 "net": 1},
                {"x1": 101.4, "y1": 100, "x2": 110, "y2": 100, "width": 0.2, "layer": layer,
                 "net": 1}]
        return build_connectivity_graph(fps, {"segments": segs, "arcs": []}, {"vias": []},
                                        None, [], {1: "N"})["N"]

    def test_annulus_joins_tracks(self):
        g = self._graph(2.5)
        self.assertEqual(g["islands"], 1)
        self.assertEqual(g["components"]["A:1"], g["components"]["B:1"])

    def test_hole_as_large_as_pad_is_no_node(self):
        g = self._graph(3.2)
        self.assertNotIn("H:", g["components"])
        self.assertNotEqual(g["components"]["A:1"], g["components"]["B:1"])

    def test_back_layer_tracks_do_not_join(self):
        g = self._graph(2.5, layer="B.Cu")
        self.assertNotEqual(g["components"]["A:1"], g["components"]["B:1"])


class TestNpthBoardsAgainstKicad(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._d.cleanup()

    def _run(self, name, text):
        path = os.path.join(self._d.name, name + ".kicad_pcb")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        res = analyze_pcb(path, include_trace_segments=True)
        self.assertNotIn("connectivity_graph_error", res)
        return path, res["connectivity_graph"]["N"]

    def test_cases(self):
        for name, (pad, layer, joined) in KICAD_CASES.items():
            with self.subTest(case=name):
                _, g = self._run(name, _board(pad, layer))
                comp = g["components"]
                self.assertIs(comp["A1:1"] == comp["B1:1"], joined)

    def test_drill_offset(self):
        # Hole as large as the pad but offset from it: the pad flashes copper (KiCad joins).
        pad = CIRCLE_3.replace("(drill 2.5)", "(drill 3 (offset 0.3 0))")
        path, g = self._run("offset", _board(pad, left_end=98.9, right_start=101.1))
        self.assertEqual(g["components"]["A1:1"], g["components"]["B1:1"])
        h = next(fp for fp in read_board(path).footprints if fp["reference"] == "H1")
        self.assertEqual(h["pads"][0]["drill"], 3.0)


if __name__ == "__main__":
    unittest.main()
