"""PWR, POWER, V1+ / V2- and a switched rail (5V_ON) are rails only when a power pin of a
real part sits on the net: a bare PWR is often a power button or power-LED line, V1+ a
meter's sense input, and 5V_ON alone an enable. A power symbol or flag pin does not count,
and the gate never admits a name that reads as a signal about a rail (PWR_ON, PWR_LED)."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_core.netnames import is_pin_gated_rail_name, is_power_net_name  # noqa: E402
from kicad_types import build_analysis_context, pin_gated_rail_nets  # noqa: E402


def _pin(ref, num, name, pin_type):
    return dict(component=ref, pin_number=num, pin_name=name, pin_type=pin_type)


def _part(ref, typ, value, lib_id, pin_names):
    return {"reference": ref, "type": typ, "value": value, "lib_id": lib_id, "footprint": "",
            "properties": {}, "pins": [{"number": n, "name": nm} for n, nm in pin_names]}


R1 = _part("R1", "resistor", "165", "Device:R", [("1", "~"), ("2", "~")])
D1 = _part("D1", "led", "LED", "Device:LED", [("1", "K"), ("2", "A")])
U_LOGIC = _part("U1", "ic", "74HC244", "74xx:74HC244", [("20", "VCC"), ("10", "GND")])
U_METER = _part("U2", "ic", "MCP39F501", "Analog:MCP39F501", [("1", "V1+")])
U_OPAMP = _part("U3", "ic", "TL072", "Amplifier_Operational:TL072", [("8", "V+")])
U_SWITCH = _part("U4", "ic", "BTS7008", "Power_Management:BTS7008", [("5", "OUT0")])
Q1 = _part("Q1", "transistor", "2N7002", "Transistor_FET:2N7002", [("1", "G")])
PWR_SYM = _part("#PWR01", "power_symbol", "PWR", "power:PWR", [("1", "PWR")])
FLAG = _part("#FLG01", "power_flag", "PWR_FLAG", "power:PWR_FLAG", [("1", "pwr")])

LED_LINE = [_pin("R1", "2", "~", "passive"), _pin("D1", "2", "A", "passive")]
LOGIC_VCC = _pin("U1", "20", "VCC", "power_in")


def _ctx(comps, net, pins):
    nets = {n: {"name": n, "pins": ps, "point_count": 0, "no_connect": False,
                "has_pwr_flag": False, "labels": []}
            for n, ps in {net: pins, "GND": [_pin("U1", "10", "GND", "power_in")]}.items()}
    return build_analysis_context(comps, nets, {}, known_power_rails={"GND"}, source="test")


class GatedNames(unittest.TestCase):
    def test_gated_forms(self):
        for name in ("PWR", "POWER", "Power", "/power/PWR", "V1+", "V2-", "V12+", "5V_ON",
                     "3V3_OFF", "12VON", "3V3_POWER_ON", "VCC_ON", "5V ON"):
            with self.subTest(name=name):
                self.assertTrue(is_pin_gated_rail_name(name))
                self.assertFalse(is_power_net_name(name))

    def test_signal_names_are_not_gated(self):
        for name in ("PWR_ON", "POWER_ON", "PWR_LED", "PWR_LED_ON", "POWER_GOOD", "PWR_EN",
                     "PWR_OK", "V3H-", "V1H+", "V1", "V1P", "5V_ON_LED", "EN_ON", "VBAT_ADC_ON",
                     "PWRON", "", None):
            with self.subTest(name=name):
                self.assertFalse(is_pin_gated_rail_name(name))


class PowerPinGate(unittest.TestCase):
    def test_bare_pwr_on_a_led_line_is_not_a_rail(self):
        ctx = _ctx([R1, D1, U_LOGIC], "PWR", list(LED_LINE))
        self.assertFalse(ctx.is_power_net("PWR"))
        self.assertEqual(ctx.pin_gated_rails, frozenset())

    def test_bare_pwr_with_a_logic_supply_pin_is_a_rail(self):
        ctx = _ctx([R1, D1, U_LOGIC], "PWR", LED_LINE + [LOGIC_VCC])
        self.assertTrue(ctx.is_power_net("PWR"))
        self.assertEqual(ctx.pin_gated_rails, {"PWR"})

    def test_only_the_pin_reading_admits_it(self):
        ctx = _ctx([R1, D1, U_LOGIC], "PWR", LED_LINE + [LOGIC_VCC])
        self.assertFalse(ctx.is_power_net("PWR", by_pins=False))

    def test_power_on_a_mosfet_gate_is_not_a_rail(self):
        ctx = _ctx([Q1, U_LOGIC], "POWER", [_pin("Q1", "1", "G", "input")])
        self.assertFalse(ctx.is_power_net("POWER"))

    def test_pwr_on_stays_an_enable_with_a_power_pin(self):
        ctx = _ctx([U_LOGIC], "PWR_ON", [LOGIC_VCC])
        self.assertFalse(ctx.is_power_net("PWR_ON"))

    def test_signal_tails_stay_signals_with_a_power_pin(self):
        for net in ("PWR_LED", "POWER_GOOD", "PWR_EN"):
            with self.subTest(net=net):
                ctx = _ctx([U_LOGIC], net, [LOGIC_VCC])
                self.assertFalse(ctx.is_power_net(net))

    def test_switched_rail_needs_a_power_pin(self):
        self.assertTrue(_ctx([U_LOGIC], "5V_ON", [LOGIC_VCC]).is_power_net("5V_ON"))
        self.assertFalse(_ctx([R1, D1, U_LOGIC], "5V_ON", list(LED_LINE)).is_power_net("5V_ON"))

    def test_meter_input_v1_plus_stays_a_signal(self):
        ctx = _ctx([U_METER, U_LOGIC], "V1+", [_pin("U2", "1", "V1+", "input")])
        self.assertFalse(ctx.is_power_net("V1+"))

    def test_opamp_supply_v1_plus_is_a_rail(self):
        ctx = _ctx([U_OPAMP, U_LOGIC], "V1+", [_pin("U3", "8", "V+", "power_in")])
        self.assertTrue(ctx.is_power_net("V1+"))

    def test_switch_output_v2_plus_is_a_rail(self):
        ctx = _ctx([U_SWITCH, U_LOGIC], "V2+", [_pin("U4", "5", "OUT0", "power_out")])
        self.assertTrue(ctx.is_power_net("V2+"))

    def test_heater_form_is_not_gated(self):
        ctx = _ctx([U_OPAMP, U_LOGIC], "V3H-", [_pin("U3", "8", "V+", "power_in")])
        self.assertFalse(ctx.is_power_net("V3H-"))

    def test_power_symbol_and_flag_pins_do_not_count(self):
        nets = {"PWR": {"pins": [_pin("#PWR01", "1", "PWR", "power_in"),
                                 _pin("#FLG01", "1", "pwr", "power_out")] + LED_LINE}}
        lookup = {c["reference"]: c for c in (PWR_SYM, FLAG, R1, D1)}
        self.assertEqual(pin_gated_rail_nets(nets, lookup), frozenset())

    def test_hash_reference_does_not_count_whatever_its_type(self):
        part = dict(PWR_SYM, type="ic")
        nets = {"PWR": {"pins": [_pin("#PWR01", "1", "PWR", "power_in")]}}
        self.assertEqual(pin_gated_rail_nets(nets, {"#PWR01": part}), frozenset())


if __name__ == "__main__":
    unittest.main()
