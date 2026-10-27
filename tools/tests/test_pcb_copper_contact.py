# tools/tests/test_pcb_copper_contact.py
"""The --full copper graph joins copper that overlaps: every track a pad touches (ends and
interiors), arc tracks, overlapping tracks and vias inside pads, judged against the real pad
shape, with `*.Cu` / `F&B.Cu` pad layers expanded and NPTH pads without copper left out."""
import math, os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.connectivity import build_connectivity_graph  # noqa: E402
import pcb.geometry as geo  # noqa: E402
from pcb.pipeline import analyze_pcb, read_board  # noqa: E402
from tools.tests._fixtures import fixture  # noqa: E402

NETS = {1: "N"}


def _pad(ref, x, y, w, h, layers=("F.Cu",), shape="rect", angle=0, typ="smd", num="1",
         drill=None):
    d = {"number": num, "abs_x": x, "abs_y": y, "width": w, "height": h,
         "layers": list(layers), "shape": shape, "type": typ, "net_name": "N"}
    if angle:
        d["angle"] = angle
    if drill is not None:
        d["drill"] = drill
    return {"reference": ref, "pads": [d]}


def _seg(x1, y1, x2, y2, w=0.2, layer="F.Cu"):
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "width": w, "layer": layer, "net": 1}


def _graph(fps, segs=(), vias=(), arcs=()):
    tracks = {"segments": list(segs), "arcs": list(arcs)}
    return build_connectivity_graph(fps, tracks, {"vias": list(vias)}, None, [], NETS)["N"]


class TestPadShapeDistance(unittest.TestCase):
    def test_oval_stadium(self):
        pad = {"abs_x": 0, "abs_y": 0, "width": 2, "height": 1, "shape": "oval"}
        # The stadium ends at x = 1.0.
        self.assertAlmostEqual(geo.segment_to_pad_distance(_seg(1.3, 0, 5, 0), pad), 0.3)
        self.assertAlmostEqual(geo.segment_to_pad_distance(_seg(1.05, 0, 5, 0), pad), 0.05)

    def test_rect_rotated_45_corner_reaches_further(self):
        pad = {"abs_x": 0, "abs_y": 0, "width": 1, "height": 1, "shape": "rect", "angle": 45}
        self.assertAlmostEqual(geo.segment_to_pad_distance(_seg(0.75, 0, 5, 0), pad),
                               0.75 - math.sqrt(0.5), places=6)
        pad.pop("angle")
        self.assertAlmostEqual(geo.segment_to_pad_distance(_seg(0.75, 0, 5, 0), pad), 0.25)

    def test_rect_rotation_sense_matches_kicad(self):
        # A 4 x 0.4 rect at 30 deg: KiCad rotates counter-clockwise on screen (y down), so
        # the +x end of its long axis sits at (2cos30, -2sin30) = (1.732, -1.0).
        pad = {"abs_x": 0, "abs_y": 0, "width": 4, "height": 0.4, "shape": "rect", "angle": 30}
        self.assertAlmostEqual(geo.segment_to_pad_distance(_seg(1.732, -1.0, 1.732, -1.0), pad), 0.0)
        self.assertGreater(geo.segment_to_pad_distance(_seg(1.732, 1.0, 1.732, 1.0), pad), 1.0)

    def test_roundrect_corner(self):
        pad = {"abs_x": 0, "abs_y": 0, "width": 2, "height": 1, "shape": "roundrect",
               "roundrect_rratio": 0.25}
        # Inner rect 1.5 x 0.5, corner radius 0.25: from (1.5, 1.0) to corner (0.75, 0.25).
        self.assertAlmostEqual(geo.segment_to_pad_distance(_seg(1.5, 1.0, 1.5, 1.0), pad),
                               math.hypot(0.75, 0.75) - 0.25, places=6)
        pad["roundrect_rratio"] = 0.0
        self.assertAlmostEqual(geo.segment_to_pad_distance(_seg(1.5, 1.0, 1.5, 1.0), pad),
                               math.hypot(0.5, 0.5), places=6)

    def test_circle_and_crossing(self):
        pad = {"abs_x": 10, "abs_y": 10, "width": 2, "height": 2, "shape": "circle"}
        self.assertAlmostEqual(geo.segment_to_pad_distance(_seg(13, 10, 20, 10), pad), 2.0)
        self.assertEqual(geo.segment_to_pad_distance(_seg(5, 10, 15, 10), pad), 0.0)


class TestPadCopperLayers(unittest.TestCase):
    CU = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]

    def test_wildcards(self):
        self.assertEqual(geo.pad_copper_layers({"type": "thru_hole", "layers": ["*.Cu", "*.Mask"]},
                                           self.CU), self.CU)
        self.assertEqual(geo.pad_copper_layers({"type": "thru_hole", "layers": ["F&B.Cu", "*.Mask"]},
                                           self.CU), ["F.Cu", "B.Cu"])
        self.assertEqual(geo.pad_copper_layers({"type": "smd", "layers": ["F.Cu", "F.Paste"]},
                                           self.CU), ["F.Cu"])

    def test_npth_hole_covering_the_pad_has_no_copper(self):
        self.assertEqual(geo.pad_copper_layers({"type": "np_thru_hole", "shape": "circle",
                                                "width": 3, "height": 3, "drill": 3.2,
                                                "layers": ["*.Cu", "*.Mask"]}, self.CU), [])


class TestCopperGraph(unittest.TestCase):
    def test_pad_ends_two_tracks(self):
        g = _graph([_pad("A", 90, 100, 1, 1), _pad("P", 100, 100, 1.5, 1.5),
                    _pad("B", 110, 100, 1, 1)],
                   [_seg(90, 100, 99.7, 100), _seg(100.3, 100, 110, 100)])
        self.assertEqual(g["islands"], 1)
        self.assertEqual(g["disconnected_pads"], [])

    def test_pad_mid_track(self):
        g = _graph([_pad("A", 95, 100, 1, 1), _pad("M", 100, 100, 1, 1),
                    _pad("B", 105, 100, 1, 1)], [_seg(95, 100, 105, 100)])
        self.assertEqual(g["islands"], 1)

    def test_long_thin_pad_bare_gap(self):
        # Pad copper ends at y = 100.2, the track edge at 100.9: 0.7 mm of bare board.
        g = _graph([_pad("A", 100, 100, 6, 0.4), _pad("B", 100, 110, 1, 1)],
                   [_seg(100, 101.0, 100, 110)])
        self.assertEqual(g["islands"], 2)
        self.assertEqual(g["disconnected_pads"], [["A:1", "B:1"]])

    def test_long_thin_pad_rotated_touches(self):
        g = _graph([_pad("A", 100, 100, 6, 0.4, angle=90), _pad("B", 100, 110, 1, 1)],
                   [_seg(100, 101.0, 100, 110)])
        self.assertEqual(g["islands"], 1)

    def test_fb_cu_pad_with_back_track(self):
        g = _graph([_pad("J", 100, 100, 1.7, 1.7, layers=("F&B.Cu", "*.Mask"),
                         shape="circle", typ="thru_hole"),
                    _pad("B", 110, 100, 1, 1, layers=("B.Cu",))],
                   [_seg(100, 100, 110, 100, layer="B.Cu")])
        self.assertEqual(g["islands"], 1)

    def test_arc_track_joins_pads(self):
        arc = {"start": [100, 100], "mid": [105, 95], "end": [110, 100], "width": 0.2,
               "layer": "F.Cu", "net": 1}
        g = _graph([_pad("A", 100, 100, 1, 1), _pad("B", 110, 100, 1, 1)], arcs=[arc])
        self.assertEqual(g["islands"], 1)
        self.assertEqual(g["components"], {"A:1": 0, "B:1": 0})

    def test_arc_interior_touches_pad(self):
        # Arc centre (105, 100), radius 5. A 0.4 mm round pad centred 5.25 mm out at 45 deg
        # leaves 0.05 mm to the centreline, inside the 0.1 mm half width; the straight chord
        # start -> mid passes 1.46 mm further in.
        k = 5.25 * math.sqrt(0.5)
        arc = {"start": [100, 100], "mid": [105, 95], "end": [110, 100], "width": 0.2,
               "layer": "F.Cu", "net": 1}
        g = _graph([_pad("P", 105 - k, 100 - k, 0.4, 0.4, shape="circle"),
                    _pad("B", 110, 100, 1, 1)], arcs=[arc])
        self.assertEqual(g["islands"], 1)

    def test_overlapping_tracks_without_shared_endpoint(self):
        # 0.528 mm between the ends < 0.5 + 0.125 of half widths.
        g = _graph([_pad("A", 130, 100, 1, 1), _pad("B", 150, 100, 1, 1)],
                   [_seg(130, 100, 138.6, 100, w=1.0), _seg(139.128, 100, 150, 100, w=0.25)])
        self.assertEqual(g["islands"], 1)

    def test_via_in_pad(self):
        via = {"x": 100.5, "y": 100, "size": 0.6, "layers": ["F.Cu", "B.Cu"], "net": 1}
        g = _graph([_pad("A", 100, 100, 2, 2), _pad("B", 110, 100, 1, 1, layers=("B.Cu",))],
                   [_seg(100.5, 100, 110, 100, layer="B.Cu")], vias=[via])
        self.assertEqual(g["islands"], 1)

    def test_npth_pad_without_copper_is_not_a_node(self):
        g = _graph([_pad("H", 100, 100, 3, 3, layers=("*.Cu", "*.Mask"), shape="circle",
                         typ="np_thru_hole", num="", drill=3.2),
                    _pad("B", 110, 100, 1, 1)], [_seg(100, 100, 110, 100)])
        self.assertEqual(sorted(g["components"]), ["B:1"])

    def test_simple_project_plus5v_one_island(self):
        # KiCad DRC reports no unconnected item: the J1:1 track runs through R1:1.
        res = analyze_pcb(str(fixture("simple-project", "simple.kicad_pcb")),
                          include_trace_segments=True)
        g = res["connectivity_graph"]
        self.assertEqual(g["+5V"]["islands"], 1)
        self.assertEqual(g["+5V"]["disconnected_pads"], [])


ARC_BOARD = """(kicad_pcb (version 20221018) (generator pcbnew)
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
  (net 0 "")
  (net 1 "SIG")
  (footprint "L:A" (layer "F.Cu") (at 100 100)
    (property "Reference" "A1") (property "Value" "v")
    (pad "1" smd roundrect (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask") (roundrect_rratio 0.2) (net 1 "SIG")))
  (footprint "L:B" (layer "F.Cu") (at 110 100)
    (property "Reference" "B1") (property "Value" "v")
    (pad "1" smd roundrect (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask") (net 1 "SIG")))
  (arc (start 100 100) (mid 102.5 97.5) (end 105 100) (width 0.25) (layer "F.Cu") (net 1))
  (arc (start 105 100) (mid 107.5 102.5) (end 110 100) (width 0.25) (layer "F.Cu") (net 1))
  (gr_line (start 90 90) (end 120 90) (layer "Edge.Cuts") (width 0.1))
  (gr_line (start 120 90) (end 120 110) (layer "Edge.Cuts") (width 0.1))
  (gr_line (start 120 110) (end 90 110) (layer "Edge.Cuts") (width 0.1))
  (gr_line (start 90 110) (end 90 90) (layer "Edge.Cuts") (width 0.1))
)
"""


class TestArcOnlyBoard(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._d.name, "arcs.kicad_pcb")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(ARC_BOARD)

    def tearDown(self):
        self._d.cleanup()

    def test_reader_carries_roundrect_rratio(self):
        bd = read_board(self.path)
        pads = {fp["reference"]: fp["pads"][0] for fp in bd.footprints}
        self.assertEqual(pads["A1"]["roundrect_rratio"], 0.2)
        self.assertEqual(pads["B1"]["roundrect_rratio"], 0.25)

    def test_full_run_joins_pads_through_arcs(self):
        res = analyze_pcb(self.path, include_trace_segments=True)
        self.assertNotIn("connectivity_graph_error", res)
        g = res["connectivity_graph"]["SIG"]
        self.assertEqual(g["islands"], 1)
        self.assertEqual(g["disconnected_pads"], [])


if __name__ == "__main__":
    unittest.main()
