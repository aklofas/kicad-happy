# tools/tests/test_pcb_graphic_copper.py
"""Tracks written with a plural (layers "F.Cu" "F.Mask") keep their copper layer, and board
graphics on a copper layer that carry a net are copper (KiCad 8+): they join the pads they
touch in the --full graph and count as routing. Expected island counts are kicad-cli 10 DRC
unconnected_items on the same boards (0 items = 1 island, 1 item = 2)."""
import os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.connectivity import build_connectivity_graph  # noqa: E402
from pcb.pipeline import analyze_pcb, read_board  # noqa: E402

LAYERS = ('(layers (0 "F.Cu" signal) (31 "B.Cu" signal) (38 "B.Mask" user) (39 "F.Mask" user)'
          ' (44 "Edge.Cuts" user))\n')


def _board(body, version="20240108", nets='(net 0 "")\n(net 1 "N")\n'):
    pads = ""
    for ref, x in (("U1", 10), ("U2", 14)):
        net = '(net 1 "N")' if nets else '(net "N")'
        pads += (f'(footprint "t:X" (layer "F.Cu") (at {x} 10)\n'
                 f' (property "Reference" "{ref}" (at 0 -3 0) (layer "F.SilkS"))\n'
                 f' (attr smd)\n'
                 f' (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask") {net}))\n')
    return (f'(kicad_pcb (version {version}) (generator "pcbnew")\n'
            '(general (thickness 1.6))\n' + LAYERS + nets +
            '(gr_rect (start 0 0) (end 30 20) (stroke (width 0.05) (type default)) (fill none)'
            ' (layer "Edge.Cuts"))\n' + pads + body + ')\n')


def _read(text):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "b.kicad_pcb"
        p.write_text(text, encoding="utf-8")
        return read_board(str(p))


def _islands(text):
    bd = _read(text)
    g = build_connectivity_graph(bd.footprints, bd.tracks, bd.vias, bd.zone_fills, bd.zones,
                                 bd.net_names, board_layers=bd.layers, graphics=bd.graphics)
    return g["N"]["islands"]


def _analyze(text):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "b.kicad_pcb"
        p.write_text(text, encoding="utf-8")
        cwd = os.getcwd()
        os.chdir(d)
        try:
            return analyze_pcb(str(p))
        finally:
            os.chdir(cwd)


FILLED_POLY = ('(gr_poly (pts (xy 9 9.5) (xy 15 9.5) (xy 15 10.5) (xy 9 10.5))'
               ' (stroke (width 0) (type solid)) (fill solid) (layer "F.Cu") (net 1))\n')
# A ring around both pads; its outline and its (empty) inside touch neither pad.
OPEN_RING = ('(gr_poly (pts (xy 7 7) (xy 17 7) (xy 17 13) (xy 7 13))'
             ' (stroke (width 0.2) (type solid)) (fill none) (layer "F.Cu") (net 1))\n')
LINE = ('(gr_line (start 10 10) (end 14 10) (stroke (width 0.5) (type solid))'
        ' (layer "F.Cu") (net 1))\n')
NO_NET_POLY = ('(gr_poly (pts (xy 9 9.5) (xy 15 9.5) (xy 15 10.5) (xy 9 10.5))'
               ' (stroke (width 0) (type solid)) (fill solid) (layer "F.Cu"))\n')
# A net-N zone whose fill covers both pads and a small net-N rect drawn inside it, away
# from the pads: the fill joins the pads and the rect (kicad-cli: 0 unconnected).
ZONE_RECT = ('(zone (net 1) (net_name "N") (layer "F.Cu") (hatch edge 0.5)'
             ' (connect_pads yes (clearance 0.2)) (min_thickness 0.25)'
             ' (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))'
             ' (polygon (pts (xy 8 8) (xy 20 8) (xy 20 12) (xy 8 12)))'
             ' (filled_polygon (layer "F.Cu") (pts (xy 8 8) (xy 20 8) (xy 20 12) (xy 8 12))))\n'
             '(gr_rect (start 17 9.5) (end 18 10.5) (stroke (width 0) (type solid)) (fill solid)'
             ' (layer "F.Cu") (net 1))\n')
PLURAL_SEG = '(segment (start 10 10) (end 14 10) (width 0.25) (layers "F.Cu" "F.Mask") (net 1))\n'


class TestPluralLayerTracks(unittest.TestCase):
    def test_segment_keeps_copper_layer(self):
        bd = _read(_board(PLURAL_SEG, version="20241229"))
        self.assertEqual(bd.tracks["segments"][0]["layer"], "F.Cu")
        self.assertEqual(bd.tracks["layer_distribution"], {"F.Cu": 1})
        self.assertEqual(_islands(_board(PLURAL_SEG, version="20241229")), 1)

    def test_arc_keeps_copper_layer(self):
        arc = ('(arc (start 10 10) (mid 12 9) (end 14 10) (width 0.25)'
               ' (layers "B.Cu" "B.Mask") (net 1))\n')
        self.assertEqual(_read(_board(arc, version="20241229")).tracks["arcs"][0]["layer"],
                         "B.Cu")


class TestGraphicCopper(unittest.TestCase):
    def test_filled_poly_joins_pads(self):
        self.assertEqual(_islands(_board(FILLED_POLY)), 1)

    def test_unfilled_ring_touching_no_pad(self):
        self.assertEqual(_islands(_board(OPEN_RING)), 3)  # two pads + the ring itself

    def test_line_joins_pads(self):
        self.assertEqual(_islands(_board(LINE)), 1)

    # kicad-cli joins the two pads through net-less copper (0 unconnected), for a graphic as for
    # a net-0 track; the per-net graph leaves all net-less copper out, tracks and graphics alike.
    def test_graphic_without_net_joins_nothing(self):
        bd = _read(_board(NO_NET_POLY))
        self.assertEqual(bd.graphics, [])
        self.assertEqual(_islands(_board(NO_NET_POLY)), 2)

    def test_graphic_net_zero_joins_nothing(self):
        text = _board(NO_NET_POLY.replace('(layer "F.Cu")', '(layer "F.Cu") (net 0)'))
        self.assertEqual(_islands(text), 2)

    def test_non_copper_graphic_ignored(self):
        text = _board(FILLED_POLY.replace('"F.Cu"', '"F.Mask"'))
        self.assertEqual(_read(text).graphics, [])

    def test_graphic_inside_same_net_fill_joins_it(self):
        self.assertEqual(_islands(_board(ZONE_RECT)), 1)

    def test_kicad10_net_name(self):
        text = _board(FILLED_POLY.replace("(net 1)", '(net "N")'), version="20260101", nets="")
        self.assertEqual(_islands(text), 1)

    def test_routed_only_by_graphic_is_not_rt001(self):
        res = _analyze(_board(FILLED_POLY))
        self.assertFalse([f for f in res.get("findings", []) if f.get("rule_id") == "RT-001"])
        self.assertTrue(res["connectivity"]["routing_complete"])
        res = _analyze(_board(""))
        self.assertEqual(len([f for f in res.get("findings", []) if f.get("rule_id") == "RT-001"]),
                         1)


if __name__ == "__main__":
    unittest.main()
