# tools/tests/test_severity_vocabulary.py
"""Pins one severity vocabulary (error/warning/info) on the output of datasheet_verify, cross_verify and summarize_findings."""
import io, json, re, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
SKILLS = Path(__file__).resolve().parents[2] / "skills"
for _d in ("kicad", "datasheets"):
    sys.path.insert(0, str(SKILLS / _d / "scripts"))

import cross_verify, datasheet_verify, summarize_findings  # noqa: E402

CANONICAL = {"error", "warning", "info"}


def _ic(ref, mpn, pin_nets):
    return {"reference": ref, "type": "ic", "mpn": mpn, "value": mpn, "pin_nets": pin_nets}


class DatasheetVerifySeverityTests(unittest.TestCase):
    def test_findings_and_summary_use_canonical_names(self):
        with tempfile.TemporaryDirectory() as d:
            ext = Path(d) / "datasheets" / "extracted"
            ext.mkdir(parents=True)
            (ext / "PARTA.json").write_text(json.dumps({"pins": [
                {"number": "1", "name": "VIN", "type": "power", "voltage_abs_max": 3.6},
                {"number": "2", "name": "VIO", "type": "power",
                 "voltage_abs_max": 5.0, "voltage_operating_max": 3.0},
            ]}), encoding="utf-8")
            (ext / "PARTB.json").write_text(json.dumps({"base": {"pinout": []}}), encoding="utf-8")
            analysis = {
                "components": [_ic("U1", "PARTA", {"1": "+5V", "2": "+3V3"}),
                               _ic("U2", "PARTB", {"1": "+3V3"})],
                "nets": {}, "rail_voltages": {},
            }
            out = datasheet_verify.run_datasheet_verification(analysis, project_dir=d)
        sev = {f["type"]: f["severity"] for f in out["findings"]}
        self.assertEqual(sev["pin_voltage_abs_max_exceeded"], "error")
        self.assertEqual(sev["pin_voltage_operating_exceeded"], "warning")
        self.assertEqual(sev["extraction_not_verifiable"], "info")
        self.assertEqual(set(out["summary"]["by_severity"]), CANONICAL)


class CrossVerifySeverityTests(unittest.TestCase):
    def _skew(self, pos_len, neg_len):
        sch = {"design_analysis": {"differential_pairs": [
            {"positive": "P", "negative": "N", "type": "USB"}]}}
        pcb = {"net_lengths": [{"net": "P", "total_length_mm": pos_len},
                               {"net": "N", "total_length_mm": neg_len}]}
        return cross_verify.check_diff_pair_routing(sch, pcb)[0]["intra_pair_skew"]["severity"]

    def test_skew_severity_canonical(self):
        self.assertEqual(self._skew(50.0, 45.0), "error")
        self.assertEqual(self._skew(50.0, 48.5), "warning")


class SummarizeSeverityTests(unittest.TestCase):
    def _run(self, *extra):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "manifest.json").write_text(
                json.dumps({"version": 1, "current": "r1", "runs": {"r1": {}}}), encoding="utf-8")
            run = Path(d) / "r1"
            run.mkdir()
            findings = [{"rule_id": "A-1", "severity": s, "summary": s, "confidence": "deterministic"}
                        for s in ("error", "warning", "info", "critical")]
            (run / "schematic.json").write_text(json.dumps({"findings": findings}), encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = summarize_findings.main([d, "--json", *extra])
            self.assertEqual(rc, 0)
            return json.loads(buf.getvalue())

    def test_totals_keys_canonical(self):
        out = self._run()
        self.assertEqual(set(out["totals"]["by_severity"]), CANONICAL)
        self.assertEqual(out["totals"]["by_severity"]["error"], 2)
        self.assertTrue({r["severity"] for r in out["rows"]} <= CANONICAL)

    def test_legacy_name_selects_same_rows(self):
        self.assertEqual(self._run("--severity", "high")["rows"], self._run("--severity", "error")["rows"])
        self.assertEqual(self._run("--severity", "error")["totals"]["findings"], 2)


class NoUppercaseSeverityLiteralTests(unittest.TestCase):
    DICT_LITERAL = re.compile(r"""["']severity["']\s*:\s*["'][A-Z]+["']""")
    ASSIGNMENT = re.compile(r"""\bseverity\s*=\s*["'][A-Z]+["']""")
    # emc_rules keeps uppercase internal severities and maps them via _EMC_SEVERITY_MAP on output.
    ASSIGNMENT_ALLOWED = {"emc_rules.py"}

    def test_no_uppercase_severity_literal_under_skills(self):
        hits = []
        for p in SKILLS.rglob("*.py"):
            text = p.read_text(encoding="utf-8")
            hits += [f"{p.relative_to(SKILLS)}: {m.group(0)}" for m in self.DICT_LITERAL.finditer(text)]
            if p.name not in self.ASSIGNMENT_ALLOWED:
                hits += [f"{p.relative_to(SKILLS)}: {m.group(0)}" for m in self.ASSIGNMENT.finditer(text)]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
