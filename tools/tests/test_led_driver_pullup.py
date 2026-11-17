# tools/tests/test_led_driver_pullup.py
"""A transistor drives an LED through the LED's series resistor: the resistor's far end is
the LED. A resistor from the drain or collector to a supply rail (or to ground) is a pull-up
(pull-down); an LED elsewhere on that rail is not driven by the transistor."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
import signal_detectors as sd  # noqa: E402
import domain_detectors as dd  # noqa: E402

RAILS = ("VCC", "GND")


def _driver(nets, kind="mosfet", load_net="DRAIN", rails=RAILS, audit=False, pchannel=False):
    """nets: {net: [(ref, pin, pin_name)]}; parts are typed by their reference letter.
    Returns the led_driver block the enrichment gives the transistor Q1, or None."""
    types = {"Q": "transistor", "R": "resistor", "D": "led", "C": "capacitor",
             "J": "connector"}
    refs = sorted({r for pins in nets.values() for r, _, _ in pins})
    comps = [{"reference": r, "type": types[r[0]], "value": "1k" if r[0] == "R" else "X",
              "lib_id": "", "pins": [], "footprint": ""} for r in refs]
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn,
                                         pin_type="passive") for r, p, pn in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    ctx = build_analysis_context(comps, full, {}, known_power_rails=set(rails))
    tc = {"reference": "Q1", "type": kind,
          ("drain_net" if kind == "mosfet" else "collector_net"): load_net}
    if kind == "mosfet":
        tc["is_pchannel"] = pchannel
    sd.enrich_transistor_led_drivers(ctx, [tc])
    if audit:
        audited = {r["summary"].split()[1] for r in dd.audit_led_circuits(ctx, [tc])
                   if r.get("rule_id") == "LA-AUD"}
        return tc.get("led_driver"), audited
    return tc.get("led_driver")


class LedDriverThroughPullUp(unittest.TestCase):
    def test_pull_up_to_a_rail_with_an_unrelated_led_is_not_a_driver(self):
        nets = {"VCC": [("R1", "2", "~"), ("D9", "1", "A")],
                "DRAIN": [("Q1", "3", "D"), ("R1", "1", "~")],
                "LEDK": [("D9", "2", "K"), ("R9", "1", "~")],
                "GND": [("Q1", "2", "S"), ("R9", "2", "~")]}
        self.assertIsNone(_driver(nets))

    def test_bjt_collector_pull_up_to_a_rail_is_not_a_driver(self):
        nets = {"VCC": [("R1", "2", "~"), ("D9", "1", "A")],
                "COLL": [("Q1", "3", "C"), ("R1", "1", "~")],
                "LEDK": [("D9", "2", "K"), ("R9", "1", "~")],
                "GND": [("Q1", "2", "E"), ("R9", "2", "~")]}
        self.assertIsNone(_driver(nets, kind="bjt", load_net="COLL"))

    def test_pull_down_to_ground_with_an_led_on_ground_is_not_a_driver(self):
        nets = {"VCC": [("Q1", "2", "S"), ("R9", "1", "~")],
                "DRAIN": [("Q1", "3", "D"), ("R1", "1", "~")],
                "LEDA": [("R9", "2", "~"), ("D9", "1", "A")],
                "GND": [("R1", "2", "~"), ("D9", "2", "K")]}
        self.assertIsNone(_driver(nets))

    def test_pull_up_to_a_rail_named_only_by_its_label_is_not_a_driver(self):
        nets = {"3.3V": [("R1", "2", "~"), ("D9", "1", "A"), ("C1", "1", "~")],
                "DRAIN": [("Q1", "3", "D"), ("R1", "1", "~")],
                "LEDK": [("D9", "2", "K"), ("R9", "1", "~")],
                "GND": [("Q1", "2", "S"), ("R9", "2", "~"), ("C1", "2", "~")]}
        self.assertIsNone(_driver(nets))

    def test_led_node_whose_name_reads_as_a_rail_is_a_driver(self):
        nets = {"VCC": [("D1", "1", "A")],
                "PWR_LED_K": [("D1", "2", "K"), ("R1", "2", "~")],
                "DRAIN": [("Q1", "3", "D"), ("R1", "1", "~")],
                "GND": [("Q1", "2", "S")]}
        drv = _driver(nets)
        self.assertEqual((drv["led_ref"], drv["current_resistor"]), ("D1", "R1"))

    def test_led_node_brought_out_to_a_connector_is_a_driver(self):
        nets = {"VCC": [("Q1", "2", "S")],
                "DRAIN": [("Q1", "3", "D"), ("R1", "1", "~")],
                "PWR_LED": [("R1", "2", "~"), ("D1", "1", "A"), ("J1", "4", "Pin_4")],
                "GND": [("D1", "2", "K")]}
        drv = _driver(nets)
        self.assertEqual((drv["led_ref"], drv["current_resistor"]), ("D1", "R1"))

    def test_power_symbol_rail_holding_only_an_led_and_a_connector_is_not_a_driver(self):
        nets = {"VCC": [("R1", "2", "~"), ("D9", "1", "A"), ("J1", "1", "Pin_1")],
                "DRAIN": [("Q1", "3", "D"), ("R1", "1", "~")],
                "LEDK": [("D9", "2", "K"), ("R9", "1", "~")],
                "GND": [("Q1", "2", "S"), ("R9", "2", "~"), ("J1", "2", "Pin_2")]}
        self.assertIsNone(_driver(nets))

    def test_drain_on_a_rail_is_not_the_driver_of_that_rails_power_led(self):
        nets = {"VBUS": [("Q1", "3", "D"), ("R1", "1", "~"), ("R2", "1", "~")],
                "SENSE": [("R1", "2", "~")],
                "PWRLED": [("R2", "2", "~"), ("D5", "1", "A")],
                "VOUT": [("Q1", "2", "S")],
                "GND": [("D5", "2", "K")]}
        drv, audited = _driver(nets, load_net="VBUS", rails=("VBUS", "GND"), audit=True)
        self.assertIsNone(drv)
        self.assertIn("D5", audited)

    def test_drain_on_ground_is_not_an_led_driver(self):
        nets = {"GND": [("Q1", "3", "D"), ("R1", "1", "~")],
                "PWRKEY": [("Q1", "2", "S")],
                "PWR_LED_K": [("R1", "2", "~"), ("D6", "2", "K")],
                "+3.3V": [("D6", "1", "A")]}
        self.assertIsNone(_driver(nets, load_net="GND", rails=("+3.3V", "GND")))

    def test_collector_on_ground_is_not_an_led_driver(self):
        nets = {"GND": [("Q1", "3", "C"), ("R1", "1", "~")],
                "OUT": [("Q1", "2", "E")],
                "LEDK": [("R1", "2", "~"), ("D6", "2", "K")],
                "VCC": [("D6", "1", "A")]}
        self.assertIsNone(_driver(nets, kind="bjt", load_net="GND"))

    def test_p_channel_load_switch_drives_the_indicator_on_its_switched_rail(self):
        nets = {"+5V": [("Q1", "2", "S")],
                "VOUT": [("Q1", "3", "D"), ("R1", "1", "~")],
                "LEDA": [("R1", "2", "~"), ("D1", "1", "A")],
                "GND": [("D1", "2", "K")]}
        drv = _driver(nets, load_net="VOUT", rails=("+5V", "VOUT", "GND"), pchannel=True)
        self.assertEqual((drv["led_ref"], drv["current_resistor"]), ("D1", "R1"))

    def test_low_side_switch_with_led_and_series_resistor_is_a_driver(self):
        nets = {"VCC": [("D1", "1", "A")],
                "LEDK": [("D1", "2", "K"), ("R1", "2", "~")],
                "DRAIN": [("Q1", "3", "D"), ("R1", "1", "~")],
                "GND": [("Q1", "2", "S")]}
        drv = _driver(nets)
        self.assertEqual((drv["led_ref"], drv["current_resistor"], drv["power_rail"]),
                         ("D1", "R1", "VCC"))

    def test_high_side_switch_with_series_resistor_to_led_is_a_driver(self):
        nets = {"VCC": [("Q1", "2", "S")],
                "DRAIN": [("Q1", "3", "D"), ("R1", "1", "~")],
                "LEDA": [("R1", "2", "~"), ("D1", "1", "A")],
                "GND": [("D1", "2", "K")]}
        drv = _driver(nets)
        self.assertEqual((drv["led_ref"], drv["current_resistor"]), ("D1", "R1"))

    def test_bjt_collector_with_led_and_series_resistor_is_a_driver(self):
        nets = {"VCC": [("D1", "1", "A")],
                "LEDK": [("D1", "2", "K"), ("R1", "2", "~")],
                "COLL": [("Q1", "3", "C"), ("R1", "1", "~")],
                "GND": [("Q1", "2", "E")]}
        drv = _driver(nets, kind="bjt", load_net="COLL")
        self.assertEqual((drv["led_ref"], drv["current_resistor"]), ("D1", "R1"))


if __name__ == "__main__":
    unittest.main()
