"""Value notation as KiCad's simulator reads R/L/C values (sim_model.cpp value inference)."""
import contextlib, io, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_core.values import ambiguous_separator, parse_value  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402


class ValueNotation(unittest.TestCase):
    def check(self, cases):
        for text, ctype, want in cases:
            got = parse_value(text, component_type=ctype)
            self.assertIsNotNone(got, msg=text)
            self.assertAlmostEqual(got / want, 1.0, places=9, msg=text)

    def test_micro_and_ohm_signs(self):
        # Both micro signs map to "u"; the ohm signs are a unit.
        self.check([("10μF", "capacitor", 1e-5), ("10 μF", "capacitor", 1e-5),
                    ("1 μH", "inductor", 1e-6), ("1μH", "inductor", 1e-6),
                    ("10µF", "capacitor", 1e-5), ("10 µF", "capacitor", 1e-5),
                    ("10kΩ", "resistor", 1e4), ("4.7kΩ", "resistor", 4700.0),
                    ("4.7kΩ", "resistor", 4700.0), ("1KΩ", "resistor", 1e3)])

    def test_meg_is_mega(self):
        self.check([("1Meg", "resistor", 1e6), ("1MEG", "resistor", 1e6), ("1 Meg", "resistor", 1e6),
                    ("2Meg", "resistor", 2e6), ("5Meg6", "resistor", 5.6e6), ("1M", "resistor", 1e6)])

    def test_unambiguous_decimal_comma_and_grouping(self):
        self.check([("4,7k", "resistor", 4700.0), ("4,7uF", "capacitor", 4.7e-6),
                    ("0,1uF", "capacitor", 1e-7), ("2,2u", "capacitor", 2.2e-6),
                    ("0,100", "resistor", 0.1), ("1,000.5", "resistor", 1000.5),
                    ("1.000,5", "resistor", 1000.5), ("1,000,000", "resistor", 1e6),
                    ("19,6 kΩ", "resistor", 19600.0), ("4,7 µH", "inductor", 4.7e-6),
                    ("78 182", "resistor", 78182.0), (".022uF", "capacitor", 2.2e-8)])

    def test_dot_with_three_digits_is_decimal(self):
        self.check([("1.000", "resistor", 1.0), ("4.700k", "resistor", 4700.0),
                    ("32.768k", "crystal", 32768.0)])
        self.assertFalse(ambiguous_separator("1.000"))
        self.assertFalse(ambiguous_separator("4.700k"))

    def test_lone_comma_with_three_digits_is_ambiguous(self):
        for text in ("1,000", "4,700k", "10,000"):
            self.assertIsNone(parse_value(text, component_type="resistor"), msg=text)
            self.assertTrue(ambiguous_separator(text), msg=text)

    def test_comma_separated_field_list_reads_the_leading_value(self):
        self.check([("0.1uF, 50V", "capacitor", 1e-7), ("100nF, X7R, 10%", "capacitor", 1e-7)])
        self.assertIsNone(parse_value("0402,100nF,50V,X7R", component_type="capacitor"))
        self.assertFalse(ambiguous_separator("0402,100nF,50V,X7R"))

    def test_exponent_e_stays_an_exponent(self):
        self.check([("4E7", "resistor", 4e7)])

    def test_unchanged_notations(self):
        self.check([("10k 1%", "resistor", 1e4), ("4K7", "resistor", 4700.0), ("0R1", "resistor", 0.1),
                    ("u1", "capacitor", 1e-7), ("4.7uF film", "capacitor", 4.7e-6),
                    ("10k fq", "resistor", 1e4)])


def _ctx(components):
    with contextlib.redirect_stderr(io.StringIO()):
        return build_analysis_context(components, {}, {})


class AmbiguousValueDiagnostics(unittest.TestCase):
    def test_one_record_for_an_ambiguous_resistor(self):
        ctx = _ctx([{"reference": "R1", "value": "10,000", "type": "resistor"},
                    {"reference": "R2", "value": "4,7k", "type": "resistor"}])
        recs = [d for d in ctx.diagnostics if d["exception"] == "AmbiguousValueSeparator"]
        self.assertEqual(len(recs), 1)
        self.assertIn("R1", recs[0]["message"])
        self.assertNotIn("R1", ctx.parsed_values)
        self.assertAlmostEqual(ctx.parsed_values["R2"], 4700.0)

    def test_no_record_outside_r_c_l(self):
        ctx = _ctx([{"reference": "Y1", "value": "32,768", "type": "crystal"},
                    {"reference": "D1", "value": "1,000", "type": "diode"}])
        self.assertEqual([d for d in ctx.diagnostics if d["exception"] == "AmbiguousValueSeparator"], [])

    def test_capped_at_twenty_plus_a_summary(self):
        ctx = _ctx([{"reference": f"C{i}", "value": "1,000", "type": "capacitor"} for i in range(25)])
        recs = [d for d in ctx.diagnostics if d["exception"] == "AmbiguousValueSeparator"]
        self.assertEqual(len(recs), 21)
        self.assertIn("5 more", recs[-1]["message"])


if __name__ == "__main__":
    unittest.main()
