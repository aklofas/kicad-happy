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


class SweepLabels(unittest.TestCase):
    def _sweep(self, change):
        return what_if._parse_changes([change])[1]

    def test_log_sweep_labels_use_si_prefixes(self):
        self.assertEqual(self._sweep("R49=1k..100k:10").value_strs,
                         ["1k", "1.668k", "2.783k", "4.642k", "7.743k", "12.92k",
                          "21.54k", "35.94k", "59.95k", "100k"])

    def test_capacitor_log_sweep_labels(self):
        self.assertEqual(self._sweep("C101=1n..100n:5").value_strs,
                         ["1n", "3.162n", "10n", "31.62n", "100n"])

    def test_labels_round_trip(self):
        for change, ctype in (("R1=900..1.1k:3", "resistor"), ("R1=999.9..1M:3", "resistor"),
                              ("L1=1u..100u:4", "inductor"), ("C1=1p..1u:7", "capacitor")):
            sweep = self._sweep(change)
            for v, label in zip(sweep.values[1:-1], sweep.value_strs[1:-1]):
                with self.subTest(change=change, label=label):
                    self.assertAlmostEqual(what_if.parse_value(label, component_type=ctype) / v,
                                           1.0, delta=0.0005)

    def test_comma_list_labels_verbatim(self):
        self.assertEqual(self._sweep("R49=1k,2.2k,4.7k").value_strs, ["1k", "2.2k", "4.7k"])

    def test_sweep_values_stay_numeric(self):
        values = self._sweep("R49=1k..100k:3").values
        self.assertEqual([round(v, 6) for v in values], [1000.0, 10000.0, 100000.0])


class NoAffectedOutput(unittest.TestCase):
    def test_no_affected_output_writes_analysis(self):
        r, exported = _run(_amp(), "R999=1k", "--output", "{OUT}")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(exported, _amp())
        self.assertIn("No subcircuit changed; wrote the unchanged analysis to", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_no_affected_without_output_prints_result(self):
        r, exported = _run(_amp(), "R999=1k")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["affected_subcircuits"], [])
        self.assertIsNone(exported)

    def test_no_affected_text_with_output_still_prints_text(self):
        r, _ = _run(_amp(), "R999=1k", "--output", "{OUT}", "--text")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("No subcircuits reference", r.stdout)


if __name__ == "__main__":
    unittest.main()
