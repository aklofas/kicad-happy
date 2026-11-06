"""Audience summaries and the manager text view ignore suppressed findings
and keep readiness for stages outside the active filter."""
import ast, sys, unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
EMC_SCRIPTS = SCRIPTS.parents[1] / "emc" / "scripts"
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


def _emc_rule_ids():
    """Every rule_id literal passed to an EMC finding constructor."""
    ids = set()
    for path in EMC_SCRIPTS.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in ("_make_finding", "make_finding"):
                continue
            arg = next((k.value for k in node.keywords if k.arg == "rule_id"), None)
            if arg is None and name == "_make_finding" and len(node.args) >= 3:
                arg = node.args[2]
            if arg is not None:
                ids |= {c.value for c in ast.walk(arg)
                        if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    return ids


class EmcStageMapTest(unittest.TestCase):
    def test_every_emc_rule_has_a_stage_row(self):
        ids = _emc_rule_ids()
        self.assertGreater(len(ids), 40)
        unmapped = sorted(r for r in ids
                          if not any(r.startswith(p) for ps in of._STAGE_RULES.values() for p in ps))
        self.assertEqual(unmapped, [])

    def test_emc_board_families_are_layout(self):
        fs = [_f(r, "warning") for r in ("SU-001", "SU-003", "PD-001", "PD-004", "EE-001", "EE-002")]
        of.assign_stages(fs)
        self.assertEqual([f["stages"] for f in fs], [["layout"]] * len(fs))

    def test_schematic_pd_detector_unchanged(self):
        fs = [_f("PD-DET", "info")]
        of.assign_stages(fs)
        self.assertEqual(fs[0]["stages"], ["schematic"])

    def test_layout_stage_keeps_stackup_error(self):
        result = {"findings": [_f("SU-001", "error"), _f("PU-001", "info")]}
        of.apply_output_filters(result, "layout")
        self.assertTrue(result["findings"][0]["in_active_stage"])
        self.assertEqual(result["stage_filter"]["included_count"], 1)
        readiness = result["audience_summary"]["manager"]["stage_readiness"]
        self.assertEqual(readiness["layout"], "needs_work")
        self.assertEqual(readiness["schematic"], "pass")
