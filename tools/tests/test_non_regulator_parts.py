"""DACs (OUT + FB pins), GaN power stages and MOSFET gate drivers (SW + BST + an inductor) are not
regulators, nor is a charger by its BTST bootstrap pins; a buck controller with gate-drive pins
still is."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import detect_power_regulators  # noqa: E402


def _regulator_refs(value, lib_id, pins, inductor_net=None, inductor_to="+3V3", bead=False):
    """Regulator refs for U1 with *pins* ``{num: (name, net)}``, and an inductor L1 (a
    ferrite bead with *bead*) from *inductor_net* to *inductor_to*."""
    comps = [{"reference": "U1", "lib_id": lib_id, "value": value, "type": "ic",
              "pins": [{"number": n, "name": name} for n, (name, _) in pins.items()]}]
    nets = {}
    for num, (name, net) in pins.items():
        nets.setdefault(net, {"pins": []})["pins"].append(
            {"component": "U1", "pin_number": num, "pin_name": name})
    if inductor_net:
        comps.append({"reference": "L1", "lib_id": "Device:L_Ferrite_Small" if bead else "Device:L",
                      "value": "4.7uH" if bead else "1uH", "type": "ferrite_bead" if bead else "inductor",
                      "pins": [{"number": "1", "name": ""}, {"number": "2", "name": ""}]})
        for num, net in (("1", inductor_net), ("2", inductor_to)):
            nets.setdefault(net, {"pins": []})["pins"].append(
                {"component": "L1", "pin_number": num, "pin_name": ""})
    return [r["ref"] for r in detect_power_regulators(build_analysis_context(comps, nets, {}), [])]


_DAC_PINS = {"1": ("FB", "DAC_OUT"), "2": ("OUT", "DAC_OUT"), "3": ("VDD", "+3V3"), "4": ("GND", "GND"),
             "5": ("SCL", "SCL"), "6": ("SDA", "SDA"), "7": ("A0", "GND")}
_DAC8551_PINS = {"1": ("VDD", "+5V"), "2": ("VREF", "+5V"), "3": ("VFB", "AOUT"), "4": ("VOUT", "AOUT"),
                 "5": ("~{SYNC}", "CS"), "6": ("SCLK", "SCK"), "7": ("DIN", "MOSI"), "8": ("GND", "GND")}
_DRIVER_PINS = {"1": ("BST", "BST"), "2": ("PWM", "PWM"), "3": ("EN", "+5V"), "4": ("VCC", "+5V"),
                "5": ("DRVL", "GL"), "6": ("GND", "GND"), "7": ("SW", "SW"), "8": ("DRVH", "GH")}
# BQ25730 buck-boost charger: bootstrap pins BTST1 / BTST2, no FB pin; a ferrite-bead
# symbol between SW1 and SW2
_BQ25730_PINS = {"1": ("VBUS", "VBUS"), "2": ("ACN", "ACN"), "3": ("ACP", "ACP"), "4": ("CHRG_OK", "CHRG"),
                 "5": ("OTG/VAP/FRS", "OTG"), "6": ("ILIM_HIZ", "ILIM"), "7": ("VDDA", "VDDA"),
                 "8": ("IADPT", "IADPT"), "9": ("IBAT", "IBAT"), "10": ("PSYS", "PSYS"),
                 "11": ("~{PROCHOT}", "INT"), "12": ("SDA", "SDA"), "13": ("SCL", "SCL"),
                 "14": ("CMPIN", "GND"), "15": ("CMPOUT", "GND"), "16": ("COMP1", "COMP1"),
                 "17": ("COMP2", "COMP2"), "18": ("CELL_BATPRESZ", "CELL"), "19": ("SRN", "SRN"),
                 "20": ("SRP", "SRP"), "21": ("~{BATDRV}", "BATDRV"), "22": ("VSYS", "VSYS"),
                 "23": ("SW2", "SWITCH_LO"), "24": ("HIDRV2", "HIDRV2"), "25": ("BTST2", "BTST2"),
                 "26": ("LODRV2", "LODRV2"), "27": ("PGND", "GND"), "28": ("REGN", "REGN"),
                 "29": ("LODRV1", "LODRV1"), "30": ("BTST1", "BTST1"), "31": ("HIDRV1", "HIDRV1"),
                 "32": ("SW1", "SWITCH_HI"), "33": ("EXP", "GND")}
_GAN_STAGE_PINS = {"1": ("VIN", "+12V"), "2": ("SW", "SW"), "3": ("BOOT", "BST"), "4": ("VDRV", "+5V"),
                   "5": ("HSIN", "PWMH"), "6": ("LSIN", "PWML"), "7": ("PGND", "GND"), "8": ("EN", "+5V")}


class NonRegulatorsWithRegulatorPins(unittest.TestCase):
    def test_dacs_are_not_regulators(self):
        self.assertEqual(_regulator_refs("DAC53401DSGR", "Custom:DAC53401", _DAC_PINS), [])
        self.assertEqual(_regulator_refs("DAC8551", "Custom:DAC8551", _DAC8551_PINS), [])

    def test_a_dac_named_only_by_its_symbol_is_not_a_regulator(self):
        self.assertEqual(_regulator_refs("~", "Custom:DAC53401DSG", _DAC_PINS), [])

    def test_gan_power_stage_is_not_a_regulator(self):
        self.assertEqual(_regulator_refs("EPC23104", "Custom:EPC23104", _GAN_STAGE_PINS, "SW"), [])

    def test_charger_with_btst_bootstrap_pins_is_not_a_regulator(self):
        self.assertEqual(_regulator_refs("BQ25730RSNR", "EXT_DCDC:BQ25730RSNR", _BQ25730_PINS,
                                         "SWITCH_HI", "SWITCH_LO", bead=True), [])

    def test_mosfet_gate_drivers_are_not_regulators(self):
        for value in ("NCP81155MNTXG", "ADP3110AKRZ", "LTC7061"):
            self.assertEqual(_regulator_refs(value, "Custom:" + value, _DRIVER_PINS, "SW"), [], value)


class RegulatorsStay(unittest.TestCase):
    def test_buck_controller_with_gate_drive_pins_stays(self):
        pins = {"1": ("VIN", "+12V"), "2": ("HO", "GH"), "3": ("LO", "GL"), "4": ("SW", "SW"),
                "5": ("FB", "FB"), "6": ("GND", "GND"), "7": ("CBOOT", "BST")}
        self.assertEqual(_regulator_refs("LM5148", "Regulator_Controller:LM5148", pins, "SW"), ["U1"])

    def test_buck_regulator_stays(self):
        pins = {"1": ("VIN", "+12V"), "2": ("SW", "SW"), "3": ("FB", "FB"), "4": ("GND", "GND"),
                "5": ("EN", "+12V")}
        self.assertEqual(_regulator_refs("TPS62130", "Regulator_Switching:TPS62130", pins, "SW"), ["U1"])


if __name__ == "__main__":
    unittest.main()
