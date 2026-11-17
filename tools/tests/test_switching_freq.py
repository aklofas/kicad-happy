"""MIC23050 switches at 4 MHz and LM2675 at 260 kHz; both keys name one part, so a longer
part number that only starts with them is not read as either."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_core.parts import lookup_switching_freq, match_known_switching  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import detect_power_regulators  # noqa: E402


class KnownFrequencies(unittest.TestCase):
    def test_mic23050_runs_at_4_mhz(self):
        # MIC23050 datasheet M9999-092211-E p3, Electrical Characteristics: Frequency 4 MHz typ.
        for part in ("MIC23050-SYML", "MIC23050_GYML", "MIC23050-CYML-TR"):
            self.assertEqual(lookup_switching_freq(part), 4.0e6, part)

    def test_lm2675_runs_at_260_khz(self):
        # LM2675 datasheet SNVS129G p7, Electrical Characteristics: fO 260 kHz typ.
        for part in ("LM2675M-5.0", "LM2675MX-ADJ/NOPB", "LM2675N-3.3"):
            self.assertEqual(lookup_switching_freq(part), 260e3, part)

    def test_lm2675_is_a_known_switcher(self):
        self.assertTrue(match_known_switching("LM2675M-5.0", ""))
        self.assertTrue(match_known_switching("U2", "Regulator_Switching:LM2675M-5"))

    def test_a_longer_part_number_is_not_read_as_the_part(self):
        for part in ("LM26750", "MIC230500", "MIC2305"):
            self.assertIsNone(lookup_switching_freq(part), part)
            self.assertFalse(match_known_switching(part, "lib:" + part), part)

    def test_lm2596_keeps_150_khz(self):
        self.assertEqual(lookup_switching_freq("LM2596S-5.0"), 150e3)


class Lm2675Record(unittest.TestCase):
    def _ctx(self):
        parts = [("U1", "ic", "MyLib:LM2675", "LM2675M-5.0",
                  {"1": ("VIN", "+15V"), "2": ("GND", "GND"), "3": ("VOUT", "-5V")}),
                 ("C1", "capacitor", "Device:C", "10u", {"1": ("1", "-5V"), "2": ("2", "GND")})]
        components, nets = [], {}
        for ref, typ, lib_id, value, pins in parts:
            components.append({"reference": ref, "lib_id": lib_id, "value": value, "type": typ,
                               "pins": [{"number": n, "name": nm} for n, (nm, _) in pins.items()]})
            for num, (name, net) in pins.items():
                nets.setdefault(net, {"name": net, "pins": []})["pins"].append(
                    {"component": ref, "pin_number": num, "pin_name": name})
        return build_analysis_context(components, nets, {})

    def test_lm2675_with_only_vin_vout_is_a_switcher(self):
        reg = detect_power_regulators(self._ctx(), [])[0]
        self.assertEqual((reg["topology"], reg["switching_frequency_hz"], reg["freq_source"]),
                         ("switching", 260e3, "lookup_table"))

    def test_lm2675_on_a_negative_output_stays_inverting(self):
        reg = detect_power_regulators(self._ctx(), [])[0]
        self.assertTrue(reg.get("inverting"))
        self.assertEqual(reg["estimated_vout"], -5.0)


if __name__ == "__main__":
    unittest.main()
