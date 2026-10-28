import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_core.netnames import is_power_net_name  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from validation_detectors import _estimate_rail_voltage_for_ic, validate_voltage_levels  # noqa: E402


class NegativeDecimalPrefixedRails(unittest.TestCase):
    # Each name is a rail in a corpus design: a negative supply, a decimal voltage,
    # a conventional supply pin name, or a voltage behind a domain prefix.
    def test_negative_rails(self):
        for name in ["-12V", "-5V_F", "-114V", "-15V", "-BATT", "-BAT", "-VIN", "-2V5",
                     "/Analog/-12V"]:
            self.assertTrue(is_power_net_name(name), name)

    def test_decimal_rails(self):
        for name in ["3.3V", "5.5V", "2.5V", "3.3V_OUT", "1.25V_REF", "/Power/3.3V"]:
            self.assertTrue(is_power_net_name(name), name)

    def test_supply_pin_names(self):
        for name in ["VPP", "VM", "/Motors/Vm", "VEE", "VNEG"]:
            self.assertTrue(is_power_net_name(name), name)

    def test_prefixed_rails(self):
        for name in ["MCU3v3", "AVDD1V8_PLL", "D+5V", "CAN+5V"]:
            self.assertTrue(is_power_net_name(name), name)


class SignalsStaySignals(unittest.TestCase):
    def test_ground_and_control_lines(self):
        for name in ["0V", "0.0V", "5VEN", "12VPG", "PWM_5V", "EN_5V", "TX_3V3",
                     "3.3V_EN", "-12V_PG", "-5VEN", "3.3VPG"]:
            self.assertFalse(is_power_net_name(name), name)

    def test_active_low_and_control_prefixed_names(self):
        # A leading '-' is also an active-low mark (-RESET, -CS); a control prefix glued
        # to a voltage (PWM3V3, EN1V8) names a signal about the rail.
        for name in ["-RESET", "-CS", "-WR", "-IN", "PWM3V3", "EN1V8", "IO3V3", "TX+5V",
                     "PWRGD1V2", "PG3V3", "SWDIO1V8", "VSNS5V0_P"]:
            self.assertFalse(is_power_net_name(name), name)

    def test_logic_signals_named_after_their_level(self):
        # Level-shifted signals named <level>_<signal> (corpus: 3.3V_SDA, 3.3V_RC_DIR).
        for name in ["3.3V_SDA", "3.3V_SCL", "3.3V_TX", "1.8V_RC_DIR", "3.3VCTL"]:
            self.assertFalse(is_power_net_name(name), name)


def _ctx(components, nets):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    return build_analysis_context(components, full, {}, known_power_rails=set())


class NegativeRailIsNotALogicDomain(unittest.TestCase):
    # An op-amp on +5 V / -12 V drives a 5 V MCU: its logic swing is set by the positive
    # supply, so its negative rail (now a power net) must not make it a 12 V IC.
    def test_split_supply_ic_takes_its_positive_rail(self):
        comps = [{"reference": "U1", "type": "ic", "value": "TL072"},
                 {"reference": "U2", "type": "ic", "value": "ATMEGA328P"}]
        nets = {"-12V": [("U1", "4", "V-", "power_in")],
                "+5V": [("U1", "8", "V+", "power_in"), ("U2", "7", "VCC", "power_in")],
                "GND": [("U2", "8", "GND", "power_in")],
                "SIG": [("U1", "1", "OUT", "output"), ("U2", "23", "PC0", "bidirectional")]}
        ctx = _ctx(comps, nets)
        self.assertEqual(_estimate_rail_voltage_for_ic(ctx, "U1"), 5.0)
        self.assertEqual([f for f in validate_voltage_levels(ctx) if f["rule_id"] == "VM-001"], [])

    def test_negative_only_ic_keeps_its_magnitude(self):
        comps = [{"reference": "U1", "type": "ic", "value": "MC10H116"}]
        nets = {"-5.2V": [("U1", "8", "VEE", "power_in")]}
        self.assertEqual(_estimate_rail_voltage_for_ic(_ctx(comps, nets), "U1"), 5.2)


if __name__ == "__main__":
    unittest.main()
