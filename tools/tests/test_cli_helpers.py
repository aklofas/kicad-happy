# tools/tests/test_cli_helpers.py
"""Pins the shared argparse flag helpers and the main(argv=None) -> int contract of the analyzer CLIs."""
import argparse, inspect, io, os, sys, tempfile, unittest
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
        self.assertEqual(acts["only_deterministic"].help, 'Accepted for consistency; analyzers never write llm_* fields. Honored by downstream consumers (Phase 4 spec §3.4).')

    def test_consumer_only_deterministic_text(self):
        p = argparse.ArgumentParser()
        add_only_deterministic_arg(p, consumer=True)
        self.assertTrue(next(a for a in p._actions if a.dest == "only_deterministic").help.startswith("Read raw analysis/<run>/<analyzer>.json"))

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

if __name__ == "__main__":
    unittest.main()
