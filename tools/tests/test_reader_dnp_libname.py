"""KiCad takes a symbol's do-not-populate state from its `dnp` attribute (SCH_SEXPR_PARSER:
SetDNP(parseBool())); the Value text carries no meaning there.  Files without the token (KiCad 6)
keep the Value guess.  A missing Value falls back to the cached library symbol, stored under
`lib_name` when the placed symbol has one."""
import os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from schematic.reader import parse_single_sheet  # noqa: E402


def lib(name, value):
    return (f'(symbol "{name}" (in_bom yes) (on_board yes)'
            f' (property "Reference" "R" (at 0 0 0)) (property "Value" "{value}" (at 0 0 0)))')


def parse(placed, libs):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.kicad_sch")
        with open(path, "w", encoding="utf-8") as f:
            f.write('(kicad_sch (version 20250114) (generator "eeschema")'
                    ' (uuid "00000000-0000-0000-0000-0000000000aa") (paper "A4")'
                    f' (lib_symbols {libs}) {placed})')
        (comp,) = parse_single_sheet(path).components
    return comp


def placed(extra="", value='(property "Value" "DNP" (at 0 0 0))', lib_id="t:R"):
    return (f'(symbol (lib_id "{lib_id}") (at 100 100 0) (unit 1) {extra} (in_bom yes) (on_board yes)'
            ' (uuid "00000000-0000-0000-0000-000000000001")'
            f' (property "Reference" "R1" (at 0 0 0)) {value})')


class ExplicitDnpTokenTest(unittest.TestCase):
    def test_dnp_no_beats_dnp_value(self):
        self.assertFalse(parse(placed("(dnp no)"), lib("t:R", "10k"))["dnp"])

    def test_dnp_yes_with_ordinary_value(self):
        c = parse(placed("(dnp yes)", '(property "Value" "10k" (at 0 0 0))'), lib("t:R", "10k"))
        self.assertTrue(c["dnp"])

    def test_no_token_keeps_value_guess(self):
        self.assertTrue(parse(placed(), lib("t:R", "10k"))["dnp"])

    def test_no_token_ordinary_value(self):
        c = parse(placed("", '(property "Value" "10k" (at 0 0 0))'), lib("t:R", "10k"))
        self.assertFalse(c["dnp"])


class LibNameValueFallbackTest(unittest.TestCase):
    def test_missing_value_reads_lib_name_symbol(self):
        c = parse(placed('(lib_name "R_1")', value=""), lib("R_1", "47k") + lib("t:R", "1k"))
        self.assertEqual(c["value"], "47k")

    def test_missing_value_without_lib_name_uses_lib_id(self):
        self.assertEqual(parse(placed(value=""), lib("t:R", "1k"))["value"], "1k")


if __name__ == "__main__":
    unittest.main()
