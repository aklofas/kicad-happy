# tools/tests/test_context_builder.py
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
FX = Path("/tmp/harness-pin/tests/fixtures")
sys.path.insert(0, str(SCRIPTS))


@unittest.skipUnless(FX.is_dir(), "frozen fixtures absent")
class Builder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from schematic.hierarchy import parse_all_sheets
        from schematic.connectivity import build_net_map
        from kicad_types import build_analysis_context
        parsed = parse_all_sheets(str(FX / "simple-project" / "simple.kicad_sch"))
        nets = build_net_map(parsed["components"], parsed["wires"], parsed["labels"],
                             parsed["power_symbols"], parsed["junctions"], parsed["no_connects"],
                             sheet_names=["simple"], bus_elements=parsed["bus_elements"])
        cls.parsed, cls.nets = parsed, nets
        cls.built = build_analysis_context(parsed["components"], nets, parsed["lib_symbols"],
                                           no_connects=parsed["no_connects"],
                                           generator_version=parsed["generator_version"], source="sch")

    def test_builder_installs_every_index(self):
        b = self.built
        self.assertIsNotNone(b.nq)
        self.assertTrue(b.comp_lookup and b.parsed_values and b.ref_pins and b.pin_net)
        self.assertEqual(b.source, "sch")

    def test_explicit_power_rails_override_the_scan(self):
        from kicad_types import build_analysis_context
        ctx = build_analysis_context(self.parsed["components"], self.nets, {}, known_power_rails={"X"})
        self.assertEqual(ctx.known_power_rails, {"X"})


if __name__ == "__main__":
    unittest.main()
