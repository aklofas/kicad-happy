# tools/tests/test_pcb_rule_severities.py
"""Checks the project sets to `ignore` in .kicad_pro rule_severities are not reported, as
KiCad's DRC never runs them; any other severity keeps the check, and a KiCad 5 board (legacy
setup tokens) keeps KiCad's default severities because KiCad does not load the project's board
settings for it."""
import json, os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.pipeline import analyze_pcb  # noqa: E402
from kicad_core.project import ignored_drc_checks  # noqa: E402
from pcb.dfm import analyze_design_rule_compliance  # noqa: E402

CRTYD = ('(fp_line (start -2 -2) (end 2 -2) (layer "F.CrtYd") (width 0.05))\n'
         '(fp_line (start 2 -2) (end 2 2) (layer "F.CrtYd") (width 0.05))\n'
         '(fp_line (start 2 2) (end -2 2) (layer "F.CrtYd") (width 0.05))\n'
         '(fp_line (start -2 2) (end -2 -2) (layer "F.CrtYd") (width 0.05))')


def _fp(ref, x, y):
    return (f'  (footprint "L:F" (layer "F.Cu") (at {x} {y})\n'
            f'    (property "Reference" "{ref}") (property "Value" "v")\n'
            f'    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
            f'    {CRTYD})\n')


# U1/U2 courtyards overlap by 2 x 4 = 8 mm²; R1 sits in a footprints-not_allowed rule area;
# the 0.1 mm track is below KiCad's 0.2 mm default minimum track width.
BOARD = """(kicad_pcb (version 20221018) (generator pcbnew)
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
  (setup {setup})
  (net 0 "") (net 1 "A")
  (segment (start 150 150) (end 155 150) (width 0.1) (layer "F.Cu") (net 1))
{fps}  (zone (net 0) (net_name "") (layers "F.Cu" "B.Cu") (name "ko") (hatch edge 0.5)
    (keepout (tracks allowed) (vias allowed) (pads allowed) (copperpour allowed) (footprints not_allowed))
    (polygon (pts (xy 120 120) (xy 130 120) (xy 130 130) (xy 120 130))))
)
"""
FPS = _fp("U1", 100, 100) + _fp("U2", 102, 100) + _fp("R1", 125, 125)


def _run(severities, setup="(pad_to_mask_clearance 0)"):
    pro = {"board": {"design_settings": {"rule_severities": severities}}}
    with tempfile.TemporaryDirectory() as tmp:
        board = os.path.join(tmp, "b.kicad_pcb")
        with open(board, "w", encoding="utf-8") as f:
            f.write(BOARD.format(setup=setup, fps=FPS))
        with open(os.path.join(tmp, "b.kicad_pro"), "w", encoding="utf-8") as f:
            json.dump(pro, f)
        return analyze_pcb(board)


def _rules(result):
    return sorted(f["rule_id"] for f in result["findings"] if f["rule_id"] in ("PM-001", "KO-001"))


def _compliance_rules(result):
    return [v["rule"] for v in result["design_rule_compliance"].get("violations", [])]


class TestRuleSeverities(unittest.TestCase):
    def test_baseline_reports_all(self):
        r = _run({})
        self.assertEqual(_rules(r), ["KO-001", "PM-001"])
        self.assertEqual(_compliance_rules(r), ["min_track_width"])

    def test_courtyards_overlap_ignored(self):
        self.assertEqual(_rules(_run({"courtyards_overlap": "ignore"})), ["KO-001"])

    def test_items_not_allowed_ignored(self):
        self.assertEqual(_rules(_run({"items_not_allowed": "ignore"})), ["PM-001"])

    def test_track_width_ignored(self):
        r = _run({"track_width": "ignore"})
        self.assertEqual(_compliance_rules(r), [])
        self.assertNotIn("_ignored_drc_checks", r.get("project_settings", {}))

    def test_warning_or_unknown_key_keeps_checks(self):
        r = _run({"courtyards_overlap": "warning", "items_not_allowed": "error",
                  "track_width": "Ignore", "silk_overlap": "ignore"})
        self.assertEqual(_rules(r), ["KO-001", "PM-001"])
        self.assertEqual(_compliance_rules(r), ["min_track_width"])

    def test_legacy_board_keeps_default_severities(self):
        # KiCad keeps a board's own (setup ...) design settings and never loads the project's
        # (board.cpp SetProject, m_LegacyDesignSettingsLoaded), so the overlap is still reported.
        r = _run({"courtyards_overlap": "ignore", "track_width": "ignore"},
                 setup="(trace_min 0.2)")
        self.assertEqual(_rules(r), ["KO-001", "PM-001"])
        self.assertEqual(_compliance_rules(r), ["min_track_width"])


class TestHoleChecks(unittest.TestCase):
    # drc_test_provider_hole_size.cpp: a micro via's hole reports microvia_drill_out_of_range,
    # a through via's or pad's drill_out_of_range.
    VIAS = {"vias": [{"type": "micro", "size": 0.3, "drill": 0.08},
                     {"size": 0.6, "drill": 0.2}]}
    MINIMA = {"min_via_drill": (0.3, "project"), "min_microvia_drill": (0.1, "project")}

    def _rules(self, ignored):
        r = analyze_design_rule_compliance({}, self.VIAS, {}, minima=self.MINIMA,
                                           ignored_checks=frozenset(ignored))
        return sorted(v["rule"] for v in r.get("violations", []))

    def test_drill_out_of_range_keeps_micro_vias(self):
        self.assertEqual(self._rules(()), ["min_microvia_drill", "min_via_drill"])
        self.assertEqual(self._rules({"drill_out_of_range"}), ["min_microvia_drill"])
        self.assertEqual(self._rules({"microvia_drill_out_of_range"}), ["min_via_drill"])


class TestIgnoredDrcChecks(unittest.TestCase):
    def test_only_ignore_values(self):
        pro = {"board": {"design_settings": {"rule_severities": {
            "drill_out_of_range": "ignore", "annular_width": "warning", "via_diameter": "error"}}}}
        self.assertEqual(ignored_drc_checks(pro), frozenset({"drill_out_of_range"}))

    def test_missing_or_malformed(self):
        self.assertEqual(ignored_drc_checks(None), frozenset())
        self.assertEqual(ignored_drc_checks({"board": {"design_settings": {
            "rule_severities": ["ignore"]}}}), frozenset())


if __name__ == "__main__":
    unittest.main()
