"""The S-expression tokenizer follows KiCad's lexer (common/dsnlexer.cpp)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from kicad_core.sexp import find_all, get_properties, get_property, has_flag, parse


class QuoteInsideAtomTest(unittest.TestCase):
    def test_quote_inside_atom_stays_in_the_atom(self):
        self.assertEqual(parse('(a (b 1.3"-128x64 (c d)))'),
                         ['a', ['b', '1.3"-128x64', ['c', 'd']]])

    def test_trailing_quotes_stay_in_the_atom(self):
        self.assertEqual(parse('(fp_text value FIDUCIAL"" (at 0 0))')[2], 'FIDUCIAL""')

    def test_footprint_after_such_an_atom_survives(self):
        board = parse(
            '(kicad_pcb (module A (layer F.Cu) (fp_text value 0.96"_OLED (at 0 0)))'
            ' (module B (layer F.Cu) (fp_text value 10k (at 1 1))))')
        self.assertEqual(len(find_all(board, "module")), 2)

    def test_nul_is_whitespace(self):
        self.assertEqual(parse('(a 0.1\x00\x00 b)'), ['a', '0.1', 'b'])


class CommentTest(unittest.TestCase):
    def test_hash_comment_only_at_line_start(self):
        self.assertEqual(parse('(a\n  # comment\n (b #x) c)'), ['a', ['b', '#x'], 'c'])

    def test_hash_inside_an_atom(self):
        self.assertEqual(parse('(net 1 /#OVERVOLTAGE)'), ['net', '1', '/#OVERVOLTAGE'])


class EscapeTest(unittest.TestCase):
    def test_c_escapes(self):
        self.assertEqual(parse(r'(a "x\ay\101\x41\q")'), ['a', 'x\x07yAA\\q'])

    def test_hex_escapes_decode_as_utf8_bytes(self):
        self.assertEqual(parse(r'(a "\xC3\xA9")'), ['a', 'é'])

    def test_existing_escapes(self):
        self.assertEqual(parse(r'(a "p\\q\"r\ns")'), ['a', 'p\\q"r\ns'])


class KeywordTest(unittest.TestCase):
    def test_quoted_private_is_a_name(self):
        n = parse('(s (property "private" "v") (property private "Name" "V2"))')
        self.assertEqual(get_property(n, "private"), "v")
        self.assertEqual(get_property(n, "Name"), "V2")
        self.assertEqual(get_properties(n), {"private": "v", "name": "V2"})

    def test_quoted_hide_is_not_a_flag(self):
        self.assertFalse(has_flag(parse('(t x "hide")'), "hide"))
        self.assertTrue(has_flag(parse('(t x hide)'), "hide"))

    def test_hide_without_value_is_hidden(self):
        self.assertTrue(has_flag(parse('(fp_text user x (hide))'), "hide"))
        self.assertFalse(has_flag(parse('(fp_text user x (hide no))'), "hide"))
        self.assertTrue(has_flag(parse('(fp_text user x (hide yes))'), "hide"))


class UnterminatedQuoteTest(unittest.TestCase):
    """Pins the behaviour before the token-rule change: the open string runs to the end."""

    def test_unterminated_quote_at_end_of_file(self):
        self.assertEqual(parse('(a "xyz'), ['a', 'xyz'])
        self.assertEqual(parse('(a (b "x\\'), ['a', ['b', 'x\\']])
        self.assertEqual(parse('(a "x\\"'), ['a', 'x"'])


if __name__ == "__main__":
    unittest.main()
