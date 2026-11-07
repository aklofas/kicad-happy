"""The S-expression parser survives truncated and mutated KiCad files, ignores
trailing content after the root, round-trips quoted strings, and the analyzers
exit 0 on truncated, too-deep or non-KiCad input with one diagnostics record."""
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

from kicad_core.sexp import parse, parse_checked
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

    def test_open_list_at_eof_closes(self):
        self.assertEqual(parse("(a (b"), ["a", ["b"]])

    def test_open_list_at_eof_is_reported(self):
        self.assertEqual(parse_checked("(a (b"),
                         (["a", ["b"]], "the file ends inside an open list"))
        self.assertEqual(parse_checked('(a "b c'),
                         (["a", "b c"], "the file ends inside an open list"))

    def test_whole_input_has_no_problem(self):
        self.assertEqual(parse_checked(SMALL), (parse(SMALL), None))


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
        self.assertEqual(parse_checked(SMALL + "\n(garbage (x"), (parse(SMALL), None))

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


def _depth(node):
    d = 0
    while isinstance(node, list):
        d += 1
        node = node[0] if node else None
    return d


class DepthTest(unittest.TestCase):
    def test_moderate_depth_parses(self):
        self.assertEqual(parse_checked("(a" * 200 + ")" * 200)[1], None)
        self.assertEqual(_depth(parse("(" * 200 + ")" * 200)), 200)

    def test_deep_nesting_parses_and_is_reported(self):
        tree, problem = parse_checked("(a (b " + "(" * 5000 + ")" * 5000 + ") (c))")
        self.assertEqual(problem, "lists nest deeper than 200 levels")
        self.assertEqual(tree[0], "a")
        self.assertEqual(tree[2], ["c"])
        self.assertEqual(_depth(tree[1][1]), 198)


def _run_cli(script, text, tmp, name, *extra):
    src = Path(tmp) / name
    src.write_text(text, encoding="utf-8")
    out = Path(tmp) / (name + ".json")
    r = subprocess.run([sys.executable, str(SCRIPTS / script), str(src),
                        "--output", str(out), *extra],
                       capture_output=True, text=True, encoding="utf-8")
    return r, out


SCH_SOURCE = "schematic.pipeline.analyze_schematic"
PCB_SOURCE = "pcb.pipeline.read_board"


def _diagnostics(test, script, text, tmp, name):
    r, out = _run_cli(script, text, tmp, name)
    test.assertEqual(r.returncode, 0, r.stderr[-500:])
    test.assertNotIn("Traceback", r.stderr)
    result = json.loads(out.read_text(encoding="utf-8"))
    test.assertIsInstance(result, dict)
    return result["diagnostics"]


def _record(source, message, effect):
    return {"source": source, "exception": "ValueError", "message": message, "effect": effect}


class CliTruncationTest(unittest.TestCase):
    def _check(self, script, src, name, seed, source, effect):
        text = src.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            for s in _prefixes(text, 8, seed):
                self.assertEqual(_diagnostics(self, script, s, tmp, name),
                                 [_record(source, f"{name}: the file ends inside an open list",
                                          effect)], len(s))

    @unittest.skipUnless(have(SCH), "KH_FIXTURES not set")
    def test_truncated_schematic_cli(self):
        self._check("analyze_schematic.py", SCH, "t.kicad_sch", 11, SCH_SOURCE,
                    "partial sheet analyzed")

    @unittest.skipUnless(have(PCB), "KH_FIXTURES not set")
    def test_truncated_board_cli(self):
        self._check("analyze_pcb.py", PCB, "t.kicad_pcb", 12, PCB_SOURCE,
                    "partial board analyzed")


LFS = ("version https://git-lfs.github.com/spec/v1\n"
       "oid sha256:4d7a214614ab2935c943f9e0ff69d22eadbb8f32b1258daaa5e2ca24d17e2393\n"
       "size 12345\n")
BOARD = '(kicad_pcb (version 20240108) (generator "pcbnew") (net 0 "") (net 1 "A"))\n'


class CliUnreadableInputTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_lfs_pointer_is_not_read_as_a_schematic_or_board(self):
        self.assertEqual(
            _diagnostics(self, "analyze_schematic.py", LFS, self.tmp, "p.kicad_sch"),
            [_record(SCH_SOURCE, "p.kicad_sch is not a KiCad schematic (.kicad_sch or legacy "
                     ".sch): it starts with 'version'", "file not read as a schematic")])
        self.assertEqual(
            _diagnostics(self, "analyze_pcb.py", LFS, self.tmp, "p.kicad_pcb"),
            [_record(PCB_SOURCE, "p.kicad_pcb is not a KiCad board (.kicad_pcb): it starts "
                     "with 'version'", "file not read as a board")])

    def test_lib_symbols_fragment_is_not_read_as_a_schematic(self):
        frag = '(lib_symbols (symbol "Device:R" (pin_numbers hide)))\n'
        self.assertEqual(
            _diagnostics(self, "analyze_schematic.py", frag, self.tmp, "f.kicad_sch"),
            [_record(SCH_SOURCE, "f.kicad_sch is not a KiCad schematic (.kicad_sch or legacy "
                     ".sch): it starts with 'lib_symbols'", "file not read as a schematic")])

    def test_merge_conflict_is_reported(self):
        conflict = BOARD.replace('(net 1 "A")', '\n<<<<<<< HEAD\n(net 1 "A")\n=======\n'
                                 '(net 1 "B"\n>>>>>>> other\n')
        self.assertEqual(
            _diagnostics(self, "analyze_pcb.py", conflict, self.tmp, "c.kicad_pcb"),
            [_record(PCB_SOURCE, "c.kicad_pcb: the file ends inside an open list",
                     "partial board analyzed")])
        first = "<<<<<<< HEAD\n" + SMALL + "\n=======\n" + SMALL + "\n>>>>>>> other\n"
        self.assertEqual(
            _diagnostics(self, "analyze_schematic.py", first, self.tmp, "c.kicad_sch"),
            [_record(SCH_SOURCE, "c.kicad_sch is not a KiCad schematic (.kicad_sch or legacy "
                     ".sch): it starts with '<<<<<<<'", "file not read as a schematic")])

    def test_deep_nesting_is_reported_not_a_crash(self):
        deep = "(" * 3000 + ")" * 3000
        self.assertEqual(
            _diagnostics(self, "analyze_schematic.py",
                         SMALL[:-1] + " (x " + deep + "))", self.tmp, "d.kicad_sch"),
            [_record(SCH_SOURCE, "d.kicad_sch: lists nest deeper than 200 levels",
                     "partial sheet analyzed")])
        self.assertEqual(
            _diagnostics(self, "analyze_pcb.py",
                         BOARD.rstrip()[:-1] + " (x " + deep + "))", self.tmp, "d.kicad_pcb"),
            [_record(PCB_SOURCE, "d.kicad_pcb: lists nest deeper than 200 levels",
                     "partial board analyzed")])

    def test_content_after_the_root_is_ignored_without_a_record(self):
        self.assertEqual(
            _diagnostics(self, "analyze_schematic.py", SMALL + "\n(junk (x", self.tmp,
                         "t.kicad_sch"), [])
        self.assertEqual(
            _diagnostics(self, "analyze_pcb.py", BOARD + ") )\n(junk", self.tmp,
                         "t.kicad_pcb"), [])


if __name__ == "__main__":
    unittest.main()
