# tools/tests/test_bom_manager_units.py
"""bom_manager packages multi-unit parts and keeps DNP parts on their own lines.

Expected values follow KiCad 10.0.7: netlist_exporter_xml.cpp addSymbolFields (a part whose
library symbol has several units takes Value / Footprint / Datasheet / Description from the
lowest-numbered unit with non-blank text; single-unit parts are untouched), and the BOM export,
which lists a DNP part with the DNP flag on its own row.
"""
import sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "bom" / "scripts"))

import bom_manager

LIB = '''(lib_symbols
  (symbol "74xx:74HC14" (symbol "74HC14_1_1") (symbol "74HC14_2_1") (symbol "74HC14_0_1"))
  (symbol "Device:R" (symbol "R_0_1") (symbol "R_1_1")))'''


def sym(lib, ref, unit, value, footprint="", uuid="", dnp=False):
    return (f'(symbol (lib_id "{lib}") (at 10 10 0) (unit {unit}) (in_bom yes) (on_board yes)'
            f' (dnp {"yes" if dnp else "no"}) (uuid "{uuid}")\n'
            f'  (property "Reference" "{ref}" (at 0 0 0))\n'
            f'  (property "Value" "{value}" (at 0 0 0))\n'
            f'  (property "Footprint" "{footprint}" (at 0 0 0)))\n')


class UnitsAndDnp(unittest.TestCase):
    def bom(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "t.kicad_sch"
            p.write_text('(kicad_sch (version 20250114) (generator "eeschema") (uuid "r")\n'
                         + LIB + "\n" + body + ")\n", encoding="utf-8")
            return bom_manager.analyze(p)["bom"]

    def line(self, bom, ref):
        return next(e for e in bom if ref in e["references"])

    def test_footprint_from_lowest_unit_that_has_one(self):
        bom = self.bom(sym("74xx:74HC14", "U1", 2, "74HC14", "", "a")
                       + sym("74xx:74HC14", "U1", 1, "74HC14", "Package_DIP:DIP-14", "b"))
        self.assertEqual(self.line(bom, "U1")["footprint"], "Package_DIP:DIP-14")
        self.assertEqual(self.line(bom, "U1")["quantity"], 1)

    def test_conflicting_units_take_the_lowest(self):
        bom = self.bom(sym("74xx:74HC14", "U1", 3, "74HC14", "Package_SO:SO-8", "a")
                       + sym("74xx:74HC14", "U1", 1, "74HC14", "Package_SO:SOP-8", "b"))
        self.assertEqual(self.line(bom, "U1")["footprint"], "Package_SO:SOP-8")

    def test_single_unit_library_symbol_is_not_merged(self):
        # Two symbols sharing a reference whose library symbol has one unit: KiCad does not merge
        bom = self.bom(sym("Device:R", "R1", 1, "10k", "", "a")
                       + sym("Device:R", "R1", 2, "10k", "R:R_0603", "b"))
        self.assertEqual(self.line(bom, "R1")["footprint"], "")

    def test_two_unit_1_symbols_sharing_a_reference_are_not_merged(self):
        # A copied single-unit symbol keeps the reference; both are (unit 1), so the gate's
        # placed-unit fallback must not merge them either, with or without the library entry
        body = (sym("Device:R", "R1", 1, "10k", "", "a")
                + sym("Device:R", "R1", 1, "10k", "R:R_0603", "b"))
        self.assertEqual(self.line(self.bom(body), "R1")["footprint"], "")
        self.assertEqual(self.line(self.bom(body.replace("Device:R", "Lib:Unknown")), "R1")["footprint"], "")

    def test_dnp_part_does_not_join_a_fitted_line(self):
        bom = self.bom(sym("Device:R", "R1", 1, "10k", "R:R_0603", "a")
                       + sym("Device:R", "R2", 1, "10k", "R:R_0603", "b", dnp=True))
        self.assertEqual(len(bom), 2)
        self.assertFalse(self.line(bom, "R1")["dnp"])
        self.assertTrue(self.line(bom, "R2")["dnp"])
        self.assertEqual(self.line(bom, "R2")["references"], ["R2"])


if __name__ == "__main__":
    unittest.main()
