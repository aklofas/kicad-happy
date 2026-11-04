import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "datasheets"))


class Inputs(unittest.TestCase):
    def test_extract_parts_honours_id_keys_order_and_inclusion(self):
        from distributor_core.inputs import extract_parts
        bom = {"bom": [{"mpn": "", "element14": "94AK", "references": ["U1"], "value": "", "type": "ic"}]}
        self.assertEqual(extract_parts(bom, id_keys=("digikey", "mouser", "lcsc")), [])
        parts = extract_parts(bom, id_keys=("element14", "digikey", "mouser", "lcsc"))
        self.assertEqual(list(parts[0])[-4:], ["element14", "digikey", "mouser", "lcsc"])

    def test_is_real_mpn_truth_table(self):
        from distributor_core.inputs import is_real_mpn
        for s, ok in (("LM358DR", True), ("10k", False), ("1234", False), ("ABCD", False), ("", False), ("DNP", False), ("C14663", True)):
            self.assertEqual(is_real_mpn(s), ok, s)


class Download(unittest.TestCase):
    def test_normalize_url_redirect_flag(self):
        from distributor_core.download import normalize_url
        ti = "https://www.ti.com/general/docs/suppproductinfo.tsp?gotoUrl=https%3A%2F%2Fwww.ti.com%2Flit%2Fgpn%2Flm358"
        self.assertEqual(normalize_url(ti), "https://www.ti.com/lit/gpn/lm358")
        self.assertEqual(normalize_url(ti, resolve_redirects=False), ti)
        self.assertEqual(normalize_url("//mm.digikey.com/x.pdf", resolve_redirects=False), "https://mm.digikey.com/x.pdf")


class Manifest(unittest.TestCase):
    def test_save_index_migrates_legacy_sibling(self):
        from distributor_core.manifest import load_index, save_index, MANIFEST_FILENAME
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "index.json").write_text('{"schematic": "s", "last_sync": "", "parts": {}}', encoding="utf-8")
            idx = load_index(Path(d) / MANIFEST_FILENAME)
            self.assertEqual(idx["schematic"], "s")
            save_index(Path(d) / MANIFEST_FILENAME, idx)
            self.assertTrue((Path(d) / "manifest.json").is_file())
            self.assertFalse((Path(d) / "index.json").exists())


if __name__ == "__main__":
    unittest.main()
