import json, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))


class WritePrimaryRun(unittest.TestCase):
    def test_creates_manifest_run_and_gitignore(self):
        from output_io import write_primary_run
        from analysis_cache import load_manifest
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "x.kicad_sch"; src.write_text("(kicad_sch (version 20231120))", encoding="utf-8")
            adir = Path(d) / "analysis"
            doc = json.dumps({"analyzer_type": "schematic", "findings": []})
            write_primary_run(str(adir), doc, analyzer="schematic", source_path=str(src), script_name="analyze_schematic.py")
            m = load_manifest(str(adir))
            self.assertTrue(m.get("current"))
            self.assertTrue((adir / m["current"] / "schematic.json").is_file())
            self.assertTrue((adir / ".gitignore").is_file())
            self.assertEqual(m["runs"][m["current"]]["scripts"]["schematic"], "analyze_schematic.py x.kicad_sch")

    def test_track_in_git_skips_gitignore(self):
        from output_io import write_primary_run
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "x.kicad_sch"; src.write_text("(kicad_sch)", encoding="utf-8")
            adir = Path(d) / "analysis"
            write_primary_run(str(adir), "{}", analyzer="schematic", source_path=str(src), script_name="s.py", track_in_git=True)
            self.assertFalse((adir / ".gitignore").exists())


if __name__ == "__main__":
    unittest.main()
