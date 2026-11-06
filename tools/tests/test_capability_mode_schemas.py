import json, subprocess, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"


class SchemaVersionsFromAnyCwd(unittest.TestCase):
    def test_populated_when_cwd_is_elsewhere(self):
        code = ("import sys, json; sys.path.insert(0, %r); from capability_mode import _read_schema_versions; "
                "print(json.dumps(_read_schema_versions()))" % str(SCRIPTS))
        with tempfile.TemporaryDirectory() as cwd:
            out = subprocess.run([sys.executable, "-c", code], cwd=cwd, capture_output=True, text=True, check=True).stdout
        versions = json.loads(out)
        self.assertIn("regulator", versions)
        self.assertIn("base", versions)


class CoveragePct(unittest.TestCase):
    def _project(self, d, parts, extracted):
        ds = Path(d) / "datasheets"
        ext = ds / "extracted"
        ext.mkdir(parents=True)
        if parts is not None:
            (ds / "manifest.json").write_text(json.dumps({"parts": {p: {} for p in parts}}), encoding="utf-8")
        for m in extracted:
            (ext / f"{m}.json").write_text("{}", encoding="utf-8")
        return ext

    def test_coverage_pct_counts_extracted_bom_parts(self):
        sys.path.insert(0, str(SCRIPTS))
        import capability_mode
        with tempfile.TemporaryDirectory() as d:
            ext = self._project(d, ["U1MPN", "U2MPN", "U3MPN", "U4MPN"], ["U1MPN", "U2MPN"])
            self.assertEqual(capability_mode._compute_coverage_pct(ext), 50)
            analysis = Path(d) / "analysis"
            rec = capability_mode.get_or_create_capability_mode(str(analysis), cache_dir=ext)
            self.assertEqual(rec["datasheet_coverage_pct"], 50)

    def test_no_distributor_manifest_is_zero(self):
        sys.path.insert(0, str(SCRIPTS))
        import capability_mode
        with tempfile.TemporaryDirectory() as d:
            ext = self._project(d, None, ["U1MPN"])
            self.assertEqual(capability_mode._compute_coverage_pct(ext), 0)

    def test_legacy_index_without_distributor_manifest_is_zero(self):
        sys.path.insert(0, str(SCRIPTS))
        import capability_mode
        with tempfile.TemporaryDirectory() as d:
            ext = self._project(d, None, ["M%d" % i for i in range(25)])
            (ext / "index.json").write_text('{"extractions": {}}', encoding="utf-8")
            self.assertEqual(capability_mode._compute_coverage_pct(ext), 0)


if __name__ == "__main__":
    unittest.main()
