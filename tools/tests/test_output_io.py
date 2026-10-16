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


class WriteDerivedOutput(unittest.TestCase):
    def test_no_run_yet_returns_the_path_actually_written(self):
        # overwrite_current on an untracked dir creates a run folder; the returned path is that file
        from output_io import write_derived_output
        with tempfile.TemporaryDirectory() as d:
            adir = Path(d) / "analysis"
            out = write_derived_output(str(adir), '{"analyzer_type": "thermal"}', analyzer="thermal")
            self.assertEqual(Path(out).name, "thermal.json")
            self.assertEqual(Path(out).read_text(encoding="utf-8"), '{"analyzer_type": "thermal"}')

    def test_with_current_run_writes_into_it_and_tracks_the_output(self):
        from output_io import write_derived_output, write_primary_run
        from analysis_cache import load_manifest
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "x.kicad_pcb"; src.write_text("(kicad_pcb (version 20241228))", encoding="utf-8")
            adir = Path(d) / "analysis"
            write_primary_run(str(adir), "{}", analyzer="pcb", source_path=str(src), script_name="analyze_pcb.py")
            out = write_derived_output(str(adir), "{}", analyzer="cross_analysis")
            m = load_manifest(str(adir))
            self.assertEqual(Path(out), adir / m["current"] / "cross_analysis.json")
            self.assertTrue(Path(out).is_file())
            self.assertIn("cross_analysis", m["runs"][m["current"]]["outputs"])

    def test_relative_dir_is_absolutised_from_cwd(self):
        import os
        from output_io import write_derived_output
        with tempfile.TemporaryDirectory() as d:
            old = os.getcwd(); os.chdir(d)
            try:
                out = write_derived_output("rel", "{}", analyzer="gerber")
            finally:
                os.chdir(old)
            self.assertTrue(os.path.isabs(out))
            self.assertTrue(os.path.isfile(out))
            self.assertTrue(out.startswith(os.path.abspath(os.path.join(d, "rel")) + os.sep))
            self.assertEqual(os.path.basename(out), "gerber.json")


if __name__ == "__main__":
    unittest.main()
