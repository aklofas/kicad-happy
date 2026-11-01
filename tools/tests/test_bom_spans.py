# tools/tests/test_bom_spans.py
"""The three BOM symbol-span scanners share kicad_sexp.iter_placed_symbol_blocks and return the frozen
spans below."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
BOM = ROOT / "skills" / "bom" / "scripts"
sys.path.insert(0, str(BOM))

SCH = """(kicad_sch (version 20231120) (generator "eeschema")
\t(lib_symbols
\t\t(symbol "Device:R"
\t\t\t(property "Reference" "R" (at 0 0 0))
\t\t\t(symbol "R_0_1" (rectangle (start -1 -2) (end 1 2)))
\t\t)
\t)
\t(symbol
\t\t(lib_id "Device:R")
\t\t(at 10 10 0)
\t\t(property "Reference" "R1" (at 0 0 0))
\t\t(property "Value" "10k \\"precision\\" (1%)" (at 0 0 0))
\t\t(property "Datasheet" "https://example.com/r.pdf" (at 0 0 0))
\t)
\t(symbol (lib_id "Device:C") (at 20 10 0)
\t\t(property "Reference" "C1" (at 0 0 0))
\t\t(property "Value" "100n" (at 0 0 0))
\t)
\t(symbol
\t\t(lib_id "power:GND")
\t\t(property "Reference" "#PWR01" (at 0 0 0))
\t\t(property "Datasheet" "~" (at 0 0 0))
\t)
)
"""


# KiCad 7+ writes (lib_name ...) before (lib_id ...) when the placed symbol's local name differs
# from the library's.
LIB_NAME_SYMBOL = """\t(symbol
\t\t(lib_name "R_1")
\t\t(lib_id "Device:R")
\t\t(at 30 10 0)
\t\t(property "Reference" "R2" (at 0 0 0))
\t\t(property "Datasheet" "https://example.com/r2.pdf" (at 0 0 0))
\t)
"""
SCH_LIB_NAME = SCH[:SCH.rindex(")")] + LIB_NAME_SYMBOL + ")\n"


class BomSpans(unittest.TestCase):
    def test_shared_scanner_yields_placed_blocks_only(self):
        from kicad_sexp import iter_placed_symbol_blocks
        spans = iter_placed_symbol_blocks(SCH)
        self.assertEqual(len(spans), 3)
        for start, end, block in spans:
            self.assertEqual(SCH[start:end + 1], block)
            self.assertTrue(block.startswith("(symbol"))
            self.assertIn("(lib_id", block)
        self.assertNotIn('"Device:R"\n\t\t\t(property', "".join(b for _, _, b in spans))

    def test_bom_manager_extract_placed_symbols(self):
        import bom_manager
        spans = [(193, 401), (404, 526), (529, 646)]
        self.assertEqual(bom_manager.extract_placed_symbols(SCH), [(s, e, SCH[s:e + 1]) for s, e in spans])

    def test_edit_properties_find_placed_symbols(self):
        import edit_properties
        self.assertEqual(edit_properties.find_placed_symbols(SCH),
                         [(193, 401, "R1"), (404, 526, "C1"), (529, 646, "#PWR01")])

    def test_sync_datasheet_urls_extract_ref_datasheets(self):
        import sync_datasheet_urls
        self.assertEqual(sync_datasheet_urls.extract_ref_datasheets(SCH),
                         {"R1": "https://example.com/r.pdf", "C1": ""})


class LibNameSpans(unittest.TestCase):
    def test_shared_scanner_sees_lib_name_symbols(self):
        from kicad_sexp import iter_placed_symbol_blocks
        spans = iter_placed_symbol_blocks(SCH_LIB_NAME)
        self.assertEqual(len(spans), 4)
        self.assertEqual(spans[-1][2], LIB_NAME_SYMBOL.strip())

    def test_writers_see_lib_name_symbols(self):
        import edit_properties, sync_datasheet_urls
        self.assertEqual([r for _, _, r in edit_properties.find_placed_symbols(SCH_LIB_NAME)],
                         ["R1", "C1", "#PWR01", "R2"])
        self.assertEqual(sync_datasheet_urls.extract_ref_datasheets(SCH_LIB_NAME),
                         {"R1": "https://example.com/r.pdf", "C1": "",
                          "R2": "https://example.com/r2.pdf"})


if __name__ == "__main__":
    unittest.main()
