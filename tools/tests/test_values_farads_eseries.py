import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_core.values import parse_value, snap_to_e_series  # noqa: E402


class CapacitorFarads(unittest.TestCase):
    def test_explicit_farads_and_exponents_are_si(self):
        for text, want in [("1F", 1.0), ("120F", 120.0), ("0.1F", 0.1), ("1 F", 1.0),
                           ("0.47F 5.5V", 0.47), ("120F 2.3v", 120.0), ("1e-6", 1e-6),
                           ("1e-6F", 1e-6), ("10e-12", 1e-11), ("1.5F/5.5V", 1.5)]:
            self.assertAlmostEqual(parse_value(text, component_type="capacitor") / want, 1.0, places=9, msg=text)

    def test_bare_plain_numbers_keep_the_legacy_rescale(self):
        for text, want in [("100", 1e-10), ("0.1", 1e-7), ("4.7", 4.7e-12), ("100n", 1e-7), ("0.1f", 1e-7)]:
            self.assertAlmostEqual(parse_value(text, component_type="capacitor") / want, 1.0, places=9, msg=text)

    def test_untyped_f_is_unchanged(self):
        self.assertEqual(parse_value("1F"), 1.0)
        self.assertAlmostEqual(parse_value("0.1f"), 0.1)

    def test_signed_explicit_si_is_not_rescaled(self):
        for text, ctype, want in [("+1e-6", "capacitor", 1e-6), ("+1F", "capacitor", 1.0),
                                  ("-12", "resistor", -12.0)]:
            self.assertAlmostEqual(parse_value(text, component_type=ctype) / want, 1.0, places=9, msg=text)

    def test_lowercase_f_is_femto_with_a_unit_or_off_a_capacitor(self):
        for text, ctype, want in [("10fF", "capacitor", 1e-14), ("10 fF", "capacitor", 1e-14),
                                  ("10f", "resistor", 1e-14), ("2fH", "inductor", 2e-15)]:
            self.assertAlmostEqual(parse_value(text, component_type=ctype) / want, 1.0, places=9, msg=text)


class ESeriesSnap(unittest.TestCase):
    def test_log_distance_and_decade_top(self):
        self.assertEqual(snap_to_e_series(9900, "E12"), (10000.0, 1.01))
        self.assertEqual(snap_to_e_series(9.6, "E24")[0], 10.0)
        self.assertEqual(snap_to_e_series(9.9, "E96")[0], 10.0)
        self.assertEqual(snap_to_e_series(8.5, "E12")[0], 8.2)
        self.assertEqual(snap_to_e_series(1.1, "E12")[0], 1.2)
        self.assertEqual(snap_to_e_series(4.7, "E12")[0], 4.7)


if __name__ == "__main__":
    unittest.main()
