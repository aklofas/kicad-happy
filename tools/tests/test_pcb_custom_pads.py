# tools/tests/test_pcb_custom_pads.py
"""A custom pad's copper is its anchor plus every drawn primitive, rotated by the pad angle
(KiCad PAD::BuildEffectiveShapes): a track that reaches only a primitive joins the pad in the
--full graph. Expected island counts are kicad-cli 10 DRC unconnected_items on the same boards
(0 items = 1 island, 1 item = 2)."""
import json, os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.connectivity import build_connectivity_graph  # noqa: E402
from pcb.pipeline import analyze_pcb, read_board  # noqa: E402

LAYERS = ('(layers (0 "F.Cu" signal) (31 "B.Cu" signal) (38 "B.Mask" user) (39 "F.Mask" user)'
          ' (44 "Edge.Cuts" user))\n')

# Anchor circle of 1 mm plus a filled 4 x 1 mm bar to the pad's local +x.
BAR = ('(primitives (gr_poly (pts (xy 0 -0.5) (xy 4 -0.5) (xy 4 0.5) (xy 0 0.5))'
       ' (width 0) (fill yes)))')
# The same reach drawn as an unfilled 0.3 mm line.
LINE = '(primitives (gr_line (start 0 0) (end 4 0) (width 0.3)))'


def _board(pad_angle=0, fp_angle=0, prims=BAR, u2=(20, 10), track=((14, 10), (20, 10)),
           anchor="circle", size=(1, 1)):
    fp_at = f"10 10 {fp_angle}" if fp_angle else "10 10"
    pad_at = f"0 0 {pad_angle}" if pad_angle else "0 0"
    (x1, y1), (x2, y2) = track
    return ('(kicad_pcb (version 20240108) (generator "pcbnew")\n'
            '(general (thickness 1.6))\n' + LAYERS + '(net 0 "")\n(net 1 "N")\n'
            '(gr_rect (start 0 0) (end 30 20) (stroke (width 0.05) (type default)) (fill none)'
            ' (layer "Edge.Cuts"))\n'
            f'(footprint "t:J" (layer "F.Cu") (at {fp_at})\n'
            ' (property "Reference" "U1" (at 0 -3 0) (layer "F.SilkS"))\n (attr smd)\n'
            f' (pad "1" smd custom (at {pad_at}) (size {size[0]} {size[1]})'
            ' (layers "F.Cu" "F.Mask") (net 1 "N")'
            f' (options (clearance outline) (anchor {anchor})) {prims}))\n'
            f'(footprint "t:X" (layer "F.Cu") (at {u2[0]} {u2[1]})\n'
            ' (property "Reference" "U2" (at 0 -3 0) (layer "F.SilkS"))\n (attr smd)\n'
            ' (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask") (net 1 "N")))\n'
            f'(segment (start {x1} {y1}) (end {x2} {y2}) (width 0.25) (layer "F.Cu") (net 1))\n'
            ')\n')


# KiCad 5 form of the bar pad: a module, primitives without a fill token (a polygon is filled).
def _legacy_board(track_end=14):
    return ('(kicad_pcb (version 20171130) (host pcbnew 5.1.9)\n'
            '(general (thickness 1.6))\n'
            '(layers (0 F.Cu signal) (31 B.Cu signal) (38 B.Mask user) (39 F.Mask user)'
            ' (44 Edge.Cuts user))\n'
            '(net 0 "") (net 1 N)\n'
            '(net_class Default "d" (clearance 0.2) (trace_width 0.25) (via_dia 0.8)'
            ' (via_drill 0.4) (uvia_dia 0.3) (uvia_drill 0.1) (add_net N))\n'
            '(gr_line (start 0 0) (end 30 0) (layer Edge.Cuts) (width 0.05))\n'
            '(gr_line (start 30 0) (end 30 20) (layer Edge.Cuts) (width 0.05))\n'
            '(gr_line (start 30 20) (end 0 20) (layer Edge.Cuts) (width 0.05))\n'
            '(gr_line (start 0 20) (end 0 0) (layer Edge.Cuts) (width 0.05))\n'
            '(module t:J (layer F.Cu) (tedit 0) (tstamp 1) (at 10 10)\n'
            ' (fp_text reference U1 (at 0 -3) (layer F.SilkS) (effects (font (size 1 1)'
            ' (thickness 0.15))))\n'
            ' (pad 1 smd custom (at 0 0) (size 1 1) (layers F.Cu F.Mask) (net 1 N)'
            ' (zone_connect 0) (options (clearance outline) (anchor circle))'
            ' (primitives (gr_poly (pts (xy 0 -0.5) (xy 4 -0.5) (xy 4 0.5) (xy 0 0.5))'
            ' (width 0)))))\n'
            '(module t:X (layer F.Cu) (tedit 0) (tstamp 2) (at 20 10)\n'
            ' (fp_text reference U2 (at 0 -3) (layer F.SilkS) (effects (font (size 1 1)'
            ' (thickness 0.15))))\n'
            ' (pad 1 smd rect (at 0 0) (size 1 1) (layers F.Cu F.Mask) (net 1 N)))\n'
            f'(segment (start {track_end} 10) (end 20 10) (width 0.25) (layer F.Cu) (net 1))\n'
            ')\n')


# Both footprints and the track on B.Cu: primitives are read as written, not mirrored again.
def _back_board():
    b = _board().replace('(layer "F.Cu") (at', '(layer "B.Cu") (at')
    return b.replace('(layers "F.Cu" "F.Mask")', '(layers "B.Cu" "B.Mask")').replace(
        '(layer "F.Cu") (net 1))', '(layer "B.Cu") (net 1))')


CASES = {
    # name: (board text, kicad-cli unconnected items)
    "bar_track_at_tip": (_board(), 0),
    "bar_track_past_tip": (_board(track=((15, 10), (20, 10))), 1),
    "anchor_only": (_board(prims=""), 1),
    "bar_pad_rotated_90": (_board(pad_angle=90, u2=(10, 2), track=((10, 6), (10, 2))), 0),
    # the pad angle in the file is absolute: footprint and pad both at 90 degrees
    "bar_fp_and_pad_rotated_90": (_board(pad_angle=90, fp_angle=90, u2=(10, 2),
                                         track=((10, 6), (10, 2))), 0),
    "bar_rotated_90_track_on_unrotated_side": (_board(pad_angle=90), 1),
    "line_primitive": (_board(prims=LINE, track=((14.1, 10), (20, 10))), 0),
    "line_primitive_past_stroke": (_board(prims=LINE, track=((14.3, 10), (20, 10))), 1),
    "anchor_rect_corner": (_board(prims="", anchor="rect", size=(3, 3),
                                  track=((11.4, 11.4), (20, 10))), 0),
    # a circle anchor has the diameter of the size's x
    "anchor_circle_uses_size_x": (_board(prims="", size=(1, 3), track=((10, 11.2), (20, 10))), 1),
    "back_side_bar": (_back_board(), 0),
    "legacy_bar": (_legacy_board(), 0),
    "legacy_anchor_gap": (_legacy_board(track_end=15), 1),
}


def _islands(text):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "b.kicad_pcb"
        p.write_text(text, encoding="utf-8")
        bd = read_board(str(p))
    g = build_connectivity_graph(bd.footprints, bd.tracks, bd.vias, bd.zone_fills, bd.zones,
                                 bd.net_names, board_layers=bd.layers, graphics=bd.graphics)
    return g["N"]["islands"]


class TestCustomPadPrimitives(unittest.TestCase):
    def test_islands_match_kicad(self):
        for name, (text, unconnected) in CASES.items():
            with self.subTest(name):
                self.assertEqual(_islands(text), unconnected + 1)

    def test_pad_geometry_stays_out_of_the_output(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.kicad_pcb"
            p.write_text(_board(), encoding="utf-8")
            cwd = os.getcwd()
            os.chdir(d)
            try:
                out = json.dumps(analyze_pcb(str(p), include_trace_segments=True))
            finally:
                os.chdir(cwd)
        self.assertNotIn('"_prims"', out)
        self.assertNotIn('"_anchor"', out)

if __name__ == "__main__":
    unittest.main()
