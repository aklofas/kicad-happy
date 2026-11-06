"""The S-expression parser survives truncated and mutated KiCad files, ignores
trailing content after the root, round-trips quoted strings, and the analyzers
exit 0 on truncated input."""
import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.sexp import parse
from tools.tests._fixtures import fixture_path, have

SCH = fixture_path("simple-project", "simple.kicad_sch")
PCB = fixture_path("simple-project", "simple.kicad_pcb")

SMALL = ("(kicad_sch (version 20231120) (generator eeschema) (lib_symbols) "
         "(wire (pts (xy 0 0) (xy 1 1))))")


def _prefixes(text, n, seed):
    rng = random.Random(seed)
    cuts = sorted(rng.randrange(1, len(text)) for _ in range(n))
    return [text[:c] for c in cuts if text[:c].strip()]


class TruncationTest(unittest.TestCase):
    def test_prefix_of_inline_text_parses(self):
        for s in _prefixes(SMALL, 60, 1234):
            self.assertIsInstance(parse(s), (list, str), s)

    @unittest.skipUnless(have(SCH), "KH_FIXTURES not set")
    def test_prefix_of_schematic_parses(self):
        text = SCH.read_text(encoding="utf-8")
        for s in _prefixes(text, 200, 1234):
            self.assertIsInstance(parse(s), (list, str), len(s))

    @unittest.skipUnless(have(PCB), "KH_FIXTURES not set")
    def test_prefix_of_board_parses(self):
        text = PCB.read_text(encoding="utf-8")
        for s in _prefixes(text, 200, 7):
            self.assertIsInstance(parse(s), (list, str), len(s))

    def test_blank_input_raises_value_error(self):
        for s in ("", "   ", "\n\t", "#c\n"):
            with self.assertRaises(ValueError):
                parse(s)

    # Flips in the diagnostics change only if the parser starts raising on
    # unterminated input; a recorded diagnostic with the same tree keeps this.
    def test_open_list_at_eof_closes(self):
        self.assertEqual(parse("(a (b"), ["a", ["b"]])


class MutationTest(unittest.TestCase):
    def _mutations(self, text, seed, n=200):
        rng = random.Random(seed)
        for _ in range(n):
            b = list(text)
            for _ in range(5):
                b[rng.randrange(len(b))] = rng.choice('()"\\ \n#{}x\0')
            yield "".join(b)

    def _check(self, text, seed):
        for s in self._mutations(text, seed):
            try:
                parse(s)
            except (ValueError, RecursionError):
                pass

    def test_inline_mutations_raise_only_value_or_recursion_error(self):
        self._check(SMALL, 7)

    @unittest.skipUnless(have(SCH), "KH_FIXTURES not set")
    def test_schematic_mutations_raise_only_value_or_recursion_error(self):
        self._check(SCH.read_text(encoding="utf-8"), 7)


class TrailingContentTest(unittest.TestCase):
    def test_trailing_list_ignored(self):
        self.assertEqual(parse(SMALL + "\n(garbage (x))"), parse(SMALL))

    def test_trailing_close_parens_ignored(self):
        self.assertEqual(parse(SMALL + " ) ) junk"), parse(SMALL))


class QuotedRoundTripTest(unittest.TestCase):
    def test_random_quoted_strings_round_trip(self):
        # no "{" in the alphabet: brace escapes decode by design
        rng = random.Random(42)
        alpha = 'ab Z0()"\\#;\n\t\x00\u00e9\u2192'
        for _ in range(500):
            s = "".join(rng.choice(alpha) for _ in range(rng.randrange(12)))
            enc = s.replace("\\", "\\\\").replace('"', '\\"')
            self.assertEqual(parse('(a "%s" (b c))' % enc),
                             ["a", s, ["b", "c"]], repr(s))


class DepthTest(unittest.TestCase):
    def test_moderate_depth_parses(self):
        self.assertIsInstance(parse("(" * 400 + ")" * 400), list)

    # changes when truncation is reported as a diagnostic: an iterative parser parses it, or the reader records the error
    def test_deep_nesting_raises_recursion_error(self):
        with self.assertRaises(RecursionError):
            parse("(" * 5000 + ")" * 5000)


def _run_cli(script, text, tmp, name, *extra):
    src = Path(tmp) / name
    src.write_text(text, encoding="utf-8")
    out = Path(tmp) / (name + ".json")
    r = subprocess.run([sys.executable, str(SCRIPTS / script), str(src),
                        "--output", str(out), *extra],
                       capture_output=True, text=True, encoding="utf-8")
    return r, out


class CliTruncationTest(unittest.TestCase):
    # A later change adds a non-empty diagnostics assertion to these; they do not assert
    # on diagnostics today.
    def _check(self, script, src, name, seed):
        text = src.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            for s in _prefixes(text, 8, seed):
                r, out = _run_cli(script, s, tmp, name)
                self.assertEqual(r.returncode, 0, (len(s), r.stderr[-500:]))
                self.assertNotIn("Traceback", r.stderr)
                self.assertIsInstance(json.loads(out.read_text(encoding="utf-8")), dict)

    @unittest.skipUnless(have(SCH), "KH_FIXTURES not set")
    def test_truncated_schematic_cli(self):
        self._check("analyze_schematic.py", SCH, "t.kicad_sch", 11)

    @unittest.skipUnless(have(PCB), "KH_FIXTURES not set")
    def test_truncated_board_cli(self):
        self._check("analyze_pcb.py", PCB, "t.kicad_pcb", 12)


if __name__ == "__main__":
    unittest.main()
