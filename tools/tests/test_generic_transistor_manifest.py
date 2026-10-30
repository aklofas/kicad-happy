import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))
from schematic.audits import check_generic_transistor_symbols

Q = {"reference": "Q1", "type": "transistor", "lib_id": "Device:Q_NMOS_GSD",
     "value": "BSS138", "mpn": "BSS138", "footprint": "Package_TO_SOT_SMD:SOT-23"}


def _audit(manifest, name="manifest.json"):
    with tempfile.TemporaryDirectory() as d:
        ds = Path(d) / "datasheets"
        ds.mkdir()
        (ds / name).write_text(json.dumps(manifest), encoding="utf-8")
        return check_generic_transistor_symbols([Q], str(Path(d) / "p.kicad_sch"))


class ManifestParts(unittest.TestCase):
    def test_ok_part_entry_counts_as_datasheet(self):
        w = _audit({"schematic": "p.kicad_sch", "parts": {"BSS138": {"status": "ok", "mpn": "BSS138"}}})
        self.assertTrue(w[0]["has_datasheet"])
        self.assertIn("(available in datasheets/)", w[0]["message"])

    def test_legacy_index_name_also_read(self):
        w = _audit({"parts": {"BSS138": {"status": "ok"}}}, name="index.json")
        self.assertTrue(w[0]["has_datasheet"])

    def test_not_found_entry_is_not_a_datasheet(self):
        w = _audit({"parts": {"BSS138": {"status": "not_found"}}})
        self.assertFalse(w[0]["has_datasheet"])
        self.assertNotIn("available in datasheets/", w[0]["message"])

    def test_other_part_ok_does_not_count(self):
        w = _audit({"parts": {"BSS138K": {"status": "ok"}}})
        self.assertFalse(w[0]["has_datasheet"])

    def test_top_level_and_components_shapes_still_work(self):
        self.assertTrue(_audit({"BSS138": {}})[0]["has_datasheet"])
        self.assertTrue(_audit({"components": {"BSS138": {}}})[0]["has_datasheet"])


if __name__ == "__main__":
    unittest.main()
