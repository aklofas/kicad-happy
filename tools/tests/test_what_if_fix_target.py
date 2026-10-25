"""what_if --fix with an impossible target names the problem on stderr and exits 1; a valid
target still prints suggestions; --target help names the real target kinds."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

WHAT_IF = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts" / "what_if.py"

# Shapes as signal_detectors emits them (detect_voltage_dividers / detect_crystal_circuits).
DIVIDER = {"detector": "detect_voltage_dividers", "rule_id": "VD-DET",
           "r_top": {"ref": "R5", "value": "22k", "ohms": 22000.0},
           "r_bottom": {"ref": "R6", "value": "2k2", "ohms": 2200.0},
           "top_net": "VBUS", "mid_net": "ADC", "bottom_net": "GND", "ratio": 0.090909}
CRYSTAL = {"detector": "detect_crystal_circuits", "rule_id": "XL-DET", "reference": "Y1",
           "value": "8MHz", "frequency": 8e6, "effective_load_pF": 14.0,
           "load_caps": [{"ref": "C1", "farads": 22e-12}, {"ref": "C2", "farads": 22e-12}]}


def _fix(fix, target):
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "sch.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"analyzer_type": "schematic", "findings": [DIVIDER, CRYSTAL], "components": []}, f)
        return subprocess.run([sys.executable, str(WHAT_IF), p, "--fix", fix, "--target", target, "--text"],
                              capture_output=True, text=True, encoding="utf-8")


class FixTargetTest(unittest.TestCase):
    def test_valid_ratio_suggests_values(self):
        r = _fix("voltage_dividers[0]", "0.5")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("R6", r.stdout)

    def test_ratio_outside_0_1_is_an_error(self):
        r = _fix("voltage_dividers[0]", "3.3")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        lines = r.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, r.stderr)
        self.assertIn("voltage_dividers[0]", lines[0])
        self.assertIn("outside (0, 1)", lines[0])

    def test_unsatisfiable_target_is_an_error(self):
        r = _fix("crystal_circuits[0]", "1")   # below the stray capacitance: no load caps reach it
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertIn("no component values reach effective_load_pF=1", r.stderr)

    def test_help_names_the_target_kinds(self):
        h = subprocess.run([sys.executable, str(WHAT_IF), "--help"], capture_output=True,
                           text=True, encoding="utf-8").stdout
        h = " ".join(h.split())
        self.assertNotIn("3.3 for Vout", h)
        self.assertIn("ratio 0-1 for voltage_dividers (Vout/Vin)", h)
        self.assertIn("feedback_networks (Vref/Vout)", h)


if __name__ == "__main__":
    unittest.main()
