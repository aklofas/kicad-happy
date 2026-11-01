"""The four property readers decode `(property [private] name value ...)` alike but keep their own
matching policy: exact vs normalised name, first match vs last wins, empty vs blank, key case."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from kicad_core import fields, sexp  # noqa: E402


class PropertyReaderTest(unittest.TestCase):
    def setUp(self):
        tree = sexp.parse("""(symbol
          (property "Reference" "U1")
          (property "Value" "first")
          (property "Value" "second")
          (property private "Secret" "hidden")
          (property "Empty" "")
          (property "Blank" "   ")
          (property "MPN" "")
          (property "mpn" "   ")
          (property "Manufacturer  P/N" "ABC-1")
          (property "Part Number" "GEN-2")
          (property "Part Number" "GEN-3"))""")
        self.node = tree

    def test_get_property_is_exact_and_first_wins(self):
        self.assertEqual(sexp.get_property(self.node, "Value"), "first")
        self.assertEqual(sexp.get_property(self.node, "value"), None)
        self.assertEqual(sexp.get_property(self.node, "Secret"), "hidden")
        self.assertEqual(sexp.get_property(self.node, "Empty"), "")
        self.assertEqual(sexp.get_property(self.node, "Blank"), "   ")
        self.assertEqual(sexp.get_property(self.node, "Missing"), None)

    def test_get_properties_lowercases_keys_and_last_wins(self):
        props = sexp.get_properties(self.node)
        self.assertEqual(props["value"], "second")
        self.assertEqual(props["secret"], "hidden")
        self.assertEqual(props["empty"], "")
        self.assertEqual(props["blank"], "   ")
        self.assertEqual(props["manufacturer  p/n"], "ABC-1")
        self.assertEqual(props["mpn"], "   ")  # "MPN" and "mpn" collide; the later one wins
        self.assertNotIn("Value", props)

    def test_get_property_ci_is_normalised_first_non_empty(self):
        ci = fields.get_property_ci
        self.assertEqual(ci(self.node, frozenset({"value"})), "first")
        self.assertEqual(ci(self.node, frozenset({"secret"})), "hidden")
        self.assertEqual(ci(self.node, frozenset({"empty"})), None)
        self.assertEqual(ci(self.node, frozenset({"blank"})), "   ")
        self.assertEqual(ci(self.node, frozenset({"manufacturer p/n"})), "ABC-1")
        self.assertEqual(ci(self.node, frozenset({"part number"})), "GEN-2")

    def test_get_mpn_property_skips_blank_values_then_falls_back(self):
        self.assertEqual(fields.get_mpn_property(self.node), "ABC-1")
        only_blank = sexp.parse('(symbol (property "MPN" "") (property "mpn" "  "))')
        self.assertEqual(fields.get_mpn_property(only_blank), "  ")
        none = sexp.parse('(symbol (property "MPN" ""))')
        self.assertEqual(fields.get_mpn_property(none), None)


if __name__ == "__main__":
    unittest.main()
