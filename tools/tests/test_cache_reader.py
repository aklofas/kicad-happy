# tools/tests/test_cache_reader.py
import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
DS = Path(__file__).resolve().parents[2] / "skills" / "datasheets"
sys.path.insert(0, str(DS))
FX = Path(os.environ.get("FX", "/tmp/harness-pin/tests/fixtures"))


class CacheReader(unittest.TestCase):
    def test_lookup_is_a_normal_package_export_without_scripts_on_path(self):
        code = ("import sys, json; from pathlib import PurePath; sys.path.insert(0, %r); import datasheet_types as dt; "
                "print(json.dumps({'lookup': dt.lookup.__module__, 'scripts_on_path': any(PurePath(p).parts[-2:] == ('datasheets', 'scripts') for p in sys.path)}))" % str(DS))
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True).stdout
        d = json.loads(out)
        self.assertEqual(d["lookup"], "datasheet_types.cache_reader")
        self.assertFalse(d["scripts_on_path"])

    def test_lookup_miss_and_malformed_json_return_none(self):
        from datasheet_types.cache_reader import lookup
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "extracted"; cache.mkdir()
            self.assertIsNone(lookup("NOPE", cache_dir=cache))
            (cache / "X1.json").write_text("{not json", encoding="utf-8")
            self.assertIsNone(lookup("X1", cache_dir=cache))

    def test_real_fixture_without_pdf_is_stale_pdf_missing(self):
        src = FX / "datasheets-extracted" / "LM2596-ADJ.json"
        if not src.is_file():
            self.skipTest(f"fixture absent: {src}")
        from datasheet_types.cache_reader import lookup, STALE_PDF_MISSING
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "extracted"; cache.mkdir()
            shutil.copy(src, cache / src.name)
            facts = lookup("LM2596-ADJ", cache_dir=cache)
            self.assertIsNotNone(facts)
            self.assertTrue(facts.stale)
            self.assertEqual(facts._cache_context.stale_reason, STALE_PDF_MISSING)
            self.assertEqual(facts._cache_context.cache_path, cache / "LM2596-ADJ.json")


if __name__ == "__main__":
    unittest.main()
