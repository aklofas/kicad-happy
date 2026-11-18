"""Resistor power derating with a VSS-named net at one end.

A VSS net that a resistor feeds from a negative rail is that negative supply (an analog AVSS
fed from -2V5 through a filter resistor), so the resistor does not see the rail against 0 V.
A VSS net fed from a positive rail stays ground at 0 V, and so does a VSS net that carries a
ground symbol: the symbol ties it to the board ground. A net named exactly VSS reads 0 V by
its name, so a negative rail across it is still rated.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from schematic.system_analyses import analyze_voltage_derating  # noqa: E402


def _pin(ref, num, name="~", pin_type="passive"):
    return {"component": ref, "pin_number": num, "pin_name": name, "pin_type": pin_type}


def _ctx(rail, vss, ground_symbol=False):
    """R1 (10 Ω 0805) from *rail* to *vss*; an ADC's supply-return pin sits on *vss*."""
    comps = [{"reference": "R1", "type": "resistor", "value": "10R",
              "footprint": "Resistor_SMD:R_0805_2012Metric", "lib_id": "Device:R"},
             {"reference": "U1", "type": "ic", "value": "ADC", "footprint": "", "lib_id": "ADC:ADC",
              "pins": [{"number": "1", "name": vss}]}]
    pins = {rail: [_pin("R1", "1")], vss: [_pin("R1", "2"), _pin("U1", "1", vss, "power_in")]}
    if ground_symbol:
        comps.append({"reference": "#PWR01", "type": "power_symbol", "value": "GND",
                      "footprint": "", "lib_id": "power:GND", "pins": [{"number": "1", "name": "GND"}]})
        pins[vss].append(_pin("#PWR01", "1", "GND", "power_in"))
    nets = {n: {"name": n, "pins": ps, "point_count": 0, "no_connect": False,
                "has_pwr_flag": False, "labels": []} for n, ps in pins.items()}
    return build_analysis_context(comps, nets, {}, known_power_rails={rail, vss}, source="test")


def _vd003(ctx):
    return [f for f in analyze_voltage_derating(ctx, {}) if f["rule_id"] == "VD-003"]


class ResistorToVss(unittest.TestCase):
    def test_vss_fed_from_a_negative_rail_is_not_rated_as_0_v(self):
        self.assertEqual(_vd003(_ctx("-2V5", "AVSS")), [])

    def test_vss_fed_from_a_positive_rail_stays_ground(self):
        (f,) = _vd003(_ctx("+3V3", "VSS"))
        self.assertEqual((f["severity"], f["voltage_across"]), ("error", 3.3))

    def test_vss_with_a_ground_symbol_stays_ground_beside_a_negative_rail(self):
        (f,) = _vd003(_ctx("-5V", "AVSS", ground_symbol=True))
        self.assertEqual((f["severity"], f["voltage_across"]), ("error", 5.0))

    def test_net_named_exactly_vss_is_0_v_by_its_name(self):
        (f,) = _vd003(_ctx("-5V", "VSS"))
        self.assertEqual((f["severity"], f["voltage_across"]), ("error", 5.0))


if __name__ == "__main__":
    unittest.main()
