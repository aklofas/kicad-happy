# tools/tests/test_pcb_return_path_reference.py
"""Return-path coverage counts only ground or power-rail zone copper on the reference layer.

The return current of a microstrip flows in the nearest plane; a power plane serves when it
is decoupled to ground (Ott, EMC Engineering ch. 16; Bogatin ch. 8). So a sample is covered
only by a ground or power zone fill; a fill of another signal net, a track or a pad is not a
reference plane. The reference layer is the nearest other copper layer (by dielectric
thickness) that carries ground or power zone copper; a layer without such copper is never the
reference. A via's own antipad in the plane stays covered.

Each case routes one F.Cu track of net SIG from x=2 to x=18 at y=10: 16 mm sampled every
2 mm = 9 points. Coverage = covered points / 9 (the analyzer reports nets below 95 %).

The same samples record the plane net under the track. Where it changes from one plane net to
another (a split between, say, +3V3 and +5V planes) the return current has to cross the split,
so the analyzer lists the change in reference_plane_changes and EMC GP-001 reports it for a
high-speed or clock net."""
import os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
EMC = Path(__file__).resolve().parents[2] / "skills" / "emc" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(EMC))

from pcb.pipeline import analyze_pcb  # noqa: E402
from pcb.routing import _build_reference_layer_map  # noqa: E402
from emc_rules import check_return_path_coverage  # noqa: E402

CU2 = '(0 "F.Cu" signal) (31 "B.Cu" signal)'
CU4 = '(0 "F.Cu" signal) (1 "In1.Cu" signal) (2 "In2.Cu" signal) (31 "B.Cu" signal)'
NETS = ["SIG", "GND", "SIG2", "+3V3", "MCU3v3", "+5V"]
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


def board(body, cu=CU2, track=SIG_TRACK):
    nets = '(net 0 "")\n' + "".join(f'(net {i + 1} "{n}")\n' for i, n in enumerate(NETS))
    return ('(kicad_pcb (version 20240108) (generator "pcbnew")\n(general (thickness 1.6))\n'
            f'(layers {cu} (38 "B.Mask" user) (39 "F.Mask" user) (44 "Edge.Cuts" user))\n'
            '(setup (pad_to_mask_clearance 0))\n' + nets
            + '(gr_rect (start 0 0) (end 50 50) (stroke (width 0.05) (type default)) (fill none)'
            ' (layer "Edge.Cuts"))\n' + track + body + ')\n')


def analyze(text):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "b.kicad_pcb"
        p.write_text(text, encoding="utf-8")
        cwd = os.getcwd()
        os.chdir(d)
        try:
            return analyze_pcb(str(p), include_trace_segments=True)
        finally:
            os.chdir(cwd)


def coverage(text):
    """SIG's reference-plane coverage in percent (100 when the analyzer reports no gap)."""
    out = analyze(text)
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


# +3V3 under x 0..9.5 and +5V under x 10.5..20 on B.Cu: a 1 mm split at x=10.
SPLIT_3V3_5V = zone("+3V3", "B.Cu", 0, 9.5) + zone("+5V", "B.Cu", 10.5, 20)


def renamed(text, name):
    return text.replace('(net 1 "SIG")', f'(net 1 "{name}")')


def cap(ref, x, y, net_a="+3V3", net_b="+5V", lib="Capacitor_SMD:C_0402"):
    """A two-pad part (a capacitor by default) joining net_a and net_b, centred at (x, y)."""
    return (f'(footprint "{lib}" (layer "F.Cu") (at {x} {y})\n'
            f' (property "Reference" "{ref}" (at 0 -1 0) (layer "F.SilkS"))\n'
            f' (property "Value" "100n" (at 0 1 0) (layer "F.Fab"))\n'
            f' (pad "1" smd rect (at -0.5 0) (size 0.5 0.5) (layers "F.Cu") (net {net_no(net_a)} "{net_a}"))\n'
            f' (pad "2" smd rect (at 0.5 0) (size 0.5 0.5) (layers "F.Cu") (net {net_no(net_b)} "{net_b}")))\n')


class ReferencePlaneChanges(unittest.TestCase):
    def test_split_between_two_plane_nets_is_one_change(self):
        out = analyze(board(SPLIT_3V3_5V))
        self.assertEqual(out["reference_plane_changes"],
                         [{"net": "SIG", "layer": "F.Cu", "reference_layer": "B.Cu",
                           "net_a": "+3V3", "net_b": "+5V", "x": 10.0, "y": 10.0,
                           "sample_points": [[8.0, 10.0], [12.0, 10.0]]}])

    def test_split_leaves_return_path_continuity_alone(self):
        self.assertEqual(analyze(board(SPLIT_3V3_5V))["return_path_continuity"], [])

    def test_same_net_plane_is_no_change(self):
        same = zone("+3V3", "B.Cu", 0, 9.5) + zone("+3V3", "B.Cu", 10.5, 20)
        self.assertEqual(analyze(board(same))["reference_plane_changes"], [])
        self.assertEqual(analyze(board(zone("GND", "B.Cu")))["reference_plane_changes"], [])

    def test_island_under_one_sample_is_no_change(self):
        # A 0.9 mm +5V island at x 9.55..10.45 under the x=10 sample only.
        island = (zone("+3V3", "B.Cu", 0, 9.5) + zone("+3V3", "B.Cu", 10.5, 20)
                  + zone("+5V", "B.Cu", 9.55, 10.45, 9.55, 10.45))
        self.assertEqual(analyze(board(island))["reference_plane_changes"], [])

    def test_split_at_a_track_corner_is_one_change(self):
        # The track turns at (10, 10), in the gap: each segment sits over one plane net.
        corner = ('(segment (start 2 10) (end 10 10) (width 0.2) (layer "F.Cu") (net 1))\n'
                  '(segment (start 10 10) (end 16 14) (width 0.2) (layer "F.Cu") (net 1))\n')
        out = analyze(board(SPLIT_3V3_5V, track=corner))
        self.assertEqual(out["reference_plane_changes"],
                         [{"net": "SIG", "layer": "F.Cu", "reference_layer": "B.Cu",
                           "net_a": "+3V3", "net_b": "+5V", "x": 10.0, "y": 10.0,
                           "sample_points": [[8.0, 10.0], [12.0, 11.33]]}])

    def test_island_under_a_short_segment_is_no_change(self):
        # A 1.4 mm +5V island at x 9.3..10.7 under a 1 mm segment between two longer ones:
        # the island holds for under 2 mm of trace, counted across the segment ends.
        island = (zone("+3V3", "B.Cu", 0, 9.1) + zone("+3V3", "B.Cu", 10.9, 20)
                  + zone("+5V", "B.Cu", 9.3, 10.7, 9.3, 10.7))
        trk = ('(segment (start 2 10) (end 9.5 10) (width 0.2) (layer "F.Cu") (net 1))\n'
               '(segment (start 9.5 10) (end 10.5 10) (width 0.2) (layer "F.Cu") (net 1))\n'
               '(segment (start 10.5 10) (end 18 10) (width 0.2) (layer "F.Cu") (net 1))\n')
        out = analyze(renamed(board(island, track=trk), "CLK"))
        self.assertEqual(out["reference_plane_changes"], [])
        self.assertEqual(split_findings(out), [])
        out = analyze(renamed(board(island), "CLK"))
        self.assertEqual(out["reference_plane_changes"], [])

    def test_plane_net_held_across_short_segments_is_a_change(self):
        # +5V under x 10.5..20 is crossed by short 1.5 mm segments only: together they
        # hold +5V over more than 2 mm of trace, so the split still counts.
        trk = ('(segment (start 2 10) (end 9 10) (width 0.2) (layer "F.Cu") (net 1))\n'
               + "".join(f'(segment (start {x} 10) (end {x + 1.5} 10) (width 0.2)'
                         f' (layer "F.Cu") (net 1))\n' for x in (9, 10.5, 12, 13.5)))
        changes = analyze(board(SPLIT_3V3_5V, track=trk))["reference_plane_changes"]
        self.assertEqual([(c["net_a"], c["net_b"]) for c in changes], [("+3V3", "+5V")])

    def test_via_antipad_sample_is_not_a_reference(self):
        # A through via at x=10 in a 1.6 mm slot: the sample there is credited as covered,
        # but its net is neither plane's. Same net on both sides: no change.
        via = '(via (at 10 10) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 2))\n'
        slot = zone("+3V3", "B.Cu", 0, 9.2) + zone("+3V3", "B.Cu", 10.8, 20)
        self.assertEqual(analyze(board(slot + via))["reference_plane_changes"], [])
        split = zone("+3V3", "B.Cu", 0, 9.2) + zone("+5V", "B.Cu", 10.8, 20)
        changes = analyze(board(split + via))["reference_plane_changes"]
        self.assertEqual([(c["net_a"], c["net_b"], c["x"]) for c in changes],
                         [("+3V3", "+5V", 10.0)])


def split_findings(out):
    return [f for f in check_return_path_coverage(out)
            if f["summary"] == "Signal crosses a split between reference planes"]


class SplitCrossingFinding(unittest.TestCase):
    def test_clock_net_over_a_split_is_one_high_finding(self):
        found = split_findings(analyze(renamed(board(SPLIT_3V3_5V), "CLK")))
        self.assertEqual(len(found), 1)
        f = found[0]
        self.assertEqual((f["rule_id"], f["detector"], f["severity"], f["nets"]),
                         ("GP-001", "emc_ground_plane", "error", ["CLK"]))  # HIGH
        self.assertIn("+3V3 / +5V", f["description"])

    def test_plain_signal_over_a_split_is_no_finding(self):
        self.assertEqual(split_findings(analyze(board(SPLIT_3V3_5V))), [])

    def test_sheet_name_is_not_the_net_name(self):
        out = analyze(renamed(board(SPLIT_3V3_5V), "/Sheet (Ethernet)/LED"))
        self.assertEqual(len(out["reference_plane_changes"]), 1)
        self.assertEqual(split_findings(out), [])

    def test_touch_net_is_no_finding(self):
        out = analyze(renamed(board(SPLIT_3V3_5V), "CLK"))
        out.setdefault("findings", []).append(
            {"rule_id": "CP-003", "nets": ["CLK"], "components": ["TP1"]})
        self.assertEqual(split_findings(out), [])

    def test_bridging_capacitor_within_5_mm_is_no_finding(self):
        out = analyze(renamed(board(SPLIT_3V3_5V + cap("C1", 10, 13)), "CLK"))
        self.assertEqual(split_findings(out), [])

    def test_bridging_capacitor_farther_than_5_mm_still_reports(self):
        out = analyze(renamed(board(SPLIT_3V3_5V + cap("C1", 10, 30)), "CLK"))
        self.assertEqual(len(split_findings(out)), 1)

    def test_unfitted_bridging_capacitor_does_not_bridge(self):
        fitted = cap("C1", 10, 13)
        dnp = fitted.replace("(at 10 13)\n", "(at 10 13)\n (attr smd dnp)\n", 1)
        self.assertNotEqual(fitted, dnp)
        out = analyze(renamed(board(SPLIT_3V3_5V + dnp), "CLK"))
        self.assertEqual(len(split_findings(out)), 1)

    def test_vc_reference_capacitor_bridges(self):
        out = analyze(renamed(board(SPLIT_3V3_5V + cap("VC1", 10, 13, lib="Custom:Part")), "CLK"))
        self.assertEqual(split_findings(out), [])

    def test_capacitor_library_part_bridges(self):
        out = analyze(renamed(board(SPLIT_3V3_5V + cap("X1", 10, 13, lib="Capacitor_SMD:C_0603")),
                              "CLK"))
        self.assertEqual(split_findings(out), [])

    def test_ferrite_or_inductor_on_a_capacitor_footprint_does_not_bridge(self):
        # The reference names the part; a ferrite between two rails carries no HF return.
        for ref, lib in (("FB1", "Capacitor_SMD:C_0603"),
                         ("L1", "Capacitor_Tantalum_SMD:CP_EIA-3216-18_Kemet-A"),
                         ("R1", "Capacitor_SMD:C_0402")):
            out = analyze(renamed(board(SPLIT_3V3_5V + cap(ref, 10, 13, lib=lib)), "CLK"))
            self.assertEqual(len(split_findings(out)), 1, ref)

    def test_resistor_does_not_bridge(self):
        out = analyze(renamed(board(SPLIT_3V3_5V + cap("R1", 10, 13, lib="Resistor_SMD:R_0402")),
                              "CLK"))
        self.assertEqual(len(split_findings(out)), 1)

    def test_bridging_distance_is_to_the_nearer_sample(self):
        # A 6 mm gap (x 7..13): the change midpoint is x=10, the bounding samples x=6 and
        # x=14. A cap at (6, 13.5) is 3.5 mm from the x=6 sample but 5.3 mm from the midpoint.
        wide = zone("+3V3", "B.Cu", 0, 7) + zone("+5V", "B.Cu", 13, 20)
        out = analyze(renamed(board(wide + cap("C1", 6, 13.5)), "CLK"))
        self.assertEqual(len(out["reference_plane_changes"]), 1)
        self.assertEqual(split_findings(out), [])

    def test_description_names_every_reference_layer(self):
        out = analyze(renamed(board(SPLIT_3V3_5V), "CLK"))
        out["reference_plane_changes"].append(
            {**out["reference_plane_changes"][0], "layer": "B.Cu", "reference_layer": "In1.Cu",
             "x": 40.0, "y": 40.0, "sample_points": [[39.0, 40.0], [41.0, 40.0]]})
        (f,) = split_findings(out)
        self.assertIn("2 time(s)", f["description"])
        self.assertIn("on B.Cu, In1.Cu", f["description"])

    def test_capacitor_on_other_nets_does_not_bridge(self):
        out = analyze(renamed(board(SPLIT_3V3_5V + cap("C1", 10, 13, "+3V3", "GND")), "CLK"))
        self.assertEqual(len(split_findings(out)), 1)


if __name__ == "__main__":
    unittest.main()
