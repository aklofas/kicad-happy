"""The Action PR comment renders every diff it is given, one row per added/removed/changed item."""
import importlib.util, json, re, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORMATTER = ROOT / "action" / "format-report.py"
_spec = importlib.util.spec_from_file_location("format_report_under_test", FORMATTER)
FORMAT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FORMAT)


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


def schematic_reports(findings):
    """(compact comment, full report) rendered from a schematic JSON with these findings."""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        doc = {"statistics": {"total_components": 1}, "findings": findings}
        (d / "sch.json").write_text(json.dumps(doc), encoding="utf-8")
        r = subprocess.run([sys.executable, str(FORMATTER), "--schematic", str(d / "sch.json"),
                            "--output", str(d / "pr.md"), "--output-full", str(d / "full.md")],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr
        return (d / "pr.md").read_text(encoding="utf-8"), (d / "full.md").read_text(encoding="utf-8")


def regulator(**kw):
    return dict({"detector": "detect_power_regulators", "ref": "U1", "value": "LDO", "topology": "LDO",
                 "input_rail": "VIN", "output_rail": "+3V3", "estimated_vout": 3.3}, **kw)


class MarkdownEscapeTest(unittest.TestCase):
    def test_schematic_strings_cannot_add_links_headings_or_cells(self):
        reg = regulator(value="LM|1117 [pwn](https://e.x) `tick` *b*", output_rail="+3V3\n## Forged")
        for md in schematic_reports([reg]):
            self.assertNotIn("\n## Forged", md)
            self.assertNotIn("[pwn](https://e.x)", md)
            self.assertIn("\\[pwn\\](https://e.x)", md)
        full = schematic_reports([reg])[1]
        row = next(line for line in full.splitlines() if line.startswith("| U1 |"))
        self.assertEqual(len(re.findall(r"(?<!\\)\|", row)), 8)

    def test_plain_values_render_unchanged(self):
        reg = regulator(value="Conn_01x02_Pin", input_rail="~{RESET}", output_rail="4.7\u00b5F/16V")
        for md in schematic_reports([reg]):
            for text in ("Conn_01x02_Pin", "~{RESET}", "4.7\u00b5F/16V"):
                self.assertIn(text, md)
            self.assertNotIn("\\_", md)

    def test_missing_mpn_list_cannot_open_a_heading(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            doc = {"statistics": {"total_components": 2, "missing_mpn": ["# Forged", "R1"]}}
            (d / "sch.json").write_text(json.dumps(doc), encoding="utf-8")
            subprocess.run([sys.executable, str(FORMATTER), "--schematic", str(d / "sch.json"),
                            "--output", str(d / "pr.md"), "--output-full", str(d / "full.md")],
                           check=True, capture_output=True)
            full = (d / "full.md").read_text(encoding="utf-8")
        self.assertNotIn("\n# Forged", full)
        self.assertIn("\\# Forged, R1", full)

    def test_analyzer_text_cannot_open_an_ordered_list(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            doc = {"statistics": {"total_components": 2, "missing_mpn": ["1. R1", "1.8V"]}}
            (d / "sch.json").write_text(json.dumps(doc), encoding="utf-8")
            subprocess.run([sys.executable, str(FORMATTER), "--schematic", str(d / "sch.json"),
                            "--output", str(d / "pr.md"), "--output-full", str(d / "full.md")],
                           check=True, capture_output=True)
            full = (d / "full.md").read_text(encoding="utf-8")
        self.assertIn("\n1\\. R1, 1.8V", full)

    def test_ordered_list_escape_leaves_numeric_values_alone(self):
        lead = FORMAT._lead
        self.assertEqual(lead("1. R1"), "1\\. R1")
        self.assertEqual(lead("12) R1"), "12\\) R1")
        self.assertEqual(lead("3."), "3\\.")
        for text in ("1.8V", "3V3", "12.5k", "1234567890. x", "R1. x"):
            self.assertEqual(lead(text), text)

    def test_list_items_led_by_analyzer_text_cannot_open_a_heading(self):
        h = "# Forged"
        sch = {"statistics": {"total_components": 6}, "findings": [
            regulator(ref=h),
            {"detector": "detect_opamp_circuits", "reference": h, "value": "LM358",
             "configuration": "buffer", "warnings": [h], "unused_channels": ["B"]},
            {"detector": "detect_voltage_dividers", "r_top": {"ref": h}, "r_bottom": {"ref": "R2"},
             "ratio": 0.5},
            {"detector": "detect_rc_filters", "resistor": {"ref": h}, "capacitor": {"ref": "C1"},
             "cutoff_hz": 100},
            {"detector": "detect_crystal_circuits", "reference": h, "value": "8MHz",
             "load_caps": []}],
            "protocol_compliance": {"findings": [
                {"protocol": "i2c", "issues": [h], "checks": {h: {"status": "pass"}}}]},
            "design_analysis": {"cross_domain_signals": [{"net": h, "power_domains": ["+3V3", "+5V"]}]}}
        emc = {"findings": [], "summary": {"total_checks": 1},
               "test_plan": {"frequency_bands": [{"band": h, "source_count": 2, "risk_level": "high"}]}}
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "sch.json").write_text(json.dumps(sch), encoding="utf-8")
            (d / "emc.json").write_text(json.dumps(emc), encoding="utf-8")
            subprocess.run([sys.executable, str(FORMATTER), "--schematic", str(d / "sch.json"),
                            "--emc", str(d / "emc.json"), "--output", str(d / "pr.md"),
                            "--output-full", str(d / "full.md")], check=True, capture_output=True)
            reports = [(d / n).read_text(encoding="utf-8") for n in ("pr.md", "full.md")]
        for md in reports:
            self.assertIn(h, md)
            for line in md.splitlines():
                self.assertNotRegex(line, r"^\s*- #", line)
        full = reports[1]
        for text in ("- \\# Forged crosses", "- \\# Forged: **pass**", "  - \\# Forged",
                     "- \\# Forged / R2", "- \\# Forged + C1", "- \\# Forged (8MHz)",
                     "- \\# Forged: 2 emission"):
            self.assertIn(text, full)


class ActionPrComment(unittest.TestCase):
    def test_schematic_and_pcb_diffs_both_reach_the_comment(self):
        sch = diff_doc({"components": {"added": [{"reference": "R9", "value": "10k", "footprint": "R_0402"}]}},
                       1, added=1)
        pcb = dict(analyzer_type="pcb", **diff_doc({"findings": {"new": [{"rule_id": "DFM-001", "severity": "warning",
                                              "summary": "Drill too small", "components": ["J1"]}]}},
                       1, added=1))
        md = comment(sch, pcb)
        self.assertIn("> 2 changes: +2 added, -0 removed, ~0 modified (major)", md)
        self.assertIn("| + R9 | New: 10k R_0402 |", md)
        self.assertIn("| NEW PCB warning | DFM-001: Drill too small |", md)

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

    def test_footprint_changes_get_rows(self):
        fp = {"added": [{"reference": "J2", "value": "USB_C", "footprint": "USB_C_Receptacle", "layer": "F.Cu"}],
              "removed": [{"reference": "TP1", "value": "TP", "layer": "B.Cu"}],
              "modified": [{"reference": "R1", "changes": [{"field": "footprint", "base": "R_0402", "head": "R_0603"},
                                                           {"field": "layer", "base": "F.Cu", "head": "B.Cu"}]}]}
        md = comment(dict(analyzer_type="pcb", **diff_doc({"footprints": fp}, 3, added=1, removed=1, modified=1)))
        self.assertIn("| + PCB J2 | New footprint: USB_C USB_C_Receptacle |", md)
        self.assertIn("| - PCB TP1 | Removed footprint: TP |", md)
        self.assertIn("| ~ PCB R1 footprint | R_0402 → R_0603 |", md)
        self.assertIn("| ~ PCB R1 layer | F.Cu → B.Cu |", md)
        self.assertNotIn("more*", md)

    def test_unlisted_items_are_counted_without_rows(self):
        md = comment(diff_doc({"bom": {"added": [{"line": 1}, {"line": 2}]}}, 2, added=2))
        self.assertIn("| | *...and 2 more* |", md)

    def test_markup_and_mentions_are_inert_in_a_cell(self):
        f = {"rule_id": "X-1", "severity": "info", "components": [], "summary": "<!-- hide --> @octocat"}
        md = comment(diff_doc({"signal_analysis": {"t": {"added": [f], "removed": [], "modified": []}}}, 1, added=1))
        self.assertIn("| + T | X-1 info: &lt;!-- hide --&gt; @\u200boctocat |", md)
        self.assertNotIn("<!-- hide", md)
        self.assertTrue(md.rstrip().endswith("<!-- kicad-happy-review -->"))

    def test_entrypoint_passes_every_diff_and_no_dead_entries(self):
        sh = (ROOT / "action" / "entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn("for dtype in schematic pcb; do", sh)
        self.assertNotIn("schematic pcb emc spice", sh)
        self.assertIn('ARGS+=(--diff "$_diff")', sh)
        self.assertNotIn("head/emc.json", sh)
        self.assertNotIn("head/spice.json", sh)


if __name__ == "__main__":
    unittest.main()
