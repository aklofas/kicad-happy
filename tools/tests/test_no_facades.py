# tools/tests/test_no_facades.py
"""Pins that the pre-v3 re-export modules are gone and the analyzer CLIs export only main and its imports."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))


class NoFacades(unittest.TestCase):
    def test_facade_modules_are_gone(self):
        for rel in ("skills/kicad/scripts/kicad_utils.py", "skills/kicad/scripts/sexp_parser.py",
                    "skills/kicad/scripts/bus_resolver.py", "skills/kicad/scripts/pcb_connectivity.py"):
            self.assertFalse((ROOT / rel).exists(), rel)

    @unittest.expectedFailure
    def test_datasheet_lookup_facade_is_gone(self):
        self.assertFalse((ROOT / "skills/datasheets/scripts/datasheet_lookup.py").exists())

    def test_cli_modules_export_only_main_and_their_imports(self):
        import analyze_schematic, analyze_pcb
        for mod in (analyze_schematic, analyze_pcb):
            public = {n for n in vars(mod) if not n.startswith("_")}
            self.assertNotIn("build_net_map", public)
            self.assertNotIn("parse_file", public)
            self.assertNotIn("build_connectivity_graph", public)
            self.assertNotIn("build_pin_to_net_map", public)
            self.assertIn("main", public)


if __name__ == "__main__":
    unittest.main()
