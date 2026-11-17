# tools/tests/test_sense_amp_names.py
"""A current-sense amplifier is matched by its part number (value, MPN or symbol name),
never by letters inside a word or by its library's name. Every family is cited below."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_core.parts import names_sense_amp  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
import signal_detectors as sd  # noqa: E402

# Family -> (a part number in it, maker datasheet: title, revision, page: text).
SENSE_AMP_FAMILIES = {
    "INA138/INA168": ("INA168NA", "TI INA1x8 High-Side Measurement Current Shunt Monitor, "
                      "SBOS122E revised December 2017, p. 1"),
    "INA139/INA169": ("INA169NA", "TI INA1x9 High-Side Measurement Current Shunt Monitor, "
                      "SBOS181F revised February 2017, p. 1"),
    "INA170": ("INA170EA", "TI INA170 High-Side, Bidirectional Current Shunt Monitor, "
               "SBOS193D revised January 2006, p. 1"),
    "INA18x": ("INA180A1", "TI INAx180 Low- and High-Side Voltage Output, Current-Sense Amplifiers, "
               "SBOS741H revised July 2022, p. 1"),
    "INA19x": ("INA199A2", "TI INA199 26-V, Bidirectional, Zero-Drift, Low- or High-Side, Voltage-Output, "
               "Current-Shunt Monitor, SBOS469H revised October 2023, p. 1"),
    "INA19x (INA190)": ("INA190A4", "TI INA190 Precision Current-Sense Amplifier With Enable, "
                        "SBOS863D revised November 2019, p. 1"),
    "INA2xx": ("INA219B", "TI INA219 Zero-Drift, Bidirectional Current/Power Monitor With I2C Interface, "
               "SBOS448G revised December 2015, p. 1"),
    "INA2xx (INA226)": ("INA226AIDGSR", "TI INA226 36V, 16-Bit, Ultra-Precise I2C Output Current, Voltage, "
                        "and Power Monitor With Alert, SBOS547C revised August 2026, p. 1"),
    "INA2xx (INA240)": ("INA240A4", "TI INA240 -4-V to 80-V, Bidirectional, Ultra-Precise Current Sense "
                        "Amplifier With Enhanced PWM Rejection, SBOS662C revised December 2021, p. 1"),
    "INA30x": ("INA301A2", "TI INA301 Current-Shunt Monitor with High-Speed, Overcurrent Comparator, "
               "SBOS713A revised February 2016, p. 1"),
    "INA31x": ("INA310B1", "TI INA310x -4 V to 110 V, 1.3 MHz, Ultra-Precise Current Sense Amplifier "
               "With Open-Drain Comparator and Reference, SBOSA86 March 2023, p. 1"),
    "INA38x": ("INA381A1", "TI INA381 26-V, High-Speed, Current Sense Amplifier With Integrated "
               "Comparator, SBOS848B revised October 2019, p. 1"),
    "dual/quad (INA2180, INA4180)": ("INA2180A1", "TI INAx180, SBOS741H revised July 2022, p. 1: "
                                     "INA180, INA2180, INA4180"),
    "quad (INA4181)": ("INA4181A1", "TI INAx181 Bidirectional, Low- and High-Side Voltage Output, "
                       "Current-Sense Amplifiers, SBOS793H revised November 2023, p. 1: INA181, INA2181, INA4181"),
    "triple (INA3221)": ("INA3221AIRGVR", "TI INA3221 26V, Triple Channel, 13-Bit, I2C Output Current and "
                         "Voltage Monitor With Alerts, SBOS576C revised September 2026, p. 1"),
    "ACS7xx": ("ACS712ELCTR-05B-T", "Allegro ACS712 Fully Integrated, Hall-Effect-Based Linear Current "
               "Sensor IC, ACS712-DS Rev. 22, p. 1"),
    "AD8210": ("AD8210YRZ", "ADI AD8210 Data Sheet, Rev. F, p. 14: High-Side Current Sense with a "
               "Low-Side Switch"),
    "AD8217": ("AD8217BRMZ", "ADI AD8217 High Resolution, Zero-Drift Current Shunt Monitor, Rev. A, p. 1"),
    "AD8218": ("AD8218BRMZ", "ADI AD8218 Zero Drift, Bidirectional Current Shunt Monitor, Rev. B, p. 1"),
    "MAX9938": ("MAX9938HEUK+T", "Maxim MAX9938 nanoPower, 4-Bump UCSP/SOT23, Precision Current-Sense "
                "Amplifier, 19-4110 Rev 7 4/17, p. 1"),
    "MAX4080/MAX4081": ("MAX4081TASA+T", "Maxim MAX4080/MAX4081 76V, High-Side, Current-Sense Amplifiers "
                        "with Voltage Output, 19-2562 Rev 6 12/20, p. 1"),
    "MAX471": ("MAX471CSA", "Maxim MAX471/MAX472 Precision, High-Side Current-Sense Amplifiers, "
               "19-0335 Rev 2 12/96, p. 2"),
    "LTC6101": ("LTC6101HV", "ADI LTC6101/LTC6101HV High Voltage, High-Side Current Sense Amplifier in "
                "SOT-23, Rev I, p. 1"),
    "LTC6102": ("LTC6102-1", "ADI LTC6102/LTC6102-1/LTC6102HV Precision Zero Drift Current Sense "
                "Amplifier, 6102fe, p. 1"),
    "LTC6103": ("LTC6103HMS8", "ADI LTC6103 Dual High Voltage, High Side Current Sense Amplifier, 6103f, p. 1"),
    "LTC4151": ("LTC4151CMS", "ADI LTC4151 High Voltage I2C Current and Voltage Monitor, Rev C, p. 1"),
    "ZXCT": ("ZXCT1010E5TA", "Diodes ZXCT1010 Enhanced High-Side Current Monitor, DS33442 Rev. 11, p. 1"),
}

# Look-alike part numbers that are not current-sense amplifiers.
NOT_SENSE_AMPS = {
    "INA188ID": "TI INA188 Precision, Zero-Drift, Rail-to-Rail Out, High-Voltage Instrumentation "
                "Amplifier, SBOS632 September 2015, p. 1",
    "INA217AIDWR": "TI INA217 Low-Noise, Low-Distortion Instrumentation Amplifier, SBOS247C revised "
                   "November 2015, p. 1",
    "MAX4714EXT+T": "Maxim MAX4714 0.8 Ohm, Low-Voltage, Single-Supply SPDT Analog Switch in SC70, "
                    "19-1982 Rev 1 5/04, p. 1",
    "PAM2401SCADJ": "Diodes PAM2401 1.0MHz Step-Up DC-DC Converter, DS37285 Rev. 1, p. 1",
    "INA128": "TI INA12x Precision, Low-Power Instrumentation Amplifiers, SBOS051G revised January 2026, p. 1",
    "INA2128": "TI INA2128 Dual, Low-Power Instrumentation Amplifier, SBOS035C revised January 2026, p. 1",
    "INA333": "TI INA333 Micro-Power (50uA), Zero-Drift, Rail-to-Rail Out Instrumentation Amplifier, "
              "SBOS445C revised December 2015, p. 1",
    "INA826": "TI INA826 Precision, 200-uA Supply Current, 3-V to 36-V Supply Instrumentation Amplifier "
              "With Rail-to-Rail Output, SBOS562G revised June 2020, p. 1",
    "TMC7300-Trinamic": "stepper driver; 'ina' inside the maker's name",
}


def _net(pins):
    return {"pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t) for r, p, pn, t in pins],
            "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}


def _ground_shunt_ic(value, lib_id, pin_name):
    """R1 (0.1 ohm) from GND to SENSE, U1's pin *pin_name* on SENSE: a low-side shunt."""
    comps = [{"reference": "U1", "type": "ic", "value": value, "lib_id": lib_id, "mpn": "",
              "pins": [], "footprint": ""},
             {"reference": "R1", "type": "resistor", "value": "0.1", "lib_id": "Device:R",
              "pins": [], "footprint": ""}]
    nets = {"SENSE": [("R1", "1", "~", "passive"), ("U1", "1", pin_name, "input")],
            "GND": [("R1", "2", "~", "passive"), ("U1", "4", "GND", "power_in")],
            "+5V": [("U1", "3", "VS", "power_in")]}
    full = {n: dict(_net(p), name=n) for n, p in nets.items()}
    ctx = build_analysis_context(comps, full, {}, known_power_rails={"+5V", "GND"})
    return [c["sense_ic"]["ref"] for c in sd.detect_current_sense(ctx)]


def _shunt_ic(value, lib_id, mpn="", rails=("VBAT", "VBAT_LOAD", "+3V3", "GND")):
    """R1 (0.1 ohm) from VBAT to VBAT_LOAD, U1's IN+/IN- across it."""
    comps = [{"reference": "U1", "type": "ic", "value": value, "lib_id": lib_id, "mpn": mpn},
             {"reference": "R1", "type": "resistor", "value": "0.1", "lib_id": "Device:R"}]
    nets = {"VBAT": [("R1", "1", "~", "passive"), ("U1", "1", "IN+", "input")],
            "VBAT_LOAD": [("R1", "2", "~", "passive"), ("U1", "2", "IN-", "input")],
            "+3V3": [("U1", "3", "VS", "power_in")], "GND": [("U1", "4", "GND", "power_in")]}
    for c in comps:
        c.setdefault("pins", [])
        c.setdefault("footprint", "")
    full = {n: dict(_net(p), name=n) for n, p in nets.items()}
    return build_analysis_context(comps, full, {}, known_power_rails=set(rails))


def _sense_refs(*args, **kwargs):
    return [c["sense_ic"]["ref"] for c in sd.detect_current_sense(_shunt_ic(*args, **kwargs))]


class SenseAmpNames(unittest.TestCase):
    def test_sense_amp_part_numbers(self):
        for value, lib in (("INA219", "Analog_ADC:INA219AxD"), ("INA3221", "Power_Management:INA3221"),
                           ("INA180A1", "Amplifier_Current:INA180A1"),
                           ("ACS712ELCTR-05B-T", "Sensor_Current:ACS712xLCTR-05B")):
            with self.subTest(value=value):
                self.assertEqual(_sense_refs(value, lib), ["U1"])

    def test_sense_amp_inside_a_module_name(self):
        self.assertEqual(_sense_refs("ModuleINA3221", "DBN:ModuleINA3221"), ["U1"])

    def test_sense_amp_named_only_by_mpn(self):
        self.assertEqual(_sense_refs("CSA", "board:IC_8PIN", mpn="INA226AIDGSR"), ["U1"])

    def test_sense_amp_off_a_rail(self):
        # VBAT_LOAD is a signal net here: the one-rail and integrated-CSA passes
        self.assertEqual(_sense_refs("INA219", "Analog_ADC:INA219AxD", rails=("VBAT", "+3V3", "GND")), ["U1"])

    def test_ina_inside_a_word_is_not_a_sense_amp(self):
        # "Trinamic", "terminal", "china" carry the letters ina
        self.assertEqual(_sense_refs("TMC7300", "lib:TMC7300-Trinamic"), [])

    def test_bridge_driver_low_side_shunt_is_not_a_sense_amp(self):
        # a stepper driver's BRA pin on a shunt from ground: "ina" inside "Trinamic"
        self.assertEqual(_ground_shunt_ic("TMC7300", "lib:TMC7300-Trinamic", "BRA"), [])

    def test_library_name_is_not_a_part_number(self):
        self.assertEqual(_sense_refs("LM358", "INA219_Breakout:LM358"), [])

    def test_instrumentation_amp_is_not_a_sense_amp(self):
        for value, lib in (("INA128", "Amplifier_Instrumentation:INA128"), ("INA188ID", "lib:INA188"),
                           ("INA217AIDWR", "lib:INA217")):
            with self.subTest(value=value):
                self.assertEqual(_sense_refs(value, lib), [])

    def test_analog_switch_is_not_max471(self):
        self.assertEqual(_sense_refs("MAX4714EXT+T", "Analog_Switch:MAX4714"), [])


class SenseAmpTable(unittest.TestCase):
    def test_every_cited_family_reads_as_a_sense_amp(self):
        for family, (pn, _) in SENSE_AMP_FAMILIES.items():
            with self.subTest(family=family):
                self.assertTrue(names_sense_amp(pn))

    def test_look_alikes_are_not_sense_amps(self):
        for pn in NOT_SENSE_AMPS:
            with self.subTest(pn=pn):
                self.assertFalse(names_sense_amp(pn))


if __name__ == "__main__":
    unittest.main()
