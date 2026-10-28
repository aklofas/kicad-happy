"""what_if on a divider arm made of parallel parts: changing any member recomputes the arm's
equivalent from that member and the unchanged ones; --suggest-fixes gives the equivalent the
group needs and names the group instead of its first ref."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

WHAT_IF = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts" / "what_if.py"

# 10k / (R2 || R3, 10k each = 5k), as detect_voltage_dividers emits it
DIVIDER = {"detector": "detect_voltage_dividers", "rule_id": "VD-DET",
           "r_top": {"ref": "R1", "value": "10k", "ohms": 10000.0},
           "r_bottom": {"ref": "R2", "value": "2 resistors parallel", "ohms": 5000.0,
                        "parallel_refs": ["R2", "R3"]},
           "top_net": "+3V3", "mid_net": "FB", "bottom_net": "GND", "ratio": 0.333333,
           "components": ["R1", "R2", "R3"]}
REGULATOR = {"detector": "detect_power_regulators", "rule_id": "PR-DET", "ref": "U1",
             "value": "TPS54040", "output_rail": "+3V3", "estimated_vout": 2.4,
             "assumed_vref": 0.8, "vref_source": "lookup", "fb_net": "FB",
             "feedback_divider": {"r_top": {"ref": "R1", "ohms": 10000.0, "value": "10k"},
                                  "r_bottom": {"ref": "R2", "ohms": 5000.0, "value": "2 resistors parallel",
                                               "parallel_refs": ["R2", "R3"]},
                                  "ratio": 0.333333}}
COMPONENTS = [{"reference": r, "type": "resistor", "value": "10k"} for r in ("R1", "R2", "R3")]


def _run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "sch.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"analyzer_type": "schematic", "findings": [DIVIDER, REGULATOR],
                       "components": COMPONENTS}, f)
        r = subprocess.run([sys.executable, str(WHAT_IF), p, *args], capture_output=True,
                           text=True, encoding="utf-8")
    return r


class ParallelArm(unittest.TestCase):
    def _ratio_after(self, change):
        r = _run(change)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        vd = [s for s in out["affected_subcircuits"] if s["type"] == "voltage_dividers"]
        self.assertEqual(len(vd), 1, out)
        return vd[0]["after"]["ratio"]

    def test_changing_the_first_member_keeps_the_other(self):
        # 20k || 10k = 6.667k; ratio 6.667 / 16.667 = 0.4
        self.assertEqual(self._ratio_after("R2=20k"), 0.4)

    def test_changing_the_second_member_is_found(self):
        self.assertEqual(self._ratio_after("R3=20k"), 0.4)

    def test_suggest_fixes_names_the_group(self):
        # +3V3 at Vref 0.8 V: target ratio 0.8/3.3; bottom equivalent = 10k * t / (1 - t) = 3200 ohms
        r = _run("--suggest-fixes")
        self.assertEqual(r.returncode, 0, r.stderr)
        fix = json.loads(r.stdout)["fix_suggestions"][0]
        best = fix["suggestions"][0]
        self.assertEqual(best["ref"], "R2")
        self.assertAlmostEqual(best["ideal"], 3200.0, places=6)
        self.assertEqual(best["combined_refs"], ["R2", "R3"])
        self.assertIn("parallel group R2, R3", best["note"])
        # the E24 value (3.3k) replaces the equivalent: 3.3k / 13.3k
        ratio = [d for d in fix["delta_with_e24"] if d["field"] == "ratio"][0]
        self.assertEqual(ratio["after"], round(3300 / 13300, 6))
        text = _run("--suggest-fixes", "--text").stdout
        self.assertIn("combined R2+R3", text)


if __name__ == "__main__":
    unittest.main()
