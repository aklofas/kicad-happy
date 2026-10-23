# tools/tests/test_pcb_dfm.py
"""Pins analyze_dfm behaviour across its module-level tables, _measure_* scans and _emit_* builders."""
import copy, json, sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.dfm import _min_drill_with_source, _is_real_drill, analyze_dfm  # noqa: E402
from pcb.pipeline import read_board  # noqa: E402

FX = Path("/tmp/harness-pin/tests/fixtures")
SIMPLE = FX / "simple-project" / "simple.kicad_pcb"
PAD_DRILL_MIN = FX / "kh412" / "pad_drill_min.kicad_pcb"


def _dfm(path):
    board = read_board(str(path))
    return board, analyze_dfm(board.footprints, board.tracks, board.vias, board.outline,
                              None, net_classes={}, design_intent=None)


@unittest.skipUnless(SIMPLE.exists() and PAD_DRILL_MIN.exists(), "harness fixtures absent")
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


if __name__ == "__main__":
    unittest.main()
