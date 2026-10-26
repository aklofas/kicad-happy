# tools/tests/test_pcb_silk_hide.py
"""Silkscreen reference/value/user texts honour KiCad's `hide` forms."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.sexp import parse as parse_sexp  # noqa: E402
from pcb.reader import extract_silkscreen  # noqa: E402

EFF = '(effects (font (size 1 1)))'


def _silk(body):
    root = parse_sexp('(kicad_pcb (version 20221018)\n(footprint "L:F" (layer "F.Cu") (at 0 0)\n'
                      + body + '))')
    return extract_silkscreen(root, [])


def _ref(flag):
    return _silk(f'(property "Reference" "R1" {flag} (layer "F.SilkS") {EFF})')


class TestSilkHide(unittest.TestCase):
    def test_property_forms(self):
        for flag, vis in (("hide", 0), ("(hide yes)", 0), ("(hide no)", 1), ("", 1)):
            r = _ref(flag)
            self.assertEqual((r["refs_visible_on_silk"], r["refs_hidden_on_silk"]),
                             (vis, 1 - vis), flag)

    def test_kicad5_fp_text_reference(self):
        r = _silk(f'(fp_text reference R1 (at 0 0) (layer F.SilkS) hide {EFF})')
        self.assertEqual((r["refs_visible_on_silk"], r["refs_hidden_on_silk"]), (0, 1))
        r = _silk(f'(fp_text reference R1 (at 0 0) (layer F.SilkS) {EFF})')
        self.assertEqual((r["refs_visible_on_silk"], r["refs_hidden_on_silk"]), (1, 0))

    def test_effects_hide_still_hides(self):
        r = _silk('(property "Reference" "R1" (layer "F.SilkS") (effects (font (size 1 1)) hide))')
        self.assertEqual(r["refs_visible_on_silk"], 0)

    def test_value_hidden(self):
        r = _silk('(property "Reference" "R1" (layer "F.SilkS"))'
                  '(fp_text value 10k (at 0 0) (layer F.SilkS) hide)'
                  '(property "Value" "10k" (hide yes) (layer "F.SilkS"))')
        self.assertNotIn("values_visible_on_silk", r)

    def test_user_text_hide(self):
        r = _silk('(fp_text user "note" (at 0 0) (layer F.SilkS) hide)'
                  '(fp_text user "hide" (at 0 0) (layer F.SilkS))')
        self.assertEqual([t["text"] for t in r["user_silk_texts"]], ["hide"])

    def test_text_literally_hide_is_visible(self):
        r = _silk(f'(property "Reference" "hide" (layer "F.SilkS") {EFF})')
        self.assertEqual(r["refs_visible_on_silk"], 1)


if __name__ == "__main__":
    unittest.main()
