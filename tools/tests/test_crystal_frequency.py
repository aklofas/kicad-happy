"""A crystal value is read as the frequency it means; a number that cannot be a crystal
frequency (a part number, a capacitance, a count) is dropped."""
import contextlib, io, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import signal_detectors as sd  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402


class ParseCrystalFrequency(unittest.TestCase):
    def test_values_without_a_unit_or_with_a_loose_unit(self):
        for text, want in (("32.768", 32768.0), ("14.31818", 14318180.0), ("7.3728", 7372800.0),
                           ("27.145 3OT", 27145000.0), ("8m", 8e6),
                           ("32768Hz", 32768.0), ("32.768Hz", 32768.0), ("32,768", 32768.0),
                           ("32,768 Hz", 32768.0), ("32_Mhz", 32e6),
                           ("32768_1206_12.5pF", 32768.0), ("8M_HS49S_20pF", 8e6)):
            got = sd._parse_crystal_frequency(text)
            self.assertIsNotNone(got, msg=text)
            self.assertAlmostEqual(got / want, 1.0, places=9, msg=text)

    def test_a_package_code_in_the_first_field_is_not_the_frequency(self):
        for text, want in (("3225_16M", 16e6), ("2520_26M_10pF", 26e6),
                           ("32768_1206_12.5pF", 32768.0), ("8M_HS49S_20pF", 8e6)):
            got = sd._parse_crystal_frequency(text)
            self.assertIsNotNone(got, msg=text)
            self.assertAlmostEqual(got / want, 1.0, places=9, msg=text)

    def test_numbers_that_cannot_be_a_crystal_frequency_are_dropped(self):
        for text in ("830108313809", "100nF", "0", "400 P", "32768MHz", "", "X7R, 50V"):
            self.assertIsNone(sd._parse_crystal_frequency(text), msg=text)

    def test_readings_that_were_right_keep_their_value(self):
        for text, want in (("SG3225VAN-250Mhz", 250e6), ("3225_4P 12MHz", 12e6),
                           ("HC49,16MHz", 16e6), ("9,84375 MHz", 9.84375e6),
                           ("ABM8-25.000MHZ", 25e6), ("YIC-12M20P2", 12e6), ("32768", 32768.0)):
            got = sd._parse_crystal_frequency(text)
            self.assertIsNotNone(got, msg=text)
            self.assertAlmostEqual(got / want, 1.0, places=9, msg=text)


class CrystalTargetLoad(unittest.TestCase):
    def test_bare_32_768_crystal_takes_the_watch_crystal_load(self):
        def cap(ref, value):
            return {"reference": ref, "type": "capacitor", "value": value, "lib_id": "",
                    "pins": [], "footprint": ""}
        comps = [{"reference": "Y1", "type": "crystal", "value": "32.768", "lib_id": "",
                  "footprint": "", "pins": [{"number": "1", "name": "1"}, {"number": "2", "name": "2"}]},
                 cap("C1", "12p"), cap("C2", "12p")]
        raw = {"XI": [("Y1", "1"), ("C1", "1")], "XO": [("Y1", "2"), ("C2", "1")],
               "GND": [("C1", "2"), ("C2", "2")]}
        nets = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name="~", pin_type="passive")
                                        for r, p in pins],
                    "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
                for n, pins in raw.items()}
        with contextlib.redirect_stderr(io.StringIO()):
            ctx = build_analysis_context(comps, nets, {})
        xl = sd.detect_crystal_circuits(ctx)
        self.assertEqual(len(xl), 1)
        self.assertEqual(xl[0]["frequency"], 32768.0)
        self.assertEqual(xl[0]["target_load_pF"], 12.5)


class CrystalLoadLegs(unittest.TestCase):
    def test_caps_group_per_net_in_first_seen_order_and_each_ref_counts_once(self):
        from kicad_core.passives import crystal_load_legs
        caps = [{"ref": "C1", "net": "XI", "farads": 12e-12},
                {"ref": "C2", "net": "XO", "farads": 10e-12},
                {"ref": "C3", "net": "XI", "farads": 5e-12},
                {"ref": "C1", "net": "XI", "farads": 12e-12}]
        legs = crystal_load_legs(caps)
        self.assertEqual([leg["net"] for leg in legs], ["XI", "XO"])
        self.assertEqual(legs[0]["refs"], ["C1", "C3"])
        self.assertAlmostEqual(legs[0]["farads"], 17e-12)
        self.assertAlmostEqual(sd._load_legs(caps)[1], 10e-12)


if __name__ == "__main__":
    unittest.main()
