"""Thermal reads the keys the analyzers write and does not invent shunt currents."""
import json
import sys
import unittest
from pathlib import Path

from tools.tests._fixtures import fixture

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import analyze_thermal as at  # noqa: E402
import cross_verify as cv  # noqa: E402
from finding_schema import make_finding  # noqa: E402


def _load(name):
    return json.loads(fixture("action-format-report", name).read_text(encoding="utf-8"))


class Shunts(unittest.TestCase):
    def test_shunt_without_current_skipped(self):
        sch = {"findings": [{
            "detector": "detect_current_sense",
            "shunt": {"ref": "R1", "value": "0.01", "ohms": 0.01},
            "max_current_50mV_A": 5.0,
            "max_current_100mV_A": 10.0,
        }]}
        results, skipped = at._estimate_all_power_dissipation(sch)
        self.assertEqual([r for r in results if r["ref"] == "R1"], [])
        self.assertIn({"ref": "R1", "value": "0.01", "reason": "no_operating_current"}, skipped)


class Packages(unittest.TestCase):
    def test_classify_package_table(self):
        table = {
            "MSOP-8": 200, "TSSOP-8": 150, "TSSOP-20": 80, "SSOP-28": 100,
            "SOIC-14_3.9x8.7mm": 100, "SOIC-8": 120, "SOP-8": 120, "SOIC-16W": 80,
            "MSOP-10-1EP": 100, "HTSSOP-20-1EP": 100,
        }
        for name, theta in table.items():
            with self.subTest(name=name):
                self.assertEqual(at._classify_package("Package_SO:" + name)[1], theta)


class TextReport(unittest.TestCase):
    def test_text_report_reads_assessments(self):
        data = _load("thermal_v14_arig_controleurspompes_error.json")
        bs = data["summary"]["by_severity"]
        text = at.format_text_report(data)
        self.assertIn("Component Thermal Summary", text)
        self.assertIn(data["assessments"][0]["ref"], text)
        for label, key in (("ERROR", "error"), ("WARNING", "warning"), ("INFO", "info")):
            self.assertIn(f"{label}:", text)
            line = [ln for ln in text.splitlines() if ln.strip().startswith(label + ":")][0]
            self.assertEqual(int(line.split(":")[1]), bs.get(key, 0))
        data["findings"].append(make_finding(
            detector="detect_tj_exceeds_max", rule_id="TJ-001", category="thermal",
            summary="Tj exceeds datasheet maximum", description="x"))
        self.assertIn("Tj exceeds datasheet maximum", at.format_text_report(data))

    def test_text_report_legacy_keys(self):
        a = _load("thermal_v14_rpi_i2c_board.json")["assessments"][0]
        legacy = {"summary": {"critical": 3, "total_findings": 3}, "findings": [],
                  "thermal_assessments": [a]}
        text = at.format_text_report(legacy)
        self.assertIn("Component Thermal Summary", text)
        self.assertIn(a["ref"], text)
        self.assertRegex(text, r"CRITICAL:\s+3")


class CrossVerify(unittest.TestCase):
    def test_cross_verify_thermal_vias(self):
        out = cv.check_thermal_vias(
            {"assessments": [{"ref": "U1", "margin_c": 5, "pdiss_w": 0.5, "tj_estimated_c": 120}]},
            {"findings": [{"detector": "analyze_thermal_pad_vias", "component": "U1", "via_count": 1}]})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["status"], "fail")


if __name__ == "__main__":
    unittest.main()
