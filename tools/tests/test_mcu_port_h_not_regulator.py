# tools/tests/test_mcu_port_h_not_regulator.py
"""Port H GPIOs (PH0, PH1) on a microcontroller are not switch pins; multi-phase regulator PH pins still are."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import detect_power_regulators  # noqa: E402


def _regulators(value, lib_id, pins, inductor_net):
    """Regulator records for U1 with *pins*, and an inductor L1 from *inductor_net* to GND."""
    comps = [{"reference": "U1", "lib_id": lib_id, "value": value, "type": "ic",
              "pins": [{"number": n, "name": name} for n, (name, _) in pins.items()]},
             {"reference": "L1", "lib_id": "Device:L", "value": "10uH", "type": "inductor",
              "pins": [{"number": "1", "name": ""}, {"number": "2", "name": ""}]}]
    nets = {}
    for num, (name, net) in pins.items():
        nets.setdefault(net, {"pins": []})["pins"].append(
            {"component": "U1", "pin_number": num, "pin_name": name})
    for num, net in (("1", inductor_net), ("2", "GND")):
        nets.setdefault(net, {"pins": []})["pins"].append(
            {"component": "L1", "pin_number": num, "pin_name": ""})
    return detect_power_regulators(build_analysis_context(comps, nets, {}), [])


def _regulator_refs(value, lib_id, pins, inductor_net):
    return [r["ref"] for r in _regulators(value, lib_id, pins, inductor_net)]


_MCU_PINS = {"1": ("VDD", "+3V3"), "2": ("VSS", "GND"), "3": ("PH0", "PH0_NET"),
             "4": ("PH1", "PH1_NET"), "5": ("PA0", "BTN"), "6": ("VDDA", "+3V3")}


class PortHPinsAreNotSwitchPins(unittest.TestCase):
    def test_mcu_with_port_h_and_port_a_pins_is_not_a_regulator(self):
        refs = _regulator_refs("STM32F405RGTx", "MCU_ST_STM32F4:STM32F405RGTx", _MCU_PINS, "PH0_NET")
        self.assertEqual(refs, [])

    def test_multi_phase_buck_phase_pins_stay_switch_pins(self):
        pins = {"1": ("VIN1", "+12V"), "2": ("VIN2", "+12V"), "3": ("PH1", "SW1"), "4": ("PH2", "SW2"),
                "5": ("BOOT1", "BST1"), "6": ("BOOT2", "BST2"), "7": ("FB1", "FB1"), "8": ("FB2", "FB2"),
                "9": ("EN1", "EN1"), "10": ("EN2", "EN2"), "11": ("GND", "GND")}
        regs = _regulators("TPS54290", "Regulator_Switching:TPS54290", pins, "SW1")
        self.assertEqual([(r["ref"], r.get("inductor")) for r in regs], [("U1", "L1")])

    def test_phase_pins_alone_make_a_regulator_without_a_feedback_pin(self):
        pins = {"1": ("VIN", "+12V"), "2": ("PH1", "SW1"), "3": ("PH2", "SW2"),
                "4": ("VSENSE", "FBK"), "5": ("GND", "GND")}
        regs = _regulators("DUAL_BUCK", "Regulator_Switching:DUAL_BUCK", pins, "SW1")
        self.assertEqual([(r["ref"], r.get("inductor")) for r in regs], [("U1", "L1")])

    def test_single_ph_pin_stays_a_switch_pin(self):
        pins = {"1": ("VIN", "+12V"), "2": ("PH", "SW"), "3": ("BOOT", "BST"),
                "4": ("VSENSE", "FBK"), "5": ("GND", "GND"), "6": ("PA0", "NC1")}
        self.assertEqual(_regulator_refs("TPS5430", "Regulator_Switching:TPS5430", pins, "SW"), ["U1"])


if __name__ == "__main__":
    unittest.main()
