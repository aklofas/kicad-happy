# tools/tests/test_led_driver_rail_guard.py
"""A drain or collector net that reads as a rail or ground by its name alone (no power
symbol, no supply pin) can be the switch's own node: an LED there counts when it sits in
the switched path. A rail by a power symbol or a supply pin keeps the guard."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_led_driver_pullup import _driver  # noqa: E402


class NameOnlyLoadNet(unittest.TestCase):
    def test_n_channel_drain_on_a_ground_named_node_drives_the_led_to_another_net(self):
        nets = {"IR-_GND": [("Q1", "3", "D"), ("R5", "1", "~")],
                "LEDA": [("R5", "2", "~"), ("D2", "1", "A")],
                "Shutdown_in": [("D2", "2", "K")]}
        drv = _driver(nets, load_net="IR-_GND", rails=())
        self.assertEqual((drv["led_ref"], drv["current_resistor"]), ("D2", "R5"))

    def test_p_channel_drain_on_a_supply_named_node_drives_the_led_to_ground(self):
        nets = {"0VCC": [("Q1", "3", "D"), ("R7", "1", "~")],
                "LEDA": [("R7", "2", "~"), ("D2", "1", "A")],
                "GND": [("D2", "2", "K")]}
        drv = _driver(nets, load_net="0VCC", rails=("GND",), pchannel=True)
        self.assertEqual((drv["led_ref"], drv["current_resistor"]), ("D2", "R7"))

    def test_n_channel_drain_on_a_port_named_like_a_rail_drives_the_led_from_another_supply(self):
        nets = {"3V3": [("Q1", "3", "D"), ("R17", "1", "~")],
                "LEDK": [("R17", "2", "~"), ("D3", "2", "K")],
                "+5V": [("D3", "1", "A")]}
        drv = _driver(nets, load_net="3V3", rails=("+5V",))
        self.assertEqual((drv["led_ref"], drv["current_resistor"]), ("D3", "R17"))

    def test_n_channel_drain_on_a_name_only_rail_with_the_led_to_ground_is_not_the_driver(self):
        nets = {"vbus": [("Q1", "3", "D"), ("R1", "1", "~")],
                "PWRLED": [("R1", "2", "~"), ("D5", "1", "A")],
                "GND": [("D5", "2", "K")]}
        self.assertIsNone(_driver(nets, load_net="vbus", rails=("GND",)))

    def test_pnp_collector_on_a_name_only_rail_with_the_led_to_ground_is_a_driver(self):
        nets = {"+5V": [("Q1", "3", "C"), ("R1", "1", "~")],
                "LEDA": [("R1", "2", "~"), ("D1", "1", "A")],
                "GND": [("D1", "2", "K")]}
        drv = _driver(nets, kind="bjt", load_net="+5V", rails=("GND",),
                      q1={"lib_id": "Device:Q_PNP_BEC", "value": "BC857"})
        self.assertEqual((drv["led_ref"], drv["current_resistor"]), ("D1", "R1"))

    def test_drain_on_a_power_symbol_rail_keeps_the_guard(self):
        nets = {"VBUS": [("Q1", "3", "D"), ("R1", "1", "~")],
                "LEDA": [("R1", "2", "~"), ("D5", "1", "A")],
                "OTHER": [("D5", "2", "K")]}
        self.assertIsNone(_driver(nets, load_net="VBUS", rails=("VBUS", "GND")))


if __name__ == "__main__":
    unittest.main()
