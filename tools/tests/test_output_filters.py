"""Audience summaries and the manager text view ignore suppressed findings
and keep readiness for stages outside the active filter."""
import sys, unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import output_filters as of  # noqa: E402


def _f(rule_id, severity, **kw):
    return {"rule_id": rule_id, "severity": severity, "category": "c",
            "summary": rule_id, **kw}


class AudienceSummarySuppressionTest(unittest.TestCase):
    def test_suppressed_error_is_not_a_blocker(self):
        s = of.build_audience_summary([
            _f("A-1", "error", suppressed=True, stages=["schematic"]),
            _f("A-2", "warning", stages=["schematic"])])
        m = s["manager"]
        self.assertEqual(m["blocker_count"], 0)
        self.assertEqual(m["warning_count"], 1)
        self.assertEqual(m["stage_readiness"]["schematic"], "needs_review")
        self.assertEqual(m["risk_level"], "low")
        self.assertEqual(s["designer"]["total_findings"], 1)
        self.assertEqual(s["designer"]["by_severity"]["error"], 0)
        self.assertEqual([i["rule_id"] for i in s["designer"]["top_issues"]], ["A-2"])

    def test_unsuppressed_input_is_unchanged(self):
        fs = [_f("A-1", "error"), _f("A-2", "warning"), _f("A-3", "info")]
        s = of.build_audience_summary(fs)
        self.assertEqual(s["designer"]["total_findings"], 3)
        self.assertEqual([i["rule_id"] for i in s["designer"]["top_issues"]],
                         ["A-1", "A-2"])
        self.assertEqual(s["manager"]["blocker_count"], 1)


class ManagerTextTest(unittest.TestCase):
    def test_other_stage_blocker_shows_work(self):
        fs = [_f("X-1", "error", stages=["layout"])]
        of.apply_stage_filter(fs, "schematic")
        text = of.format_text(fs, "manager", "schematic")
        self.assertIn("  layout       WORK", text)
        self.assertNotIn("X-1", text)

    def test_no_stage_unchanged(self):
        fs = [_f("X-1", "error", stages=["layout"]), _f("X-2", "warning")]
        text = of.format_text(fs, "manager")
        self.assertIn("  layout       WORK", text)
        self.assertIn("- X-1: X-1", text)

    def test_suppressed_blocker_not_listed(self):
        fs = [_f("X-1", "error", suppressed=True), _f("X-2", "warning")]
        text = of.format_text(fs, "manager")
        self.assertNotIn("X-1", text)
        self.assertIn("Blockers:      0", text)
