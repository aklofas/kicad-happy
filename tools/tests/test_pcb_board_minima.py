# tools/tests/test_pcb_board_minima.py
"""Design-rule compliance holds the board to the minima KiCad resolves: the project's, a KiCad 5
board's own (setup ...) minima (the project's board settings then ignored), or KiCad's defaults;
micro vias are held to the net class micro-via diameter and the micro-via drill minimum."""
import json, os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.pipeline import analyze_pcb  # noqa: E402

MODERN = """(kicad_pcb (version 20221018) (generator pcbnew)
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (1 "In1.Cu" signal) (2 "In2.Cu" signal) (31 "B.Cu" signal))
  (setup (pad_to_mask_clearance 0))
  (net 0 "") (net 1 "A")
{items})
"""
LEGACY = """(kicad_pcb (version 20171130) (host pcbnew 5.1.6)
  (general (thickness 1.6))
  (layers (0 F.Cu signal) (31 B.Cu signal))
  (setup {setup})
  (net 0 "") (net 1 A)
  (net_class Default "This is the default net class." (clearance 0.2) (trace_width 0.25)
    (via_dia 0.8) (via_drill 0.4) (uvia_dia 0.3) (uvia_drill 0.1) (add_net A))
{items})
"""


def track(width):
    return f'  (segment (start 0 0) (end 5 0) (width {width}) (layer "F.Cu") (net 1))\n'


def via(size, drill, micro=False):
    kind = "micro " if micro else ""
    layers = '"F.Cu" "In1.Cu"' if micro else '"F.Cu" "B.Cu"'
    return f'  (via {kind}(at 1 1) (size {size}) (drill {drill}) (layers {layers}) (net 1))\n'


def pro(rules, default_class=None):
    return json.dumps({"board": {"design_settings": {"rules": rules}},
                       "net_settings": {"classes": [dict({"name": "Default"},
                                                         **(default_class or {}))]}})


def compliance(board_text, pro_text=None):
    with tempfile.TemporaryDirectory() as tmp:
        board = os.path.join(tmp, "b.kicad_pcb")
        with open(board, "w", encoding="utf-8") as f:
            f.write(board_text)
        if pro_text is not None:
            with open(os.path.join(tmp, "b.kicad_pro"), "w", encoding="utf-8") as f:
                f.write(pro_text)
        return analyze_pcb(board)["design_rule_compliance"]


def by_rule(result):
    return {v["rule"]: v for v in result.get("violations", [])}


class BoardMinimaTest(unittest.TestCase):
    def test_legacy_setup_minimum_without_project(self):
        # kicad-cli 10.0.7: track_width "board setup constraints min width 0.2"
        v = by_rule(compliance(LEGACY.format(setup="(trace_min 0.2)", items=track(0.1))))
        self.assertEqual(v["min_track_width"]["source"], "board_setup")
        self.assertEqual(v["min_track_width"]["required_mm"], 0.2)

    def test_modern_board_without_project_uses_kicad_default(self):
        # BOARD_DESIGN_SETTINGS default minimum track width 0.2 mm
        v = by_rule(compliance(MODERN.format(items=track(0.15))))
        self.assertEqual(v["min_track_width"]["source"], "kicad_default")
        self.assertEqual(v["min_track_width"]["required_mm"], 0.2)

    def test_legacy_board_ignores_its_project_board_settings(self):
        # board.cpp: legacy setup tokens loaded -> the project's board settings are not read
        text = LEGACY.format(setup="(trace_min 0.25)", items=track(0.2))
        v = by_rule(compliance(text, pro({"min_track_width": 0.1})))
        self.assertEqual(v["min_track_width"]["source"], "board_setup")
        self.assertEqual(v["min_track_width"]["required_mm"], 0.25)

    def test_micro_vias_held_to_netclass_microvia_diameter(self):
        # tomu-fpga: kicad-cli 10.0.7 via_diameter "min diameter 0.3000 mm; actual 0.2" (the
        # Default net class micro-via diameter); not the 0.5/0.3 through-via minima
        v = by_rule(compliance(MODERN.format(items=via(0.2, 0.1, micro=True))))
        self.assertEqual(v["min_microvia_diameter"]["required_mm"], 0.3)
        self.assertEqual(v["min_microvia_diameter"]["source"], "kicad_default")
        self.assertNotIn("min_via_diameter", v)
        self.assertNotIn("min_via_drill", v)
        self.assertNotIn("min_microvia_drill", v)

    def test_micro_via_meeting_project_netclass_is_not_flagged(self):
        # prrplsattiny20: kicad-cli 10.0.7 reports nothing for a 0.245/0.1 micro via
        text = MODERN.format(items=via(0.245, 0.1, micro=True) + track(0.25))
        result = compliance(text, pro({"min_via_diameter": 0.5, "min_microvia_diameter": 0.2,
                                       "min_microvia_drill": 0.1},
                                      {"microvia_diameter": 0.245, "microvia_drill": 0.1}))
        self.assertEqual(result.get("violations", []), [])
        self.assertTrue(result["compliant"])

    def test_project_default_class_without_microvia_size_keeps_board_minimum(self):
        # kicad-cli 10.0.7: a class read without microvia_diameter has none, so only the board
        # micro-via minimum (default 0.2) applies to a 0.25 micro via; its drill 0.05 < 0.08
        text = MODERN.format(items=via(0.25, 0.05, micro=True))
        v = by_rule(compliance(text, pro({"min_microvia_drill": 0.08})))
        self.assertNotIn("min_microvia_diameter", v)
        self.assertEqual(v["min_microvia_drill"]["source"], "project")
        self.assertEqual(v["min_microvia_drill"]["required_mm"], 0.08)

    def test_board_without_project_meeting_kicad_defaults_is_compliant(self):
        result = compliance(MODERN.format(items=track(0.2) + via(0.6, 0.3)))
        self.assertTrue(result["compliant"])
        self.assertNotIn("violations", result)
        self.assertNotIn("rules_source", result)
        self.assertEqual(result["rules_checked"], 3)

    def test_legacy_micro_via_uses_board_netclass(self):
        text = LEGACY.format(setup="(trace_min 0.2) (uvia_min_size 0.2) (uvia_min_drill 0.1)",
                             items=via(0.25, 0.1, micro=True))
        v = by_rule(compliance(text))
        self.assertEqual(v["min_microvia_diameter"]["required_mm"], 0.3)
        self.assertEqual(v["min_microvia_diameter"]["source"], "board_setup")


if __name__ == "__main__":
    unittest.main()
