"""export_issues names severities the way the analyzers do: error / warning / info."""
import contextlib, io, json, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    import export_issues
finally:
    sys.path.pop(0)


def _finding(severity):
    return {"rule_id": "X-1", "severity": severity, "summary": "s"}


class SeverityVocabulary(unittest.TestCase):
    def test_error_findings_are_labelled_error(self):
        labels = export_issues.issue_labels(_finding("error"), [])
        self.assertIn("severity:error", labels)
        self.assertNotIn("severity:high", labels)
        body = export_issues.format_issue_body(_finding("error"))
        self.assertIn("| **Severity** | error |", body)

    def test_legacy_names_are_labelled_error(self):
        for name in ("critical", "high"):
            self.assertIn("severity:error", export_issues.issue_labels(_finding(name), []))

    def test_warning_and_info_keep_their_labels(self):
        self.assertIn("severity:warning", export_issues.issue_labels(_finding("warning"), []))
        self.assertIn("severity:info", export_issues.issue_labels(_finding("info"), []))

    def test_legacy_names_accepted_on_input(self):
        findings = [{"severity": "critical"}, {"severity": "medium"}, {"severity": "low"}]
        self.assertEqual(export_issues.filter_findings(findings, "high", None), findings[:1])
        self.assertEqual(export_issues.filter_findings(findings, "warning", None), findings[:2])
        self.assertEqual(export_issues.filter_findings(findings, "error", None), findings[:1])

    def test_dry_run_json_says_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "a.json"
            data.write_text(json.dumps({"findings": [_finding("error")]}), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                rc = export_issues.main([str(data), "--repo", "o/r", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.getvalue())["issues"][0]["severity"], "error")


if __name__ == "__main__":
    unittest.main()
