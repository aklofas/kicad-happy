"""A quoted bracket in an S-expression is a string, not punctuation."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from kicad_core.sexp import find_all, parse


class QuotedBracketTest(unittest.TestCase):
    def test_quoted_close_paren_in_schematic_text(self):
        got = parse('(kicad_sch (text ")") (symbol (lib_id "Device:R")))')
        self.assertEqual(got, ['kicad_sch', ['text', ')'], ['symbol', ['lib_id', 'Device:R']]])

    def test_quoted_open_paren(self):
        self.assertEqual(parse('(a "(" (b x))'), ['a', '(', ['b', 'x']])
        self.assertEqual(parse('(a (b ")") (c "("))'), ['a', ['b', ')'], ['c', '(']])

    def test_escaped_quotes_around_a_bracket(self):
        self.assertEqual(parse(r'(a "a \"(\" b")'), ['a', 'a "(" b'])

    def test_pcb_text_bracket_keeps_following_segment(self):
        root = parse('(kicad_pcb (gr_text "(" (at 1 2)) (segment (start 0 0) (end 1 1)))')
        self.assertEqual(len(find_all(root, 'segment')), 1)

    def test_stray_close_paren_unchanged(self):
        # Malformed input keeps its pre-existing results.
        self.assertEqual(parse('(a b))'), ['a', 'b'])
        self.assertEqual(parse(') (a)'), ')')
        self.assertEqual(parse(')'), ')')


if __name__ == "__main__":
    unittest.main()
