# tools/tests/test_pcb_routing_complete.py
"""routing_complete with --full comes from the copper graph: a net is unrouted when more than
one copper island holds its pads, and a track end inside a same-net fill joins that fill.
Without --full it means every multi-pad net has copper, and one diagnostics record says so.
Expected values are kicad-cli 10 DRC unconnected_items on the same boards (n islands holding
a net's pads = n - 1 items)."""
import contextlib, io, os, sys, tempfile, unittest
from unittest import mock
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.pipeline import analyze_pcb  # noqa: E402

NOTE = "routing_complete means every multi-pad net has copper; completeness not proven without --full"
LAYERS = ('(layers (0 "F.Cu" signal) (31 "B.Cu" signal) (38 "B.Mask" user) (39 "F.Mask" user)'
          ' (44 "Edge.Cuts" user))\n')


def _fp(ref, x, pads=('1',), step=2, extra=''):
    body = "".join(f' (pad "{n}" smd rect (at {i * step} 0) (size 1 1) (layers "F.Cu" "F.Mask")'
                   f' (net 1 "N"))\n' for i, n in enumerate(pads))
    return (f'(footprint "t:X" (layer "F.Cu") (at {x} 10)\n'
            f' (property "Reference" "{ref}" (at 0 -3 0) (layer "F.SilkS"))\n'
            f' (attr smd){extra}\n{body})\n')


def _board(fps, body=""):
    return ('(kicad_pcb (version 20240108) (generator "pcbnew")\n(general (thickness 1.6))\n'
            + LAYERS + '(net 0 "")\n(net 1 "N")\n'
            '(gr_rect (start 0 0) (end 30 20) (stroke (width 0.05) (type default)) (fill none)'
            ' (layer "Edge.Cuts"))\n' + "".join(fps) + body + ')\n')


def _seg(x1, x2, layer="F.Cu"):
    return f'(segment (start {x1} 10) (end {x2} 10) (width 0.25) (layer "{layer}") (net 1))\n'


def _zone(layer, outline, fill):
    def pts(x0, x1):
        return f'(pts (xy {x0} 9) (xy {x1} 9) (xy {x1} 11) (xy {x0} 11))'
    filled = f' (filled_polygon (layer "{layer}") {pts(*fill)})' if fill else ''
    return (f'(zone (net 1) (net_name "N") (layer "{layer}") (hatch edge 0.5)'
            ' (connect_pads yes (clearance 0.2)) (min_thickness 0.25)'
            ' (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))'
            f' (polygon {pts(*outline)}){filled})\n')


TWO = [_fp("U1", 10), _fp("U2", 14)]
# Each pad's track ends inside one N fill between the pads; the fill touches neither pad.
FILL = _zone("F.Cu", (11.5, 12.5), (11.5, 12.5))
INTO_FILL = _seg(10, 11.8) + _seg(14, 12.2)


def _analyze(text, full):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "b.kicad_pcb"
        p.write_text(text, encoding="utf-8")
        cwd = os.getcwd()
        os.chdir(d)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                return analyze_pcb(str(p), include_trace_segments=full)
        finally:
            os.chdir(cwd)


def _rt001(res):
    return [f["summary"] for f in res["findings"] if f.get("rule_id") == "RT-001"]


def _notes(res):
    return [d for d in res["diagnostics"] if d["effect"] == NOTE]


class TestRoutingFromGraph(unittest.TestCase):
    STUB = _board([_fp("U1", 10), _fp("U2", 14), _fp("U3", 18)], _seg(10, 11))

    def test_stub_default_is_complete_with_note(self):
        res = _analyze(self.STUB, full=False)
        self.assertTrue(res["connectivity"]["routing_complete"])
        self.assertTrue(res["statistics"]["routing_complete"])
        self.assertEqual(_rt001(res), [])
        self.assertEqual(len(_notes(res)), 1)
        self.assertEqual(_notes(res)[0]["source"], "pcb.presentation.assemble_result")

    def test_stub_full_three_islands(self):
        # kicad-cli: 2 unconnected items on net N
        res = _analyze(self.STUB, full=True)
        self.assertFalse(res["connectivity"]["routing_complete"])
        self.assertEqual(res["connectivity"]["unrouted_count"], 1)
        self.assertFalse(res["statistics"]["routing_complete"])
        self.assertEqual(res["statistics"]["unrouted_net_count"], 1)
        self.assertEqual(_rt001(res),
                         ["Incompletely routed net N (3 copper islands hold its 3 pads)"])
        self.assertEqual(_notes(res), [])

    def test_track_ends_in_same_net_fill_join(self):
        # kicad-cli: 0 unconnected
        res = _analyze(_board(TWO, FILL + INTO_FILL), full=True)
        self.assertTrue(res["connectivity"]["routing_complete"])
        self.assertEqual(res["connectivity_graph"]["N"]["islands"], 1)
        self.assertEqual(_rt001(res), [])

    def test_fill_on_other_layer_joins_nothing(self):
        # The track ends lie over an N fill on B.Cu only. kicad-cli: 1 unconnected.
        res = _analyze(_board(TWO, _zone("B.Cu", (11.5, 12.5), (11.5, 12.5)) + INTO_FILL),
                       full=True)
        self.assertFalse(res["connectivity"]["routing_complete"])
        self.assertEqual(_rt001(res),
                         ["Incompletely routed net N (2 copper islands hold its 2 pads)"])

    def test_zone_outline_without_fill_there_joins_nothing(self):
        # The zone outline covers both track ends but its fill (an island KiCad kept) only one.
        # kicad-cli: 1 unconnected.
        res = _analyze(_board(TWO, _zone("F.Cu", (11.5, 12.5), (11.5, 11.9)) + INTO_FILL),
                       full=True)
        self.assertFalse(res["connectivity"]["routing_complete"])

    # KiCad joins pads that share a number only through copper or the footprint's jumper
    # settings (connectivity_algo.cpp updateJumperPads).
    def test_duplicate_pad_numbers_apart_stay_apart(self):
        # Two pads numbered "1" on one footprint, 2 mm apart, no copper. kicad-cli: 1 unconnected.
        text = _board([_fp("U1", 10, pads=("1", "1"))])
        for full in (True, False):
            res = _analyze(text, full=full)
            self.assertFalse(res["connectivity"]["routing_complete"])
            self.assertEqual(_rt001(res), ["Unrouted net N (2 pads)"])

    def test_two_footprints_with_one_reference_stay_apart(self):
        # Two footprints both H1, pad 1 on N, no copper. kicad-cli: 1 unconnected.
        res = _analyze(_board([_fp("H1", 10), _fp("H1", 14)]), full=True)
        self.assertFalse(res["connectivity"]["routing_complete"])
        self.assertEqual(_rt001(res), ["Unrouted net N (2 pads)"])

    def test_overlapping_duplicate_pads_join(self):
        # Pads "1","1" overlapping by 0.5 mm, plus U2. kicad-cli: 1 unconnected (U1 to U2).
        res = _analyze(_board([_fp("U1", 10, pads=("1", "1"), step=0.5), _fp("U2", 14)]),
                       full=True)
        self.assertEqual(res["connectivity_graph"]["N"]["islands"], 2)

    def test_overlapping_pads_of_two_footprints_join(self):
        # kicad-cli: 0 unconnected.
        res = _analyze(_board([_fp("U1", 10), _fp("U2", 10.8)]), full=True)
        self.assertTrue(res["connectivity"]["routing_complete"])

    def test_duplicate_pad_numbers_are_jumpers_join(self):
        # kicad-cli: 0 unconnected; the default test still sees no copper.
        text = _board([_fp("U1", 10, pads=("1", "1"),
                           extra=" (duplicate_pad_numbers_are_jumpers yes)")])
        self.assertTrue(_analyze(text, full=True)["connectivity"]["routing_complete"])
        self.assertEqual(_rt001(_analyze(text, full=False)), ["Unrouted net N (2 pads)"])

    def test_jumper_pad_groups_join(self):
        # kicad-cli: 0 unconnected.
        text = _board([_fp("U1", 10, pads=("1", "2"), extra=' (jumper_pad_groups ("1" "2"))')])
        self.assertTrue(_analyze(text, full=True)["connectivity"]["routing_complete"])

    def test_no_copper_net_keeps_its_text(self):
        res = _analyze(_board(TWO), full=True)
        self.assertEqual(_rt001(res), ["Unrouted net N (2 pads)"])

    def test_graph_error_records_itself_and_no_routing_note(self):
        # A failed graph build is its own diagnostic; the default-path note would be wrong there
        with mock.patch("pcb.presentation.build_connectivity_graph",
                        side_effect=RuntimeError("boom")):
            res = _analyze(_board(TWO, _seg(10, 14)), full=True)
        self.assertEqual(res["connectivity_graph_error"],
                         "connectivity graph unavailable: RuntimeError: boom")
        self.assertEqual([(d["source"], d["effect"]) for d in res["diagnostics"]
                          if d["effect"] == "connectivity_graph omitted"],
                         [("pcb.presentation.assemble_result", "connectivity_graph omitted")])
        self.assertTrue(res["connectivity"]["routing_complete"])
        self.assertEqual(_notes(res), [])

    def test_returns_a_new_dict(self):
        from pcb.presentation import _routing_from_graph
        conn = {"total_nets_with_pads": 1, "routed_nets": 1, "unrouted_count": 0,
                "routing_complete": True, "unrouted": []}
        graph = {"N": {"islands": 2, "components": {"U1:1": 0, "U2:1": 1, "via_0": 1},
                       "gaps": [], "disconnected_pads": [["U1:1", "U2:1"]]}}
        out = _routing_from_graph(conn, graph)
        self.assertIsNot(out, conn)
        self.assertTrue(conn["routing_complete"])
        self.assertEqual(out["unrouted_count"], 1)
        self.assertEqual(out["unrouted"][0]["pads"], ["U1.1", "U2.1"])
        self.assertEqual(out["routed_nets"], 0)


if __name__ == "__main__":
    unittest.main()
