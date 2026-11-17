"""Resistor power derating for a resistor between two supply rails."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from schematic.system_analyses import analyze_voltage_derating  # noqa: E402


def _ctx(value, footprint, rails):
    """R1 with pin 1 on rails[0] and pin 2 on rails[1]."""
    nets = {}
    for pin, net in zip(("1", "2"), rails):
        nets[net] = {"name": net, "pins": [{"component": "R1", "pin_number": pin, "pin_name": pin,
                                            "pin_type": "passive"}],
                     "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
    comps = [{"reference": "R1", "type": "resistor", "value": value,
              "footprint": footprint, "lib_id": "Device:R"}]
    return build_analysis_context(comps, nets, {}, known_power_rails=set(rails))


def _resistor_derating(ctx):
    return [f for f in analyze_voltage_derating(ctx, {}) if f["rule_id"] in ("VD-003", "VD-004")]


class SeriesResistorBetweenRails(unittest.TestCase):
    def test_milliohm_shunt_between_two_rails_has_no_rail_difference_dissipation(self):
        ctx = _ctx("3m", "Resistor_SMD:R_2512_6332Metric", ["+12V", "+5V"])
        self.assertEqual(_resistor_derating(ctx), [])

    def test_sub_ohm_link_between_two_rails_has_none_either(self):
        ctx = _ctx("0.33", "Resistor_SMD:R_1206_3216Metric", ["+5V", "+3V3"])
        self.assertEqual(_resistor_derating(ctx), [])

    def test_resistor_of_an_ohm_or_more_between_two_rails_still_warns(self):
        (f,) = _resistor_derating(_ctx("1k", "Resistor_SMD:R_0402_1005Metric", ["+12V", "+5V"]))
        self.assertEqual((f["rule_id"], f["severity"], f["voltage_across"]), ("VD-003", "warning", 7.0))
        (f,) = _resistor_derating(_ctx("47", "Resistor_SMD:R_0402_1005Metric", ["+5V", "+3V3"]))
        self.assertEqual(f["rule_id"], "VD-003")
        self.assertAlmostEqual(f["voltage_across"], 1.7)


if __name__ == "__main__":
    unittest.main()
