# tools/tests/test_schematic_facade.py
import json, sys, unittest
from pathlib import Path
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parents[1] / "skills" / "kicad" / "scripts"))


class Facades(unittest.TestCase):
    def test_analyze_schematic_binds_every_round3_name(self):
        import analyze_schematic as asch
        names = json.loads((TESTS / "analyze_schematic_names_round3.json").read_text(encoding="utf-8"))
        missing = [n for n in names if not hasattr(asch, n)]
        self.assertEqual(missing, [])

    def test_bus_resolver_binds_every_round3_name(self):
        import bus_resolver, schematic.connectivity as conn
        for n in json.loads((TESTS / "bus_resolver_names_round3.json").read_text(encoding="utf-8")):
            self.assertIs(getattr(bus_resolver, n), getattr(conn, n), n)

    def test_pipeline_names_are_the_same_objects(self):
        import analyze_schematic as asch, schematic.pipeline as pl
        for n in ("analyze_schematic", "analyze_signal_paths", "parse_legacy_schematic", "MAX_TESTED_FORMAT_VERSION"):
            self.assertIs(getattr(asch, n), getattr(pl, n), n)

    def test_round4_additions_are_the_same_objects(self):
        import analyze_schematic as asch
        import schematic.connectivity as conn, schematic.pipeline as pl, schematic.hierarchy as hi
        import kicad_core.netquery as nq
        for mod, names in ((conn, ("BusGraph", "expand_bus_name", "match_ports")),
                           (nq, ("build_pin_to_net_map",)),
                           (pl, ("analyze_legacy_schematic", "finalize_for_cli")),
                           (hi, ("merge_top_level_sheets",))):
            for n in names:
                self.assertIs(getattr(asch, n), getattr(mod, n), n)

    def test_led_driver_rename_keeps_emitted_string(self):
        import signal_detectors as sd, inspect
        self.assertIs(sd.detect_led_drivers, sd.enrich_transistor_led_drivers)
        self.assertIn('"detect_led_drivers"', inspect.getsource(sd.enrich_transistor_led_drivers))


if __name__ == "__main__":
    unittest.main()
