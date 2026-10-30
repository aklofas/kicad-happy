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


def sym(lib, ref, unit, value, footprint="", uuid="", dnp=False, populate=None):
    extra = f'  (property "POPULATE" "{populate}" (at 0 0 0))\n' if populate is not None else ""
    return (f'(symbol (lib_id "{lib}") (at 10 10 0) (unit {unit}) (in_bom yes) (on_board yes)'
            f' (dnp {"yes" if dnp else "no"}) (uuid "{uuid}")\n'
            f'  (property "Reference" "{ref}" (at 0 0 0))\n'
            f'  (property "Value" "{value}" (at 0 0 0))\n'
            + extra +
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


class PopulateField(unittest.TestCase):
    """POPULATE is a population flag: 0/no/false = not fitted, 1/yes/true/empty = fitted."""

    def test_is_dnp_vocabulary(self):
        no = "(symbol (dnp no))"
        for val, expect in (("1", False), ("0", True), ("", False), ("yes", False),
                            ("true", False), ("no", True), ("false", True), (" 0 ", True),
                            ("DNP", True), ("dnp", True)):
            self.assertEqual(bom_manager.is_dnp(no, {"POPULATE": val}), expect, val)

    def test_dnp_attribute_and_dnp_field_still_win(self):
        self.assertTrue(bom_manager.is_dnp("(symbol (dnp yes))", {"POPULATE": "1"}))
        self.assertTrue(bom_manager.is_dnp("(symbol (dnp no))", {"DNP": "1"}))
        self.assertTrue(bom_manager.is_dnp("(symbol (dnp no))", {"POPULATE": "1", "DNP": "yes"}))

    def test_populate_one_is_never_dnp(self):
        self.assertFalse(bom_manager.is_dnp("", {"POPULATE": "1"}))

    def test_two_identical_parts_split_by_populate(self):
        body = (sym("Device:R", "R1", 1, "10k", "R:R_0603", "a", populate="1")
                + sym("Device:R", "R2", 1, "10k", "R:R_0603", "b", populate="0"))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "t.kicad_sch"
            p.write_text('(kicad_sch (version 20250114) (generator "eeschema") (uuid "r")\n'
                         + LIB + "\n" + body + ")\n", encoding="utf-8")
            bom = bom_manager.analyze(p)["bom"]
        self.assertEqual(len(bom), 2)
        fitted = next(e for e in bom if "R1" in e["references"])
        unfitted = next(e for e in bom if "R2" in e["references"])
        self.assertFalse(fitted["dnp"])
        self.assertTrue(unfitted["dnp"])

    def test_order_file_holds_only_the_fitted_part(self):
        body = (sym("Device:R", "R1", 1, "10k", "R:R_0603", "a", populate="1")
                + sym("Device:R", "R2", 1, "10k", "R:R_0603", "b", populate="0"))
        with tempfile.TemporaryDirectory() as tmp:
            sch = Path(tmp) / "t.kicad_sch"
            sch.write_text('(kicad_sch (version 20250114) (generator "eeschema") (uuid "r")\n'
                           + LIB + "\n" + body + ")\n", encoding="utf-8")
            csv_path = Path(tmp) / "bom.csv"
            bom_manager.export_csv(bom_manager.analyze(sch), csv_path)
            import csv
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                rows = {r["Reference"]: r for r in csv.DictReader(f)}
            self.assertEqual(rows["R1"]["DNP"], "")
            self.assertEqual(rows["R2"]["DNP"].lower(), "yes")
            out = Path(tmp) / "orders"
            summary = bom_manager.generate_order_files(csv_path, out, distributor_filter="lcsc")
            self.assertEqual(summary.get("skipped_dnp"), ["R2"], summary)


if __name__ == "__main__":
    unittest.main()
