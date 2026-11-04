"""The four consumers read analysis/merged/<run>/<file> only while it equals the raw file once its
llm_* fields are stripped, and never with --only-deterministic."""
import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(os.environ.get("KH_PRODUCT") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import analysis_cache, diff_analysis, lifecycle_audit, summarize_findings, what_if  # noqa: E402

DOC = {"analyzer_type": "schematic", "findings": [], "assessments": [], "bom": [], "components": []}


def _run(main, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = main(argv)
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue() + err.getvalue()


RAW = dict(DOC, findings=[{"rule_id": "R-1", "severity": "warning", "summary": "raw"}])


class OverlaySelection(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.adir = Path(td.name) / "analysis"
        self.raw = self.adir / "r1" / "schematic.json"
        self.merged = self.adir / "merged" / "r1" / "schematic.json"
        self.raw.parent.mkdir(parents=True)
        self.merged.parent.mkdir(parents=True)
        self.raw.write_text(json.dumps(RAW), encoding="utf-8")
        (self.adir / "manifest.json").write_text(json.dumps(
            {"version": 1, "current": "r1", "runs": {"r1": {}}}), encoding="utf-8")

    def test_matching_overlay_is_read(self):
        self.merged.write_text(json.dumps(dict(RAW, findings=[dict(
            RAW["findings"][0], llm_review={"verdict": "confirmed"})])), encoding="utf-8")
        self.assertEqual(analysis_cache.reviewed_overlay(str(self.raw)), str(self.merged))
        rc, text = _run(summarize_findings.main, [str(self.adir), "--json"])
        self.assertEqual(rc, 0)
        self.assertNotIn("Note:", text)

    def test_missing_overlay_is_silent(self):
        self.assertIsNone(analysis_cache.reviewed_overlay(str(self.raw)))

    def test_stale_overlay_falls_back_to_raw(self):
        self.merged.write_text(json.dumps(dict(DOC, findings=[
            {"rule_id": "M-1", "severity": "warning", "summary": "merged"}])), encoding="utf-8")
        rc, text = _run(summarize_findings.main, [str(self.adir), "--json"])
        self.assertEqual(rc, 0)
        self.assertIn("R-1", text)
        self.assertNotIn("M-1", text)
        self.assertIn("Note:", text)

    def test_missing_raw_file_is_named_not_called_a_mismatch(self):
        self.merged.write_text(json.dumps(RAW), encoding="utf-8")
        self.raw.unlink()
        rc, text = _run(lambda a: analysis_cache.reviewed_overlay(a[0]), [str(self.raw)])
        self.assertIsNone(rc)
        self.assertIn("cannot read", text)
        self.assertNotIn("does not match", text)

    def test_directory_overlay_falls_back_to_raw(self):
        self.merged.mkdir()
        self.assertIsNone(analysis_cache.reviewed_overlay(str(self.raw)))

    def test_diff_what_if_lifecycle_ignore_a_broken_overlay(self):
        self.merged.write_text("{not json", encoding="utf-8")
        rc, text = _run(diff_analysis.main, [str(self.raw), str(self.raw)])
        self.assertNotIn("Error reading", text)
        rc, text = _run(what_if.main, [str(self.raw), "--suggest-fixes"])
        self.assertNotIn("Error reading", text)
        rc, text = _run(lifecycle_audit.main, [str(self.raw)])
        self.assertNotIn(f"input {self.merged}", text)

    def test_only_deterministic_never_reads_the_overlay(self):
        self.merged.write_text("{not json", encoding="utf-8")
        for main, argv in ((diff_analysis.main, [str(self.raw), str(self.raw)]),
                           (what_if.main, [str(self.raw), "--suggest-fixes"])):
            rc, text = _run(main, argv + ["--only-deterministic"])
            self.assertNotIn("Error reading", text)
            self.assertNotIn("Note:", text)
        rc, text = _run(summarize_findings.main, [str(self.adir), "--json", "--only-deterministic"])
        self.assertNotIn("Note:", text)


if __name__ == "__main__":
    unittest.main()
