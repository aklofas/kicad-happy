"""A JSON input nested deeper than Python can parse is malformed input: the CLIs give it the
error and exit code a syntactically broken file gets, never a traceback."""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from tools.tests._fixtures import fixture_path, have

ROOT = Path(__file__).resolve().parents[2]
K = ROOT / "skills" / "kicad" / "scripts"
FX = fixture_path("simple-project")
sys.path.insert(0, str(K))
sys.path.insert(0, str(ROOT / "skills" / "datasheets" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "datasheets"))

DEEP = "[" * 100000


def _run(args):
    with tempfile.TemporaryDirectory() as cwd:
        return _run_in(args, cwd)


def _run_in(args, cwd):
    env = {k: v for k, v in os.environ.items() if not k.endswith(("_API_KEY", "_CLIENT_SECRET"))}
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True,
                          timeout=120, env=env, cwd=cwd)


class CliDeepJsonTest(unittest.TestCase):
    def _cases(self, tmp, X):
        o = os.path.join(tmp, "o")
        rd = os.path.join(tmp, "run-" + os.path.basename(X))
        os.makedirs(rd, exist_ok=True)
        Path(rd, "schematic.json").write_text(Path(X).read_text(encoding="utf-8"), encoding="utf-8")
        return {
            "fab_release_gate": [K / "fab_release_gate.py", "-s", X, "-p", X],
            "analyze_emc": [ROOT / "skills/emc/scripts/analyze_emc.py", "--schematic", X],
            "cross_analysis": [K / "cross_analysis.py", "--schematic", X, "--pcb", X],
            "analyze_thermal": [K / "analyze_thermal.py", "--schematic", X, "--pcb", X],
            "lifecycle_audit": [K / "lifecycle_audit.py", X],
            "format_report": [ROOT / "action/format-report.py", "--schematic", X, "--output", o + ".md"],
            "diff_analysis": [K / "diff_analysis.py", X, X],
            "what_if": [K / "what_if.py", X, "R1=1k"],
            "simulate_subcircuits": [ROOT / "skills/spice/scripts/simulate_subcircuits.py", X],
            "extract_parasitics": [ROOT / "skills/spice/scripts/extract_parasitics.py", X],
            "check_report_sections": [K / "check_report_sections.py", "--run-dir", rd],
        }

    def test_cli_treats_deep_json_as_malformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            deep = os.path.join(tmp, "deep.json")
            bad = os.path.join(tmp, "bad.json")
            Path(deep).write_text(DEEP, encoding="utf-8")
            Path(bad).write_text("{", encoding="utf-8")
            ref = self._cases(tmp, bad)
            for name, args in self._cases(tmp, deep).items():
                with self.subTest(name):
                    r_deep, r_bad = _run(args), _run(ref[name])
                    self.assertNotIn("Traceback", r_deep.stderr, r_deep.stderr[-400:])
                    self.assertEqual(r_deep.returncode, r_bad.returncode)

    def test_summarize_findings_treats_deep_manifest_as_malformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "manifest.json").write_text(DEEP, encoding="utf-8")
            r = _run([K / "summarize_findings.py", "--analysis-dir", tmp])
            self.assertNotIn("Traceback", r.stderr)

    @unittest.skipUnless(have(FX), "needs fixture")
    def test_analyze_pcb_treats_deep_schematic_json_as_malformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            deep, bad = os.path.join(tmp, "deep.json"), os.path.join(tmp, "bad.json")
            Path(deep).write_text(DEEP, encoding="utf-8")
            Path(bad).write_text("{", encoding="utf-8")
            pcb = FX / "simple.kicad_pcb"
            r_deep = _run([K / "analyze_pcb.py", pcb, "--schematic", deep])
            r_bad = _run([K / "analyze_pcb.py", pcb, "--schematic", bad])
            self.assertNotIn("Traceback", r_deep.stderr)
            self.assertEqual(r_deep.returncode, r_bad.returncode)

    def test_edit_properties_updates_deep_or_malformed_is_one_line_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            sch = Path(tmp, "a.kicad_sch")
            sch.write_text('(kicad_sch (version 20231120) (generator "eeschema"))\n', encoding="utf-8")
            for text in (DEEP, "{"):
                upd = Path(tmp, "u.json")
                upd.write_text(text, encoding="utf-8")
                r = _run([ROOT / "skills/bom/scripts/edit_properties.py", sch, "--updates", upd,
                          "--dry-run"])
                with self.subTest(text[:2]):
                    self.assertNotIn("Traceback", r.stderr, r.stderr[-400:])
                    self.assertEqual(r.returncode, 1)
                    self.assertIn("updates are not valid JSON", r.stderr)

    def test_cross_verify_deep_fails_as_malformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            deep, bad = Path(tmp, "deep.json"), Path(tmp, "bad.json")
            deep.write_text(DEEP, encoding="utf-8")
            bad.write_text("{", encoding="utf-8")
            r_deep = _run([K / "cross_verify.py", "-s", deep, "-p", deep])
            r_bad = _run([K / "cross_verify.py", "-s", bad, "-p", bad])
            self.assertNotIn("RecursionError", r_deep.stderr)
            self.assertIn("JSONDecodeError", r_deep.stderr)
            self.assertEqual(r_deep.returncode, r_bad.returncode)

    def test_validate_sanity_vector_deep_extraction_is_one_line_error(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("needs PyYAML")
        with tempfile.TemporaryDirectory() as tmp:
            vec, deep = Path(tmp, "v.yaml"), Path(tmp, "deep.json")
            vec.write_text("checks: []\n", encoding="utf-8")
            deep.write_text(DEEP, encoding="utf-8")
            r = _run([ROOT / "skills/datasheets/scripts/validate_sanity_vector.py", vec, deep])
            self.assertNotIn("Traceback", r.stderr, r.stderr[-400:])
            self.assertEqual(r.returncode, 1)


class DeepJsonHelpersTest(unittest.TestCase):
    def test_merge_annotations_deep_review_is_malformed_json(self):
        import json
        sys.path.insert(0, str(ROOT / "skills" / "kicad" / "review" / "scripts"))
        import merge_annotations
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp, "raw")
            raw.mkdir()
            review = Path(tmp, "review.json")
            review.write_text(DEEP, encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                merge_annotations.merge(raw, review, Path(tmp, "merged"))
            Path(raw, merge_annotations.ANALYZER_FILES[0]).write_text(DEEP, encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                merge_annotations._load_raw_envelopes(raw)

    def test_load_jsonc_deep_is_value_error(self):
        from kicad_core.project import load_jsonc
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "x.kicad_pro")
            Path(p).write_text(DEEP, encoding="utf-8")
            with self.assertRaises(ValueError):
                load_jsonc(p)

    def test_distributor_input_deep_is_unreadable(self):
        from distributor_core.inputs import get_analyzer_output
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp, "a.json")
            p.write_text(DEEP, encoding="utf-8")
            self.assertIsNone(get_analyzer_output(p))

    def test_merge_results_and_plan_extraction_deep(self):
        import merge_results, plan_extraction
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            name = merge_results.sanitize_mpn("PART")
            (cache / f"{name}.t1.result.json").write_text(DEEP, encoding="utf-8")
            (cache / f"{name}.json").write_text(DEEP, encoding="utf-8")
            res = merge_results._read_result(cache, "PART", "t1")
            self.assertEqual(res["status"], "failed")
            self.assertIsNone(plan_extraction._load_existing_extraction(cache, "PART"))


if __name__ == "__main__":
    unittest.main()
