# tools/tests/test_pcb_dfm.py
"""Pins analyze_dfm behaviour across its module-level tables, _measure_* scans and _emit_* builders."""
import copy, json, os, sys, unittest
from pathlib import Path
from tools.tests._fixtures import fixture_path, have
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.dfm import _min_drill_with_source, _is_real_drill, analyze_dfm  # noqa: E402
from pcb.pipeline import read_board  # noqa: E402

FX = fixture_path()
SIMPLE = FX / "simple-project" / "simple.kicad_pcb"
PAD_DRILL_MIN = FX / "kh412" / "pad_drill_min.kicad_pcb"


def _dfm(path):
    board = read_board(str(path))
    return board, analyze_dfm(board.footprints, board.tracks, board.vias, board.outline,
                              None, net_classes={}, design_intent=None)


@unittest.skipUnless((have(SIMPLE) and have(PAD_DRILL_MIN)),
                     "harness fixtures absent")
class TestPcbDfm(unittest.TestCase):
    def test_metrics_key_order_and_tables_are_module_level(self):
        _, r = _dfm(SIMPLE)
        self.assertEqual(list(r["metrics"]), ["min_track_width_mm", "approx_min_spacing_mm", "min_drill_mm",
                                              "min_annular_ring_mm", "board_width_mm", "board_height_mm"])
        from pcb.dfm import JLCPCB_LIMITS_STANDARD, JLCPCB_LIMITS_ADVANCED, IPC_CLASS_LIMITS
        self.assertEqual(JLCPCB_LIMITS_STANDARD["min_drill"], 0.2)
        self.assertEqual(JLCPCB_LIMITS_ADVANCED["min_track_width"], 0.1)
        self.assertIn(3, IPC_CLASS_LIMITS)

    def test_tables_not_mutated_and_result_idempotent(self):
        from pcb.dfm import JLCPCB_LIMITS_STANDARD, JLCPCB_LIMITS_ADVANCED, IPC_CLASS_LIMITS
        before = (copy.deepcopy(JLCPCB_LIMITS_STANDARD), copy.deepcopy(JLCPCB_LIMITS_ADVANCED),
                  copy.deepcopy(IPC_CLASS_LIMITS))
        _, r1 = _dfm(PAD_DRILL_MIN)
        _, r2 = _dfm(PAD_DRILL_MIN)
        self.assertEqual(json.dumps(r1, sort_keys=True), json.dumps(r2, sort_keys=True))
        self.assertEqual(before, (JLCPCB_LIMITS_STANDARD, JLCPCB_LIMITS_ADVANCED, IPC_CLASS_LIMITS))

    def test_pad_drill_attribution_names_first_pad(self):
        board, r = _dfm(PAD_DRILL_MIN)
        via_drills = [v["drill"] for v in board.vias.get("vias", []) if _is_real_drill(v.get("drill", 0))]
        min_drill, source = _min_drill_with_source(via_drills, board.footprints)
        self.assertTrue(source.startswith("pad "))
        drill = [v for v in r.get("violations", []) if v["parameter"] in ("via_drill", "pad_drill")]
        self.assertEqual(len(drill), 1)
        self.assertEqual(drill[0]["parameter"], "pad_drill")
        self.assertEqual(drill[0]["actual_mm"], min_drill)
        self.assertIn(f" on {source[4:]} ", drill[0]["message"])


class TestPcbDfmSynthetic(unittest.TestCase):
    def test_violations_keep_emit_order_across_kinds(self):
        def seg(net, x):
            return {"layer": "F.Cu", "net": net, "net_name": f"N{net}", "x1": x, "y1": 0.0, "x2": x, "y2": 5.0,
                    "width": 0.1}
        tracks = {"segments": [seg(1, 0.0), seg(2, 0.18)], "arcs": []}
        vias = {"vias": [{"drill": 0.15, "size": 0.35, "x": 9.0, "y": 9.0}]}
        r = analyze_dfm([], tracks, vias, {}, None, net_classes={}, design_intent=None)
        self.assertEqual([(v["parameter"], v["actual_mm"]) for v in r["violations"]],
                         [("track_width", 0.1), ("track_spacing", 0.08), ("via_drill", 0.15),
                          ("annular_ring", 0.1)])
        self.assertEqual(r["violation_count"], 4)


IPC_BOARD = """(kicad_pcb (version 20221018) (generator pcbnew)
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
  (setup (pad_to_mask_clearance 0))
  (net 0 "") (net 1 "A")
  (via (at 10 10) (size 0.42) (drill 0.2) (layers "F.Cu" "B.Cu") (net 1))
  (gr_line (start 0 0) (end 20 0) (stroke (width 0.1) (type solid)) (layer "Edge.Cuts"))
  (gr_line (start 20 0) (end 20 20) (stroke (width 0.1) (type solid)) (layer "Edge.Cuts"))
  (gr_line (start 20 20) (end 0 20) (stroke (width 0.1) (type solid)) (layer "Edge.Cuts"))
  (gr_line (start 0 20) (end 0 0) (stroke (width 0.1) (type solid)) (layer "Edge.Cuts"))
  {extra})
"""


def _ipc_dfm(config=None, extra=""):
    """(dfm_summary.ipc_class_compliance, DFM-002 summaries) of a board whose via annular
    ring is 0.11 mm."""
    import tempfile
    from pcb.pipeline import analyze_pcb
    with tempfile.TemporaryDirectory() as tmp:
        board = os.path.join(tmp, "b.kicad_pcb")
        with open(board, "w", encoding="utf-8") as f:
            f.write(IPC_BOARD.format(extra=extra))
        result = analyze_pcb(board, config=config)
    return (result["dfm_summary"].get("ipc_class_compliance"),
            [f["summary"] for f in result["findings"] if f["rule_id"] == "DFM-002"])


class TestDfmDesignIntent(unittest.TestCase):
    """DFM judges annular rings against the IPC class the design intent resolves."""

    def test_config_class_3_reaches_the_dfm(self):
        comp, summaries = _ipc_dfm({"design_intent": {"ipc_class": 3}})
        self.assertEqual(comp, {"detected_class": 3, "detection_source": "config"})
        self.assertTrue(any("IPC Class 3 minimum 0.15mm" in s for s in summaries))

    def test_config_class_1_accepts_a_ring_class_2_rejects(self):
        comp, summaries = _ipc_dfm({"design_intent": {"ipc_class": 1}})
        self.assertEqual(comp, {"detected_class": 1, "detection_source": "config"})
        self.assertEqual(summaries, [])

    def test_fab_note_names_the_class(self):
        note = ('(gr_text "Fabricate to IPC Class 3" (at 5 5) (layer "F.Fab")'
                ' (effects (font (size 1 1))))')
        comp, _ = _ipc_dfm(extra=note)
        self.assertEqual(comp, {"detected_class": 3, "detection_source": "pcb_fab_notes"})

    def test_auto_keeps_class_2_and_the_default_source(self):
        comp, summaries = _ipc_dfm()
        self.assertEqual(comp, {"detected_class": 2, "detection_source": "default"})
        self.assertTrue(any("IPC Class 2 minimum 0.125mm" in s for s in summaries))


if __name__ == "__main__":
    unittest.main()
