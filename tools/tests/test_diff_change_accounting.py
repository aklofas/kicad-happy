"""diff change accounting: every non-empty section is a change, routing changes are major,
an EMC risk-score fall is the regression, totals count listed items and scalar paths are
listed in summary.metric_changes, and --text -o writes UTF-8 whatever the locale."""
import copy, io, json, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_report_sections  # noqa: E402
import diff_analysis  # noqa: E402
import diff_engine  # noqa: E402
from finding_schema import assign_finding_ids  # noqa: E402


def _f(detector, rule_id, components, nets, summary, severity, **extra):
    """One finding with the producer's field names (`--schema`)."""
    f = {"detector": detector, "rule_id": rule_id, "category": extra.pop("category", "test"),
         "severity": severity, "confidence": "heuristic", "evidence_source": "topology",
         "summary": summary, "description": summary, "components": list(components),
         "nets": list(nets), "pins": [], "recommendation": "", "detection_id": None}
    f.update(extra)
    return f


def _doc(findings, source, **extra):
    findings = copy.deepcopy(findings)
    for f in findings:
        f.pop("finding_id", None)
    assign_finding_ids(findings, source)
    doc = {"analyzer_type": source, "findings": findings}
    doc.update(extra)
    return doc


def _pcb(routing_complete, unrouted, tracks=10, findings=()):
    return _doc(list(findings), "pcb",
                statistics={"footprint_count": 3, "track_segments": tracks},
                connectivity={"routing_complete": routing_complete, "unrouted_count": unrouted},
                footprints=[{"reference": "R1", "value": "10k", "footprint": "R_0603", "layer": "F.Cu"}],
                tracks={})


def _run(base, head, *extra):
    """diff_analysis CLI on two documents; returns parsed JSON (or text)."""
    with tempfile.TemporaryDirectory() as t:
        paths = []
        for name, doc in (("base.json", base), ("head.json", head)):
            p = os.path.join(t, name)
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
            paths.append(p)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = diff_analysis.main(paths + list(extra) + ["--only-deterministic"])
        assert rc == 0, rc
        out = buf.getvalue()
        return out if "--text" in extra else json.loads(out)


def _dc001(caps, sev, summary):
    return _f("check_decoupling", "DC-001", ["U3"] + caps, [], summary, sev, category="decoupling")


def _emc(findings, score, by_sev):
    return _doc(findings, "emc", summary={"emc_risk_score": score, "by_severity": by_sev})


class RoutingAndStatistics(unittest.TestCase):
    def test_routing_only_change_is_a_major_change(self):
        # one net left unrouted, nothing else moved
        out = _run(_pcb(True, 0), _pcb(False, 1))
        self.assertTrue(out["has_changes"])
        self.assertEqual(out["summary"]["severity"], "major")
        self.assertEqual(out["summary"]["total_changes"], 0)
        self.assertEqual(out["summary"]["metric_changes"],
                         ["connectivity.routing_complete", "connectivity.unrouted_count"])
        self.assertEqual(diff_engine.classify_severity("pcb", out["diff"]), "major")

    def test_statistics_only_change(self):
        out = _run(_pcb(True, 0, tracks=10), _pcb(True, 0, tracks=12))
        self.assertTrue(out["has_changes"])
        self.assertEqual(out["summary"]["total_changes"], 0)
        self.assertEqual(out["summary"]["metric_changes"], ["statistics.track_segments"])
        self.assertEqual(out["summary"]["severity"], "minor")

    def test_routing_text_is_printed_and_findings_are_labelled_by_source(self):
        rt = _f("analyze_connectivity", "RT-001", [], ["/SDA"], "Net /SDA is not fully routed", "warning")
        text = _run(_pcb(True, 0), _pcb(False, 1, findings=[rt]), "--text")
        self.assertNotIn("No changes detected", text)
        self.assertIn("Routing complete: True → False", text)
        self.assertIn("Unrouted nets: 0 → 1", text)
        self.assertIn("PCB Findings:", text)
        self.assertNotIn("EMC Findings:", text)
        # one change, one line printed: nothing is left over
        self.assertNotIn("more changes", text)

    def test_assessments_holding_only_unchanged_count_are_no_change(self):
        diff = {"assessments": {"added": [], "removed": [], "unchanged_count": 3}}
        self.assertFalse(diff_engine.has_changes(diff))
        self.assertEqual(diff_engine.classify_severity("thermal", diff), "none")


class EmcScore(unittest.TestCase):
    # stm32 REV1.0 -> 1.1 (survey oracle): DC-001 U4 resolved, DC-001 U3 error -> warning,
    # risk score 74.5 -> 86.5 (0 = worst, 100 = lowest risk).
    BASE = [_dc001(["C19", "C14"], "error", "Decoupling cap too far from U3"),
            _f("check_decoupling", "DC-001", ["U4", "C20"], [], "Decoupling cap far from U4", "warning",
               category="decoupling")]
    HEAD = [_dc001(["C13", "C18"], "warning", "Decoupling cap moderately far from U3")]

    def test_stm32_pair_counts_and_score_rise_is_an_improvement(self):
        out = _run(_emc(self.BASE, 74.5, {"error": 1, "warning": 1, "info": 0}),
                   _emc(self.HEAD, 86.5, {"error": 0, "warning": 1, "info": 0}))
        s = out["summary"]
        self.assertEqual((s["added"], s["removed"], s["modified"]), (0, 1, 1))
        self.assertEqual(s["metric_changes"], ["summary.by_severity.error", "summary.emc_risk_score"])
        self.assertNotIn("regressions", out)

    def test_score_fall_is_the_regression(self):
        regs = diff_engine.classify_regressions("emc", {"risk_score": {"base": 86.5, "head": 74.5, "delta": -12.0}})
        self.assertEqual([(r["category"], r["severity"]) for r in regs], [("emc_risk", "major")])
        self.assertEqual(diff_engine.classify_regressions(
            "emc", {"risk_score": {"base": 74.5, "head": 86.5, "delta": 12.0}}), [])

    def test_score_only_change_is_minor(self):
        out = _run(_emc([], 74.5, {"error": 0}), _emc([], 86.5, {"error": 0}))
        self.assertTrue(out["has_changes"])
        self.assertEqual(out["summary"]["severity"], "minor")
        self.assertEqual((out["summary"]["total_changes"], out["summary"]["metric_changes"]),
                         (0, ["summary.emc_risk_score"]))


class ListedItems(unittest.TestCase):
    def test_bom_and_erc_lines_are_counted_once_each(self):
        base = _doc([], "schematic", components=[], bom=[{"value": "10k", "footprint": "R_0603", "quantity": 2}],
                    statistics={"total_components": 2},
                    design_analysis={"erc_warnings": [{"type": "no_driver", "net": "EN", "message": "EN has no driver"}]})
        head = _doc([], "schematic", components=[], bom=[{"value": "10k", "footprint": "R_0603", "quantity": 3}],
                    statistics={"total_components": 3}, design_analysis={"erc_warnings": []})
        out = _run(base, head)
        s = out["summary"]
        # one BOM quantity change + one resolved ERC warning; the component count is a metric
        self.assertEqual((s["total_changes"], s["added"], s["removed"], s["modified"]), (2, 0, 1, 1))
        self.assertEqual(s["metric_changes"], ["statistics.total_components"])
        self.assertEqual(s["severity"], "minor")


class FalseOutput(unittest.TestCase):
    def test_self_diff_reports_nothing(self):
        doc = _emc(EmcScore.BASE, 74.5, {"error": 1, "warning": 1, "info": 0})
        out = _run(doc, copy.deepcopy(doc))
        self.assertFalse(out["has_changes"])
        self.assertEqual((out["summary"]["total_changes"], out["summary"]["metric_changes"]), (0, []))
        self.assertEqual(out["summary"]["severity"], "none")

    def test_reordered_rerun_of_the_same_design_reports_nothing(self):
        # Same design, sheets in the other order: DC-DET instances share a detection_id and
        # come back in reverse with re-assigned ids; unnamed nets are renumbered.
        dc = [_f("detect_decoupling", "DC-DET", caps, [], f"Decoupling on {rail}", "info",
                 detection_id="decoupling_analysis:9a1adf60f6b2", rail=rail, rail_net=None)
              for rail, caps in (("+3V3", ["C1", "C2"]), ("+5V", ["C7"]), ("VBUS", ["C9", "C10"]))]
        nt = [_f("analyze_connectivity", "NT-001", ["D1"], [f"__unnamed_{n}"],
                 f"Single-pin net: D1.{p} only connects to D1.{k} ({p}) (passive)", "info")
              for n, p, k in ((4, "K", 1), (9, "A", 2))]
        renum = [dict(f, nets=[{"__unnamed_4": "__unnamed_12", "__unnamed_9": "__unnamed_3"}[f["nets"][0]]])
                 for f in nt]
        stats = {"total_components": 8, "total_nets": 6}
        out = _run(_doc(dc + nt, "schematic", components=[], statistics=stats),
                   _doc(renum[::-1] + dc[::-1], "schematic", components=[], statistics=dict(stats)))
        self.assertFalse(out["has_changes"])
        self.assertEqual(out["diff"], {})
        self.assertEqual((out["summary"]["total_changes"], out["summary"]["metric_changes"]), (0, []))


class TextOutput(unittest.TestCase):
    def test_text_output_file_is_utf8_under_an_ascii_locale(self):
        base = _doc([], "schematic", components=[{"reference": "R1", "value": "10k"}])
        head = _doc([], "schematic", components=[{"reference": "R1", "value": "22k"}])
        with tempfile.TemporaryDirectory() as t:
            for name, doc in (("b.json", base), ("h.json", head)):
                with open(os.path.join(t, name), "w", encoding="utf-8") as fh:
                    json.dump(doc, fh)
            env = {k: v for k, v in os.environ.items() if not k.startswith(("LC_", "PYTHONUTF8", "PYTHONIOENCODING"))}
            env.update(LC_ALL="POSIX", LANG="C", PYTHONCOERCECLOCALE="0", PYTHONDONTWRITEBYTECODE="1")
            out = os.path.join(t, "d.txt")
            r = subprocess.run([sys.executable, "-X", "utf8=0", str(SCRIPTS / "diff_analysis.py"),
                                os.path.join(t, "b.json"), os.path.join(t, "h.json"), "--text", "-o", out],
                               env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out, "rb") as fh:
                self.assertIn("R1: value 10k → 22k", fh.read().decode("utf-8"))

    def test_more_changes_footer_counts_printed_footprint_lines(self):
        fps = lambda refs: [{"reference": r, "value": "1k", "footprint": "R_0603", "layer": "F.Cu"} for r in refs]  # noqa: E731
        base = dict(_pcb(True, 0), footprints=fps([]))
        head = dict(_pcb(True, 0), footprints=fps(["R1", "R2", "R3", "R4", "R5", "R6", "R7"]))
        text = _run(base, head, "--text")
        # 7 added, 5 printed: 2 more
        self.assertIn("... and 2 more changes", text)


class ReportSections(unittest.TestCase):
    def _sections(self, emc_text):
        with tempfile.TemporaryDirectory() as t:
            with open(os.path.join(t, "schematic.json"), "w", encoding="utf-8") as fh:
                json.dump({"analyzer_type": "schematic"}, fh)
            if emc_text is not None:
                with open(os.path.join(t, "emc.json"), "w", encoding="utf-8") as fh:
                    fh.write(emc_text)
            err = io.StringIO()
            old, sys.stderr = sys.stderr, err
            try:
                envs = check_report_sections._load_envelopes(t)
            finally:
                sys.stderr = old
            labels = [s[0] for s in check_report_sections.required_sections(envs, t)]
            return labels, err.getvalue()

    def test_truncated_emc_json_still_requires_its_section(self):
        labels, err = self._sections('{"analyzer_type": "emc", "findings": [')
        self.assertIn("EMC / Cross-Domain Analysis", labels)
        self.assertEqual(err.count("Warning:"), 1)
        self.assertIn("emc.json", err)

    def test_non_object_emc_json_still_requires_its_section(self):
        labels, err = self._sections("[]")
        self.assertIn("EMC / Cross-Domain Analysis", labels)
        self.assertEqual(err.count("Warning:"), 1)

    def test_absent_emc_json_requires_nothing(self):
        labels, err = self._sections(None)
        self.assertNotIn("EMC / Cross-Domain Analysis", labels)
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
