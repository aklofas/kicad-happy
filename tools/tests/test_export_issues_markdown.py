"""Analyzer text in an exported issue body cannot add headings, links or table cells, or end a code span."""
import re, sys, unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import export_issues  # noqa: E402


class IssueBodyMarkdownTest(unittest.TestCase):
    def test_body_cells_and_code_spans_stay_intact(self):
        body = export_issues.format_issue_body({
            "rule_id": "X-1", "summary": "a\n## Forged", "confidence": "hi|gh",
            "components": [{"ref": "R`1", "value": "[l](u)"}]})
        self.assertNotIn("\n## Forged", body)
        row = next(line for line in body.splitlines() if line.startswith("| **Confidence** |"))
        self.assertEqual(len(re.findall(r"(?<!\\)\|", row)), 3)
        self.assertEqual(row.count("\\|"), 1)
        self.assertIn("`R1`", body)
        self.assertNotIn("[l](u)", body)

    def test_raw_html_link_in_summary_is_inert(self):
        body = export_issues.format_issue_body({
            "rule_id": "X-1", "summary": 'Value <a href="https://evil.example">click</a>',
            "components": [{"ref": "R1", "value": "<b>10k</b>"}]})
        self.assertNotIn("<a ", body)
        self.assertNotIn("<b>", body)
        self.assertIn('&lt;a href="https://evil.example">click&lt;/a>', body)

    def test_ordinary_title_and_text_are_unchanged(self):
        finding = {"rule_id": "PU-001", "summary": "R4.7k pull-up on SDA_NET", "components": ["R1"]}
        self.assertEqual(export_issues.format_issue_title(finding), "[PU-001] R4.7k pull-up on SDA_NET (R1)")
        self.assertIn("R4.7k pull-up on SDA_NET", export_issues.format_issue_body(finding))


if __name__ == "__main__":
    unittest.main()
