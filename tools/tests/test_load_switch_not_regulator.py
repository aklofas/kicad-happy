# tools/tests/test_load_switch_not_regulator.py
"""Power switches and load switches are not recorded as regulators; real LDOs and chargers still are."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import detect_power_regulators  # noqa: E402


def _regulators(value, lib_id, pins):
    comp = {"reference": "U1", "lib_id": lib_id, "value": value, "type": "ic",
            "pins": [{"number": n, "name": name} for n, (name, _) in pins.items()]}
    nets = {}
    for num, (name, net) in pins.items():
        nets.setdefault(net, {"pins": []})["pins"].append(
            {"component": "U1", "pin_number": num, "pin_name": name})
    return detect_power_regulators(build_analysis_context([comp], nets, {}), [])


_SWITCH_PINS = {"1": ("VIN", "+5V"), "2": ("VOUT", "VBUS_OUT"), "3": ("GND", "GND"), "4": ("EN", "EN")}


class LoadSwitchesAreNotRegulators(unittest.TestCase):
    def test_load_and_usb_power_switches_are_not_regulators(self):
        for value in ("RT9742", "TPS2061", "TPS2065C", "AP2171W", "AP2191", "MT9700", "SY6280",
                      "AP2281-1", "RT9701"):
            self.assertEqual(_regulators(value, "Power_Management:" + value, _SWITCH_PINS), [], value)

    def test_real_linear_regulators_stay(self):
        ldo = {"1": ("GND", "GND"), "2": ("VOUT", "+3V3"), "3": ("VIN", "+5V")}
        for value in ("NJM2870", "LP3874", "AMS1117-3.3"):
            regs = _regulators(value, "Regulator_Linear:" + value, ldo)
            self.assertEqual([r["ref"] for r in regs], ["U1"], value)

    def test_chargers_stay(self):
        pins = {"1": ("IN", "+5V"), "2": ("OUT", "VBAT"), "3": ("GND", "GND"), "4": ("FB", "FB")}
        for value in ("BQ25170", "BQ24074"):
            regs = _regulators(value, "Battery_Management:" + value, pins)
            self.assertEqual([r["ref"] for r in regs], ["U1"], value)


if __name__ == "__main__":
    unittest.main()
