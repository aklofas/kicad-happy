"""LED series resistor: LR-001 and the LED audit take the resistor in the LED's own
current path; rescue-library diodes are not LEDs."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_core.classify import classify_component  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402


def _ctx(components, nets, rails=()):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name="", pin_type=t) for r, p, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    return build_analysis_context(components, full, {}, known_power_rails=set(rails))


def _led(ref, value="LED_RED"):
    return {"reference": ref, "type": "led", "value": value, "lib_id": "Device:LED"}


def _r(ref, value):
    return {"reference": ref, "type": "resistor", "value": value}


def _p(ref, pin, t="passive"):
    return (ref, pin, t)


# Device:LED pin 1 = K, pin 2 = A.

def _lr(ctx):
    from validation_detectors import validate_led_resistors
    return [f for f in validate_led_resistors(ctx) if f.get("rule_id") == "LR-001"]


def _audit(ctx, ref):
    from domain_detectors import audit_led_circuits
    return [f for f in audit_led_circuits(ctx, []) if f.get("rule_id") == "LA-AUD" and f["ref"] == ref][0]


class LR001(unittest.TestCase):
    def test_low_side_resistor_current(self):
        ctx = _ctx([_led("D1"), _r("R10", "47")],
                   {"+5V": [_p("D1", "2")], "N1": [_p("D1", "1"), _p("R10", "1")],
                    "GND": [_p("R10", "2")]}, {"+5V", "GND"})
        lr = _lr(ctx)
        # (5 V - 1.8 V red) / 47 Ohm = 68.1 mA, over 2 x 20 mA
        self.assertEqual([f["summary"] for f in lr if f["severity"] == "warning"],
                         ["LED D1: current too high (68mA via R10)"])
        self.assertNotIn("error", [f["severity"] for f in lr])

    def test_high_side_330r_is_quiet(self):
        ctx = _ctx([_led("D1"), _r("R1", "330")],
                   {"+5V": [_p("R1", "1")], "LED_A": [_p("R1", "2"), _p("D1", "2")],
                    "GND": [_p("D1", "1")]}, {"+5V", "GND"})
        self.assertEqual(_lr(ctx), [])

    def test_resistor_from_the_rail_to_ground_is_not_the_series_resistor(self):
        # D1 sits straight across +3V3/GND; R2 10k elsewhere on +3V3 limits nothing.
        ctx = _ctx([_led("D1"), _r("R2", "10k")],
                   {"+3V3": [_p("D1", "2"), _p("R2", "1")],
                    "GND": [_p("D1", "1"), _p("R2", "2")]}, {"+3V3", "GND"})
        self.assertEqual([f["summary"] for f in _lr(ctx)], ["LED D1: no current-limiting resistor found"])

    def test_resistor_to_a_transistor_is_present_and_current_unknown(self):
        ctx = _ctx([_led("D1"), _r("R1", "100"),
                    {"reference": "Q1", "type": "transistor", "value": "2N7002"}],
                   {"+5V": [_p("D1", "2")], "N1": [_p("D1", "1"), _p("R1", "1")],
                    "DRAIN": [_p("R1", "2"), _p("Q1", "3")], "GND": [_p("Q1", "2")]},
                   {"+5V", "GND"})
        self.assertEqual(_lr(ctx), [])

    def test_bleeder_across_the_led_is_ignored(self):
        # R2 47R sits across D1 (+5V to N1); taken as a series resistor it would read 68 mA.
        ctx = _ctx([_led("D1"), _r("R1", "1k"), _r("R2", "47"),
                    {"reference": "Q1", "type": "transistor", "value": "2N7002"}],
                   {"+5V": [_p("D1", "2"), _p("R2", "1")],
                    "N1": [_p("D1", "1"), _p("R2", "2"), _p("R1", "1")],
                    "DRAIN": [_p("R1", "2"), _p("Q1", "3")], "GND": [_p("Q1", "2")]},
                   {"+5V", "GND"})
        self.assertEqual(_lr(ctx), [])

    def test_led_node_named_like_a_rail(self):
        ctx = _ctx([_led("D1"), _r("R1", "47")],
                   {"+5V": [_p("R1", "1")], "VBUS_LED_A": [_p("R1", "2"), _p("D1", "2")],
                    "GND": [_p("D1", "1")]}, {"+5V", "GND"})
        # (5 - 1.8) / 47 = 68.1 mA through the resistor on the LED's own node
        self.assertEqual([f["summary"] for f in _lr(ctx) if f["severity"] == "warning"],
                         ["LED D1: current too high (68mA via R1)"])

    def test_dangling_led_keeps_its_missing_resistor_error(self):
        # Anode net holds nothing but D1; a 10k from GND to a rail is not its resistor.
        ctx = _ctx([_led("D1"), _r("R5", "10k")],
                   {"LED_A": [_p("D1", "2")], "GND": [_p("D1", "1"), _p("R5", "1")],
                    "+5V": [_p("R5", "2")]}, {"+5V", "GND"})
        self.assertEqual([f["summary"] for f in _lr(ctx)], ["LED D1: no current-limiting resistor found"])

    def test_resistor_network_on_the_led_node(self):
        ctx = _ctx([_led("D1"), {"reference": "RN1", "type": "resistor_network", "value": "1k"}],
                   {"+5V": [_p("D1", "2")], "N1": [_p("D1", "1"), _p("RN1", "1")],
                    "GND": [_p("RN1", "8")]}, {"+5V", "GND"})
        self.assertEqual(_lr(ctx), [])


class LedAudit(unittest.TestCase):
    def test_pull_up_on_the_supply_rail_is_not_the_series_resistor(self):
        # Anode on pin 1 (as some LED symbols number it), so the rail is scanned first.
        ctx = _ctx([_led("D1"), _r("R2", "10k"), _r("R1", "330"),
                    {"reference": "U1", "type": "ic", "value": "MCU"}],
                   {"+3V3": [_p("R2", "1"), _p("D1", "1"), _p("U1", "1", "power_in")],
                    "SDA": [_p("R2", "2"), _p("U1", "2", "bidirectional")],
                    "N1": [_p("D1", "2"), _p("R1", "1")],
                    "GPIO": [_p("R1", "2"), _p("U1", "3", "bidirectional")],
                    "GND": [_p("U1", "4", "power_in")]}, {"+3V3", "GND"})
        e = _audit(ctx, "D1")
        self.assertEqual(e["series_resistor"], {"ref": "R1", "ohms": 330.0})
        self.assertEqual(e["drive_method"], "resistor_limited")

    def test_led_string_sums_forward_voltage(self):
        ctx = _ctx([_led("D1"), _led("D2"), _led("D3"), _r("R1", "1k")],
                   {"+12V": [_p("D1", "2")], "N1": [_p("D1", "1"), _p("D2", "2")],
                    "N2": [_p("D2", "1"), _p("D3", "2")], "N3": [_p("D3", "1"), _p("R1", "1")],
                    "GND": [_p("R1", "2")]}, {"+12V", "GND"})
        e = _audit(ctx, "D1")
        self.assertEqual(e["series_resistor"]["ref"], "R1")
        # (12 V - 3 x 2.0 V red) / 1 kOhm = 6.0 mA
        self.assertEqual(e["estimated_current_mA"], 6.0)

    def test_bleeder_across_the_led_is_ignored(self):
        ctx = _ctx([_led("D1"), _r("R1", "330"), _r("R2", "47k")],
                   {"+5V": [_p("D1", "2"), _p("R2", "1")],
                    "N1": [_p("D1", "1"), _p("R2", "2"), _p("R1", "1")],
                    "GND": [_p("R1", "2")]}, {"+5V", "GND"})
        e = _audit(ctx, "D1")
        self.assertEqual(e["series_resistor"], {"ref": "R1", "ohms": 330.0})

    def test_gpio_on_the_other_node_stays_the_driver(self):
        ctx = _ctx([_led("D1"), _r("R1", "1k"), {"reference": "U1", "type": "ic", "value": "MCU"}],
                   {"STAT": [_p("D1", "2"), _p("U1", "5", "output")],
                    "N1": [_p("D1", "1"), _p("R1", "1")], "GND": [_p("R1", "2")]}, {"GND"})
        e = _audit(ctx, "D1")
        self.assertEqual((e["series_resistor"]["ref"], e.get("driver_source")), ("R1", "U1"))
        self.assertIsNone(e.get("supply_net"))  # ground is not the LED's supply

    def test_regulator_on_the_resistor_rail_is_not_the_driver(self):
        # +3V3 -> 62R -> LED -> open-drain ALERT pin of U1; U2 is the 3V3 regulator.
        ctx = _ctx([_led("D1"), _r("R6", "62"), {"reference": "U1", "type": "ic", "value": "STUSB4500"},
                    {"reference": "U2", "type": "ic", "value": "LDO"}],
                   {"+3V3": [_p("R6", "1"), _p("U2", "3", "power_out")],
                    "N1": [_p("R6", "2"), _p("D1", "2")],
                    "ALERT": [_p("D1", "1"), _p("U1", "19", "open_collector")]}, {"+3V3"})
        e = _audit(ctx, "D1")
        self.assertEqual((e["series_resistor"]["ref"], e.get("driver_source")), ("R6", "U1"))
        # (3.3 V - 2.0 V red) / 62 Ohm = 20.97 mA
        self.assertEqual(e["estimated_current_mA"], 21.0)

    def test_transistor_sunk_led_is_driven(self):
        ctx = _ctx([_led("D1"), {"reference": "Q1", "type": "transistor", "value": "2N7002"}],
                   {"+5V": [_p("D1", "2")], "N1": [_p("D1", "1"), _p("Q1", "3")],
                    "GND": [_p("Q1", "2")]}, {"+5V", "GND"})
        e = _audit(ctx, "D1")
        self.assertEqual((e["drive_method"], e.get("driver_source"), e.get("issue")),
                         ("ic_direct", "Q1", None))


class RescueDiodes(unittest.TestCase):
    def test_types(self):
        cases = [("LED_driver-rescue:D_Zener", "D_Zener", "diode"),
                 ("kiml-led-smd:0603_RED_KT-0603R", "0603_RED", "led"),
                 ("Device:LED", "LED", "led"),
                 ("LED:IR204A", "IR204A", "led")]
        for lib_id, value, want in cases:
            self.assertEqual(classify_component("D1", lib_id, value), want, lib_id)


if __name__ == "__main__":
    unittest.main()
