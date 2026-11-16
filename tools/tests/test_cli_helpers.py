# tools/tests/test_cli_helpers.py
"""Pins the shared argparse flag helpers and the main(argv=None) -> int contract of the analyzer CLIs."""
import argparse, glob, inspect, io, json, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tools.tests._fixtures import fixture_path, have
SKILLS = Path(__file__).resolve().parents[2] / "skills"
for _d in ("kicad", "emc", "spice"):
    sys.path.insert(0, str(SKILLS / _d / "scripts"))
FX = fixture_path()

from kicad_core.cli import (add_compact_arg, add_config_arg, add_only_deterministic_arg,  # noqa: E402
                            add_output_arg, add_schema_arg, add_stage_audience_args, add_text_arg)
import analyze_schematic, analyze_pcb, analyze_gerbers, analyze_thermal, cross_analysis  # noqa: E402
import diff_analysis, what_if, lifecycle_audit, summarize_findings  # noqa: E402
import analyze_emc, simulate_subcircuits, extract_parasitics  # noqa: E402


class CliHelperTests(unittest.TestCase):
    def test_helpers_declare_identical_actions(self):
        p = argparse.ArgumentParser()
        add_stage_audience_args(p)
        add_only_deterministic_arg(p)
        add_schema_arg(p)
        add_output_arg(p)
        add_compact_arg(p)
        add_text_arg(p, help="Print human-readable text report to stdout")
        add_config_arg(p)
        acts = {a.dest: a for a in p._actions}
        self.assertEqual(acts["stage"].choices, ['schematic', 'layout', 'pre_fab', 'bring_up'])
        self.assertEqual(acts["audience"].help, 'Audience level for summaries and --text output')
        self.assertEqual(acts["output"].option_strings, ["--output", "-o"])
        self.assertEqual(acts["only_deterministic"].help, 'Accepted for consistency; analyzers never write llm_* fields. Honored by downstream consumers.')

    def test_consumer_only_deterministic_text(self):
        p = argparse.ArgumentParser()
        add_only_deterministic_arg(p, consumer=True)
        self.assertTrue(next(a for a in p._actions if a.dest == "only_deterministic").help.startswith("Read raw analysis/<run>/<analyzer>.json"))

    def test_derived_analysis_dir_help_names_the_run_file(self):
        for mod, name in ((analyze_gerbers, "gerber.json"), (analyze_thermal, "thermal.json")):
            out = io.StringIO()
            with redirect_stdout(out), self.assertRaises(SystemExit):
                mod.main(["--help"])
            text = " ".join(out.getvalue().split())
            self.assertIn(f"Write {name} into the current run", text, mod.__name__)
            self.assertNotIn("gerbers.json", text)

    def test_every_cli_main_takes_argv_and_returns_int(self):
        for mod in (analyze_schematic, analyze_pcb, analyze_gerbers, analyze_thermal, cross_analysis, diff_analysis, what_if, lifecycle_audit, summarize_findings, analyze_emc, simulate_subcircuits, extract_parasitics):
            sig = inspect.signature(mod.main)
            self.assertEqual(list(sig.parameters), ["argv"], mod.__name__)
            # "int" where the module has `from __future__ import annotations` (cross_analysis, summarize_findings)
            self.assertIn(sig.return_annotation, (int, "int"), mod.__name__)

    @unittest.skipUnless(have(FX), "frozen fixtures absent")
    def test_main_returns_exit_codes_in_process(self):
        # main() resolves ./analysis as its capability-mode dir; keep that write out of the tree.
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(analyze_schematic.main([str(FX / "determinism" / "usb_dual_esd.kicad_sch"), "--text"]), 0)
                    with self.assertRaises(SystemExit) as cm:
                        analyze_schematic.main(["--no-such-flag"])
                    self.assertEqual(cm.exception.code, 2)
            finally:
                os.chdir(cwd)


SIMPLE = fixture_path("simple-project")


@unittest.skipUnless(have(SIMPLE), "frozen fixtures absent")
class TextWithOutputTest(unittest.TestCase):
    """--text prints the report on stdout; a JSON destination given with it is still written."""

    @classmethod
    def setUpClass(cls):
        cls._cwd = os.getcwd()
        cls._tmp = tempfile.TemporaryDirectory()
        os.chdir(cls._tmp.name)   # main() writes ./analysis/capability_mode.json
        cls.sch, cls.pcb = os.path.join(cls._tmp.name, "sch.json"), os.path.join(cls._tmp.name, "pcb.json")
        with redirect_stderr(io.StringIO()):
            assert analyze_schematic.main([str(SIMPLE / "simple.kicad_sch"), "-o", cls.sch]) == 0
            assert analyze_pcb.main([str(SIMPLE / "simple.kicad_pcb"), "-o", cls.pcb]) == 0
        chain = ["--schematic", cls.sch, "--pcb", cls.pcb]
        cls.cases = {
            "schematic": (analyze_schematic.main, [str(SIMPLE / "simple.kicad_sch")]),
            "pcb": (analyze_pcb.main, [str(SIMPLE / "simple.kicad_pcb")]),
            "cross": (cross_analysis.main, chain),
            "emc": (analyze_emc.main, chain),
            "thermal": (analyze_thermal.main, chain),
            "gerbers": (analyze_gerbers.main, [str(SIMPLE / "gerbers")]),
        }

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._cwd)
        cls._tmp.cleanup()

    def _main(self, main, argv):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            self.assertEqual(main(argv), 0)
        return out.getvalue()

    def _expected_text(self, name, result):
        from output_filters import format_text
        if name in ("emc", "thermal"):
            mod = analyze_emc if name == "emc" else analyze_thermal
            return mod.format_text_report(result) + "\n"
        return format_text(result["findings"], "designer", None) + "\n"

    def test_text_with_output_writes_both(self):
        for name, (main, argv) in self.cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                out = os.path.join(d, "out.json")
                text = self._main(main, argv + ["--text", "-o", out])
                with open(out, encoding="utf-8") as f:
                    result = json.load(f)
                self.assertIn("findings", result)
                self.assertTrue(text.strip())
                self.assertEqual(text, self._expected_text(name, result))

    def test_text_with_analysis_dir_writes_both(self):
        for name, (main, argv) in self.cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                if name in ("cross", "thermal", "gerbers"):   # these write into the current run
                    self.assertEqual(self._main(analyze_schematic.main,
                                                [str(SIMPLE / "simple.kicad_sch"), "--analysis-dir", d]), "")
                text = self._main(main, argv + ["--text", "--analysis-dir", d])
                canonical = {"schematic": "schematic.json", "pcb": "pcb.json", "cross": "cross_analysis.json",
                             "emc": "emc.json", "thermal": "thermal.json", "gerbers": "gerber.json"}[name]
                written = glob.glob(os.path.join(d, "*", canonical))
                self.assertEqual(len(written), 1, os.listdir(d))
                with open(written[0], encoding="utf-8") as f:
                    result = json.load(f)
                self.assertEqual(text, self._expected_text(name, result))

    def test_text_alone_and_output_alone_are_unchanged(self):
        for name, (main, argv) in self.cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                os.chdir(d)
                try:
                    text = self._main(main, argv + ["--text"])
                    files = sorted(os.path.relpath(os.path.join(r, f), d)
                                   for r, _, fs in os.walk(d) for f in fs)
                    out = os.path.join(d, "out.json")
                    self.assertEqual(self._main(main, argv + ["-o", out]), "")
                finally:
                    os.chdir(self._tmp.name)
                self.assertEqual(files, [os.path.join("analysis", "capability_mode.json")])
                with open(out, encoding="utf-8") as f:
                    self.assertEqual(text, self._expected_text(name, json.load(f)))

    @unittest.skipIf(os.name == "nt", "no /dev/stdout")
    def test_text_with_output_to_dev_stdout_prints_text_then_json(self):
        scripts = {"schematic": (SKILLS / "kicad" / "scripts" / "analyze_schematic.py",
                                 [str(SIMPLE / "simple.kicad_sch")]),
                   "emc": (SKILLS / "emc" / "scripts" / "analyze_emc.py",
                           ["--schematic", self.sch, "--pcb", self.pcb])}
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        for name, (script, argv) in scripts.items():
            cmd = [sys.executable, str(script), *argv, "--text", "-o", "/dev/stdout"]
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                piped = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                       cwd=d, env=env, timeout=120)
                self.assertEqual(piped.returncode, 0, piped.stderr[-2000:])
                redirected = os.path.join(d, "stdout.txt")
                with open(redirected, "w", encoding="utf-8") as f:
                    r = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True,
                                       encoding="utf-8", cwd=d, env=env, timeout=120)
                self.assertEqual(r.returncode, 0, r.stderr[-2000:])
                with open(redirected, encoding="utf-8") as f:
                    from_file = f.read()
            for stdout in (piped.stdout, from_file):
                cut = stdout.index("\n{")
                text, result = stdout[:cut + 1], json.loads(stdout[cut + 1:])
                self.assertEqual(text, self._expected_text(name, result))


if __name__ == "__main__":
    unittest.main()
