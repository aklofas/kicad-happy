# tools/tests/test_bom_spans.py
"""The three BOM symbol-span scanners share kicad_sexp.iter_placed_symbol_blocks and return what they
returned before the merge (the 0490c49 bodies, loaded from git)."""
import subprocess, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
BOM = ROOT / "skills" / "bom" / "scripts"
sys.path.insert(0, str(BOM))

BEFORE = "0490c49"
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


def _old(rel: str, name: str):
    """The function *name* from the BEFORE revision of *rel*, run against today's helper modules."""
    try:
        src = subprocess.run(["git", "-C", str(ROOT), "show", f"{BEFORE}:{rel}"], capture_output=True,
                             text=True, encoding="utf-8", check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise unittest.SkipTest(f"{BEFORE} not readable from git: {exc}")
    ns = {"__name__": f"_before_{Path(rel).stem}", "__file__": str(ROOT / rel)}
    exec(compile(src, rel, "exec"), ns)
    return ns[name]


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

    def test_bom_manager_extract_placed_symbols_unchanged(self):
        import bom_manager
        old = _old("skills/bom/scripts/bom_manager.py", "extract_placed_symbols")
        self.assertEqual(bom_manager.extract_placed_symbols(SCH), old(SCH))

    def test_edit_properties_find_placed_symbols_unchanged(self):
        import edit_properties
        old = _old("skills/bom/scripts/edit_properties.py", "find_placed_symbols")
        self.assertEqual(edit_properties.find_placed_symbols(SCH), old(SCH))
        self.assertEqual([r for _, _, r in edit_properties.find_placed_symbols(SCH)], ["R1", "C1", "#PWR01"])

    def test_sync_datasheet_urls_extract_ref_datasheets_unchanged(self):
        import sync_datasheet_urls
        old = _old("skills/bom/scripts/sync_datasheet_urls.py", "extract_ref_datasheets")
        self.assertEqual(sync_datasheet_urls.extract_ref_datasheets(SCH), old(SCH))
        self.assertEqual(sync_datasheet_urls.extract_ref_datasheets(SCH),
                         {"R1": "https://example.com/r.pdf", "C1": ""})


if __name__ == "__main__":
    unittest.main()
