"""The BOM manager reads Value, Footprint, Datasheet and Description as the analyzer does."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "bom" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import bom_manager
from kicad_core.fields import symbol_field_map
from kicad_core.sexp import parse
from schematic.reader import _symbol_fields, mandatory_property


def _block(*props):
    return "(symbol (lib_id \"Device:R\") " + " ".join(
        f'(property "{n}" "{v}" (at 0 0 0))' for n, v in props) + ")"


class ExtractPropertiesTest(unittest.TestCase):
    def test_lowercase_mandatory_fields_read(self):
        p = bom_manager.extract_properties(_block(
            ("value", "10k"), ("footprint", "R_0603"), ("datasheet", "http://d"),
            ("DESCRIPTION", "res")))
        self.assertEqual((p["Value"], p["Footprint"], p["Datasheet"], p["Description"]),
                         ("10k", "R_0603", "http://d", "res"))
        self.assertNotIn("value", p)

    def test_last_duplicate_wins_reference_first(self):
        p = bom_manager.extract_properties(_block(
            ("Reference", "R1"), ("Reference", "R9"), ("Footprint", "A"), ("footprint", "B")))
        self.assertEqual((p["Reference"], p["Footprint"]), ("R1", "B"))

    def test_exact_names_unchanged(self):
        p = bom_manager.extract_properties(_block(
            ("Reference", "R1"), ("Value", "10k"), ("Footprint", "F"), ("MPN", "X")))
        self.assertEqual(p, {"Reference": "R1", "Value": "10k", "Footprint": "F", "MPN": "X"})

    def test_lowercase_reference_is_a_custom_field(self):
        p = bom_manager.extract_properties(_block(("reference", "X"), ("Reference", "R1")))
        self.assertEqual((p["Reference"], p["reference"]), ("R1", "X"))

    def test_custom_field_last_wins(self):
        p = bom_manager.extract_properties(_block(("MPN", "A"), ("MPN", "B")))
        self.assertEqual(p["MPN"], "B")


class HelperParityTest(unittest.TestCase):
    PAIRS = [("Reference", "R1"), ("Reference", "R9"), ("value", "10k"), ("Value", "22k"),
             ("FOOTPRINT", "A"), ("footprint", "B"), ("datasheet", "http://x"),
             ("description", "d1"), ("Description", "d2")]
    EXPECTED = {"Reference": "R1", "Value": "22k", "Footprint": "B",
                "Datasheet": "http://x", "Description": "d2"}

    def test_helper_matches_analyzer(self):
        mine = symbol_field_map(self.PAIRS)
        sym = parse(_block(*self.PAIRS))
        value = mandatory_property(sym, "Value")
        footprint = mandatory_property(sym, "Footprint")
        theirs = dict(_symbol_fields(sym, value, footprint, False))
        for name, expected in self.EXPECTED.items():
            self.assertEqual(mine[name], expected, name)
            self.assertEqual(theirs[name], expected, name)

    def test_helper_does_not_trim_whitespace(self):
        self.assertEqual(symbol_field_map([("Value", "  10k ")])["Value"], "  10k ")


class AnalyzeTest(unittest.TestCase):
    def test_bom_groups_by_any_case_value(self):
        def sym(ref, value_name, uuid):
            return ('(symbol (lib_id "Device:R") (at 10 10 0) (unit 1) (in_bom yes) (on_board yes)'
                    f' (dnp no) (uuid "{uuid}")\n  (property "Reference" "{ref}" (at 0 0 0))\n'
                    f'  (property "{value_name}" "10k" (at 0 0 0))\n'
                    '  (property "Footprint" "R:R_0603" (at 0 0 0))\n)\n')
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.kicad_sch"
            p.write_text('(kicad_sch (version 20250114) (generator "eeschema") (uuid "r")\n'
                         + sym("R1", "Value", "a") + sym("R2", "value", "b") + ")\n",
                         encoding="utf-8")
            report = bom_manager.analyze(p)
        self.assertEqual([e["quantity"] for e in report["bom"]], [2])


if __name__ == "__main__":
    unittest.main()
