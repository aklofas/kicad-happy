"""what_if mode combinations: a sweep refuses tolerance corners and --output, --output with no
affected subcircuit writes the unchanged analysis, and a suggested fix carries the detector's
own confidence for the regulator's Vout."""
import json, os, sys, unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import what_if  # noqa: E402
from test_what_if_patched_design import _amp, _run  # noqa: E402

DIVIDER = {"r_top": {"ref": "R1", "ohms": 10000.0}, "r_bottom": {"ref": "R2", "ohms": 3000.0}}


def _signal(**reg_extra):
    reg = {"ref": "U1", "estimated_vout": 1.8, "assumed_vref": 0.8, "output_rail": "+3V3",
           "feedback_divider": dict(DIVIDER)}
    reg.update(reg_extra)
    return {"power_regulators": [reg],
            "voltage_dividers": [dict(DIVIDER, ratio=0.2308)]}


def _confidence(**reg_extra):
    issues = what_if._scan_fixable(_signal(**reg_extra))
    return next(i for i in issues if i["category"] == "value_fix")["confidence"]


class FixConfidenceFollowsDetector(unittest.TestCase):
    def test_fix_confidence_follows_detector(self):
        self.assertEqual(_confidence(vref_source="datasheet", _estimated_vout_provenance={
            "confidence": "deterministic"}), "deterministic")
        self.assertEqual(_confidence(vref_source="lookup", _estimated_vout_provenance={
            "confidence": "heuristic"}), "heuristic")
        self.assertEqual(_confidence(vref_source="lookup"), "heuristic")


class SweepRefusals(unittest.TestCase):
    def _refused(self, *args, message):
        r, exported = _run(_amp(), *args)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn(message, r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertIsNone(exported)

    def test_sweep_with_tolerance_exits_2(self):
        msg = "tolerance corners are not supported with a sweep; run each value as a single change"
        self._refused("R49=1k,2.2k+-5%", message=msg)
        self._refused("R49=1k,2.2k", "R13=10k+-1%", message=msg)

    def test_sweep_with_output_exits_2(self):
        self._refused("R49=1k,2.2k", "--output", "{OUT}",
                      message="--output exports one patched design; it cannot be combined with a sweep")


class NoAffectedOutput(unittest.TestCase):
    def test_no_affected_output_writes_analysis(self):
        r, exported = _run(_amp(), "R999=1k", "--output", "{OUT}")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(exported, _amp())
        self.assertIn("No subcircuit changed; wrote the unchanged analysis to", r.stderr)
        self.assertEqual(json.loads(r.stdout)["affected_subcircuits"], [])


if __name__ == "__main__":
    unittest.main()
