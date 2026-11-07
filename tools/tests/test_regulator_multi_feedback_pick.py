# tools/tests/test_regulator_multi_feedback_pick.py
"""A regulator with several feedback pins estimates Vout from the divider that sets its output, whatever the pin order."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import detect_power_regulators, detect_voltage_dividers  # noqa: E402


def _regulator(value, lib_id, pins, dividers, reverse=False):
    """The U1 record for *pins* {num: (name, net)} with resistor dividers [(top_net, mid_net, r_top, r_bottom)] to GND.

    *reverse* enumerates U1's pins in the opposite order.
    """
    comps = [{"reference": "U1", "lib_id": lib_id, "value": value, "type": "ic",
              "pins": [{"number": n, "name": name} for n, (name, _) in pins.items()]}]
    nets = {}
    pin_items = list(pins.items())
    for num, (name, net) in (reversed(pin_items) if reverse else pin_items):
        nets.setdefault(net, {"pins": []})["pins"].append(
            {"component": "U1", "pin_number": num, "pin_name": name})
    for i, (top, mid, r_top, r_bot) in enumerate(dividers):
        for ref, val, n1, n2 in ((f"R{2 * i + 1}", r_top, top, mid), (f"R{2 * i + 2}", r_bot, mid, "GND")):
            comps.append({"reference": ref, "lib_id": "Device:R", "value": val, "type": "resistor",
                          "pins": [{"number": "1", "name": ""}, {"number": "2", "name": ""}]})
            for num, net in (("1", n1), ("2", n2)):
                nets.setdefault(net, {"pins": []})["pins"].append(
                    {"component": ref, "pin_number": num, "pin_name": ""})
    ctx = build_analysis_context(comps, nets, {})
    vds = detect_voltage_dividers(ctx)["voltage_dividers"]
    regs = [r for r in detect_power_regulators(ctx, vds) if r["ref"] == "U1"]
    assert len(regs) == 1, regs
    return regs[0]


# Dual adjustable LDO with one output pin, on channel 2's rail
_DUAL_ADJ = {"1": ("IN", "+5V"), "2": ("OUT", "+3V3"), "3": ("ADJ1", "ADJ1_NET"),
             "4": ("ADJ2", "ADJ2_NET"), "5": ("GND", "GND")}

# TPS63070 buck-boost: FB2 is a mode-select pin tied to GND, FB carries the divider
_TPS63070 = {"1": ("FB2", "GND"), "2": ("VIN", "+12V"), "3": ("L1", "SW1"), "4": ("L2", "SW2"),
             "5": ("VOUT", "+5V"), "6": ("FB", "FB_NET"), "7": ("GND", "GND"), "8": ("EN", "+12V")}


class MultiFeedbackPick(unittest.TestCase):
    def test_divider_on_second_adjust_pin_is_used_under_either_pin_order(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                reg = _regulator("DUAL_LDO_ADJ", "Regulator_Linear:DUAL_LDO_ADJ", _DUAL_ADJ,
                                 [("+3V3", "ADJ2_NET", "33k", "10k")], reverse=reverse)
                self.assertEqual(reg.get("fb_net"), "ADJ2_NET")
                self.assertEqual(reg["feedback_divider"]["r_top"]["ref"], "R1")

    def test_divider_whose_top_is_the_output_rail_wins_over_the_first_pin_by_name(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                reg = _regulator("DUAL_LDO_ADJ", "Regulator_Linear:DUAL_LDO_ADJ", _DUAL_ADJ,
                                 [("+1V8", "ADJ1_NET", "12k", "10k"), ("+3V3", "ADJ2_NET", "33k", "10k")],
                                 reverse=reverse)
                self.assertEqual(reg.get("output_rail"), "+3V3")
                self.assertEqual(reg.get("fb_net"), "ADJ2_NET")
                self.assertEqual(reg["feedback_divider"]["r_top"]["ref"], "R3")

    def test_feedback_pins_without_a_divider_pick_the_first_by_name(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                reg = _regulator("DUAL_LDO_ADJ", "Regulator_Linear:DUAL_LDO_ADJ", _DUAL_ADJ, [],
                                 reverse=reverse)
                self.assertEqual(reg.get("fb_net"), "ADJ1_NET")

    def test_buck_boost_with_mode_pin_on_ground_estimates_from_its_feedback_divider(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                reg = _regulator("TPS63070", "Regulator_Switching:TPS63070", _TPS63070,
                                 [("+5V", "FB_NET", "100k", "20k")], reverse=reverse)
                self.assertEqual(reg.get("fb_net"), "FB_NET")
                self.assertIsNotNone(reg.get("estimated_vout"))
                self.assertEqual(reg["feedback_divider"]["r_top"]["ref"], "R1")


if __name__ == "__main__":
    unittest.main()
