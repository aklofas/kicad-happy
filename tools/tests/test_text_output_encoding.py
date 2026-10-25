"""--text output survives a stdout that is not UTF-8 (a Windows cp1252 redirect)."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from tools.tests._fixtures import fixture_path, have

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
FIXTURES = fixture_path()
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


@unittest.skipUnless(have(ESD), "harness fixtures not present")
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


FORMAT_REPORT = ROOT / "action" / "format-report.py"
SIMPLE = FIXTURES / "simple-project"


@unittest.skipUnless(have(SIMPLE / "simple.kicad_pcb"), "harness fixtures not present")
class ActionReportEncodingTest(unittest.TestCase):
    ASCII_ENV = dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="ascii", LC_ALL="C", LANG="C",
                     PYTHONDONTWRITEBYTECODE="1")

    def test_report_files_are_utf8_under_an_ascii_locale(self):
        with tempfile.TemporaryDirectory() as tmp:
            sch, pcb = os.path.join(tmp, "sch.json"), os.path.join(tmp, "pcb.json")
            for script, src, out in (("analyze_schematic.py", "simple.kicad_sch", sch),
                                     ("analyze_pcb.py", "simple.kicad_pcb", pcb)):
                subprocess.run([sys.executable, str(SCRIPTS / script), str(SIMPLE / src), "--output", out],
                               check=True, capture_output=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            outs = [os.path.join(tmp, n) for n in ("r.md", "full.md", "summary.json")]
            r = subprocess.run([sys.executable, str(FORMAT_REPORT), "--schematic", sch, "--pcb", pcb,
                                "--output", outs[0], "--output-full", outs[1], "--output-summary", outs[2]],
                               capture_output=True, env=self.ASCII_ENV, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-1500:])
            for p in outs[:2]:
                with open(p, "rb") as f:
                    text = f.read().decode("utf-8")
                self.assertIn("\u2014", text)  # em dash, written as UTF-8
            with open(outs[0], "rb") as f:
                comment = f.read().decode("utf-8")
            self.assertIn("\u2705", comment)
            with open(outs[2], "rb") as f:
                json.loads(f.read().decode("utf-8"))

    def test_load_json_survives_a_non_utf8_file(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("format_report_mod", FORMAT_REPORT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "bad.json")
            with open(p, "wb") as f:
                f.write(b'{"a": "\xff\xfe"}')
            self.assertIsNone(mod._load_json(p))
