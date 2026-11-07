# tools/tests/test_part_table_lookups.py
"""Switching frequency and ADC resolution come from the part's own datasheet family:
TPS62160-63 run at 2.25 MHz and TPS63000-02 at 1.5 MHz; an ADC's resolution is read from
the value before the lib_id, and an LTC23xx-NN part number carries NN bits."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_core.parts import lookup_switching_freq, match_known_switching  # noqa: E402
from domain_detectors import _infer_adc_resolution  # noqa: E402


class SwitchingFrequency(unittest.TestCase):
    def test_tps6216x_family_runs_at_2_25_mhz(self):
        for part in ("TPS62160DSGR", "TPS62161", "TPS62162DSGR", "TPS62163"):
            self.assertEqual(lookup_switching_freq(part), 2.25e6, part)

    def test_tps6300x_family_runs_at_1_5_mhz(self):
        for part in ("TPS63000", "TPS63001DRCR", "TPS63002"):
            self.assertEqual(lookup_switching_freq(part), 1.5e6, part)

    def test_neighbouring_families_keep_their_own_frequency(self):
        self.assertEqual(lookup_switching_freq("TPS63020"), 2.4e6)
        self.assertEqual(lookup_switching_freq("TPS630250"), 2.5e6)
        self.assertEqual(lookup_switching_freq("TPS62170"), 2.25e6)
        self.assertEqual(lookup_switching_freq("TPS62130"), 2.5e6)

    def test_tps63001_is_a_known_switcher(self):
        self.assertTrue(match_known_switching("TPS63001", "Regulator_Switching:TPS63001"))


class AdcResolution(unittest.TestCase):
    def test_mcp3427_is_16_bit(self):
        self.assertEqual(_infer_adc_resolution("MCP3427", "Analog_ADC:MCP3427"), 16)

    def test_ltc23xx_suffix_gives_the_bits(self):
        self.assertEqual(_infer_adc_resolution("LTC2378-20", "Analog_ADC:LTC2378-20"), 20)
        self.assertEqual(_infer_adc_resolution("LTC2320-16", ""), 16)
        self.assertEqual(_infer_adc_resolution("LTC2380-24", "Analog_ADC:LTC2380-24"), 24)

    def test_value_is_read_before_the_lib_id(self):
        self.assertEqual(_infer_adc_resolution("MCP3204", "Analog_ADC:MCP3304"), 12)
        self.assertEqual(_infer_adc_resolution("MCP3427", "Analog_ADC:MCP3204"), 16)

    def test_mcp3304_is_13_bit(self):
        self.assertEqual(_infer_adc_resolution("MCP3304", "Analog_ADC:MCP3304"), 13)

    def test_ltc23xx_without_suffix_has_no_resolution(self):
        self.assertIsNone(_infer_adc_resolution("LTC2323", "Analog_ADC:LTC2323"))


if __name__ == "__main__":
    unittest.main()
