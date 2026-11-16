"""Design rules as KiCad reads them. Each .kicad_dru case was run through kicad-cli 10.0.8
`pcb drc` on the same board (a sentinel rule w, track_width min 0.5 mm, on a 0.2 mm track):
- a rule with two `layer` items is refused ("'layer' keyword already present."), so no custom
  rule of the file applies;
- the deprecated constraint names `hole`, `mechanical_clearance` and
  `mechanical_hole_clearance` are read as `hole_size`, `physical_clearance` and
  `physical_hole_clearance`, so a rule giving one constraint under both names is refused
  ("Rule already has a 'hole_size' constraint.", naming the second as written);
- a bound written with a decimal comma (`0,5mm`) is a length;
- a bound KiCad cannot read refuses the file with KiCad's message: "Missing units." only when
  the expression holds one number and it has no unit (a unary minus adds a number, so `-0.1`
  and `2 * 0.1` load and `+0.1` and `(0.1)` do not), units in another case or on `via_count`,
  time units outside `length` and `skew`, bounds in different units, and a tab or line break
  between two tokens of a bound (not after the keyword or before the `)`:
  in a CRLF file `(min 0.1mm\r\n)` loads and `(min 0.1mm\r\n+ 0.1mm)` is refused);
- a unit on `track_angle` (`45deg`, `45 deg`, `(max 90deg)`) is refused by kicad-cli 10.0.8
  ("Unexpected units.") but read as an angle by KiCad master since the KiCad 11 line
  (drc_rule_parser.cpp impliedDegrees), so such a file is read, as it was before;
- a condition KiCad's expression parser rejects is refused ("Could not parse expression."): a
  missing operand or parenthesis, a character outside its lexer (tab, CR, `@`, `"`, `;`, a
  single `=`), a unit word as an operand, a chained comparison, or one number without a unit;
  an unterminated `'` string, a tab inside one, `,` arguments and `!!` load;
- a `${VAR}` left unresolved anywhere in a rule refuses the file ("Unresolved text
  variable."): KiCad resolves its own names (`${VCSHASH}` and `${VCSSHORTHASH}` too, empty
  outside a git repository; case-sensitive: `${title}` and `${projectname}` are refused), `X:Y` references, the .kicad_pro's text variables in the case they are
  defined in (`${foo}` loads when the project defines `foo`, and is refused when it defines
  `FOO`) and the board's properties, and ignores comment lines and an escaped `\${FOO}`;
- a rule naming a layer by its other KiCad name (`F.Silkscreen` on a board whose file says
  `F.SilkS`) applies, with or without a user name;
- a rule layer matches a copper layer by its canonical name or the board's name for it
  (`TopCopper`, `Top*`, `GND`, `G?D`, and `*.Cu`, `In*`, `*` on a board that renames F.Cu and
  In1.Cu), for tracks, and for vias and annular rings judged on F.Cu (a `GND` rule does not
  reach the F.Cu–B.Cu via); a board name equal to another layer's name (In1.Cu called `B.Cu`)
  matches that layer too, but not for `outer`/`inner`, which are layer sets (no track_width
  violation on In1 for an `outer` rule there).
A KiCad 5 board keeps its own design settings and net classes: with a .kicad_pro beside it the
project's classes and rules are not reported as the rules in use (kicad-cli reports no
clearance violation for a 0.3 mm gap when the board's class says 0.2 mm and the project's
0.5 mm)."""
import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.project import load_kicad_dru_checked  # noqa: E402
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
# F.Cu and In1.Cu renamed by the board, with a 0.2 mm track on each
RENAMED = (BOARD.replace('(0 "F.Cu" signal)', '(0 "F.Cu" signal "TopCopper")')
           .replace('(1 "In1.Cu" signal)', '(1 "In1.Cu" signal "GND")')
           .replace('  (via ', '  (segment (start 0 3) (end 5 3) (width 0.2) (layer "In1.Cu") (net 1))\n  (via '))


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


def dru(rules, board=BOARD, pro=None):
    """(custom_rules_error, rule names with a violation, constraint types loaded); *pro* is the
    .kicad_pro's text variables."""
    files = {"b.kicad_dru": rules}
    if pro is not None:
        files["b.kicad_pro"] = json.dumps({"text_variables": pro,
                                           "meta": {"filename": "b.kicad_pro", "version": 1}})
    res = _run(board, files)
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

    def test_old_and_new_constraint_name_in_one_rule_refuses_the_file(self):
        rule = W + '(rule d (constraint {}) (constraint {}))'
        for first, second in (("hole", "hole_size"), ("hole_size", "hole"),
                              ("mechanical_clearance", "physical_clearance"),
                              ("mechanical_hole_clearance", "physical_hole_clearance")):
            with self.subTest(first=first, second=second):
                err, hit, _ = dru(rule.format(f"{first} (min 0.1mm)", f"{second} (min 0.1mm)"))
                self.assertEqual(err, f"Rule already has a '{second}' constraint.")
                self.assertEqual(hit, [])

    def test_one_name_per_rule_loads(self):
        for rules in ('(rule d (constraint hole (min 0.1mm)) (constraint hole_clearance (min 0.1mm)))',
                      '(rule d (constraint hole (min 0.1mm)))\n'
                      '(rule e (constraint hole_size (min 0.1mm)))'):
            with self.subTest(rules=rules):
                err, hit, _ = dru(W + rules)
                self.assertIsNone(err)
                self.assertEqual(hit, ["custom:w"])

    def test_bounds_kicad_applies(self):
        for bound in (
                "clearance (min -0.1)", "clearance (min - 0.1)", "clearance (min -0)",
                "clearance (min 2 * 0.1)", "clearance (min 2*0.25)", "clearance (min 0.1 + 0.1)",
                "clearance (min -0.1) (max -0.2)",
                "solder_paste_rel_margin (opt -0.1)", "solder_paste_rel_margin (opt -10)",
                "solder_paste_rel_margin (opt -0.1mm)", "solder_paste_rel_margin (opt 2 * 0.05)",
                "solder_paste_abs_margin (opt -0.1)",
                "min_resolved_spokes 2", "min_resolved_spokes -1", "min_resolved_spokes .5",
                "track_angle (min 45)", "track_angle (min 45,5)", "track_angle (min -45)",
                "via_count (max 1,5)", "via_count (max 1 + 1)",
                "clearance (min 0,1mm)", "clearance (min 0,1 mm)", "clearance (min 0,1 + 0,1)",
                "clearance (min 2 * 0,1)", "clearance (min 0,1,2mm)", "clearance (min 1,mm)",
                "clearance (min 1,000mm)", "clearance (min -0,1)",
                "clearance (min 45deg)", "clearance (min 10deg) (max 45deg)",
                "length (min 1ps) (max 2fs)", "length (max 1ps * 2)", "length (max 1deg)",
                "skew (max 1ps)", "skew (max 1mm) (within_diff_pairs)",
                "clearance (min 0.1mm  +  0.1mm)", "clearance (min 6 mil)",
                "clearance (min 0.1mm) (opt 4mil)", "clearance (min -0.1mm) (max 0.5mm)",
                "clearance (min 0.1mm + 0.1) (max 0.5mm)",
                "clearance (min (0.1mm)) (max 1mm)", "clearance (min +0.1mm)",
                "clearance (min\t0.1mm)", "clearance (min 0.1mm\t)", "clearance\t(min 0.1mm)",
                "clearance (min 0.1mm\r\n)"):
            with self.subTest(bound=bound):
                self.assertEqual(dru(W + f'(rule a (constraint {bound}))')[:2], (None, ["custom:w"]))

    def test_bounds_kicad_refuses(self):
        for message, bounds in (
                ("Missing units.", ("clearance (min 0,1)", "clearance (min 1,5)", "clearance (min 1,)",
                                    "clearance (min 0.1)", "solder_paste_rel_margin (opt 0.1)",
                                    "solder_paste_rel_margin (opt 0)", "clearance (min +0.1)",
                                    "clearance (min (0.1))")),
                ("Syntax error", ("clearance (min 0.1MM)", "clearance (min 0.1Mm)", "clearance (min 5MIL)",
                                  "clearance (min 0.01IN)", "clearance (min .1mm)", "clearance (min 5%)",
                                  "clearance (min 1, 5mm)", "clearance (min 0.1.2mm)")),
                ("Unexpected units.", ("via_count (max 2mm)", "via_count (max 2deg)", "via_count (max 2ps)",
                                       "via_count (max 1mm + 1)")),
                ("Unrecognized item.", ("min_resolved_spokes (min 2)", "min_resolved_spokes (opt 2)",
                                        "min_resolved_spokes x", "min_resolved_spokes",
                                        "min_resolved_spokes 2mm")),
                ("Missing ')'.", ("min_resolved_spokes 2 3",)),
                ("Time based units not allowed for constraint type.",
                 ("clearance (min 1ps)", "diff_pair_gap (max 1ps)")),
                ("Mixed units for constraint values.",
                 ("clearance (min 0.1mm) (max 45deg)", "skew (min 0mm) (max 1ps)",
                  "solder_paste_rel_margin (opt -0.1) (max 0.1mm)", "clearance (min 0.1mm) (max -0.1)",
                  "length (min 0mm) (max -1)")),
                ("Missing '('.", ("clearance 0.1mm", "track_angle 45")),
                ("within_diff_pairs option invalid for constraint type.",
                 ("clearance (min 0.1mm) (within_diff_pairs)",)),
                ("Missing min value.", ("clearance (min)",)),
                ("Missing max value.", ("clearance (max)",)),
                ("Unrecognized character.", ("clearance (min 0.1mm\t+\t0.1mm)", "clearance (min 0.1\tmm)",
                                             "clearance (min 0.1mm\n+ 0.1mm)",
                                             "clearance (min 0.1mm\r\n+ 0.1mm)"))):
            for bound in bounds:
                with self.subTest(bound=bound):
                    self.assertEqual(dru(W + f'(rule a (constraint {bound}))')[:2], (message, []))

    def test_track_angle_with_units_loads(self):
        # kicad-cli 10.0.8 refuses these; KiCad master reads them as degrees (KiCad 11)
        for bound in ("track_angle (min 45deg)", "track_angle (min 45 deg)", "track_angle (max 90deg)",
                      "track_angle (min 45) (max 90deg)"):
            with self.subTest(bound=bound):
                self.assertEqual(dru(W + f'(rule a (constraint {bound}))')[:2], (None, ["custom:w"]))

    def test_condition_kicad_cannot_parse_refuses_the_file(self):
        for cond in ("A.Type == ", "A.Type == 'track' &&", "&& A.isPlated()",
                     "(A.Type == 'track'", "A.Type == 'track')", "()",
                     "A.Type ==\t'track'", "A.Type == 'track'\r", "A.Type == 'track' @",
                     "A.Type == == 'track'", "A.Type == 'track' || || A.Type == 'via'",
                     "1", "A.Width > 0.2", "A.Width > 0.2MM", "A.Width > 1e3mm", "A.Width > .1mm",
                     "A.Type = 'track'", "A.Type == 'track' & A.Type == 'via'",
                     "A.Type == 'track' ^ A.Type == 'via'", "A.Type == 'track';", "A.Type == 'track' in",
                     "mm", "A.Type == 'track' == 'x'", "A.Width < 1mm < 2mm",
                     "A.insideArea('x')('y')", "(A.isPlated())(A.isPlated())", "A.insideArea(", "A.",
                     'A.NetName == \\"x\\"'):
            with self.subTest(cond=cond):
                rule = W + f'(rule a (condition "{cond}") (constraint clearance (min 0.01mm)))'
                self.assertEqual(dru(rule)[:2], ("Could not parse expression.", []))

    def test_condition_kicad_parses_loads(self):
        for cond in ("A.Type == 'track'", "A.Type  ==  'track'", "  A.Type == 'track'  ",
                     "", "   ", "A", "'x'", "1mm", "'a', 'b'",
                     "!A.isPlated()", "!!A.isPlated()", "!(A.Type == 'track')", "(A.Type == 'track') == 'x'",
                     "A.insideArea('X')", "A.fromTo('U1-1', 'U2-1')",
                     "A.Width > 0.2mm", "A.Width > 0,1mm", "A.Width > -0.1mm", "A.Width > (0.1mm)",
                     "A.Width > 1 && A.Width < 2",
                     "A.Type == 'track", "A.NetName == 'a\tb'",
                     "A.Type == 'track' && B.Type == 'via'", "L == 'F.Cu'"):
            with self.subTest(cond=cond):
                rule = W + f'(rule a (condition "{cond}") (constraint clearance (min 0.01mm)))'
                self.assertEqual(dru(rule)[:2], (None, ["custom:w"]))

    def test_unresolved_text_variable_refuses_the_file(self):
        cond = W + '(rule a (condition "A.NetClass == \'{}\'") (constraint clearance (min 0.01mm)))'
        for rules, pro in (
                *((cond.format(v), None) for v in ("${FOO}", "${LAYER}", "${KIPRJMOD}", "${FOO",
                                                   "${title}", "${projectname}")),
                (W + '(rule a (constraint clearance (min ${FOO})))', None),
                (W + '(rule a (constraint ${FOO} (min 0.01mm)))', None),
                (W + '(rule a (layer "${FOO}") (constraint clearance (min 0.01mm)))', None),
                (W + '(rule "${FOO}" (constraint clearance (min 0.01mm)))', None),
                (W + '(rule a (constraint disallow ${FOO}))', None),
                (cond.format("${foo}"), {"FOO": "Default"}),
                (cond.format("${FOO}"), {"foo": "Default"}),
                (cond.format("${${FOO}}"), {"FOO": "Default"}),
                (cond.format("${${FOO}}"), {"FOO": "BAR"})):
            with self.subTest(rules=rules, pro=pro):
                self.assertEqual(dru(rules, pro=pro)[:2], ("Unresolved text variable.", []))

    def test_nested_text_variable_names_the_variable_by_its_value(self):
        """kicad-cli 10.0.8: ``${${FOO}}`` loads when FOO's value names a defined variable
        (FOO=BAR with BAR defined, FOO=TITLE) and refuses otherwise; the project's value of
        FOO is used before the board property's."""
        cond = W + '(rule a (condition "A.NetClass == \'${${FOO}}\'") (constraint clearance (min 0.01mm)))'
        prop = BOARD.replace("(setup (pad_to_mask_clearance 0))",
                             '(setup (pad_to_mask_clearance 0))\n  (property "FOO" "{}")')
        for board, pro, want in (
                (BOARD, {"FOO": "BAR", "BAR": "x"}, (None, ["custom:w"])),
                (BOARD, {"FOO": "TITLE"}, (None, ["custom:w"])),
                (prop.format("BAR"), {"BAR": "x"}, (None, ["custom:w"])),
                (prop.format("Default"), {"FOO": "BAR", "BAR": "x"}, (None, ["custom:w"])),
                (prop.format("BAR"), {"FOO": "Default", "BAR": "x"},
                 ("Unresolved text variable.", []))):
            with self.subTest(board=board, pro=pro):
                self.assertEqual(dru(cond, board, pro)[:2], want)

    def test_resolved_text_variable_loads(self):
        cond = W + '(rule a (condition "A.NetClass == \'{}\'") (constraint clearance (min 0.01mm)))'
        prop = BOARD.replace("(setup (pad_to_mask_clearance 0))",
                             '(setup (pad_to_mask_clearance 0))\n  (property "BPROP" "Default")')
        for rules, board, pro in (
                (cond.format("${FOO}"), BOARD, {"FOO": "Default"}),
                (cond.format("${foo}"), BOARD, {"foo": "Default"}),
                (cond.format("${Foo}"), BOARD, {"Foo": "Default"}),
                (W + '(rule a (constraint clearance (min ${FOO})))', BOARD, {"FOO": "0.01mm"}),
                *((cond.format(v), BOARD, None)
                  for v in ("${PROJECTNAME}", "${CURRENT_DATE}", "${TITLE}", "${COMMENT9}", "${FILENAME}",
                            "${VARIANT}", "${VCSHASH}", "${VCSSHORTHASH}", "${U1:VALUE}", "${DRC_ERROR}",
                            "${}", "\\\\${FOO}")),
                (cond.format("${BPROP}"), prop, None),
                (W + "# ${FOO}\n", BOARD, None)):
            with self.subTest(rules=rules, pro=pro):
                self.assertEqual(dru(rules, board, pro)[:2], (None, ["custom:w"]))

    def test_text_variables_unchecked_without_names(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "b.kicad_dru").write_text(
                W + "(rule a (condition \"A.NetClass == '${FOO}'\") (constraint clearance (min 0.01mm)))\n",
                encoding="utf-8")
            rules, err = load_kicad_dru_checked(str(Path(d, "b.kicad_pcb")))
        self.assertEqual(len(rules), 2)
        self.assertIsNone(err)

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

    def test_rule_layer_matches_the_board_name_of_a_copper_layer(self):
        rule = '(version 1)\n(rule s (layer "{}") (constraint {} (min 5mm)))\n'
        for layer, ctype, hit in (
                *((layer, "track_width", ["custom:s"])
                  for layer in ("TopCopper", "Top*", "*Copper", "GND", "G?D", "*.Cu", "In*", "*")),
                ("TopCopper", "via_diameter", ["custom:s"]), ("TopCopper", "annular_width", ["custom:s"]),
                ("GND", "via_diameter", []), ("GND", "annular_width", []),
                ("B.Cu", "track_width", [])):
            with self.subTest(layer=layer, ctype=ctype):
                self.assertEqual(dru(rule.format(layer, ctype), RENAMED)[:2], (None, hit))

    def test_wildcard_rule_layer_judges_only_the_layers_it_names(self):
        wide = RENAMED.replace('(width 0.2) (layer "In1.Cu")', '(width 0.3) (layer "In1.Cu")')
        rule = '(version 1)\n(rule s (layer "{}") (constraint track_width (min 5mm)))\n'
        for layer, actual in (("*.Cu", 0.2), ("In*", 0.3), ("Top*", 0.2), ("G?D", 0.3)):
            with self.subTest(layer=layer):
                res = _run(wide, {"b.kicad_dru": rule.format(layer)})
                self.assertNotIn("custom_rules_error", res["project_settings"])
                violations = res["design_rule_compliance"].get("violations", [])
                self.assertEqual([(v["rule"], v["actual_mm"]) for v in violations if v.get("rule") == "custom:s"],
                                 [("custom:s", actual)])

    def test_board_name_equal_to_another_layers_name(self):
        clash = RENAMED.replace('"In1.Cu" signal "GND"', '"In1.Cu" signal "B.Cu"')
        rule = '(version 1)\n(rule s (layer "B.Cu") (constraint track_width (min 5mm)))\n'
        self.assertEqual(dru(rule, clash)[:2], (None, ["custom:s"]))

    def test_outer_and_inner_ignore_board_names(self):
        # In1.Cu called B.Cu; the F.Cu track passes an outer rule, so only In1 could break it
        clash = (RENAMED.replace('"In1.Cu" signal "GND"', '"In1.Cu" signal "B.Cu"')
                 .replace('(width 0.2) (layer "F.Cu")', '(width 6) (layer "F.Cu")'))
        rule = '(version 1)\n(rule s (layer {}) (constraint track_width (min 5mm)))\n'
        self.assertEqual(dru(rule.format("outer"), clash)[:2], (None, []))
        self.assertEqual(dru(rule.format("inner"), clash)[:2], (None, ["custom:s"]))

    def test_board_name_of_another_board_is_not_a_layer(self):
        err, hit, _ = dru(W + '(rule s (layer "TopCopper") (constraint track_width (min 5mm)))')
        self.assertEqual((err, hit), ("Unrecognized layer.", []))

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
