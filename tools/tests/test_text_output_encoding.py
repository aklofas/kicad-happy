"""--text output survives a stdout that is not UTF-8 (a Windows cp1252 redirect)."""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
FIXTURES = Path(os.environ.get("KH_FIXTURES", "/tmp/harness-pin/tests/fixtures"))
ESD = FIXTURES / "determinism" / "usb_dual_esd.kicad_sch"


def _run(args, cwd):
    env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, *args], capture_output=True, cwd=cwd, env=env, timeout=300)


class HelperTest(unittest.TestCase):
    def test_helper_reencodes_a_cp1252_stdout_as_utf8(self):
        code = ("import sys; sys.path.insert(0, %r); from kicad_core.cli import utf8_text_stdout; "
                "utf8_text_stdout(); print('\\u03a9 \\u2264 \\u2265')" % str(SCRIPTS))
        with tempfile.TemporaryDirectory() as tmp:
            r = _run(["-c", code], tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.decode("utf-8").strip(), "Ω ≤ ≥")


@unittest.skipUnless(ESD.is_file(), "harness fixtures not present")
class CliTest(unittest.TestCase):
    def test_schematic_text_with_non_cp1252_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _run([str(SCRIPTS / "analyze_schematic.py"), str(ESD), "--text"], tmp)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-1500:])
        text = r.stdout.decode("utf-8")
        self.assertTrue(any(c in text for c in "≤≥Ω"))

    def test_pcb_text_under_cp1252(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _run([str(SCRIPTS / "analyze_pcb.py"),
                      str(FIXTURES / "simple-project" / "simple.kicad_pcb"), "--text"], tmp)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-1500:])
        r.stdout.decode("utf-8")


# Real-shape findings (as analyze_schematic.py emits them) whose fix suggestion prints kΩ values.
_REGULATOR = {
    "ref": "U1301", "value": "LM27313XMFX/NOPB", "topology": "switching", "output_rail": "5V",
    "estimated_vout": 3.397, "assumed_vref": 0.6, "vref_source": "heuristic",
    "feedback_divider": {"r_top": {"ref": "R1303", "ohms": 62000.0, "value": "62k"},
                         "r_bottom": {"ref": "R1302", "ohms": 13300.0, "value": "13.3k"},
                         "ratio": 0.176627},
    "detector": "detect_power_regulators", "rule_id": "PR-DET", "category": "power_management",
    "severity": "info", "confidence": "deterministic", "evidence_source": "topology",
    "summary": "Regulator U1301 switching", "components": ["U1301"], "nets": [], "pins": [],
}
_DIVIDER = {
    "r_top": {"ref": "R1303", "value": "62k", "ohms": 62000.0},
    "r_bottom": {"ref": "R1302", "value": "13.3k", "ohms": 13300.0},
    "top_net": "VOUT", "mid_net": "__unnamed_14", "bottom_net": "GND", "ratio": 0.176627,
    "is_feedback": True, "detector": "detect_voltage_dividers", "rule_id": "VD-DET",
    "category": "voltage_dividers", "severity": "info", "confidence": "deterministic",
    "evidence_source": "topology", "summary": "Voltage divider R1303/R1302",
    "components": ["R1302", "R1303"], "nets": [], "pins": [], "purpose": "feedback",
}


class WhatIfSuggestFixesTest(unittest.TestCase):
    def test_suggest_fixes_text_under_cp1252(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "sch.json")
            with open(src, "w", encoding="utf-8") as f:
                json.dump({"analyzer_type": "schematic", "findings": [_REGULATOR, _DIVIDER]}, f)
            r = _run([str(SCRIPTS / "what_if.py"), src, "--suggest-fixes", "--text"], tmp)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-1500:])
        self.assertIn("k\u03a9", r.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
