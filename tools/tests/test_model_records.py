# tools/tests/test_model_records.py
"""The TypedDicts in kicad_core/model.py must be truthful for both readers."""
import sys, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "skills" / "kicad" / "scripts"
FX = Path("/tmp/harness-pin/tests/fixtures")
sys.path.insert(0, str(SCRIPTS))


def _annotations(td):
    out = {}
    for klass in reversed(td.__mro__):
        out.update(getattr(klass, "__annotations__", {}))
    return set(out)


@unittest.skipUnless(FX.is_dir(), "frozen fixtures absent")
class RecordShapes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import analyze_schematic as asch
        from kicad_core import model
        cls.model = model
        cls.results = []
        for f in sorted(set(FX.rglob("*.kicad_sch")) | set(FX.rglob("*.sch"))):
            try:
                cls.results.append(asch.analyze_schematic(str(f), no_hierarchy=True))
            except Exception:
                continue
        assert len(cls.results) >= 10, "fixture set too small to trust"
        cls.sheet = asch.parse_single_sheet(str(FX / "simple-project" / "simple.kicad_sch"))

    def test_component_keys(self):
        allowed = _annotations(self.model.Component)
        required = self.model.Component.__required_keys__
        for r in self.results:
            for c in r["components"]:
                self.assertTrue(required <= set(c), f"{c.get('reference')} lacks {required - set(c)}")
                self.assertTrue(set(c) <= allowed, f"{c.get('reference')} has undeclared {set(c) - allowed}")

    def test_net_and_netpin_keys(self):
        net_allowed = _annotations(self.model.Net); net_required = self.model.Net.__required_keys__
        pin_required = self.model.NetPin.__required_keys__
        for r in self.results:
            for name, n in r["nets"].items():
                self.assertTrue(net_required <= set(n) <= net_allowed, name)
                for p in n["pins"]:
                    self.assertEqual(set(p), pin_required, name)

    def test_symbol_pin_keys(self):
        allowed = _annotations(self.model.Pin); required = self.model.Pin.__required_keys__
        for c in self.sheet.components:
            for p in c["pins"]:
                self.assertTrue(required <= set(p) <= allowed, c["reference"])

    def test_sheetdata_field_order_matches_old_tuple(self):
        import dataclasses
        names = [f.name for f in dataclasses.fields(self.model.SheetData)]
        self.assertEqual(names, ["root", "components", "wires", "labels", "junctions", "no_connects",
                                 "sub_sheet_paths", "lib_symbols", "text_annotations", "bus_elements", "title_block"])
        self.assertIsInstance(self.sheet, self.model.SheetData)


if __name__ == "__main__":
    unittest.main()
