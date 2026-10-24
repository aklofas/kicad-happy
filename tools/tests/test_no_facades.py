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

    def test_name_level_facades_are_gone(self):
        import inspect, finding_schema, kicad_types, signal_detectors, lookup_helpers, project_config, output_filters
        import schematic.pipeline as pl
        self.assertNotIn("design_context", inspect.signature(finding_schema.make_finding).parameters)
        for n in ("hierarchy_context", "design_context"):
            self.assertNotIn(n, kicad_types.AnalysisContext.__dataclass_fields__)
        self.assertFalse(hasattr(kicad_types.AnalysisContext, "__post_init__"))
        for mod, n in ((signal_detectors, "detect_led_drivers"), (lookup_helpers, "read_design_context"),
                       (pl, "parse_legacy_schematic"), (project_config, "_strip_jsonc"), (finding_schema, "normalize_severity"),
                       (finding_schema, "_SEVERITY_NORMALIZE"), (output_filters, "_severity_bucket")):
            self.assertFalse(hasattr(mod, n), f"{mod.__name__}.{n}")
        self.assertIn('"detect_led_drivers"', inspect.getsource(signal_detectors.enrich_transistor_led_drivers))

    def test_get_net_components_uses_the_query_layer_only(self):
        import inspect, signal_detectors
        self.assertNotIn("ctx.nets[net_name]", inspect.getsource(signal_detectors._get_net_components))


if __name__ == "__main__":
    unittest.main()
