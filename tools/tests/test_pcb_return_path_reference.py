# tools/tests/test_pcb_return_path_reference.py
"""Return-path coverage counts only ground or power-rail zone copper on the reference layer.

The return current of a microstrip flows in the nearest plane; a power plane serves when it
is decoupled to ground (Ott, EMC Engineering ch. 16; Bogatin ch. 8). So a sample is covered
only by a ground or power zone fill; a fill of another signal net, a track or a pad is not a
reference plane. The reference layer is the nearest other copper layer (by dielectric
thickness) that carries ground or power zone copper; a layer without such copper is never the
reference. A via's own antipad in the plane stays covered (KH-392).

Each case routes one F.Cu track of net SIG from x=2 to x=18 at y=10: 16 mm sampled every
2 mm = 9 points. Coverage = covered points / 9 (the analyzer reports nets below 95 %)."""
import os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.pipeline import analyze_pcb  # noqa: E402
from pcb.routing import _build_reference_layer_map  # noqa: E402

CU2 = '(0 "F.Cu" signal) (31 "B.Cu" signal)'
CU4 = '(0 "F.Cu" signal) (1 "In1.Cu" signal) (2 "In2.Cu" signal) (31 "B.Cu" signal)'
NETS = ["SIG", "GND", "SIG2", "+3V3", "MCU3v3"]
SIG_TRACK = '(segment (start 2 10) (end 18 10) (width 0.2) (layer "F.Cu") (net 1))\n'


def net_no(name):
    return NETS.index(name) + 1


def zone(net, layer, x0=0, x1=20, y0=5, y1=15):
    pts = f'(pts (xy {x0} {y0}) (xy {x1} {y0}) (xy {x1} {y1}) (xy {x0} {y1}))'
    return (f'(zone (net {net_no(net)}) (net_name "{net}") (layer "{layer}") (hatch edge 0.5)'
            ' (connect_pads (clearance 0.2)) (min_thickness 0.25)'
            ' (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))'
            f' (polygon {pts}) (filled_polygon (layer "{layer}") {pts}))\n')


# A GND fill far from the track, so the board has fill data but none near the signal.
FAR_GND = zone("GND", "B.Cu", 40, 45, 40, 45)


def board(body, cu=CU2):
    nets = '(net 0 "")\n' + "".join(f'(net {i + 1} "{n}")\n' for i, n in enumerate(NETS))
    return ('(kicad_pcb (version 20240108) (generator "pcbnew")\n(general (thickness 1.6))\n'
            f'(layers {cu} (38 "B.Mask" user) (39 "F.Mask" user) (44 "Edge.Cuts" user))\n'
            '(setup (pad_to_mask_clearance 0))\n' + nets
            + '(gr_rect (start 0 0) (end 50 50) (stroke (width 0.05) (type default)) (fill none)'
            ' (layer "Edge.Cuts"))\n' + SIG_TRACK + body + ')\n')


def coverage(text):
    """SIG's reference-plane coverage in percent (100 when the analyzer reports no gap)."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "b.kicad_pcb"
        p.write_text(text, encoding="utf-8")
        cwd = os.getcwd()
        os.chdir(d)
        try:
            out = analyze_pcb(str(p), include_trace_segments=True)
        finally:
            os.chdir(cwd)
    entries = {e["net"]: e for e in out.get("return_path_continuity") or []}
    return entries["SIG"]["reference_plane_coverage_pct"] if "SIG" in entries else 100.0


class ReferenceCopper(unittest.TestCase):
    def test_ground_fill_covers(self):
        self.assertEqual(coverage(board(zone("GND", "B.Cu"))), 100.0)

    def test_power_rail_fill_covers(self):
        self.assertEqual(coverage(board(zone("+3V3", "B.Cu"))), 100.0)

    def test_signal_net_fill_is_a_gap(self):
        self.assertEqual(coverage(board(zone("SIG2", "B.Cu") + FAR_GND)), 0.0)

    def test_ground_track_without_zone_is_a_gap(self):
        gnd_track = '(segment (start 2 10) (end 18 10) (width 0.5) (layer "B.Cu") (net 2))\n'
        self.assertEqual(coverage(board(gnd_track + FAR_GND)), 0.0)

    def test_npth_pad_is_a_gap(self):
        npth = ('(footprint "t:H" (layer "F.Cu") (at 10 10)\n'
                ' (property "Reference" "H1" (at 0 -3 0) (layer "F.SilkS")) (attr board_only)\n'
                ' (pad "" np_thru_hole circle (at 0 0) (size 3 3) (drill 3) (layers "*.Cu" "*.Mask")))\n')
        self.assertEqual(coverage(board(npth + FAR_GND)), 0.0)


class ViaAntipad(unittest.TestCase):
    # GND fill on B.Cu with a 1.6 mm slot at x 9.2..10.8: the sample at x=10 sees no copper
    # within 0.5 mm, unless a through via sits there (its antipad is an expected void).
    SPLIT = zone("GND", "B.Cu", 0, 9.2) + zone("GND", "B.Cu", 10.8, 20)

    def test_slot_without_via_is_one_gap(self):
        self.assertEqual(coverage(board(self.SPLIT)), round(8 / 9 * 100, 1))

    def test_via_antipad_is_covered(self):
        via = '(via (at 10 10) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 2))\n'
        self.assertEqual(coverage(board(self.SPLIT + via)), 100.0)


class ReferenceLayer(unittest.TestCase):
    def test_empty_inner_layers_are_not_the_reference(self):
        # 4 layers, no stackup in the file, nothing on In1/In2: the return current flows in
        # the B.Cu GND plane, so the F.Cu track is fully covered.
        self.assertEqual(coverage(board(zone("GND", "B.Cu"), cu=CU4)), 100.0)

    def test_inner_layer_with_only_signal_fill_is_not_the_reference(self):
        self.assertEqual(coverage(board(zone("SIG2", "In1.Cu") + zone("GND", "B.Cu"), cu=CU4)),
                         100.0)

    def test_power_plane_on_inner_layer_covers(self):
        self.assertEqual(coverage(board(zone("MCU3v3", "In2.Cu"), cu=CU4)), 100.0)

    def test_nearest_reference_layer_wins(self):
        # In1 carries GND only at x 0..10; B.Cu is a full GND plane. In1 is the nearer
        # reference, so the samples at x=12..18 (4 of 9) are gaps there.
        text = board(zone("GND", "In1.Cu", 0, 10) + zone("GND", "B.Cu"), cu=CU4)
        self.assertEqual(coverage(text), round(5 / 9 * 100, 1))

    def test_map_without_reference_layers_is_the_adjacent_layer(self):
        st = [{"name": "F.Cu", "type": "copper"}, {"type": "core", "thickness": 0.48},
              {"name": "In1.Cu", "type": "copper"}, {"type": "prepreg", "thickness": 0.48},
              {"name": "In2.Cu", "type": "copper"}, {"type": "core", "thickness": 0.48},
              {"name": "B.Cu", "type": "copper"}]
        self.assertEqual(_build_reference_layer_map(st),
                         {"F.Cu": "In1.Cu", "In1.Cu": "F.Cu", "In2.Cu": "In1.Cu",
                          "B.Cu": "In2.Cu"})
        self.assertEqual(_build_reference_layer_map(st, {"B.Cu"}),
                         {"F.Cu": "B.Cu", "In1.Cu": "B.Cu", "In2.Cu": "B.Cu",
                          "B.Cu": "In2.Cu"})

    def test_a_layer_is_never_its_own_reference(self):
        # A file stackup that lists its copper twice (seen in the corpus).
        st = [{"name": "F.Cu", "type": "copper"}, {"type": "core", "thickness": 1.5},
              {"name": "B.Cu", "type": "copper"}, {"name": "F.Cu", "type": "copper"},
              {"type": "core", "thickness": 1.5}, {"name": "B.Cu", "type": "copper"}]
        self.assertEqual(_build_reference_layer_map(st, {"B.Cu"}),
                         {"F.Cu": "B.Cu", "B.Cu": "F.Cu"})


if __name__ == "__main__":
    unittest.main()
