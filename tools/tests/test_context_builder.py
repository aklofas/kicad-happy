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
        import analyze_schematic as asch
        from kicad_types import AnalysisContext, build_analysis_context
        parsed = asch.parse_all_sheets(str(FX / "simple-project" / "simple.kicad_sch"))
        nets = asch.build_net_map(parsed["components"], parsed["wires"], parsed["labels"],
                                  parsed["power_symbols"], parsed["junctions"], parsed["no_connects"],
                                  sheet_names=["simple"], bus_elements=parsed["bus_elements"])
        cls.parsed, cls.nets = parsed, nets
        cls.built = build_analysis_context(parsed["components"], nets, parsed["lib_symbols"],
                                           no_connects=parsed["no_connects"],
                                           generator_version=parsed["generator_version"], source="sch")
        # the pre-v3 construction (what the harness still does): dataclass + __post_init__
        cls.direct = AnalysisContext(components=parsed["components"], nets=nets,
                                     lib_symbols=parsed["lib_symbols"],
                                     pin_net=asch.build_pin_to_net_map(nets),
                                     no_connects=parsed["no_connects"],
                                     generator_version=parsed["generator_version"])

    def test_builder_installs_every_index(self):
        b = self.built
        self.assertIsNotNone(b.nq)
        self.assertTrue(b.comp_lookup and b.parsed_values and b.ref_pins and b.pin_net)
        self.assertEqual(b.source, "sch")

    def test_builder_equals_direct_construction(self):
        b, d = self.built, self.direct
        self.assertEqual(b.comp_lookup, d.comp_lookup)
        self.assertEqual(b.parsed_values, d.parsed_values)
        self.assertEqual(b.known_power_rails, d.known_power_rails)
        self.assertEqual(b.ref_pins.keys(), d.ref_pins.keys())
        self.assertEqual({k: v[0] for k, v in b.pin_net.items()}, {k: v[0] for k, v in d.pin_net.items()})
        self.assertIs(b.no_connects, self.parsed["no_connects"])     # aliasing preserved

    def test_explicit_power_rails_override_the_scan(self):
        from kicad_types import build_analysis_context
        ctx = build_analysis_context(self.parsed["components"], self.nets, {}, known_power_rails={"X"})
        self.assertEqual(ctx.known_power_rails, {"X"})

    def test_direct_construction_still_works_without_nq(self):
        """Facade: harness-built contexts have no nq and string pin_net values."""
        from signal_detectors import _get_net_components
        d = self.direct
        self.assertIsNone(d.nq)
        any_net = next(iter(self.nets))
        self.assertIsInstance(_get_net_components(d, any_net, "none"), list)
        self.assertIsInstance(d.get_two_pin_nets(next(iter(d.comp_lookup))), tuple)


if __name__ == "__main__":
    unittest.main()
