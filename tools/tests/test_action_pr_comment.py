"""The Action PR comment renders every diff it is given, one row per added/removed/changed item."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORMATTER = ROOT / "action" / "format-report.py"


def diff_doc(diff, total, added=0, removed=0, modified=0, metrics=(), severity="major", has_changes=True):
    return {"has_changes": has_changes,
            "summary": {"total_changes": total, "added": added, "removed": removed, "modified": modified,
                        "metric_changes": list(metrics), "severity": severity},
            "diff": diff}


def comment(*diffs):
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        args = [sys.executable, str(FORMATTER), "--output", str(d / "pr.md")]
        for i, doc in enumerate(diffs):
            (d / f"diff{i}.json").write_text(json.dumps(doc), encoding="utf-8")
            args += ["--diff", str(d / f"diff{i}.json")]
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr
        return (d / "pr.md").read_text(encoding="utf-8")


class ActionPrComment(unittest.TestCase):
    def test_schematic_and_pcb_diffs_both_reach_the_comment(self):
        sch = diff_doc({"components": {"added": [{"reference": "R9", "value": "10k", "footprint": "R_0402"}]}},
                       1, added=1)
        pcb = diff_doc({"findings": {"new": [{"rule_id": "DFM-001", "severity": "warning",
                                              "summary": "Drill too small", "components": ["J1"]}]}},
                       1, added=1)
        md = comment(sch, pcb)
        self.assertIn("> 2 changes: +2 added, -0 removed, ~0 modified (major)", md)
        self.assertIn("| + R9 | New: 10k R_0402 |", md)
        self.assertIn("| NEW warning | DFM-001: Drill too small |", md)

    def test_added_and_removed_detections_get_rows(self):
        va = {"rule_id": "VD-001", "severity": "error", "components": ["C11"], "summary": "Divider out of range"}
        vr = {"rule_id": "VD-001", "severity": "warning", "components": ["C14"], "summary": "Divider drift"}
        doc = diff_doc({"signal_analysis": {"validation_findings": {"added": [va], "removed": [vr],
                                                                   "modified": []}}}, 2, added=1, removed=1)
        md = comment(doc)
        self.assertIn("| + Validation Findings | VD-001 error C11: Divider out of range |", md)
        self.assertIn("| - Validation Findings | VD-001 warning C14: Divider drift |", md)

    def test_identity_with_pipe_stays_in_one_cell(self):
        mod = {"identity": "PU-001/R1|R2", "changes": [{"field": "severity", "base": "warning", "head": "error"}]}
        doc = diff_doc({"signal_analysis": {"validation_findings": {"added": [], "removed": [],
                                                                   "modified": [mod]}}}, 1, modified=1)
        md = comment(doc)
        self.assertIn("| ~ Validation Findings PU-001/R1\\|R2 | severity: warning → error |", md)

    def test_empty_diff_has_no_table(self):
        md = comment(diff_doc({}, 0, severity="none", has_changes=False))
        self.assertNotIn("Changes from Base", md)
        self.assertNotIn("| Change |", md)

    def test_metric_only_diff_names_the_metrics(self):
        doc = diff_doc({"statistics": {"total_nets": {"base": 10, "head": 12, "delta": 2}}}, 0,
                       metrics=["total_nets"])
        md = comment(doc)
        self.assertIn("### Changes from Base", md)
        self.assertNotIn("0 changes", md)
        self.assertNotIn("| Change |", md)
        self.assertIn("Metric changes: total_nets", md)

    def test_more_footer_counts_unprinted_items_only(self):
        comp = {"reference": "R1", "changes": [{"field": "value", "base": "1k", "head": "2k"},
                                               {"field": "footprint", "base": "a", "head": "b"},
                                               {"field": "mpn", "base": "x", "head": "y"}]}
        bom = {"added": [{"line": i} for i in range(12)]}
        doc = diff_doc({"components": {"modified": [comp]}, "bom": bom}, 13, added=12, modified=1)
        md = comment(doc)
        self.assertEqual(md.count("| ~ R1 "), 3)  # three rows for one item
        self.assertIn("*...and 12 more*", md)
        one = diff_doc({"components": {"modified": [comp]}}, 1, modified=1)
        self.assertNotIn("more*", comment(one))

    def test_entrypoint_passes_every_diff_and_no_dead_entries(self):
        sh = (ROOT / "action" / "entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn("for dtype in schematic pcb; do", sh)
        self.assertNotIn("schematic pcb emc spice", sh)
        self.assertIn('ARGS+=(--diff "$_diff")', sh)


if __name__ == "__main__":
    unittest.main()
