# tools/tests/test_bom_manager_hierarchy.py
"""bom_manager walks sub-sheets, references and sheet attributes as KiCad 10 loads them.

Expected values follow KiCad 10.0.7: sheet file property "Sheetfile" / "Sheet file" in any case
(sch_io_kicad_sexpr_parser.cpp), a symbol's reference per sheet instance (SCH_SYMBOL::GetRef,
with the missing-instance fallback of CheckForMissingSymbolInstances), KiCad 6 root
(symbol_instances) (SCH_SHEET_LIST::UpdateSymbolInstanceData), sheet in_bom / dnp OR-ed down the
instance path (SCH_SHEET_PATH::GetExcludedFromBOM / GetDNP, from the sheet's own attributes), and
"~" read as empty in files older than 20250318.
"""
import os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "bom" / "scripts"))

import bom_manager, kicad_sexp


def sym(ref, uuid="", value="10k", footprint="R:R_0603", instances="", extra="", lib_name=""):
    head = f'(lib_name "{lib_name}") ' if lib_name else ""
    return (f'\t(symbol {head}(lib_id "Device:R") (at 10 10 0) (unit 1)\n'
            f'\t\t(in_bom yes) (on_board yes) {extra}\n'
            + (f'\t\t(uuid "{uuid}")\n' if uuid else "")
            + f'\t\t(property "Reference" "{ref}" (at 0 0 0))\n'
            f'\t\t(property "Value" "{value}" (at 0 0 0))\n'
            f'\t\t(property "Footprint" "{footprint}" (at 0 0 0))\n'
            + (f'\t\t(instances {instances})\n' if instances else "")
            + '\t)\n')


def sheet(uuid, file, at=(50, 50), attrs="", prop="Sheetfile", instances=""):
    return (f'\t(sheet (at {at[0]} {at[1]}) (size 20 20) {attrs}\n'
            f'\t\t(uuid "{uuid}")\n'
            f'\t\t(property "Sheetname" "S{uuid}" (at 0 0 0))\n'
            f'\t\t(property "{prop}" "{file}" (at 0 0 0))\n'
            + (f'\t\t(instances {instances})\n' if instances else "")
            + '\t)\n')


def sch(version, body, uuid="root-uuid", extra=""):
    return (f'(kicad_sch (version {version}) (generator "eeschema")\n'
            f'\t(uuid "{uuid}")\n\t(lib_symbols)\n{body}{extra})\n')


class _Project(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text):
        p = self.dir / name
        p.write_text(text, encoding="utf-8")
        return p

    def bom(self, root, recursive=True):
        report = bom_manager.analyze(root, recursive=recursive)
        rows = {}
        for line in report["bom"]:
            for ref in line["references"]:
                rows[ref] = line
        return report, rows


class SheetFileName(_Project):
    def test_kicad6_sheet_file_property_is_followed(self):
        root = self.write("p.kicad_sch", sch(20211123, sheet("s1", "child.kicad_sch",
                                                             prop="Sheet file")))
        self.write("child.kicad_sch", sch(20211123, sym("R1"), uuid="c"))
        report, rows = self.bom(root)
        self.assertEqual(len(report["stats"]["schematic_files"]), 2)
        self.assertEqual(sorted(rows), ["R1"])

    def test_sheet_file_name_any_case(self):
        root = self.write("p.kicad_sch", sch(20231120, sheet("s1", "child.kicad_sch",
                                                             prop="SHEETFILE")))
        self.write("child.kicad_sch", sch(20231120, sym("R1"), uuid="c"))
        self.assertEqual(sorted(self.bom(root)[1]), ["R1"])

    def test_collect_schematic_files_follows_kicad6_sheets(self):
        root = self.write("p.kicad_sch", sch(20211123, sheet("s1", "child.kicad_sch",
                                                             prop="Sheet file")))
        child = self.write("child.kicad_sch", sch(20211123, sym("R1"), uuid="c"))
        self.assertEqual(kicad_sexp.collect_schematic_files(root, True),
                         [root.resolve(), child.resolve()])

    def test_repeated_sheet_file_listed_once(self):
        root = self.write("p.kicad_sch", sch(20231120,
                                             sheet("s1", "child.kicad_sch", at=(20, 20))
                                             + sheet("s2", "child.kicad_sch", at=(60, 20))))
        self.write("child.kicad_sch", sch(20231120, sym("R1"), uuid="c"))
        files = self.bom(root)[0]["stats"]["schematic_files"]
        self.assertEqual([Path(f).name for f in files], ["p.kicad_sch", "child.kicad_sch"])


class LibNameSymbols(_Project):
    def test_symbol_starting_with_lib_name_is_seen(self):
        root = self.write("p.kicad_sch", sch(20231120, sym("R1") + sym("R2", lib_name="R_1")))
        self.assertEqual(sorted(self.bom(root, recursive=False)[1]), ["R1", "R2"])


class InstanceReferences(_Project):
    def test_repeated_sheet_gives_each_instance_its_reference(self):
        inst = ('(project "p" (path "/root-uuid/s1" (reference "C4") (unit 1))'
                ' (path "/root-uuid/s2" (reference "C7") (unit 1)))')
        root = self.write("p.kicad_sch", sch(20231120,
                                             sheet("s1", "child.kicad_sch", at=(20, 20))
                                             + sheet("s2", "child.kicad_sch", at=(60, 20))))
        self.write("child.kicad_sch", sch(20231120, sym("C4", uuid="u1", instances=inst),
                                          uuid="c"))
        self.assertEqual(sorted(self.bom(root)[1]), ["C4", "C7"])

    def test_root_symbol_uses_its_root_path_instance(self):
        inst = '(project "p" (path "/root-uuid" (reference "R45") (unit 1)))'
        root = self.write("p.kicad_sch", sch(20231120, sym("R22", uuid="u1", instances=inst)))
        self.assertEqual(sorted(self.bom(root, recursive=False)[1]), ["R45"])

    def test_missing_instance_falls_back_to_the_projects_first(self):
        inst = ('(project "other" (path "/x/y" (reference "R9") (unit 1)))'
                ' (project "p" (path "/old-root" (reference "R5") (unit 1)))')
        root = self.write("p.kicad_sch", sch(20231120, sym("R1", uuid="u1", instances=inst)))
        self.assertEqual(sorted(self.bom(root, recursive=False)[1]), ["R5"])

    def test_instance_of(self):
        block = sym("R22", uuid="u1", instances=(
            '(project "p" (path "/root-uuid" (reference "R45") (unit 2)))')).strip()
        self.assertEqual(kicad_sexp.instance_of(block, "/ROOT-UUID"), ("R45", 2))
        self.assertIsNone(kicad_sexp.instance_of(sym("R1").strip(), "/root-uuid"))

    def test_kicad6_symbol_instances_set_reference_unit_value(self):
        si = ('\t(symbol_instances\n'
              '\t\t(path "/s1/u1" (reference "C9") (unit 2) (value "22pF") (footprint "C:C_0402"))\n'
              '\t)\n')
        root = self.write("p.kicad_sch", sch(20211123, sheet("s1", "child.kicad_sch"), extra=si))
        self.write("child.kicad_sch", sch(20211123, sym("C?", uuid="u1", value="", footprint=""),
                                          uuid="c"))
        rows = self.bom(root)[1]
        self.assertEqual(sorted(rows), ["C9"])
        self.assertEqual((rows["C9"]["value"], rows["C9"]["footprint"]), ("22pF", "C:C_0402"))

    def test_kicad6_repeated_sheet_takes_the_last_value_in_sheet_order(self):
        # KiCad's sheet list orders sibling sheets by x then y: s2 (x 20) before s1 (x 100),
        # so s1's value is applied last and the shared symbol shows it on both sheets.
        si = ('\t(symbol_instances\n'
              '\t\t(path "/s1/u1" (reference "R1") (unit 1) (value "10k") (footprint ""))\n'
              '\t\t(path "/s2/u1" (reference "R2") (unit 1) (value "22k") (footprint ""))\n'
              '\t)\n')
        root = self.write("p.kicad_sch", sch(20211123,
                                             sheet("s1", "child.kicad_sch", at=(100, 20))
                                             + sheet("s2", "child.kicad_sch", at=(20, 20)),
                                             extra=si))
        self.write("child.kicad_sch", sch(20211123, sym("R?", uuid="u1", value="1k"), uuid="c"))
        rows = self.bom(root)[1]
        self.assertEqual(sorted(rows), ["R1", "R2"])
        self.assertEqual((rows["R1"]["value"], rows["R2"]["value"]), ("10k", "10k"))

    def test_stale_symbol_instances_ignored_from_20221002(self):
        si = '\t(symbol_instances (path "/s1/u1" (reference "C9") (unit 1)))\n'
        inst = '(project "p" (path "/root-uuid/s1" (reference "C3") (unit 1)))'
        root = self.write("p.kicad_sch", sch(20230121, sheet("s1", "child.kicad_sch"), extra=si))
        self.write("child.kicad_sch", sch(20230121, sym("C1", uuid="u1", instances=inst),
                                          uuid="c"))
        self.assertEqual(sorted(self.bom(root)[1]), ["C3"])


class SheetAttributes(_Project):
    def _two_instances(self, attrs_a="", attrs_b=""):
        inst = ('(project "p" (path "/root-uuid/sa" (reference "R1") (unit 1))'
                ' (path "/root-uuid/sb" (reference "R2") (unit 1)))')
        root = self.write("p.kicad_sch", sch(20250114,
                                             sheet("sa", "child.kicad_sch", at=(20, 20),
                                                   attrs=attrs_a)
                                             + sheet("sb", "child.kicad_sch", at=(60, 20),
                                                     attrs=attrs_b)))
        self.write("child.kicad_sch", sch(20250114, sym("R1", uuid="u1", instances=inst),
                                          uuid="c"))
        return self.bom(root)

    def test_sheet_excluded_from_bom_drops_its_instance(self):
        self.assertEqual(sorted(self._two_instances(attrs_a="(in_bom no) (dnp yes)")[1]), ["R2"])

    def test_dnp_sheet_marks_its_symbols_dnp(self):
        root = self.write("p.kicad_sch", sch(20250114, sheet("sa", "child.kicad_sch",
                                                             attrs="(dnp yes)")))
        self.write("child.kicad_sch", sch(20250114, sym("R1", uuid="u1"), uuid="c"))
        self.assertTrue(self.bom(root)[1]["R1"]["dnp"])

    def test_exclusion_inherits_down_nested_sheets(self):
        root = self.write("p.kicad_sch", sch(20250114,
                                             sym("R9", uuid="r9")
                                             + sheet("sa", "a.kicad_sch", attrs="(in_bom no)")))
        self.write("a.kicad_sch", sch(20250114, sheet("sb", "b.kicad_sch"), uuid="a"))
        self.write("b.kicad_sch", sch(20250114, sym("C1", uuid="u1"), uuid="b"))
        self.assertEqual(sorted(self.bom(root)[1]), ["R9"])

    def test_only_the_sheets_own_dnp_counts(self):
        inst = '(project "p" (path "/root-uuid" (page "2") (variant (name "x") (dnp yes))))'
        root = self.write("p.kicad_sch", sch(20250114, sheet("sa", "child.kicad_sch",
                                                             attrs="(dnp no)", instances=inst)))
        self.write("child.kicad_sch", sch(20250114, sym("R1", uuid="u1"), uuid="c"))
        self.assertFalse(self.bom(root)[1]["R1"]["dnp"])


class TildeIsEmpty(_Project):
    def test_tilde_reads_empty_before_20250318(self):
        root = self.write("p.kicad_sch", sch(20231120, sym("R1", value="~", footprint="~")))
        line = self.bom(root, recursive=False)[1]["R1"]
        self.assertEqual((line["value"], line["footprint"]), ("", ""))

    def test_tilde_is_text_from_20250318(self):
        root = self.write("p.kicad_sch", sch(20250318, sym("R1", value="~")))
        self.assertEqual(self.bom(root, recursive=False)[1]["R1"]["value"], "~")


if __name__ == "__main__":
    unittest.main()
