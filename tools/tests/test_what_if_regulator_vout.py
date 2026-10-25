"""what_if recomputes a regulator's estimated_vout from its patched feedback divider."""
import copy, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from detection_schema import recalc_derived  # noqa: E402

# Field names and values as analyze_schematic.py emits a switching regulator with a divider.
REGULATOR = {
    "ref": "U1301", "value": "LM27313XMFX/NOPB", "topology": "switching",
    "estimated_vout": 3.397, "assumed_vref": 0.6, "vref_source": "heuristic",
    "feedback_divider": {"r_top": {"ref": "R1303", "ohms": 62000.0, "value": "62k"},
                         "r_bottom": {"ref": "R1302", "ohms": 13300.0, "value": "13.3k"},
                         "ratio": 0.176627},
    "detector": "detect_power_regulators", "rule_id": "PR-DET", "category": "power_management",
    "severity": "info", "confidence": "deterministic", "evidence_source": "topology",
    "summary": "Regulator U1301 switching", "components": ["U1301"], "nets": [], "pins": [],
}


class RecalcTest(unittest.TestCase):
    def test_unpatched_divider_reproduces_the_detector_value(self):
        det = copy.deepcopy(REGULATOR)
        recalc_derived(det, "power_regulators")
        self.assertEqual(det["estimated_vout"], 3.397)

    def test_patched_divider_moves_vout(self):
        det = copy.deepcopy(REGULATOR)
        det["feedback_divider"]["r_bottom"]["ohms"] = 10000.0
        recalc_derived(det, "power_regulators")
        self.assertEqual(det["feedback_divider"]["ratio"], 0.138889)
        self.assertEqual(det["estimated_vout"], 4.32)

    def test_inverting_regulator_stays_negative(self):
        det = copy.deepcopy(REGULATOR)
        det["estimated_vout"] = -3.397
        det["feedback_divider"]["r_bottom"]["ohms"] = 10000.0
        recalc_derived(det, "power_regulators")
        self.assertEqual(det["estimated_vout"], -4.32)

    def test_no_vref_leaves_vout_alone(self):
        det = copy.deepcopy(REGULATOR)
        det["assumed_vref"] = None
        det["feedback_divider"]["r_bottom"]["ohms"] = 10000.0
        recalc_derived(det, "power_regulators")
        self.assertEqual(det["estimated_vout"], 3.397)


class CliTest(unittest.TestCase):
    def test_what_if_reports_the_vout_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "sch.json")
            with open(src, "w", encoding="utf-8") as f:
                json.dump({"analyzer_type": "schematic", "findings": [REGULATOR],
                           "components": [{"reference": "R1302", "value": "13.3k", "type": "resistor"}]}, f)
            r = subprocess.run([sys.executable, str(SCRIPTS / "what_if.py"), src, "R1302=10k"],
                               capture_output=True, text=True, encoding="utf-8", cwd=tmp, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        reg = [a for a in json.loads(r.stdout)["affected_subcircuits"] if a["type"] == "power_regulators"]
        self.assertEqual(len(reg), 1)
        self.assertEqual(reg[0]["label"], "power regulator U1301")
        self.assertEqual(reg[0]["delta"], [{"field": "estimated_vout", "before": 3.397, "after": 4.32,
                                            "delta_pct": 27.2}])


if __name__ == "__main__":
    unittest.main()
