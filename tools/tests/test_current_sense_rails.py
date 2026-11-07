# tools/tests/test_current_sense_rails.py
"""A low-value shunt between two named rails (VBAT -> VBAT_LOAD) is a current sense when a
current-sense amplifier reads across it. An op-amp's IN+/IN- across the same shunt is not."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
import signal_detectors as sd  # noqa: E402

RAILS = ("VBAT", "VBAT_LOAD", "+3V3", "GND")


def _ctx(components, nets):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    for c in components:
        c.setdefault("lib_id", "")
        c.setdefault("pins", [])
        c.setdefault("footprint", "")
    return build_analysis_context(components, full, {}, known_power_rails=set(RAILS))


def _p(ref, pin):
    return (ref, pin, "~", "passive")


def _sense(ctx):
    return [(c["shunt"]["ref"], c["sense_ic"]["ref"]) for c in sd.detect_current_sense(ctx)]


def _across(value, lib_id, shunt="0.1"):
    # U1's inputs sit directly on the two rails the shunt joins
    comps = [{"reference": "U1", "type": "ic", "value": value, "lib_id": lib_id},
             {"reference": "R1", "type": "resistor", "value": shunt}]
    nets = {"VBAT": [_p("R1", "1"), ("U1", "1", "IN+", "input")],
            "VBAT_LOAD": [_p("R1", "2"), ("U1", "2", "IN-", "input")],
            "+3V3": [("U1", "3", "VS", "power_in")],
            "GND": [("U1", "4", "GND", "power_in")]}
    return _ctx(comps, nets)


def _through_filter(value, lib_id):
    # U1's IN- reaches the load rail through a 10 ohm input filter resistor
    comps = [{"reference": "U1", "type": "ic", "value": value, "lib_id": lib_id},
             {"reference": "R1", "type": "resistor", "value": "0.05"},
             {"reference": "R2", "type": "resistor", "value": "10"}]
    nets = {"VBAT": [_p("R1", "1"), ("U1", "1", "IN+", "input")],
            "VBAT_LOAD": [_p("R1", "2"), _p("R2", "1")],
            "SENSE_N": [_p("R2", "2"), ("U1", "2", "IN-", "input")],
            "+3V3": [("U1", "3", "VS", "power_in")],
            "GND": [("U1", "4", "GND", "power_in")]}
    return _ctx(comps, nets)


def _with_ballast():
    # R5 is an LED ballast on the measured rail; only R1 sits between U1's inputs
    comps = [{"reference": "U1", "type": "ic", "value": "INA219", "lib_id": "Analog_ADC:INA219AxD"},
             {"reference": "R1", "type": "resistor", "value": "0.1"},
             {"reference": "R5", "type": "resistor", "value": "0.22"}]
    nets = {"VBAT": [_p("R1", "1"), _p("R5", "1"), ("U1", "1", "IN+", "input")],
            "VBAT_LOAD": [_p("R1", "2"), ("U1", "2", "IN-", "input")],
            "LED_A": [_p("R5", "2")],
            "+3V3": [("U1", "3", "VS", "power_in")],
            "GND": [("U1", "4", "GND", "power_in")]}
    return _ctx(comps, nets)


class ShuntBetweenRails(unittest.TestCase):
    def test_sense_amplifier_across_two_rails_is_found(self):
        ctx = _across("INA219", "Analog_ADC:INA219AxD")
        self.assertEqual(_sense(ctx), [("R1", "U1")])

    def test_op_amp_across_two_rails_is_not_a_current_sense(self):
        self.assertEqual(_sense(_across("LM358", "Amplifier_Operational:LM358")), [])

    def test_zero_ohm_link_between_rails_is_not_a_shunt(self):
        self.assertEqual(_sense(_across("INA219", "Analog_ADC:INA219AxD", shunt="0")), [])

    def test_sense_amplifier_input_on_one_rail_is_found(self):
        self.assertEqual(_sense(_through_filter("INA219", "Analog_ADC:INA219AxD")),
                         [("R1", "U1")])

    def test_op_amp_input_on_one_rail_is_not_a_current_sense(self):
        self.assertEqual(_sense(_through_filter("LM358", "Amplifier_Operational:LM358")), [])

    def test_other_resistor_on_the_measured_rail_is_not_a_shunt(self):
        self.assertEqual(_sense(_with_ballast()), [("R1", "U1")])


if __name__ == "__main__":
    unittest.main()
