# tools/tests/test_instrumentation_amps.py
"""An instrumentation amplifier sets its gain with RG, not op-amp feedback: it is not reported as
an op-amp stage, and EMC still counts it as a sensitive part. Every family is cited below."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))
from kicad_core.parts import is_instrumentation_amp  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from finding_schema import Det  # noqa: E402
from emc_rules import check_inductor_leakage  # noqa: E402
import signal_detectors as sd  # noqa: E402

# Family -> (a part number in it, maker datasheet: title, revision, page).
INAMP_FAMILIES = {
    "AD620": ("AD620ARZ", "ADI AD620 Low Cost Low Power Instrumentation Amplifier, Rev. H, p. 1"),
    "AD621": ("AD621AN", "ADI AD621 Low Drift, Low Power Instrumentation Amplifier, Rev. B, p. 1"),
    "AD622": ("AD622AR", "ADI AD622 Low Cost Instrumentation Amplifier, Rev. E, p. 1"),
    "AD623": ("AD623ARMZ", "ADI AD623 Single and Dual-Supply, Rail-to-Rail, Low Cost Instrumentation "
              "Amplifier, Rev. G, p. 1"),
    "AD624": ("AD624AD", "ADI AD624 Precision Instrumentation Amplifier, Rev. C, p. 1"),
    "AD625": ("AD625JN", "ADI AD625 Low Cost Programmable Gain Instrumentation Amplifier, Rev. D, p. 1"),
    "AD627": ("AD627ARZ", "ADI AD627 Micropower, Single- and Dual-Supply, Rail-to-Rail Instrumentation "
              "Amplifier, Rev. E, p. 1"),
    "AD8220": ("AD8220ARMZ", "ADI AD8220 JFET Input Instrumentation Amplifier with Rail-to-Rail Output in "
               "MSOP Package, Rev. C, p. 1"),
    "AD8221": ("AD8221ARZ", "ADI AD8221 Precision Instrumentation Amplifier, Rev. C, p. 1"),
    "AD8222": ("AD8222ACPZ-R7", "ADI AD8222 Precision, Dual-Channel Instrumentation Amplifier, Rev. B, p. 1"),
    "AD8223": ("AD8223ARZ", "ADI AD8223 Single-Supply, Low Cost Instrumentation Amplifier, Rev. 0, p. 1"),
    "AD8224": ("AD8224ACPZ", "ADI AD8224 Precision, Dual-Channel, JFET Input, Rail-to-Rail Instrumentation "
               "Amplifier, Rev. D, p. 1"),
    "AD8225": ("AD8225ARZ", "ADI AD8225 Precision Gain of 5 Instrumentation Amplifier, Rev. A, p. 1"),
    "AD8226": ("AD8226BRZ-RL", "ADI AD8226 Wide Supply Range, Rail-to-Rail Output Instrumentation "
               "Amplifier, Rev. D, p. 1"),
    "AD8227": ("AD8227ARMZ", "ADI AD8227 Wide Supply Range, Rail-to-Rail Output Instrumentation "
               "Amplifier, Rev. 0, p. 1"),
    "AD8228": ("AD8228ARZ", "ADI AD8228 Low Gain Drift Precision Instrumentation Amplifier, Rev. 0, p. 1"),
    "AD8229": ("AD8229HRZ", "ADI AD8229 1 nV/sqrt(Hz) Low Noise 210 C Instrumentation Amplifier, Rev. B, p. 1"),
    "AD8230": ("AD8230YRZ", "ADI AD8230 16 V Rail-to-Rail, Zero-Drift, Precision Instrumentation "
               "Amplifier, Rev. B, p. 1"),
    "AD8231": ("AD8231ACPZ", "ADI AD8231 Zero Drift, Digitally Programmable Instrumentation Amplifier, "
               "Rev. A, p. 1"),
    "AD8232": ("AD8232ACPZ-R7", "ADI AD8232 Single-Lead, Heart Rate Monitor Front End, Rev. D, p. 18: "
               "contains a specialized instrumentation amplifier"),
    "AD8233": ("AD8233ACBZ-R7", "ADI AD8233 50 uA, 2 mm x 1.7 mm WLCSP, Low Noise, Heart Rate Monitor for "
               "Wearable Products, Rev. D, p. 1: a filter coupled with its instrumentation amplifier"),
    "AD8235": ("AD8235ACBZ", "ADI AD8235 40 uA Micropower Instrumentation Amplifier in WLCSP Package, "
               "Rev. A, p. 1"),
    "AD8236": ("AD8236ARMZ", "ADI AD8236 40 uA Micropower Instrumentation Amplifier with Zero Crossover "
               "Distortion, Rev. 0, p. 1"),
    "AD8237": ("AD8237ARMZ", "ADI AD8237 Micropower, Zero Drift, True Rail-to-Rail Instrumentation "
               "Amplifier, Rev. 0, p. 1"),
    "AD8250": ("AD8250ARMZ", "ADI AD8250 10 MHz, G = 1, 2, 5, 10 iCMOS Programmable Gain Instrumentation "
               "Amplifier, Rev. C, p. 1"),
    "AD8251": ("AD8251ARMZ", "ADI AD8251 10 MHz, G = 1, 2, 4, 8 iCMOS Programmable Gain Instrumentation "
               "Amplifier, Rev. B, p. 1"),
    "AD8253": ("AD8253ARMZ", "ADI AD8253 10 MHz, G = 1, 10, 100, 1000 iCMOS Programmable Gain "
               "Instrumentation Amplifier, Rev. B, p. 1"),
    "AD8293": ("AD8293G80ARJZ", "ADI AD8293G80/AD8293G160 Low Cost, Zero-Drift In-Amp with Filter and "
               "Fixed Gain, Rev. 0, p. 1"),
    "AD8295": ("AD8295ACPZ", "ADI AD8295 Precision Instrumentation Amplifier with Signal Processing "
               "Amplifiers, Rev. A, p. 1"),
    "AD8420": ("AD8420ARMZ", "ADI AD8420 Wide Supply Range, Micropower, Rail-to-Rail Instrumentation "
               "Amplifier, Rev. B, p. 1"),
    "AD8421": ("AD8421ARMZ", "ADI AD8421 3 nV/sqrt(Hz), Low Power Instrumentation Amplifier, Rev. A, p. 1"),
    "AD8422": ("AD8422BRMZ", "ADI AD8422 High Performance, Low Power, Rail-to-Rail Precision "
               "Instrumentation Amplifier, Rev. C, p. 1"),
    "AD8426": ("AD8426ACPZ", "ADI AD8426 Wide Supply Range, Rail-to-Rail Output Instrumentation "
               "Amplifier (dual), Rev. 0, p. 1"),
    "AD8428": ("AD8428ARZ", "ADI AD8428 Low Noise, Low Gain Drift, G = 2000 Instrumentation Amplifier, "
               "Rev. A, p. 1"),
    "AD8429": ("AD8429ARZ", "ADI AD8429 1 nV/sqrt(Hz) Low Noise Instrumentation Amplifier, Rev. A, p. 1"),
    "AD8553": ("AD8553ARMZ", "ADI AD8553 1.8 V to 5 V Auto-Zero, In-Amp with Shutdown, Rev. A, p. 1"),
    "INA101": ("INA101KU", "TI INA101 High Accuracy Instrumentation Amplifier, SBOS133, p. 1"),
    "INA103": ("INA103KP", "TI INA103 Low Noise, Low Distortion Instrumentation Amplifier, SBOS003A "
               "revised September 2023, p. 1"),
    "INA110": ("INA110KU", "TI INA110 Fast-Settling FET-Input Instrumentation Amplifier, SBOS147A, p. 1"),
    "INA111": ("INA111AU", "TI INA111 High Speed FET-Input Instrumentation Amplifier, SBOS015, p. 1"),
    "INA114": ("INA114AU", "TI INA114 Precision Instrumentation Amplifier, SBOS014B revised January 2026, p. 1"),
    "INA115": ("INA115BU", "TI INA115 Precision Instrumentation Amplifier, SBOS021, p. 1"),
    "INA116": ("INA116UA", "TI INA116 Ultra Low Input Bias Current Instrumentation Amplifier, SBOS034, p. 1"),
    "INA118": ("INA118U", "TI INA118 Precision, Low-Power Instrumentation Amplifier, SBOS027C revised "
               "September 2022, p. 1"),
    "INA121": ("INA121PA", "TI INA121 FET-Input, Low Power Instrumentation Amplifier, SBOS078, p. 1"),
    "INA122": ("INA122P", "TI INA122 Single Supply, Micropower Instrumentation Amplifier, SBOS069B revised "
               "December 2025, p. 1"),
    "INA125": ("INA125U", "TI INA125 Instrumentation Amplifier with Precision Voltage Reference, SBOS060, p. 1"),
    "INA126/INA2126": ("INA2126UA", "TI INAx126 MicroPower Instrumentation Amplifiers, SBOS062D revised "
                       "December 2025, p. 1"),
    "INA128/INA129": ("INA129UA", "TI INA12x Precision, Low-Power Instrumentation Amplifiers, SBOS051G "
                      "revised January 2026, p. 1"),
    "INA2128": ("INA2128UA", "TI INA2128 Dual, Low-Power Instrumentation Amplifier, SBOS035C revised "
                "January 2026, p. 1"),
    "INA163": ("INA163UA", "TI INA163 Low-Noise, Low-Distortion Instrumentation Amplifier, SBOS177D "
               "revised May 2005, p. 1"),
    "INA166": ("INA166UA", "TI INA166 Low-Noise, Low-Distortion, G = 2000 Instrumentation Amplifier, "
               "SBOS178, p. 1"),
    "INA188": ("INA188ID", "TI INA188 Precision, Zero-Drift, Rail-to-Rail Out, High-Voltage "
               "Instrumentation Amplifier, SBOS632 September 2015, p. 1"),
    "INA217": ("INA217AIDWR", "TI INA217 Low-Noise, Low-Distortion Instrumentation Amplifier, SBOS247C "
               "revised November 2015, p. 1"),
    "INA321/INA2321": ("INA2321EA", "TI INA321/INA2321 microPower, Single-Supply, CMOS Instrumentation "
                       "Amplifier, SBOS168D revised January 2006, p. 1"),
    "INA322/INA2322": ("INA322EA", "TI INA322/INA2322 microPower, Single-Supply, CMOS Instrumentation "
                       "Amplifier, SBOS174B revised February 2006, p. 1"),
    "INA326/INA327": ("INA327EA", "TI INA326/INA327 Precision, Rail-to-Rail I/O Instrumentation Amplifier, "
                      "SBOS222D revised November 2004, p. 1"),
    "INA331/INA2331": ("INA2331AIPWR", "TI INA331/INA2331 Low-Power, Single-Supply, CMOS Instrumentation "
                       "Amplifiers, SBOS215C revised April 2005, p. 1"),
    "INA332/INA2332": ("INA332AIDGKR", "TI INA332/INA2332 Low-Power, Single-Supply, Wide-Bandwidth, CMOS "
                       "Instrumentation Amplifiers, SBOS216B revised October 2006, p. 1"),
    "INA333": ("INA333AIDGKR", "TI INA333 Micro-Power (50uA), Zero-Drift, Rail-to-Rail Out Instrumentation "
               "Amplifier, SBOS445C revised December 2015, p. 1"),
    "INA350": ("INA350CDSIDDFR", "TI INA350 Cost and Size Optimized, Low Power, 1.8-V to 5.5-V Selectable "
               "Gain Instrumentation Amplifier, SBOSAA0C revised May 2023, p. 1"),
    "INA351": ("INA351ABSIDDFR", "TI INA351 Cost and Size Optimized, Low Power, 1.8V to 5.5V Selectable Gain "
               "Instrumentation Amplifier with Integrated Reference Buffer, SBOSAD5D revised November 2024, p. 1"),
    "INA818": ("INA818IDR", "TI INA818 35-uV Offset, 8-nV/sqrt(Hz) Noise, Low-Power, Precision Instrumentation "
               "Amplifier, SBOS894A revised June 2019, p. 1"),
    "INA819": ("INA819IDR", "TI INA819 35-uV Offset, 8-nV/sqrt(Hz) Noise, Low-Power, Precision Instrumentation "
               "Amplifier, SBOS959D revised April 2022, p. 1"),
    "INA821": ("INA821ID", "TI INA821 35-uV Offset, 7-nV/sqrt(Hz) Noise, Low-Power, Precision Instrumentation "
               "Amplifier, SBOS893D revised June 2020, p. 1"),
    "INA823": ("INA823DR", "TI INA823 Precision, Low-Power, Wide-Supply (2.7-V to 36-V) Instrumentation "
               "Amplifier, SBOSA75B revised November 2021, p. 1"),
    "INA826": ("INA826AIDR", "TI INA826 Precision, 200-uA Supply Current, 3-V to 36-V Supply Instrumentation "
               "Amplifier With Rail-to-Rail Output, SBOS562G revised June 2020, p. 1"),
    "INA827": ("INA827AIDGKR", "TI INA827 Wide-Supply, High-CMRR Instrumentation Amplifier With a Minimum "
               "Gain of 5, SBOS631B revised November 2017, p. 1"),
    "INA828": ("INA828IDR", "TI INA828 50-uV Offset, 7-nV/sqrt(Hz) Noise, Low-Power, Precision Instrumentation "
               "Amplifier, SBOS792A revised January 2018, p. 1"),
    "INA848": ("INA848ID", "TI INA848 Ultra-Low-Noise (1.5 nV/sqrt(Hz)), High-Bandwidth Instrumentation "
               "Amplifier, SBOS946, p. 1"),
    "INA849": ("INA849DR", "TI INA849 Ultra-Low-Noise (1 nV/sqrt(Hz)), High-Bandwidth, Instrumentation "
               "Amplifier, SBOS945B revised April 2021, p. 1"),
    "INA851": ("INA851RGTR", "TI INA851 Precision, Low-Noise, Fully Differential Output Instrumentation "
               "Amplifier, SBOS999A revised October 2022, p. 1"),
    "LT1101": ("LT1101CN8", "ADI LT1101 Precision, Micropower, Single Supply Instrumentation Amplifier "
               "(Fixed Gain = 10 or 100), 1101fa, p. 1"),
    "LT1102": ("LT1102CN8", "ADI LT1102 High Speed, Precision, JFET Input Instrumentation Amplifier "
               "(Fixed Gain = 10 or 100), 1102fb, p. 1"),
    "LT1167": ("LT1167CS8", "ADI LT1167 Single Resistor Gain Programmable, Precision Instrumentation "
               "Amplifier, 1167fc, p. 1"),
    "LT1168": ("LT1168CS8", "ADI LT1168 Low Power, Single Resistor Gain Programmable, Precision "
               "Instrumentation Amplifier, 1168fa, p. 1"),
    "LT1789": ("LT1789CS8-1", "ADI LT1789-1/LT1789-10 Micropower, Single Supply Rail-to-Rail Output "
               "Instrumentation Amplifiers, 1789fc, p. 1"),
    "LTC1100": ("LTC1100CN8", "ADI LTC1100 Precision, Zero-Drift Instrumentation Amplifier, 1100fc, p. 1"),
    "LTC2053": ("LTC2053CMS8", "ADI LTC2053/LTC2053-SYNC Precision, Rail-to-Rail, Zero-Drift, "
                "Resistor-Programmable Instrumentation Amplifier, Rev. D, p. 1"),
    "LTC6800": ("LTC6800HMS8", "ADI LTC6800 Rail-to-Rail, Input and Output, Instrumentation Amplifier, "
                "6800fb, p. 1"),
    "LTC6915": ("LTC6915IGN", "ADI LTC6915 Zero Drift, Precision Instrumentation Amplifier with Digitally "
                "Programmable Gain, 6915fb, p. 1"),
    "MAX4194-MAX4197": ("MAX4196ESA+", "Maxim MAX4194-MAX4197 Micropower, Single-Supply, Rail-to-Rail, "
                        "Precision Instrumentation Amplifiers, 19-1468 Rev 2, p. 1"),
    "MAX4208/MAX4209": ("MAX4209HAUA+T", "Maxim MAX4208/MAX4209 Ultra-Low Offset/Drift, Precision "
                        "Instrumentation Amplifiers with REF Buffer, 19-0924 Rev 3, p. 1"),
    "MAX4460-MAX4462": ("MAX4460ESA", "Maxim MAX4460/MAX4461/MAX4462 SOT23, 3V/5V, Single-Supply, "
                        "Rail-to-Rail Instrumentation Amplifiers, 19-2279 Rev 4 3/06, p. 1"),
    "PGA204/PGA205": ("PGA205BU", "TI PGA204/PGA205 Programmable Gain Instrumentation Amplifier, SBOS022, p. 1"),
    "PGA206/PGA207": ("PGA207PA", "TI PGA206/PGA207 Programmable Gain Instrumentation Amplifier, SBOS033, p. 1"),
    "PGA280": ("PGA280AIPWR", "TI PGA280 Zero-Drift, High-Voltage, Programmable Gain Instrumentation "
               "Amplifier, SBOS487B revised March 2020, p. 1"),
    "PGA281": ("PGA281AIPWR", "TI PGA281 Precision, Zero-Drift, High-Voltage, Programmable Gain "
               "Instrumentation Amplifier, SBOS664A revised June 2013, p. 1"),
}

# Look-alike part numbers that are not instrumentation amplifiers.
NOT_INAMPS = {
    "AD626ARZ": "ADI AD626 Low Cost, Single-Supply Differential Amplifier, Rev. D, p. 1",
    "AD822ARZ": "ADI AD822 Single-Supply, Rail-to-Rail Low Power FET-Input Op Amp, Rev. J, p. 1",
    "AD8276ARMZ": "ADI AD8276/AD8277 Low Power, Wide Supply Range, Low Cost Unity-Gain Difference "
                  "Amplifiers, Rev. D, p. 1",
    "AD8554ARUZ": "ADI AD8551/AD8552/AD8554 Zero-Drift, Single-Supply, Rail-to-Rail Input/Output "
                  "Operational Amplifiers, Rev. F, p. 1",
    "INA117KU": "TI INA117 High Common-Mode Voltage Difference Amplifier, SBOS154C revised January 2026, p. 1",
    "INA219B": "TI INA219 Zero-Drift, Bidirectional Current/Power Monitor With I2C Interface, SBOS448G "
               "revised December 2015, p. 1",
    "INA3221AIRGVR": "TI INA3221 26V, Triple Channel, 13-Bit, I2C Output Current and Voltage Monitor With "
                     "Alerts, SBOS576C revised September 2026, p. 1",
    "INA4180A2": "TI INAx180 Low- and High-Side Voltage Output, Current-Sense Amplifiers, SBOS741H revised "
                 "July 2022, p. 1",
    "MAX4466EXK+T": "Maxim MAX4465-MAX4469 Low-Cost, Micropower, SC70/SOT23-8, Microphone Preamplifiers "
                    "with Complete Shutdown, 19-1950 Rev 2 6/12, p. 1: micropower op amps",
    "PGA2040": "an RP2040 microcontroller board; the PGA204 digits run on",
}


def _net(pins):
    return {"pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t) for r, p, pn, t in pins],
            "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}


def _opamp_records(value, lib_id, description="", mpn="", pin_names=("-", "+")):
    """U1 with inverting input on INN, non-inverting on INP and its output on OUT."""
    pins = [{"number": "2", "name": pin_names[0]}, {"number": "3", "name": pin_names[1]},
            {"number": "6", "name": "OUT"}]
    comps = [{"reference": "U1", "type": "ic", "value": value, "lib_id": lib_id, "mpn": mpn,
              "description": description, "pins": pins, "footprint": ""}]
    nets = {"INN": [("U1", "2", pin_names[0], "input")], "INP": [("U1", "3", pin_names[1], "input")],
            "OUT": [("U1", "6", "OUT", "output")]}
    full = {n: dict(_net(p), name=n) for n, p in nets.items()}
    return sd.detect_opamp_circuits(build_analysis_context(comps, full, {}, known_power_rails=set()))


class InstrumentationAmps(unittest.TestCase):
    def test_in_amps_are_not_op_amp_stages(self):
        for value, lib, desc in (("INST OP-AMP", "SymLib:INA823DR", "Instrumentation Amplifier"),
                                 ("AD620", "Amplifier_Instrumentation:AD620", ""),
                                 ("AD623", "Lib:AD623AR", "Single Supply, Rail to Rail, Instumentation Amplifier"),
                                 ("AD8226", "AD8226", ""), ("INA128", "Custom:INA128", ""),
                                 ("AD8222ACPZ-R7", "mainbox:AD8222ACPZ-R7", "")):
            with self.subTest(value=value):
                self.assertEqual(_opamp_records(value, lib, desc), [])

    def test_in_amp_named_by_value_on_an_op_amp_symbol(self):
        for value in ("INA826", "INA128", "AD8421"):
            with self.subTest(value=value):
                self.assertEqual(_opamp_records(value, "Amplifier_Operational:OPAMP"), [])

    def test_in_amp_named_only_by_mpn(self):
        self.assertEqual(_opamp_records("AMP", "Amplifier_Operational:OPAMP", mpn="INA826AIDR"), [])

    def test_rescued_in_amp_symbol(self):
        self.assertEqual(_opamp_records("AD8421", "proj-rescue:AD8421-Amplifier_Instrumentation"), [])

    def test_rg_pin_pair_marks_an_in_amp(self):
        self.assertTrue(is_instrumentation_amp("X", pin_names=("RG", "RG", "OUT")))
        self.assertTrue(is_instrumentation_amp("X", pin_names=("+RG", "-RG")))
        self.assertFalse(is_instrumentation_amp("X", pin_names=("RG", "OUT")))

    def test_op_amps_stay_op_amps(self):
        for value, lib in (("TL071", "Amplifier_Operational:TL071"), ("AD822", "Amplifier_Operational:AD822"),
                           ("OPA2333", "Amplifier_Operational:OPA2333xxD"),
                           ("AD8554", "Amplifier_Operational:AD8554"), ("MAX4466", "Amplifier_Audio:MAX4466")):
            with self.subTest(value=value):
                self.assertEqual(len(_opamp_records(value, lib)), 1)


class InstrumentationAmpTable(unittest.TestCase):
    def test_every_cited_family_reads_as_an_in_amp(self):
        for family, (pn, _) in INAMP_FAMILIES.items():
            with self.subTest(family=family):
                self.assertTrue(is_instrumentation_amp(pn))

    def test_look_alikes_are_not_in_amps(self):
        for pn in NOT_INAMPS:
            with self.subTest(pn=pn):
                self.assertFalse(is_instrumentation_amp(pn))

    def test_library_and_description(self):
        self.assertTrue(is_instrumentation_amp("X", library="Amplifier_Instrumentation"))
        self.assertTrue(is_instrumentation_amp("X", description="Precision In-Amp"))
        self.assertFalse(is_instrumentation_amp("X", library="Amplifier_Operational",
                                                description="Precision op amp for instrumentation"))


def _ml001(amp_comps, oa_records=()):
    """L2 is an unshielded buck inductor 5 mm from U1."""
    sch = {"components": list(amp_comps), "findings": [
        {"detector": Det.POWER_REGULATORS, "ref": "U5", "topology": "buck",
         "inductor": "L2", "switching_frequency_hz": 500e3}, *oa_records]}
    pcb = {"footprints": [
        {"reference": "L2", "x": 100.0, "y": 100.0,
         "library": "Inductor_SMD:L_1210_3225Metric", "value": "4.7uH", "mpn": ""},
        {"reference": "U1", "x": 105.0, "y": 100.0}]}
    return [f["components"] for f in check_inductor_leakage(pcb, sch) if f["rule_id"] == "ML-001"]


class InstrumentationAmpEmc(unittest.TestCase):
    def test_in_amp_near_an_unshielded_inductor_is_sensitive(self):
        amp = {"reference": "U1", "type": "ic", "value": "AD620", "lib_id": "Amplifier_Instrumentation:AD620"}
        self.assertEqual(_ml001([amp]), [["L2", "U1"]])

    def test_in_amp_on_an_op_amp_symbol_is_sensitive(self):
        amp = {"reference": "U1", "type": "ic", "value": "INA826", "lib_id": "Amplifier_Operational:OPAMP"}
        self.assertEqual(_ml001([amp], _opamp_records("INA826", "Amplifier_Operational:OPAMP")),
                         [["L2", "U1"]])

    def test_op_amp_counts_through_its_op_amp_record_only(self):
        amp = {"reference": "U1", "type": "ic", "value": "TL071", "lib_id": "Amplifier_Operational:TL071"}
        self.assertEqual(_ml001([amp]), [])


if __name__ == "__main__":
    unittest.main()
