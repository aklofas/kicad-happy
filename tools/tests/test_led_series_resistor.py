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
        # (5 V - 2.0 V red) / 47 Ohm = 63.8 mA, over 2 x 20 mA
        self.assertEqual([f["summary"] for f in lr if f["severity"] == "warning"],
                         ["LED D1: current too high (64mA via R10)"])
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
        # (5 - 2.0) / 47 = 63.8 mA through the resistor on the LED's own node
        self.assertEqual([f["summary"] for f in _lr(ctx) if f["severity"] == "warning"],
                         ["LED D1: current too high (64mA via R1)"])

    def test_dangling_led_keeps_its_missing_resistor_error(self):
        # Anode net holds nothing but D1; a 10k from GND to a rail is not its resistor.
        # No IC or transistor sits on GND here: one there still silences the error.
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


def _string(top_r, r="1k"):
    """+12V -> D1 -> D2 -> D3 -> GND with R1 at the top or the bottom of the string."""
    comps = [_led("D1"), _led("D2"), _led("D3"), _r("R1", r)]
    if top_r:
        nets = {"+12V": [_p("R1", "1")], "N0": [_p("R1", "2"), _p("D1", "2")],
                "N1": [_p("D1", "1"), _p("D2", "2")], "N2": [_p("D2", "1"), _p("D3", "2")],
                "GND": [_p("D3", "1")]}
    else:
        nets = {"+12V": [_p("D1", "2")], "N1": [_p("D1", "1"), _p("D2", "2")],
                "N2": [_p("D2", "1"), _p("D3", "2")], "N3": [_p("D3", "1"), _p("R1", "1")],
                "GND": [_p("R1", "2")]}
    return _ctx(comps, nets, {"+12V", "GND"})


def _shared_led_node(rail_symbol):
    """+5V -> R1 330R -> +5V_LED -> D1..D4 -> GND (parallel LEDs on one resistor)."""
    leds = [_led(f"D{i}") for i in range(1, 5)]
    nets = {"+5V": [_p("R1", "1")], "+5V_LED": [_p("R1", "2")] + [_p(f"D{i}", "2") for i in range(1, 5)],
            "GND": [_p(f"D{i}", "1") for i in range(1, 5)]}
    rails = {"+5V", "GND"} | ({"+5V_LED"} if rail_symbol else set())
    return _ctx(leds + [_r("R1", "330")], nets, rails)


class LedStrings(unittest.TestCase):
    def test_every_led_in_a_string_gets_the_string_current(self):
        for top_r in (True, False):
            ctx = _string(top_r)
            # (12 V - 3 x 2.0 V red) / 1 kOhm = 6.0 mA for each LED
            self.assertEqual([_audit(ctx, d).get("estimated_current_mA") for d in ("D1", "D2", "D3")],
                             [6.0, 6.0, 6.0], top_r)
            self.assertEqual([_audit(ctx, d)["series_resistor"]["ref"] for d in ("D1", "D2", "D3")],
                             ["R1"] * 3, top_r)

    def test_upper_leds_of_a_string_have_their_resistor(self):
        for top_r in (True, False):
            self.assertEqual(_lr(_string(top_r)), [], top_r)

    def test_string_current_in_lr001(self):
        for top_r in (True, False):
            lr = _lr(_string(top_r, r="100"))
            # (12 V - 3 x 2.0 V red) / 100 Ohm = 60 mA, over 2 x 20 mA, for each LED
            self.assertEqual(sorted(f["summary"] for f in lr if f["severity"] == "warning"),
                             [f"LED D{i}: current too high (60mA via R1)" for i in (1, 2, 3)], top_r)
            # P = 0.060^2 x 100 = 360 mW, reported once for the string
            self.assertEqual([f["summary"] for f in lr if f["severity"] == "info"],
                             ["LED resistor R1: power dissipation 360mW"], top_r)


    def test_dissipation_once_when_string_leds_number_pins_differently(self):
        # +12V -> R1 100R -> D1 -> D2 -> GND, D2 with its anode on pin 1.
        ctx = _ctx([_led("D1"), _led("D2"), _r("R1", "100")],
                   {"+12V": [_p("R1", "1")], "N0": [_p("R1", "2"), _p("D1", "2")],
                    "N1": [_p("D1", "1"), _p("D2", "1")], "GND": [_p("D2", "2")]}, {"+12V", "GND"})
        # (12 V - 2 x 2.0 V) / 100 Ohm = 80 mA; P = 0.080^2 x 100 = 640 mW
        self.assertEqual([f["summary"] for f in _lr(ctx) if f["severity"] == "info"],
                         ["LED resistor R1: power dissipation 640mW"])


def _named_ctx(components, nets, rails):
    """Like _ctx, with a pin written (ref, number, name)."""
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=nm, pin_type="passive")
                                    for r, p, nm in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    return build_analysis_context(components, full, {}, known_power_rails=set(rails))


_IC = {"reference": "U1", "type": "ic", "value": "MCU", "lib_id": "MCU:Chip"}


class LedAcrossSupply(unittest.TestCase):
    def test_led_straight_across_a_supply_is_reported_beside_an_ic(self):
        ctx = _named_ctx([_led("D1"), _IC],
                         {"+5V": [("D1", "2", "A"), ("U1", "1", "VDD")],
                          "GND": [("D1", "1", "K"), ("U1", "2", "VSS")]}, {"+5V", "GND"})
        self.assertEqual([(f["severity"], f["summary"]) for f in _lr(ctx)],
                         [("error", "LED D1: no current-limiting resistor found")])

    def test_led_driven_by_an_ic_sink_has_no_error(self):
        ctx = _named_ctx([_led("D1"), _IC],
                         {"+5V": [("D1", "2", "A")], "SINK": [("D1", "1", "K"), ("U1", "3", "OUT")],
                          "GND": [("U1", "2", "VSS")]}, {"+5V", "GND"})
        self.assertEqual(_lr(ctx), [])

    def test_cathode_on_the_rail_is_silent(self):
        ctx = _named_ctx([_led("D1"), _IC],
                         {"+5V": [("D1", "1", "K"), ("U1", "1", "VDD")],
                          "GND": [("D1", "2", "A"), ("U1", "2", "VSS")]}, {"+5V", "GND"})
        self.assertEqual(_lr(ctx), [])

    def test_rail_without_a_power_symbol_is_silent(self):
        ctx = _named_ctx([_led("D1"), _IC],
                         {"+5V": [("D1", "2", "A"), ("U1", "1", "VDD")],
                          "GND": [("D1", "1", "K"), ("U1", "2", "VSS")]}, {"GND"})
        self.assertEqual(_lr(ctx), [])

    def test_three_pin_led_is_silent(self):
        led = _led("D1", "LED_RGB")
        ctx = _named_ctx([led, _IC],
                         {"+5V": [("D1", "2", "A"), ("U1", "1", "VDD")],
                          "GND": [("D1", "1", "K"), ("U1", "2", "VSS")], "N3": [("D1", "3", "K2")]},
                         {"+5V", "GND"})
        self.assertEqual(_lr(ctx), [])

    def test_led_with_an_unconnected_pin_stays_silenced_by_an_ic_on_ground(self):
        ctx = _named_ctx([_led("D1"), _IC],
                         {"+5V": [("D1", "2", "A")], "GND": [("U1", "2", "VSS")]}, {"+5V", "GND"})
        self.assertEqual(_lr(ctx), [])


def _parallel(n, ohms="100", anti=False):
    """+12V -> R1 -> node -> n LEDs -> GND; with anti, one more LED the other way round."""
    leds = [_led(f"D{i}") for i in range(1, n + 1)]
    pins_node = [_p("R1", "2")] + [_p(f"D{i}", "2") for i in range(1, n + 1)]
    pins_gnd = [_p(f"D{i}", "1") for i in range(1, n + 1)]
    if anti:
        leds.append(_led("D9"))
        pins_node.append(_p("D9", "1"))
        pins_gnd.append(_p("D9", "2"))
    return _ctx(leds + [_r("R1", ohms)],
                {"+12V": [_p("R1", "1")], "N0": pins_node, "GND": pins_gnd}, {"+12V", "GND"})


class ParallelStrings(unittest.TestCase):
    def test_two_leds_share_the_resistor_current(self):
        lr = _lr(_parallel(2))
        # (12 V - 2.0 V) / 100 Ohm = 100 mA in R1, 50 mA each
        self.assertEqual(sorted(f["summary"] for f in lr if f["severity"] == "warning"),
                         ["LED D1: current too high (50mA via R1)", "LED D2: current too high (50mA via R1)"])
        # the resistor dissipates 0.1^2 x 100 = 1000 mW, once
        self.assertEqual([f["summary"] for f in lr if f["severity"] == "info"],
                         ["LED resistor R1: power dissipation 1000mW"])

    def test_three_leds_in_parallel_are_under_the_limit(self):
        lr = _lr(_parallel(3))
        self.assertEqual([f["summary"] for f in lr if f["severity"] == "warning"], [])

    def test_anti_parallel_led_keeps_the_full_resistor_current(self):
        lr = _lr(_parallel(1, anti=True))
        self.assertEqual(sorted(f["summary"] for f in lr if f["severity"] == "warning"),
                         ["LED D1: current too high (100mA via R1)",
                          "LED D9: current too high (100mA via R1)"])


class SharedLedNode(unittest.TestCase):
    def test_power_named_led_node_is_not_a_rail(self):
        from detector_helpers import is_led_rail
        self.assertFalse(is_led_rail(_shared_led_node(False), "+5V_LED"))
        ctx = _shared_led_node(False)
        self.assertEqual(_lr(ctx), [])
        e = _audit(ctx, "D1")
        self.assertEqual((e["drive_method"], e["series_resistor"]["ref"]), ("resistor_limited", "R1"))

    def test_power_symbol_rail_feeding_leds_stays_a_rail(self):
        from detector_helpers import is_led_rail
        self.assertTrue(is_led_rail(_shared_led_node(True), "+5V_LED"))


class LedNodeNeedsItsResistor(unittest.TestCase):
    def test_leds_with_a_pull_up_to_a_signal_are_a_rail(self):
        from detector_helpers import is_led_rail
        leds = [_led(f"D{i}") for i in range(1, 4)]
        ctx = _ctx(leds + [_r("R9", "10k")],
                   {"+3V3": [_p(f"D{i}", "2") for i in range(1, 4)] + [_p("R9", "1")],
                    "SIG": [_p("R9", "2")], "GND": [_p(f"D{i}", "1") for i in range(1, 4)]}, {"GND"})
        self.assertTrue(is_led_rail(ctx, "+3V3"))

    def test_leds_alone_on_a_power_named_net_are_a_rail(self):
        from detector_helpers import is_led_rail
        leds = [_led(f"D{i}") for i in range(1, 5)]
        ctx = _ctx(leds, {"+3V3": [_p(f"D{i}", "2") for i in range(1, 5)],
                          "GND": [_p(f"D{i}", "1") for i in range(1, 5)]}, {"GND"})
        self.assertTrue(is_led_rail(ctx, "+3V3"))

    def test_resistor_to_ground_keeps_the_node_an_led_node(self):
        from detector_helpers import is_led_rail
        leds = [_led(f"D{i}") for i in range(1, 4)]
        ctx = _ctx(leds + [_r("R1", "330")],
                   {"VLED": [_p(f"D{i}", "2") for i in range(1, 4)] + [_p("R1", "1")],
                    "GND": [_p(f"D{i}", "1") for i in range(1, 4)] + [_p("R1", "2")]}, {"GND"})
        self.assertFalse(is_led_rail(ctx, "VLED"))


class ChainWalk(unittest.TestCase):
    def test_led_gets_its_own_resistor_not_a_parallel_branchs(self):
        # D1 and D2 share the anode node NODE (driven by U1); D2 has R2 on its cathode.
        ctx = _ctx([_led("D1"), _led("D2"), _r("R2", "330"),
                    {"reference": "U1", "type": "ic", "value": "MCU"}],
                   {"NODE": [_p("D1", "2"), _p("D2", "2"), _p("U1", "1", "output")],
                    "N2": [_p("D2", "1"), _p("R2", "1")],
                    "GND": [_p("D1", "1"), _p("R2", "2")]}, {"GND"})
        e = _audit(ctx, "D1")
        self.assertNotEqual(e["drive_method"], "resistor_limited")
        self.assertEqual(_audit(ctx, "D2")["series_resistor"]["ref"], "R2")

    def test_series_parallel_array_keeps_its_resistor(self):
        # +5V - R1 - N0; D1, D2 on N0; D3 in series after D1, D4 after D2.
        ctx = _ctx([_led(f"D{i}") for i in range(1, 5)] + [_r("R1", "220")],
                   {"+5V": [_p("R1", "1")], "N0": [_p("R1", "2"), _p("D1", "2"), _p("D2", "2")],
                    "N1": [_p("D1", "1"), _p("D3", "2")], "N2": [_p("D2", "1"), _p("D4", "2")],
                    "GND": [_p("D3", "1"), _p("D4", "1")]}, {"+5V", "GND"})
        for d in ("D3", "D4"):
            self.assertEqual(_audit(ctx, d)["series_resistor"]["ref"], "R1", d)

    def test_series_leds_with_a_test_point_keep_the_far_resistor(self):
        tp = {"reference": "TP1", "type": "other", "value": "TestPoint"}
        ctx = _ctx([_led("D1"), _led("D2"), _r("R1", "470"), tp],
                   {"+12V": [_p("R1", "1")], "N0": [_p("R1", "2"), _p("D1", "2")],
                    "N1": [_p("D1", "1"), _p("D2", "2"), _p("TP1", "1")],
                    "GND": [_p("D2", "1")]}, {"+12V", "GND"})
        self.assertEqual(_audit(ctx, "D2")["series_resistor"]["ref"], "R1")


class DriveMethod(unittest.TestCase):
    def test_unparsed_resistor_before_transistor(self):
        ctx = _ctx([_led("D1"), _r("R1", "R"), {"reference": "Q1", "type": "transistor", "value": "2N7002"}],
                   {"+5V": [_p("R1", "1")], "N1": [_p("R1", "2"), _p("D1", "2")],
                    "N2": [_p("D1", "1"), _p("Q1", "3")], "GND": [_p("Q1", "2")]}, {"+5V", "GND"})
        e = _audit(ctx, "D1")
        self.assertEqual((e["drive_method"], e.get("issue")), ("resistor_unparsed", "has_resistor_unparsed_value"))

    def test_ic_on_ground_without_a_power_symbol_is_not_the_driver(self):
        # U1 STAT -> LED -> 1k -> GND, U2 on GND; no power symbols anywhere.
        ctx = _ctx([_led("D1"), _r("R1", "1k"), {"reference": "U1", "type": "ic", "value": "CHG"},
                    {"reference": "U2", "type": "ic", "value": "MCU"}],
                   {"STAT": [_p("D1", "2"), _p("U1", "5", "open_collector")],
                    "N1": [_p("D1", "1"), _p("R1", "1")],
                    "GND": [_p("R1", "2"), _p("U2", "8", "power_in")]})
        self.assertEqual(_audit(ctx, "D1").get("driver_source"), "U1")


def _audit_low_side(ohms, ref_type="resistor"):
    r = _r("R1", ohms)
    r["type"] = ref_type
    return _audit(_ctx([_led("D1"), r],
                       {"+5V": [_p("D1", "2")], "N1": [_p("D1", "1"), _p("R1", "1")],
                        "GND": [_p("R1", "2")]}, {"+5V", "GND"}), "D1")


class TypedResistorRead(unittest.TestCase):
    def test_value_with_a_package_suffix_is_read(self):
        for value, ohms in (("1k_0402", 1000), ("330R_0603", 330), ("4k7", 4700)):
            with self.subTest(value=value):
                e = _audit_low_side(value)
                self.assertEqual(e["drive_method"], "resistor_limited")
                self.assertEqual(e["series_resistor"]["ohms"], ohms)

    def test_resistor_network_keeps_the_untyped_read(self):
        e = _audit_low_side("1k_0402", ref_type="resistor_network")
        self.assertEqual(e["drive_method"], "resistor_unparsed")


def _low_side(value, rail="+5V", ohms="47"):
    return _ctx([_led("D1", value), _r("R1", ohms)],
                {rail: [_p("D1", "2")], "N1": [_p("D1", "1"), _p("R1", "1")],
                 "GND": [_p("R1", "2")]}, {rail, "GND"})


class LedForwardVoltage(unittest.TestCase):
    def test_resistor_check_and_led_audit_read_the_same_vf(self):
        ctx = _low_side("LED_RED")
        # (5 V - 2.0 V red) / 47 Ohm = 63.8 mA in both checks
        self.assertEqual(_audit(ctx, "D1")["estimated_current_mA"], 63.8)
        self.assertEqual([f["summary"] for f in _lr(ctx) if f["severity"] == "warning"],
                         ["LED D1: current too high (64mA via R1)"])

    def test_bare_green_is_the_ingan_nominal(self):
        ctx = _low_side("LED_GREEN")
        # (5 V - 3.2 V) / 47 Ohm = 38.3 mA: under 2 x 20 mA, no over-current warning
        self.assertEqual(_audit(ctx, "D1")["estimated_current_mA"], 38.3)
        self.assertEqual([f for f in _lr(ctx) if f["severity"] == "warning"], [])

    def test_bare_green_keeps_the_gap_floor(self):
        from domain_detectors import audit_led_circuits
        la004 = [f for f in audit_led_circuits(_low_side("LED_GREEN", rail="+1V8"), [])
                 if f.get("rule_id") == "LA-004"]
        self.assertEqual([(f["color"], f["color_vf_floor"]) for f in la004], [("green", 2.1)])

    def test_ir_starts_a_word(self):
        from detector_helpers import led_forward_voltage
        from kicad_core.parts import led_color
        cases = [({"value": "LED_IR", "lib_id": "Device:LED"}, "ir"),
                 ({"value": "IR204A", "lib_id": "LED:IR204A"}, "ir"),
                 ({"value": "IR LED", "lib_id": "Device:LED"}, "ir"),
                 ({"value": "LED", "lib_id": "easyEDA:XYC-IRA3212A25-X4_smaller"}, "ir"),
                 ({"value": "SFH 4556", "lib_id": "LED:IRL81A"}, "ir"),
                 ({"value": "rgbled kira", "lib_id": "Device:LED"}, None),
                 ({"value": "wiring", "lib_id": "Device:LED"}, None),
                 ({"value": "IRQ", "lib_id": "Device:LED"}, None),
                 ({"value": "LED Diode",
                   "lib_id": "test-altium-import:ROOT_0_LED Diode_IRNAS_MPPT LT3652.SchLib"}, None),
                 ({"value": "LED_bidirectional", "lib_id": "Device:LED"}, None),
                 # a library nickname is not part of the part's name
                 ({"value": "SK6812MINI-E", "lib_id": "irex_led:SK6805MINI-E"}, None)]
        for comp, want in cases:
            self.assertEqual(led_color(comp), want, comp["value"])
        self.assertEqual(led_forward_voltage({"value": "LED_IR", "lib_id": "Device:LED"}), 1.2)
        self.assertEqual(led_forward_voltage({"value": "SFH 4556", "lib_id": "LED:IRL81A"}), 1.2)
        self.assertEqual(led_forward_voltage({"value": "rgbled kira", "lib_id": "Device:LED"}), 2.0)


class LedColourWords(unittest.TestCase):
    """The colour is a whole word of the value (then of the symbol name), not a substring."""

    def test_colour_words(self):
        from kicad_core.parts import led_color
        cases = [({"value": "Infrared", "lib_id": "Device:LED"}, "ir"),
                 ({"value": "LED", "lib_id": "LED:LED_Infrared"}, "ir"),
                 ({"value": "Ultraviolet", "lib_id": "Device:LED"}, "uv"),
                 ({"value": "Green", "lib_id": "MyLib:LED_Red_0805"}, "green"),
                 ({"value": "LED", "lib_id": "1-altium-import:root_3_mirrored_LED"}, None),
                 ({"value": "LED", "lib_id": "shared:LED"}, None),
                 ({"value": "Bluetooth", "lib_id": "Device:LED"}, None),
                 ({"value": "Redundant", "lib_id": "Device:LED"}, None),
                 ({"value": "Pump UVLO", "lib_id": "Device:LED"}, None),
                 ({"value": "wiring", "lib_id": "Device:LED"}, None),
                 ({"value": "LTST-C190KRKT", "lib_id": "Device:LED"}, None),
                 ({"value": "0603_WHITE", "lib_id": "Lib:0603_GREEN"}, "white"),
                 ({"value": "LEDRED", "lib_id": "Device:LED"}, "red"),
                 ({"value": "BlueLED", "lib_id": "Device:LED"}, "blue"),
                 ({"value": "PCAmber", "lib_id": "Device:LED"}, "amber"),
                 ({"value": "warmWhite", "lib_id": "Device:LED"}, "white"),
                 ({"value": "greenled", "lib_id": "Device:LED"}, "green"),
                 ({"value": "YellowLED", "lib_id": "Device:LED"}, "yellow"),
                 ({"value": "LED", "lib_id": "Device:LED_0805_Blue"}, "blue"),
                 ({"value": "IR204A", "lib_id": "LED:IR204A"}, "ir"),
                 ({"value": "Yellow-Green", "lib_id": "Device:LED"}, "yellow")]
        for comp, want in cases:
            self.assertEqual(led_color(comp), want, comp)


class AddressableLeds(unittest.TestCase):
    """A WS2812/SK6812/APA102-style LED regulates its own current from its supply pins:
    neither LR-001 nor the LED audit asks it for a series resistor."""

    def _strip(self, ref, value, lib_id):
        # VDD, DOUT, VSS, DIN on a 5 V rail, no resistor anywhere.
        led = {"reference": ref, "type": "led", "value": value, "lib_id": lib_id}
        return _ctx([led], {"+5V": [_p(ref, "1", "power_in")], "DOUT": [_p(ref, "2", "output")],
                            "GND": [_p(ref, "3", "power_in")], "DIN": [_p(ref, "4", "input")]},
                    {"+5V", "GND"})

    def test_addressable_leds_get_no_lr001(self):
        cases = [("SLED1", "SK6803 MINI-E", "BFS9000:LED_SK6803MINI_E"),
                 ("D1", "WS2812B", "LED:WS2812B"),
                 ("LED1", "APA102-2020", "MyLib:APA102"),
                 ("D2", "LED", "LED:SK6812MINI")]
        for ref, value, lib_id in cases:
            self.assertEqual(_lr(self._strip(ref, value, lib_id)), [], value)

    def test_addressable_leds_get_no_led_audit(self):
        from domain_detectors import audit_led_circuits
        ctx = self._strip("SLED1", "SK6803 MINI-E", "BFS9000:LED_SK6803MINI_E")
        self.assertEqual([f for f in audit_led_circuits(ctx, []) if f.get("ref") == "SLED1"], [])

    def test_plain_led_without_a_resistor_keeps_its_error(self):
        ctx = _ctx([_led("D1", "RED")], {"+5V": [_p("D1", "2")], "GND": [_p("D1", "1")]},
                   {"+5V", "GND"})
        self.assertEqual([f["summary"] for f in _lr(ctx)], ["LED D1: no current-limiting resistor found"])


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
