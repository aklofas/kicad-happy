"""BOM tools read private fields and escaped quoted text the way KiCad does."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "bom" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import bom_manager
import edit_properties
import kicad_sexp
import sync_datasheet_urls


def sheet(props):
    return ('(kicad_sch (version 20250114) (generator "eeschema")\n'
            '\t(symbol (lib_id "Device:R") (at 10 10 0)\n'
            '\t\t(property "Reference" "R1" (at 0 0 0))\n'
            + props + '\t)\n)\n')


class PrivatePropertyTest(unittest.TestCase):
    def test_extract_properties_reads_private(self):
        block = ('(symbol (lib_id "Device:R") (property "Reference" "R1") '
                 '(property private "MPN" "ABC"))')
        self.assertEqual(bom_manager.extract_properties(block)["MPN"], "ABC")

    def test_private_property_updated_in_place(self):
        t = sheet('\t\t(property private "MPN" "OLD" (at 0 0 0))\n')
        out, log = edit_properties.apply_updates(t, {"R1": {"MPN": "NEW"}})
        self.assertIn('(property private "MPN" "NEW"', out)
        self.assertEqual(out.count('"MPN"'), 1)
        self.assertEqual([e["action"] for e in log], ["updated"])

    def test_property_named_private_is_a_name(self):
        block = '(symbol (property "Reference" "R1") (property "private" "v"))'
        self.assertEqual(bom_manager.extract_properties(block)["private"], "v")

    def test_plain_update_unchanged(self):
        t = sheet('\t\t(property "MPN" "OLD" (at 0 0 0))\n')
        out, _ = edit_properties.apply_updates(t, {"R1": {"MPN": "NEW"}})
        self.assertEqual(out, t.replace('"OLD"', '"NEW"'))

    def test_sync_reads_private_mpn(self):
        t = sheet('\t\t(property private "MPN" "ABC" (at 0 0 0))\n')
        self.assertEqual(sync_datasheet_urls.extract_symbols(t)["R1"]["keys"][0], "ABC")


class EscapedTextTest(unittest.TestCase):
    def test_identical_escaped_value_unchanged(self):
        t = sheet('\t\t(property "Value" "a\\"b" (at 0 0 0))\n')
        out, log = edit_properties.apply_updates(t, {"R1": {"Value": 'a"b'}})
        self.assertEqual(out, t)
        self.assertEqual([e["action"] for e in log], ["unchanged"])

    def test_extract_properties_decodes_escapes(self):
        block = ('(symbol (property "A" "10\\"") (property "B" "a\\\\b") '
                 '(property "C" "l1\\nl2"))')
        p = bom_manager.extract_properties(block)
        self.assertEqual((p["A"], p["B"], p["C"]), ('10"', "a\\b", "l1\nl2"))

    def test_sheetfile_escape_decoded(self):
        with tempfile.TemporaryDirectory() as d:
            try:
                (Path(d) / 'my"sheet.kicad_sch').write_text("(kicad_sch)")
            except OSError:
                self.skipTest("file system cannot hold a quote in a name")
            root = ('(kicad_sch (sheet (at 0 0) (uuid "s1") '
                    '(property "Sheetfile" "my\\"sheet.kicad_sch")))')
            entries = kicad_sexp.find_sub_sheet_entries(root, Path(d))
            self.assertEqual(entries[0].path.name, 'my"sheet.kicad_sch')

    def _sheet_root(self, name):
        return ('(kicad_sch (sheet (at 0 0) (uuid "s1") '
                '(property "Sheetfile" "%s")))' % name)

    def test_sheetfile_backslash_followed(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "sub").mkdir()
            (d / "sub/power.kicad_sch").write_text("(kicad_sch)")
            entries = kicad_sexp.find_sub_sheet_entries(
                self._sheet_root("sub\\\\power.kicad_sch"), d, d / "root.kicad_sch")
            self.assertEqual([e.path for e in entries], [d / "sub/power.kicad_sch"])

    def test_sheetfile_projectname_expanded(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "board.kicad_pro").write_text("{}")
            (d / "board_power.kicad_sch").write_text("(kicad_sch)")
            entries = kicad_sexp.find_sub_sheet_entries(
                self._sheet_root("${PROJECTNAME}_power.kicad_sch"), d, d / "board.kicad_sch")
            self.assertEqual([e.path for e in entries], [d / "board_power.kicad_sch"])

    def test_plain_sheetfile_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "sub").mkdir()
            (d / "sub/power.kicad_sch").write_text("(kicad_sch)")
            root = self._sheet_root("sub/power.kicad_sch")
            for sch in (None, d / "root.kicad_sch"):
                entries = kicad_sexp.find_sub_sheet_entries(root, d, sch)
                self.assertEqual([e.path for e in entries], [d / "sub/power.kicad_sch"])

    def test_unknown_variable_left_as_written(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            entries = kicad_sexp.find_sub_sheet_entries(
                self._sheet_root("${NOPE}.kicad_sch"), d, d / "root.kicad_sch")
            self.assertEqual(entries, [])

    def test_self_including_sheet_terminates(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            root = d / "root.kicad_sch"
            root.write_text(self._sheet_root(".\\\\root.kicad_sch"))
            files = kicad_sexp.collect_schematic_files(root, True)
            self.assertEqual(files, [root.resolve()])
            result = bom_manager.analyze(root, recursive=True)
            self.assertEqual(result["bom"], [])


if __name__ == "__main__":
    unittest.main()
