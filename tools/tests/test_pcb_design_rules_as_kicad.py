"""Design rules as KiCad reads them. Each .kicad_dru case was run through kicad-cli 10.0.8
`pcb drc` on the same board (a sentinel rule w, track_width min 0.5 mm, on a 0.2 mm track):
- a rule with two `layer` items is refused ("'layer' keyword already present."), so no custom
  rule of the file applies;
- the deprecated constraint names `hole`, `mechanical_clearance` and
  `mechanical_hole_clearance` are read as `hole_size`, `physical_clearance` and
  `physical_hole_clearance`;
- a bound written with a decimal comma (`0,5mm`) is a length;
- a rule naming a layer by its other KiCad name (`F.Silkscreen` on a board whose file says
  `F.SilkS`) applies, with or without a user name.
A KiCad 5 board keeps its own design settings and net classes: with a .kicad_pro beside it the
project's classes and rules are not reported as the rules in use (kicad-cli reports no
clearance violation for a 0.3 mm gap when the board's class says 0.2 mm and the project's
0.5 mm)."""
import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.pipeline import analyze_pcb  # noqa: E402

BOARD = """(kicad_pcb (version 20221018) (generator pcbnew)
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (1 "In1.Cu" signal) (2 "In2.Cu" signal) (31 "B.Cu" signal)
    (37 "F.SilkS" user "F.Silkscreen") (44 "Edge.Cuts" user))
  (setup (pad_to_mask_clearance 0))
  (net 0 "") (net 1 "A")
  (segment (start 0 0) (end 5 0) (width 0.2) (layer "F.Cu") (net 1))
  (via (at 1 1) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1))
)
"""
W = '(version 1)\n(rule w (constraint track_width (min 0.5mm)))\n'


def _run(board, files):
    with tempfile.TemporaryDirectory() as d:
        Path(d, "b.kicad_pcb").write_text(board, encoding="utf-8")
        for name, text in files.items():
            Path(d, name).write_text(text, encoding="utf-8")
        cwd = os.getcwd()
        os.chdir(d)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                return analyze_pcb(str(Path(d, "b.kicad_pcb")))
        finally:
            os.chdir(cwd)


def dru(rules, board=BOARD):
    """(custom_rules_error, rule names with a violation, constraint types loaded)."""
    res = _run(board, {"b.kicad_dru": rules})
    ps = res.get("project_settings") or {}
    drc = res.get("design_rule_compliance") or {}
    hit = sorted({v.get("rule") for v in drc.get("violations", [])})
    types = [c.get("type") for r in ps.get("custom_rules") or [] for c in r.get("constraints", [])]
    return ps.get("custom_rules_error"), hit, types


class DruAsKiCadReadsIt(unittest.TestCase):
    def test_two_layer_items_refuse_the_file(self):
        for layers in ('(layer outer) (layer inner)', '(layer F.Cu) (layer F.Cu)',
                       '(layer "F.Silkscreen") (layer "B.Silkscreen")'):
            with self.subTest(layers=layers):
                err, hit, _ = dru(W + f'(rule z {layers} (constraint clearance (min 0.01mm)))')
                self.assertEqual(err, "'layer' keyword already present.")
                self.assertEqual(hit, [])

    def test_one_layer_item_loads(self):
        err, hit, _ = dru(W + '(rule z (layer outer) (constraint clearance (min 0.01mm)))')
        self.assertIsNone(err)
        self.assertEqual(hit, ["custom:w"])

    def test_deprecated_constraint_names_read_as_current_names(self):
        self.assertEqual(dru(W + '(rule h (constraint hole (min 0.5mm)))')[1],
                         ["custom:h", "custom:w"])
        self.assertEqual(dru(W + '(rule m (constraint mechanical_clearance (min 0.01mm)))')[2],
                         ["track_width", "physical_clearance"])
        self.assertEqual(dru(W + '(rule m (constraint mechanical_hole_clearance (min 0.01mm)))')[2],
                         ["track_width", "physical_hole_clearance"])

    def test_decimal_comma_bound_is_a_length(self):
        err, hit, _ = dru('(version 1)\n(rule w (constraint track_width (min 0,5mm)))\n')
        self.assertIsNone(err)
        self.assertEqual(hit, ["custom:w"])

    def test_silkscreen_rule_applies_by_either_layer_name(self):
        hole = '(rule h (layer {}) (constraint hole_size (min 0.5mm)))'
        no_alias = BOARD.replace(' user "F.Silkscreen")', ' user)')
        for layer, board in (("F.Silkscreen", BOARD), ("F.SilkS", BOARD),
                             ("F.Silkscreen", no_alias)):
            with self.subTest(layer=layer, alias=board is BOARD):
                self.assertEqual(dru(W + hole.format(layer), board)[1], ["custom:h", "custom:w"])

    def test_rule_on_a_layer_the_board_lacks_does_not_apply(self):
        self.assertEqual(dru(W + '(rule h (layer F.Mask) (constraint hole_size (min 0.5mm)))')[1],
                         ["custom:w"])


LEGACY = """(kicad_pcb (version 20171130) (host pcbnew 5.1.9)
  (general (thickness 1.6))
  (layers (0 F.Cu signal) (31 B.Cu signal) (44 Edge.Cuts user))
  (setup (trace_clearance 0.2) (trace_min 0.2) (via_min_size 0.4) (via_min_drill 0.3)
    (pad_to_mask_clearance 0))
  (net 0 "") (net 1 A) (net 2 B)
  (net_class Default "This is the default net class." (clearance 0.2) (trace_width 0.25)
    (via_dia 0.8) (via_drill 0.4) (uvia_dia 0.3) (uvia_drill 0.1) (add_net A) (add_net B))
  (segment (start 0 0) (end 10 0) (width 0.25) (layer F.Cu) (net 1))
  (segment (start 0 0.65) (end 10 0.65) (width 0.25) (layer F.Cu) (net 2))
)
"""
PRO = json.dumps({
    "board": {"design_settings": {"rules": {"min_clearance": 0.0, "min_track_width": 0.0}}},
    "meta": {"filename": "b.kicad_pro", "version": 1},
    "net_settings": {"classes": [{"name": "Default", "clearance": 0.5, "track_width": 0.25,
                                  "via_diameter": 0.8, "via_drill": 0.4,
                                  "microvia_diameter": 0.3, "microvia_drill": 0.1}],
                     "meta": {"version": 3}}})


class KiCad5BoardRules(unittest.TestCase):
    def test_project_rules_are_not_reported_on_a_kicad5_board(self):
        res = _run(LEGACY, {"b.kicad_pro": PRO})
        ps = res.get("project_settings") or {}
        self.assertEqual(ps.get("source"), "b.kicad_pro")
        self.assertNotIn("net_classes", ps)
        self.assertNotIn("design_rules", ps)
        self.assertNotIn("rules_source", res["design_rule_compliance"])
        self.assertNotIn("_board_rules", ps)
        # the top-level net_classes stay as today
        self.assertIn("net_classes", res)


if __name__ == "__main__":
    unittest.main()
