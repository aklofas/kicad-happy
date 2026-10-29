# tools/tests/test_pcb_custom_rules.py
"""Custom .kicad_dru rules as KiCad 10 applies them: minimum and maximum bounds, the rule's
layer, (severity ignore), mil/in units, pad holes and plated pad annuli, and precedence (a later
rule replaces an earlier one and any custom minimum replaces the board minimum). Expected values
are kicad-cli 10.0.7 DRC results on the same boards."""
import json, os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.project import load_kicad_dru, parse_dru_length  # noqa: E402
from pcb.pipeline import analyze_pcb  # noqa: E402

BOARD = """(kicad_pcb (version 20221018) (generator pcbnew)
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (1 "In1.Cu" signal) (2 "In2.Cu" signal) (31 "B.Cu" signal)
    (37 "F.SilkS" user "F.Silkscreen") (44 "Edge.Cuts" user))
  (setup (pad_to_mask_clearance 0))
  (net 0 "") (net 1 "A")
{items})
"""


def track(width, layer="F.Cu"):
    return f'  (segment (start 0 0) (end 5 0) (width {width}) (layer "{layer}") (net 1))\n'


def via(size, drill):
    return f'  (via (at 1 1) (size {size}) (drill {drill}) (layers "F.Cu" "B.Cu") (net 1))\n'


def footprint(ref, pad_type, size, drill, x=20):
    layers = '"*.Cu" "*.Mask"'
    return (f'  (footprint "T:{ref}" (layer "F.Cu") (at {x} 20)\n'
            f'    (fp_text reference "{ref}" (at 0 -3) (layer "F.SilkS")\n'
            f'      (effects (font (size 1 1) (thickness 0.15))))\n'
            f'    (pad "1" {pad_type} circle (at 0 0) (size {size} {size}) (drill {drill})'
            f' (layers {layers})))\n')


def pro(rules):
    return json.dumps({"board": {"design_settings": {"rules": rules}},
                       "net_settings": {"classes": [{"name": "Default"}]}})


def compliance(items, dru, pro_text=None):
    with tempfile.TemporaryDirectory() as tmp:
        board = os.path.join(tmp, "b.kicad_pcb")
        with open(board, "w", encoding="utf-8") as f:
            f.write(BOARD.format(items=items))
        with open(os.path.join(tmp, "b.kicad_dru"), "w", encoding="utf-8") as f:
            f.write("(version 1)\n" + dru)
        if pro_text is not None:
            with open(os.path.join(tmp, "b.kicad_pro"), "w", encoding="utf-8") as f:
                f.write(pro_text)
        return analyze_pcb(board)["design_rule_compliance"]


def violations(result):
    return [(v["rule"], v.get("bound"), v["required_mm"], v["actual_mm"])
            for v in result.get("violations", [])]


LOW_MINIMA = pro({"min_track_width": 0.05, "min_via_diameter": 0.2,
                  "min_through_hole_diameter": 0.1})


class DruLengthTest(unittest.TestCase):
    def test_units(self):
        # pcbexpr_evaluator.cpp unit resolver: mil, mm, in. A bare number is "Missing units"
        # (libeval_compiler.cpp) and kicad-cli then loads none of the file's rules.
        self.assertEqual(parse_dru_length("5mil"), 0.127)
        self.assertEqual(parse_dru_length("6 mil"), 0.1524)
        self.assertEqual(parse_dru_length("0.2mm"), 0.2)
        self.assertEqual(parse_dru_length("0.01in"), 0.254)
        self.assertIsNone(parse_dru_length("0.2"))
        self.assertIsNone(parse_dru_length("2 * 0.1mm"))

    def test_loader_reads_mil_and_spaced_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "b.kicad_dru"), "w", encoding="utf-8") as f:
                f.write('(version 1)\n(rule w (constraint track_width (min 5mil) (max 6 mil)))\n'
                        '(rule e (severity ignore) (constraint hole_size (min "2*0.1mm")))\n')
            rules = load_kicad_dru(os.path.join(tmp, "b.kicad_pcb"))
        self.assertEqual(rules[0]["constraints"], [{"type": "track_width", "min": 0.127,
                                                    "max": 0.1524}])
        self.assertEqual(rules[1]["severity"], "ignore")
        self.assertEqual(rules[1]["constraints"][0]["min"], "2*0.1mm")


class CustomRuleTest(unittest.TestCase):
    def test_hole_max_bound(self):
        # kicad-cli: drill_out_of_range "(a max hole 6.3000 mm; actual 6.4000 mm)"
        dru = "(rule a (constraint hole_size (min 0.2mm) (max 6.3mm)))\n"
        result = compliance(footprint("H1", "np_thru_hole", 6.4, 6.4), dru)
        self.assertEqual(violations(result), [("custom:a", "max", 6.3, 6.4)])
        self.assertEqual(result["violations"][0]["source_ref"], "H1")

    def test_custom_via_diameter_min_and_max(self):
        # kicad-cli: via_diameter "(rule 'v' min diameter 0.7000 mm; actual 0.6000 mm)" and
        # "(rule 'v' max diameter 0.9000 mm; actual 1.0000 mm)"
        dru = "(rule v (constraint via_diameter (min 0.7mm) (max 0.9mm)))\n"
        self.assertEqual(violations(compliance(via(0.6, 0.3), dru, LOW_MINIMA)),
                         [("custom:v", "min", 0.7, 0.6)])
        self.assertEqual(violations(compliance(via(1.0, 0.3), dru, LOW_MINIMA)),
                         [("custom:v", "max", 0.9, 1.0)])

    def test_layer_rule_on_holes_follows_the_enabled_layers(self):
        # A hole has no layer of its own: an In1.Cu rule applies to an NPTH hole because the board
        # enables In1.Cu; an In3.Cu rule does not (kicad-cli: drill_out_of_range "(rule 'h' min
        # hole 0.5000 mm; actual 0.3000 mm)" for In1.Cu only)
        hole = footprint("H1", "np_thru_hole", 0.3, 0.3)
        in1 = "(rule h (layer In1.Cu) (constraint hole_size (min 0.5mm)))\n"
        in3 = "(rule h (layer In3.Cu) (constraint hole_size (min 0.5mm)))\n"
        self.assertEqual(violations(compliance(hole, in1, LOW_MINIMA)),
                         [("custom:h", "min", 0.5, 0.3)])
        self.assertEqual(violations(compliance(hole, in3, LOW_MINIMA)), [])

    def test_unconditional_custom_minimum_replaces_the_board_minimum(self):
        # KH-427; kicad-cli: no drill_out_of_range for the 0.25 mm hole
        dru = "(rule h (constraint hole_size (min 0.2mm)))\n"
        result = compliance(via(0.6, 0.25), dru,
                            pro({"min_through_hole_diameter": 0.3, "min_via_diameter": 0.5}))
        self.assertEqual(violations(result), [])

    def test_rule_on_another_layer_is_not_applied(self):
        # kicad-cli: no track_width for the F.Cu track; one for the In1.Cu track
        dru = "(rule in1 (layer In1.Cu) (constraint track_width (min 0.127mm)))\n"
        self.assertEqual(violations(compliance(track(0.1), dru, LOW_MINIMA)), [])
        self.assertEqual(violations(compliance(track(0.1, "In1.Cu"), dru, LOW_MINIMA)),
                         [("custom:in1", "min", 0.127, 0.1)])

    def test_later_rule_replaces_an_earlier_one(self):
        # kicad-cli: no track_width (rule b, last in the file, wins)
        dru = ("(rule a (constraint track_width (min 0.2mm)))\n"
               "(rule b (constraint track_width (min 0.1mm)))\n")
        self.assertEqual(violations(compliance(track(0.15), dru, LOW_MINIMA)), [])

    def test_conditional_minimum_lowers_the_floor(self):
        # The condition is not evaluated, so 0.08 may apply: no violation (kicad-cli: none,
        # the condition matches the track).
        dru = "(rule c (condition \"A.NetName == 'A'\") (constraint track_width (min 0.08mm)))\n"
        result = compliance(track(0.09), dru, pro({"min_track_width": 0.1}))
        self.assertEqual(violations(result), [])
        self.assertEqual(result["conditional_rules_skipped"], ["c"])

    def test_severity_ignore_silences_the_type(self):
        # kicad-cli: no track_width; the ignored rule also replaces the board minimum
        dru = "(rule x (severity ignore) (constraint track_width (min 0.3mm)))\n"
        self.assertEqual(violations(compliance(track(0.15), dru)), [])

    def test_plated_pad_annulus_checked_and_npth_excluded(self):
        # kicad-cli: annular_width "(r min annular width 0.2000 mm; actual 0.1000 mm)" on P1 only
        dru = "(rule r (constraint annular_width (min 0.2mm)))\n"
        items = (footprint("P1", "thru_hole", 1.0, 0.8)
                 + footprint("N1", "np_thru_hole", 1.0, 0.8, x=30))
        result = compliance(items, dru, LOW_MINIMA)
        self.assertEqual(violations(result), [("custom:r", "min", 0.2, 0.1)])


    def test_bare_number_drops_every_custom_rule(self):
        # "Missing units" for (min 0.2): kicad-cli loads none of the file's rules, so the strict
        # track rule is not applied and the board minimum still fails the 0.25 mm hole
        # ("board setup constraints min hole 0.3000 mm; actual 0.2500 mm").
        dru = ("(rule bare (constraint hole_size (min 0.2)))\n"
               "(rule strict (constraint track_width (min 0.3mm)))\n")
        result = compliance(via(0.6, 0.25) + track(0.25), dru,
                            pro({"min_through_hole_diameter": 0.3, "min_via_diameter": 0.5}))
        self.assertEqual(violations(result), [("min_via_drill", None, 0.3, 0.25)])

    def test_custom_pad_annulus_is_not_estimated_from_its_anchor(self):
        # The anchor gives (0.9 - 0.8) / 2 = 0.05 mm, but KiCad measures the pad outline (anchor
        # plus a 2 mm copper circle): kicad-cli reports no annular_width.
        pad = ('  (footprint "T:C1" (layer "F.Cu") (at 20 20)\n'
               '    (fp_text reference "C1" (at 0 -3) (layer "F.SilkS")\n'
               '      (effects (font (size 1 1) (thickness 0.15))))\n'
               '    (pad "1" thru_hole custom (at 0 0) (size 0.9 0.9) (drill 0.8)'
               ' (layers "*.Cu" "*.Mask") (options (clearance outline) (anchor circle))\n'
               '      (primitives (gr_circle (center 0 0) (end 1 0) (width 0) (fill yes)))))\n')
        dru = "(rule r (constraint annular_width (min 0.2mm)))\n"
        self.assertEqual(violations(compliance(pad, dru, LOW_MINIMA)), [])


if __name__ == "__main__":
    unittest.main()
