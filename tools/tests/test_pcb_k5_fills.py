# tools/tests/test_pcb_k5_fills.py
"""KiCad 5 stored each zone fill as the centre line of a stroke min_thickness wide. KiCad 10
loads a file older than 20250210 that does not say `(filled_areas_thickness no)` by growing every
fill by min_thickness/2 with round corners (PCB_IO_KICAD_SEXPR_PARSER::parseZONE,
InflateWithLinkedHoles). Expected areas are the fills of the same board after
`kicad-cli pcb upgrade` (10.0.6): 105.081 mm^2 (10 x 10 square) and 350.112 mm^2 (20 x 20 square
with an 8 x 8 hole joined to the outline by a zero-width slit)."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.sexp import parse  # noqa: E402
from pcb.reader import extract_zones  # noqa: E402

KICAD_SQUARE = 105.081
KICAD_SLIT = 350.112

SQUARE = '(filled_polygon (pts (xy 1 1) (xy 11 1) (xy 11 11) (xy 1 11)))'
SLIT = ('(filled_polygon (pts (xy 15 1) (xy 35 1) (xy 35 21) (xy 15 21) (xy 15 11) (xy 21 11)'
        ' (xy 21 15) (xy 29 15) (xy 29 7) (xy 21 7) (xy 21 11) (xy 15 11)))')


def _board(fill, version=20171130, extra="", layer="F.Cu", keepout=""):
    return parse(
        f'(kicad_pcb (version {version}) (host pcbnew 5.1.9)\n'
        '(layers (0 F.Cu signal) (31 B.Cu signal) (44 Edge.Cuts user))\n'
        '(net 0 "") (net 1 GND)\n'
        f'(zone (net 1) (net_name GND) (layer {layer}) (hatch edge 0.508)\n'
        ' (connect_pads (clearance 0.508)) (min_thickness 0.254)' + extra + keepout + '\n'
        ' (fill yes (arc_segments 32) (thermal_gap 0.508) (thermal_bridge_width 0.508))\n'
        ' (polygon (pts (xy 0 0) (xy 40 0) (xy 40 30) (xy 0 30)))\n'
        f' {fill}))\n')


class KiCad5StrokedFill(unittest.TestCase):
    def test_square_area_matches_kicad_upgrade(self):
        zones, _ = extract_zones(_board(SQUARE))
        self.assertAlmostEqual(zones[0]["filled_area_mm2"], KICAD_SQUARE,
                               delta=KICAD_SQUARE * 0.005)

    def test_linked_hole_slit_edges_add_no_area(self):
        zones, _ = extract_zones(_board(SLIT, layer="B.Cu"))
        # A slit counted as outline would add 2 x 6 x 0.127 = 1.52 mm^2 (0.44 %).
        self.assertAlmostEqual(zones[0]["filled_area_mm2"], KICAD_SLIT,
                               delta=KICAD_SLIT * 0.002)

    def test_copper_reaches_half_min_thickness_past_the_outline(self):
        zones, fills = extract_zones(_board(SQUARE))
        self.assertTrue(fills.has_copper_at(11.1, 5, "F.Cu"))
        self.assertFalse(fills.has_copper_at(11.2, 5, "F.Cu"))
        self.assertEqual(len(fills.zones_at_point(0.9, 0.95, "F.Cu", zones)), 1)
        self.assertEqual(fills.fill_regions_at_point(11.1, 5, "F.Cu", zones, net_name="GND"),
                         [(0, 0)])
        # Hole of the slit polygon: its edge moves 0.127 mm into the hole.
        zones, fills = extract_zones(_board(SLIT, layer="B.Cu"))
        self.assertTrue(fills.has_copper_at(21.1, 11, "B.Cu"))
        self.assertFalse(fills.has_copper_at(21.2, 11, "B.Cu"))
        self.assertEqual(zones[0]["filled_bbox"], [14.873, 0.873, 35.127, 21.127])

    def test_edge_distance_is_to_the_grown_outline(self):
        _zones, fills = extract_zones(_board(SQUARE))
        self.assertAlmostEqual(fills.min_edge_distance(11.5, 5, "F.Cu"), 0.373, places=6)
        self.assertAlmostEqual(fills.min_edge_distance(11.05, 5, "F.Cu"), 0.077, places=6)
        self.assertAlmostEqual(fills.min_edge_distance(6, 5, "F.Cu"), 4 + 0.127, places=6)

    def test_not_stroked_when_the_file_says_so(self):
        for board in (_board(SQUARE, extra=" (filled_areas_thickness no)"),
                      _board(SQUARE, version=20250210),
                      _board(SQUARE, keepout=" (keepout (tracks not_allowed))")):
            zones, fills = extract_zones(board)
            self.assertAlmostEqual(zones[0]["filled_area_mm2"], 100.0, places=2)
            self.assertFalse(fills.has_copper_at(11.1, 5, "F.Cu"))
            self.assertAlmostEqual(fills.min_edge_distance(11.5, 5, "F.Cu"), 0.5, places=6)

    def test_stroked_when_the_token_is_absent_or_yes(self):
        # KiCad 10 keeps the stroke unless the token is present and false.
        zones, _ = extract_zones(_board(SQUARE, version=20221018,
                                        extra=" (filled_areas_thickness yes)"))
        self.assertAlmostEqual(zones[0]["filled_area_mm2"], KICAD_SQUARE,
                               delta=KICAD_SQUARE * 0.005)


if __name__ == "__main__":
    unittest.main()
