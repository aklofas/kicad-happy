# tools/tests/test_writer_file_version.py
"""A property added to a schematic uses the hide syntax its KiCad version can load."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "bom" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import edit_properties, kicad_sexp


def sheet(version, header_break=False):
    sep = "\n\t" if header_break else " "
    return (f'(kicad_sch{sep}(version {version}){sep}(generator "eeschema")\n'
            '\t(symbol (lib_id "Device:R") (at 10 10 0)\n'
            '\t\t(property "Reference" "R1" (at 0 0 0))\n'
            '\t)\n)\n')


def insert(version, **kw):
    text, _ = edit_properties.apply_updates(sheet(version, **kw), {"R1": {"MPN": "X1"}})
    return text


class FileVersionTest(unittest.TestCase):
    def test_reads_version(self):
        self.assertEqual(kicad_sexp.sch_file_version(sheet(20211123)), 20211123)
        self.assertEqual(kicad_sexp.sch_file_version(sheet(20250114, True)), 20250114)
        self.assertIsNone(kicad_sexp.sch_file_version("(kicad_pcb (version 20240108))"))
        self.assertIsNone(kicad_sexp.sch_file_version("EESchema Schematic File Version 4"))


class HideSyntaxTest(unittest.TestCase):
    def test_kicad6_and_7_get_bare_hide(self):
        # KiCad 6.0.11 / 7.0.11 reject "(hide yes)" in effects.
        for v in (20211123, 20230121, 20230620):
            out = insert(v)
            self.assertIn("\thide\n", out, v)
            self.assertNotIn("(hide yes)", out, v)
            self.assertNotIn("(id ", out, v)

    def test_kicad8_and_later_get_hide_yes(self):
        for v in (20231120, 20250114, 20251028):
            out = insert(v)
            self.assertIn("(hide yes)", out, v)

    def test_unknown_version_gets_bare_hide(self):
        text, _ = edit_properties.apply_updates(
            '(kicad_sch\n\t(symbol (lib_id "Device:R")\n\t\t(property "Reference" "R1" (at 0 0 0))\n\t)\n)\n',
            {"R1": {"MPN": "X1"}})
        self.assertNotIn("(hide yes)", text)
        self.assertIn("\thide\n", text)

    def test_build_new_property_direct(self):
        self.assertIn("(hide yes)", edit_properties.build_new_property("A", "b", "\t\t", 20231120))
        self.assertNotIn("(hide yes)", edit_properties.build_new_property("A", "b", "\t\t", 20230121))


if __name__ == "__main__":
    unittest.main()
