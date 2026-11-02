"""The compact and full Action reports project the schematic's source name, de-duplicated
protocol issues and device names; both are pinned byte-for-byte against goldens."""
import importlib.util, json, os, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).resolve().parent / "fixtures"

_spec = importlib.util.spec_from_file_location("format_report_under_test", ROOT / "action" / "format-report.py")
FR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FR)

SCHEMATIC = {
    "file": "legacy/board.kicad_sch",
    "statistics": {"total_components": 12, "unique_parts": 7, "total_nets": 9,
                   "total_no_connects": 1, "power_rails": ["+3V3", "+5V"]},
    "findings": [
        {"detector": "analyze_voltage_derating", "rule_id": "VD-001", "severity": "warning",
         "summary": "C1 (10uF) has marginal voltage derating on +5V (5.0V on 6V cap)"},
        {"detector": "analyze_voltage_derating", "rule_id": "VD-002", "severity": "error",
         "summary": "U1 exceeds datasheet absolute-max voltage on +3V3 (3.3V > 3.6V)"},
        {"detector": "analyze_voltage_derating", "rule_id": "VD-003", "severity": "warning",
         "summary": "R1 (10R) 0402 has marginal power derating (100mW / 63mW rated)"},
        {"detector": "analyze_voltage_derating", "rule_id": "VD-004", "severity": "info",
         "summary": "C2 is over-designed"},
    ],
    "protocol_compliance": {"findings": [
        {"protocol": "i2c", "sda_net": "SDA", "issues": ["pull-up too weak", "bus too long"],
         "devices": [{"ref": "U1"}, {"reference": "U2"}, "U3", {"value": "x"}, "U5", "U6"],
         "checks": {"pull_ups_present": {"status": "pass"},
                    "rise_time": {"sda": {"valid_400khz": True, "rise_time_ns": 250},
                                  "scl": {"valid_400khz": False, "rise_time_ns": 900}}}},
        {"protocol": "i2c", "sda_net": "SDA2", "issues": ["pull-up too weak", "address clash"],
         "devices": ["U7"], "checks": {"pull_ups_present": {"status": "fail"}}},
        {"protocol": "spi", "issues": ["bus too long", "no chip select"], "devices": []},
    ]},
}


def _render():
    with tempfile.TemporaryDirectory() as tmp:
        sch = os.path.join(tmp, "sch.json")
        with open(sch, "w", encoding="utf-8") as f:
            json.dump(SCHEMATIC, f)
        compact, _ = FR.format_report(sch, None, None, None, "all", "commercial")
        full = FR.format_full_report(sch, None, None, None, "commercial")
    return compact, full


class ReportProjectionsTest(unittest.TestCase):
    def test_reports_match_goldens(self):
        compact, full = _render()
        for name, text in (("compact", compact), ("full", full)):
            with open(GOLDEN / f"format_report_projections_{name}.md", encoding="utf-8", newline="") as f:
                self.assertEqual(text, f.read(), name)


if __name__ == "__main__":
    unittest.main()
