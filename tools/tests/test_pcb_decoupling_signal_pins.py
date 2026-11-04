"""PCB decoupling placement leaves out caps that share only the IC's signal-pin nets."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "skills"
sys.path.insert(0, str(ROOT / "kicad" / "scripts"))

from pcb.assembly import analyze_decoupling_placement  # noqa: E402


def pad(num, net, x, pintype=None):
    p = {"number": num, "net_name": net, "abs_x": x, "abs_y": 0.0}
    if pintype:
        p["pintype"] = pintype
    return p


def ic(ref, value, pads):
    return {"reference": ref, "value": value, "layer": "F.Cu", "x": 0.0, "y": 0.0,
            "pads": pads}


def cap(ref, net, x):
    return {"reference": ref, "value": "100n", "layer": "F.Cu", "x": x, "y": 0.0,
            "pads": [pad("1", net, x), pad("2", "GND", x + 1.0)]}


def caps_of(results, ref):
    return [[c["cap"] for c in e["nearby_caps"]] for e in results if e["ic"] == ref]


class DecouplingSignalPins(unittest.TestCase):
    def test_crystal_load_cap_on_input_pin_does_not_count(self):
        u1 = ic("U1", "STM32", [pad("1", "/XTAL_IN", 0.0, "input"),
                                pad("2", "GND", 0.5, "power_in")])
        out = analyze_decoupling_placement([u1, cap("C1", "/XTAL_IN", 2.0)])
        self.assertEqual(caps_of(out, "U1"), [])

    def test_supply_cap_on_power_in_pin_counts(self):
        u1 = ic("U1", "STM32", [pad("1", "/XTAL_IN", 0.0, "input"),
                                pad("2", "Net-(U1-VDD)", 0.5, "power_in"),
                                pad("3", "GND", 1.0, "power_in")])
        out = analyze_decoupling_placement(
            [u1, cap("C1", "/XTAL_IN", 2.0), cap("C2", "Net-(U1-VDD)", 3.0)])
        self.assertEqual(caps_of(out, "U1"), [["C2"]])

    def test_rail_named_net_on_input_pin_counts(self):
        u1 = ic("U1", "MCP9700", [pad("1", "+3V3", 0.0, "input"),
                                  pad("2", "GND", 0.5, "power_in")])
        out = analyze_decoupling_placement([u1, cap("C1", "+3V3", 2.0)])
        self.assertEqual(caps_of(out, "U1"), [["C1"]])

    def test_supply_pin_named_vdd_typed_input_counts(self):
        u9 = ic("U9", "MCP9700", [pad("1", "Net-(U9-VDD)", 0.0, "input"),
                                  pad("2", "GND", 0.5, "power_in")])
        u9["pads"][0]["pinfunction"] = "VDD"
        out = analyze_decoupling_placement([u9, cap("C1", "Net-(U9-VDD)", 2.0)])
        self.assertEqual(caps_of(out, "U9"), [["C1"]])

    def test_signal_pins_named_like_supplies_still_drop(self):
        for name, pintype in (("VCOUT", "output"), ("V0", "output"), ("VIN+", "input"),
                              ("+", "input")):
            u1 = ic("U1", "X", [pad("1", "Net-(U1-P1)", 0.0, pintype),
                                pad("2", "GND", 0.5, "power_in")])
            u1["pads"][0]["pinfunction"] = name
            out = analyze_decoupling_placement([u1, cap("C1", "Net-(U1-P1)", 2.0)])
            self.assertEqual(caps_of(out, "U1"), [], name)

    def test_no_pin_types_unchanged(self):
        u1 = ic("U1", "NE555", [pad("1", "/TIMING", 0.0), pad("2", "GND", 0.5)])
        out = analyze_decoupling_placement([u1, cap("C1", "/TIMING", 2.0)])
        self.assertEqual(caps_of(out, "U1"), [["C1"]])

    def test_esd_bypass_path_unchanged(self):
        u1 = ic("U1", "USBLC6-2", [pad("1", "/USB_DP", 0.0, "input"),
                                   pad("2", "GND", 0.5, "power_in")])
        out = analyze_decoupling_placement([u1, cap("C1", "/USB_DP", 2.0)])
        self.assertEqual(caps_of(out, "U1"), [["C1"]])
        self.assertEqual(out[0]["category"], "esd_bypass")


if __name__ == "__main__":
    unittest.main()
