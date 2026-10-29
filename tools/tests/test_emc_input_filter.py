"""EF-001/EF-002 judge the filter on the regulator's own input rail."""
import math, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from emc_rules import _input_lc_filter, check_emi_filter_effectiveness  # noqa: E402
from finding_schema import Det  # noqa: E402


def _part(ref, kind, value, nets, dnp=False):
    return {"reference": ref, "type": kind, "parsed_value": value, "dnp": dnp,
            "pin_nets": {str(i + 1): n for i, n in enumerate(nets)}}


def _sch(parts, input_rail="VIN", sw_hz=1.0e6, extra=None):
    reg = {"detector": Det.POWER_REGULATORS, "ref": "U1", "value": "AP63357Q", "topology": "buck", "input_rail": input_rail,
           "switching_frequency_hz": sw_hz}
    return {"components": parts, "findings": [reg], **(extra or {})}


# fc = 1 / (2 pi sqrt(10 uH * 10 uF)) = 15.9 kHz
FC = 1 / (2 * math.pi * math.sqrt(10e-6 * 10e-6))
FILTER = [_part("L1", "inductor", 10e-6, ["VIN_RAW", "VIN"]),
          _part("C1", "capacitor", 10e-6, ["VIN", "GND"])]


class InputFilter(unittest.TestCase):
    def test_series_lc_on_the_input_rail(self):
        found, fc = _input_lc_filter(_sch(FILTER), "VIN")
        self.assertTrue(found)
        self.assertAlmostEqual(fc, FC, delta=1)
        self.assertEqual(f"{fc / 1e3:.1f}", "15.9")

    def test_boost_switch_node_inductor_is_not_a_filter(self):
        parts = [_part("L1", "inductor", 10e-6, ["VIN", "SW"]), FILTER[1]]
        self.assertEqual(_input_lc_filter(_sch(parts), "VIN"), (False, None))

    def test_lc_on_a_signal_net_is_ignored(self):
        parts = [_part("L1", "inductor", 10e-6, ["SIG_A", "SIG_B"]),
                 _part("C1", "capacitor", 10e-6, ["SIG_B", "GND"])]
        self.assertEqual(_input_lc_filter(_sch(parts), "VIN"), (False, None))

    def test_ferrite_needs_a_value_in_henries_below_10mh(self):
        for value in (None, 0.5, 10e-3, 600.0):
            parts = [_part("FB1", "ferrite_bead", value, ["VIN_RAW", "VIN"]), FILTER[1]]
            self.assertEqual(_input_lc_filter(_sch(parts), "VIN"), (False, None), value)
        parts = [_part("FB1", "ferrite_bead", 10e-6, ["VIN_RAW", "VIN"]), FILTER[1]]
        self.assertTrue(_input_lc_filter(_sch(parts), "VIN")[0])

    def test_dnp_parts_are_ignored(self):
        for i in (0, 1):
            parts = [dict(p) for p in FILTER]
            parts[i]["dnp"] = True
            self.assertEqual(_input_lc_filter(_sch(parts), "VIN"), (False, None))

    def test_capacitance_sums_non_dnp_input_caps(self):
        parts = FILTER + [_part("C2", "capacitor", 10e-6, ["GND", "VIN"]),
                          _part("C3", "capacitor", 100e-6, ["VIN", "GND"], dnp=True)]
        _, fc = _input_lc_filter(_sch(parts), "VIN")
        self.assertAlmostEqual(fc, 1 / (2 * math.pi * math.sqrt(10e-6 * 20e-6)), delta=1)

    def test_no_caps_means_no_filter(self):
        self.assertEqual(_input_lc_filter(_sch(FILTER[:1]), "VIN"), (False, None))


class Findings(unittest.TestCase):
    def _run(self, parts, rail="VIN", sw_hz=1.0e6):
        return check_emi_filter_effectiveness(None, _sch(parts, rail, sw_hz))

    def test_ef002_against_the_switching_frequency(self):
        fs = self._run(FILTER)
        self.assertEqual([f["rule_id"] for f in fs], ["EF-002"])

    def test_ef001_when_cutoff_is_near_the_switching_frequency(self):
        fs = self._run(FILTER, sw_hz=50e3)
        self.assertEqual([f["rule_id"] for f in fs], ["EF-001"])

    def test_unrelated_lc_record_no_longer_counts(self):
        sch = _sch([_part("L9", "inductor", 10e-6, ["SIG_A", "SIG_B"])])
        sch["findings"] += [{"detector": Det.LC_FILTERS, "inductor": "L9", "resonant_hz": 1e3}]
        self.assertEqual(check_emi_filter_effectiveness(None, sch), [])

    def test_unresolved_input_rail_yields_no_finding(self):
        self.assertEqual(self._run(FILTER, rail=""), [])


if __name__ == "__main__":
    unittest.main()
