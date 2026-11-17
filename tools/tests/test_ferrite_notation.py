# tools/tests/test_ferrite_notation.py
"""A bead is specified as an impedance at a frequency; an inductor's value is never ohms."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.classify import classify_component  # noqa: E402


class FerriteNotation(unittest.TestCase):
    def test_ohm_at_frequency_is_a_bead(self):
        for v in ("330 OHM@100MHZ", "600Ohm@100MHz", "120 Ohm @ 100 MHz",
                  "33Ω @ 100MHz", "600OHM/2A", "600R/200mA", "120R@100MHz"):
            self.assertEqual(classify_component("L1", "Device:L", v), "ferrite_bead", v)

    def test_inductances_stay_inductors(self):
        for v in ("10uH 0.5Ohm/2A", "10uH 0.5R/2A", "2.2\u00b5H 50mOhm@1MHz", "4.7mH 10Ohm/1A",
                  "10uH", "4R7", "2R2", "10uH/2A", "100nH"):
            self.assertEqual(classify_component("L1", "Device:L", v), "inductor", v)


if __name__ == "__main__":
    unittest.main()
