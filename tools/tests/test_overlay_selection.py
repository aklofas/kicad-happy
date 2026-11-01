"""The four consumers read analysis/merged/<run>/<file> when it exists and analysis/<run>/<file>
with --only-deterministic. The merged copy here is not JSON, so reading it is visible as the
consumer's read error, and skipping it as getting past the read."""
import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(os.environ.get("KH_PRODUCT") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import diff_analysis, lifecycle_audit, summarize_findings, what_if  # noqa: E402

DOC = {"analyzer_type": "schematic", "findings": [], "assessments": [], "bom": [], "components": []}


def _run(main, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = main(argv)
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue() + err.getvalue()


class OverlaySelection(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.adir = Path(td.name) / "analysis"
        self.raw = self.adir / "r1" / "schematic.json"
        self.merged = self.adir / "merged" / "r1" / "schematic.json"
        self.raw.parent.mkdir(parents=True)
        self.merged.parent.mkdir(parents=True)
        self.raw.write_text(json.dumps(DOC), encoding="utf-8")
        self.merged.write_text("{not json", encoding="utf-8")
        (self.adir / "manifest.json").write_text(json.dumps(
            {"version": 1, "current": "r1", "runs": {"r1": {}}}), encoding="utf-8")

    def test_diff(self):
        rc, text = _run(diff_analysis.main, [str(self.raw), str(self.raw)])
        self.assertEqual(rc, 1)
        self.assertIn(f"Error reading base file {self.raw}", text)
        rc, text = _run(diff_analysis.main, [str(self.raw), str(self.raw), "--only-deterministic"])
        self.assertNotIn("Error reading", text)

    def test_what_if(self):
        rc, text = _run(what_if.main, [str(self.raw), "--suggest-fixes"])
        self.assertEqual(rc, 1)
        self.assertIn(f"Error reading {self.raw}", text)
        rc, text = _run(what_if.main, [str(self.raw), "--suggest-fixes", "--only-deterministic"])
        self.assertNotIn("Error reading", text)

    def test_lifecycle(self):
        rc, text = _run(lifecycle_audit.main, [str(self.raw)])
        self.assertEqual(rc, 2)
        self.assertIn(f"input {self.merged}: not JSON", text)
        self.merged.unlink()
        self.merged.mkdir()  # a directory there is taken as the overlay too (exists, not is_file)
        rc, text = _run(lifecycle_audit.main, [str(self.raw)])
        self.assertIn(f"input {self.merged}: is a directory", text)

    def test_summarize(self):
        self.merged.write_text(json.dumps(dict(DOC, findings=[
            {"rule_id": "M-1", "severity": "warning", "summary": "merged"}])), encoding="utf-8")
        rc, text = _run(summarize_findings.main, [str(self.adir), "--json"])
        self.assertEqual(rc, 0)
        self.assertIn("M-1", text)
        rc, text = _run(summarize_findings.main, [str(self.adir), "--json", "--only-deterministic"])
        self.assertNotIn("M-1", text)
        self.merged.unlink()
        self.merged.mkdir()  # summarize takes only a file as the overlay
        self.raw.write_text(json.dumps(dict(DOC, findings=[
            {"rule_id": "R-1", "severity": "warning", "summary": "raw"}])), encoding="utf-8")
        rc, text = _run(summarize_findings.main, [str(self.adir), "--json"])
        self.assertEqual(rc, 0)
        self.assertIn("R-1", text)


if __name__ == "__main__":
    unittest.main()
