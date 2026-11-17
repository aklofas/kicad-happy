"""A library nickname often names the board or its main part (an ESP32 Feather, an ADS1262 board):
the regulator screen and ADC detection read the part's value and symbol name, while a category
library (Comparator:, Memory_Flash:) still says what the part is."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from domain_detectors import detect_adc_circuits  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import detect_power_regulators  # noqa: E402


def _ctx(value, lib_id, pins, inductor_net=None):
    """U1 with *pins* ``{num: (name, net)}``, and an inductor L1 from *inductor_net* to +5V."""
    comps = [{"reference": "U1", "lib_id": lib_id, "value": value, "type": "ic",
              "pins": [{"number": n, "name": name} for n, (name, _) in pins.items()]}]
    nets = {}
    for num, (name, net) in pins.items():
        nets.setdefault(net, {"pins": []})["pins"].append(
            {"component": "U1", "pin_number": num, "pin_name": name})
    if inductor_net:
        comps.append({"reference": "L1", "lib_id": "Device:L", "value": "10uH", "type": "inductor",
                      "pins": [{"number": "1", "name": ""}, {"number": "2", "name": ""}]})
        for num, net in (("1", inductor_net), ("2", "+5V")):
            nets.setdefault(net, {"pins": []})["pins"].append(
                {"component": "L1", "pin_number": num, "pin_name": ""})
    return build_analysis_context(comps, nets, {})


def _regulator_refs(value, lib_id, pins, inductor_net=None):
    return [r["ref"] for r in detect_power_regulators(_ctx(value, lib_id, pins, inductor_net), [])]


_BOOST_PINS = {"1": ("SW", "SW"), "2": ("GND", "GND"), "3": ("FB", "FB"), "4": ("EN", "+5V"),
               "5": ("IN", "+5V")}
_LDO_PINS = {"1": ("VIN", "+5V"), "2": ("GND", "GND"), "3": ("EN", "+5V"), "4": ("VOUT", "+3V3")}
_ADJ_LDO_PINS = {"1": ("VIN", "+5V"), "2": ("GND", "GND"), "3": ("EN", "+5V"), "4": ("ADJ", "FB"),
                 "5": ("VOUT", "+3V3")}


class NicknameDoesNotHideARegulator(unittest.TestCase):
    def test_boost_in_an_adc_board_library_is_a_regulator(self):
        self.assertEqual(_regulator_refs("MT3608", "BB-ADS1262-Rev.A:MT3608(SOT23-6)", _BOOST_PINS, "SW"),
                         ["U1"])

    def test_ldos_in_adc_board_libraries_are_regulators(self):
        self.assertEqual(_regulator_refs("AP2127K-ADJ", "BB-ADS1262-Rev.A:AP2127K-ADJ", _ADJ_LDO_PINS),
                         ["U1"])
        self.assertEqual(_regulator_refs("TPS7A4901", "Isolated_ADS1256:TPS7A4901", _ADJ_LDO_PINS),
                         ["U1"])

    def test_ldo_in_a_dev_board_library_is_a_regulator(self):
        self.assertEqual(_regulator_refs("AP2112K-3.3", "Adafruit ESP32 Feather V2-eagle-import:AP2112K",
                                         _LDO_PINS), ["U1"])

    def test_ldo_in_an_rf_board_library_is_a_regulator(self):
        self.assertEqual(_regulator_refs("XC6206P332MR", "GPS_LNA_board:XC6206", _LDO_PINS), ["U1"])

    def test_ldo_in_an_ideal_diode_project_library_named_by_a_part_is_a_regulator(self):
        self.assertEqual(_regulator_refs("AP2112K-3.3", "LTC4359_ORing:AP2112K", _LDO_PINS), ["U1"])


class PartTextAndCategoryLibrariesStillExclude(unittest.TestCase):
    def test_comparator_library_part_is_not_a_regulator(self):
        pins = {"1": ("OUT", "CMP_OUT"), "2": ("-", "IN_N"), "3": ("+", "+5V"), "4": ("V-", "GND"),
                "8": ("V+", "+5V")}
        self.assertEqual(_regulator_refs("LM393", "Comparator:LM393", pins), [])
        pins = {"1": ("OUT", "+3V3"), "2": ("IN", "+5V"), "3": ("FB", "FB"), "4": ("GND", "GND")}
        self.assertEqual(_regulator_refs("XYZ123", "Comparator:XYZ123", pins), [])

    def test_flash_in_a_memory_library_is_not_a_regulator(self):
        pins = {"1": ("VIN", "+5V"), "2": ("GND", "GND"), "3": ("VOUT", "+3V3"), "4": ("FB", "FB")}
        self.assertEqual(_regulator_refs("W25Q32JVSS", "Memory_Flash:W25Q32JVSS", pins), [])
        self.assertEqual(_regulator_refs("XYZ123", "Memory_Flash:XYZ123", pins), [])

    def test_part_stem_in_the_value_or_symbol_still_excludes(self):
        pins = {"1": ("OUT", "+3V3"), "2": ("IN", "+5V"), "3": ("FB", "FB"), "4": ("GND", "GND")}
        self.assertEqual(_regulator_refs("OPA2333", "Custom:U", pins), [])
        self.assertEqual(_regulator_refs("U", "Custom:ADS1115", pins), [])
        self.assertEqual(_regulator_refs("ESP32-WROOM-32", "Custom:Module", pins), [])

    def test_load_switch_or_ideal_diode_library_still_excludes(self):
        self.assertEqual(_regulator_refs("XYZ123", "Power_Mux:XYZ123", _ADJ_LDO_PINS), [])
        self.assertEqual(_regulator_refs("XYZ123", "my_ideal_diode:XYZ123", _ADJ_LDO_PINS), [])


def _adc_records(value, lib_id):
    pins = {"1": ("AIN0", "SENSE0"), "2": ("AIN1", "SENSE1"), "3": ("SCLK", "SCK"), "4": ("DIN", "MOSI"),
            "5": ("DOUT", "MISO"), "6": ("AVDD", "+5V"), "7": ("AVSS", "GND")}
    return detect_adc_circuits(_ctx(value, lib_id, pins), [], [])


class AdcReadsThePartNotTheNickname(unittest.TestCase):
    def test_boost_in_an_adc_board_library_is_not_an_adc(self):
        self.assertEqual(_adc_records("MT3608", "BB-ADS1262-Rev.A:MT3608(SOT23-6)"), [])
        self.assertEqual(_adc_records("TPS7A4901", "Isolated_ADS1256:TPS7A4901"), [])

    def test_the_adc_itself_keeps_its_record_and_resolution(self):
        recs = _adc_records("ADS1262", "BB-ADS1262-Rev.A:ADS1262")
        self.assertEqual([(r["ref"], r["resolution_bits"]) for r in recs], [("U1", 32)])

    def test_resolution_comes_from_the_symbol_not_the_nickname(self):
        recs = _adc_records("ADC", "LTC2380-24_eval:ADS1115")
        self.assertEqual([(r["ref"], r["resolution_bits"]) for r in recs], [("U1", 16)])

    def test_symbol_name_still_admits_a_generic_value(self):
        recs = _adc_records("ADC", "Analog_ADC:ADS1115IDGS")
        self.assertEqual([(r["ref"], r["resolution_bits"]) for r in recs], [("U1", 16)])


if __name__ == "__main__":
    unittest.main()
