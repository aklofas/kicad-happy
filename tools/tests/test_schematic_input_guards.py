"""Recursive and empty inputs: a sheet that includes its own ancestor or an empty sub-sheet is
skipped with a diagnostic; an empty top-level input is a usage error (exit 2); a KiCad 5 .pro
resolves to its sibling schematic."""
import json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
FX = Path(os.environ.get("KH_FIXTURES", "/tmp/harness-pin/tests/fixtures")) / "simple-project"


def _limit_memory():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (4 * 1024 ** 3, 4 * 1024 ** 3))
    except (ImportError, ValueError, OSError):
        pass


def _run(script, *args, cwd):
    env = dict(os.environ, PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True,
                          text=True, encoding="utf-8", cwd=cwd, env=env, timeout=120,
                          preexec_fn=_limit_memory if os.name == "posix" else None)


def _with_sheet(base, sheet_file, uuid="99999999-0000-0000-0000-000000000001"):
    """The simple fixture plus one (sheet ...) block naming *sheet_file*."""
    tail = base.rindex("\t(sheet_instances")
    block = f'''\t(sheet (at 50 50) (size 20 20) (uuid "{uuid}")
\t\t(property "Sheetname" "Sub" (at 50 49 0) (effects (font (size 1.27 1.27))))
\t\t(property "Sheetfile" "{sheet_file}" (at 50 71 0) (effects (font (size 1.27 1.27))))
\t\t(pin "IN" input (at 50 55 180) (uuid "99999999-0000-0000-0000-0000000000a1") (effects (font (size 1.27 1.27))))
\t\t(instances (project "simple" (path "/11111111-1111-1111-1111-111111111111" (page "2"))))
\t)
'''
    return base[:tail] + block + base[tail:]


@unittest.skipUnless(FX.is_dir(), "harness fixtures not present")
class SheetGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = (FX / "simple.kicad_sch").read_text(encoding="utf-8")

    def _analyze(self, tmp, root):
        out = os.path.join(tmp, "out.json")
        t0 = time.monotonic()
        r = _run("analyze_schematic.py", root, "-o", out, cwd=tmp)
        self.assertLess(time.monotonic() - t0, 60)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertNotIn("Traceback", r.stderr)
        with open(out, encoding="utf-8") as f:
            return json.load(f)

    def test_self_referencing_sheet_terminates_with_one_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "self_ref.kicad_sch")
            Path(root).write_text(_with_sheet(self.base, "self_ref.kicad_sch"), encoding="utf-8")
            d = self._analyze(tmp, root)
        effects = [x for x in d["diagnostics"] if x["effect"] == "recursive sheet skipped"]
        self.assertEqual(len(effects), 1, d["diagnostics"])
        self.assertEqual(effects[0]["source"], "schematic.hierarchy.parse_all_sheets")
        self.assertGreater(len(d["components"]), 0)

    def test_mutual_recursion_terminates_with_one_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "mutual.kicad_sch")
            Path(root).write_text(_with_sheet(self.base, "b.kicad_sch"), encoding="utf-8")
            Path(tmp, "b.kicad_sch").write_text(
                _with_sheet(self.base, "mutual.kicad_sch", uuid="99999999-0000-0000-0000-000000000002"),
                encoding="utf-8")
            d = self._analyze(tmp, root)
        effects = [x for x in d["diagnostics"] if x["effect"] == "recursive sheet skipped"]
        self.assertEqual(len(effects), 1, d["diagnostics"])

    def test_empty_sub_sheet_is_skipped_with_a_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "empty_sub.kicad_sch")
            Path(root).write_text(_with_sheet(self.base, "child.kicad_sch"), encoding="utf-8")
            Path(tmp, "child.kicad_sch").write_text("", encoding="utf-8")
            d = self._analyze(tmp, root)
        self.assertEqual([(x["source"], x["effect"]) for x in d["diagnostics"]],
                         [("schematic.hierarchy.parse_all_sheets", "empty sheet skipped")])

    def test_acyclic_fixture_has_no_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._analyze(tmp, str(FX / "simple.kicad_sch"))
        self.assertEqual(d["diagnostics"], [])


@unittest.skipUnless(FX.is_dir(), "harness fixtures not present")
class RootInputTest(unittest.TestCase):
    def _usage_error(self, script, path, needle):
        with tempfile.TemporaryDirectory() as tmp:
            r = _run(script, path, "-o", os.path.join(tmp, "out.json"), cwd=tmp)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("usage:", r.stderr)
        self.assertIn(needle, r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def _file(self, tmp, name, data):
        p = os.path.join(tmp, name)
        Path(p).write_bytes(data)
        return p

    def test_empty_inputs_are_usage_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._usage_error("analyze_schematic.py", self._file(tmp, "e.kicad_sch", b""), "file is empty")
            self._usage_error("analyze_schematic.py", self._file(tmp, "e.sch", b""), "file is empty")
            self._usage_error("analyze_pcb.py", self._file(tmp, "e.kicad_pcb", b""), "file is empty")

    def test_whitespace_only_input_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._usage_error("analyze_schematic.py", self._file(tmp, "w.kicad_sch", b" \r\n\t\n"),
                              "file is empty")

    def test_kicad5_pro_resolves_to_the_sibling_schematic(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "board.pro").write_text("update=0\n", encoding="utf-8")
            Path(tmp, "board.kicad_sch").write_bytes((FX / "simple.kicad_sch").read_bytes())
            out = os.path.join(tmp, "out.json")
            r = _run("analyze_schematic.py", os.path.join(tmp, "board.pro"), "-o", out, cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Resolved from board.pro", r.stderr)
            with open(out, encoding="utf-8") as f:
                self.assertGreater(len(json.load(f)["components"]), 0)

    def test_kicad5_pro_without_a_sibling_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            pro = self._file(tmp, "lonely.pro", b"update=0\n")
            self._usage_error("analyze_schematic.py", pro, "lonely.sch")
            self._usage_error("analyze_pcb.py", pro, "lonely.kicad_pcb")


if __name__ == "__main__":
    unittest.main()
