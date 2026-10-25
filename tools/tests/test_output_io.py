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

    def test_extra_sources_script_entry_and_no_project(self):
        from output_io import write_primary_run
        from analysis_cache import load_manifest
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "p.kicad_pro").write_text("{}", encoding="utf-8")
            sch = Path(d) / "sch.json"; sch.write_text("{}", encoding="utf-8")
            pcb = Path(d) / "pcb.json"; pcb.write_text("[]", encoding="utf-8")
            adir = Path(d) / "analysis"
            write_primary_run(str(adir), "{}", analyzer="emc", source_path=str(sch), script_name="analyze_emc.py",
                              extra_source_paths=(str(pcb), str(Path(d) / "missing.json")),
                              script_entry="analyze_emc.py", record_project=False)
            m = load_manifest(str(adir))
            run = m["runs"][m["current"]]
            self.assertEqual(m["project"], "")
            self.assertEqual(list(run["source_hashes"]), ["sch.json", "pcb.json"])
            self.assertEqual(run["scripts"], {"emc": "analyze_emc.py"})

    def test_project_recorded_by_default(self):
        from output_io import write_primary_run
        from analysis_cache import load_manifest
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "p.kicad_pro").write_text("{}", encoding="utf-8")
            src = Path(d) / "x.kicad_sch"; src.write_text("(kicad_sch)", encoding="utf-8")
            adir = Path(d) / "analysis"
            write_primary_run(str(adir), "{}", analyzer="schematic", source_path=str(src), script_name="s.py")
            self.assertEqual(load_manifest(str(adir))["project"], "p.kicad_pro")

    def _runs(self, adir, docs, **kw):
        from output_io import write_primary_run
        src = Path(adir).parent / "x.kicad_sch"; src.write_text("(kicad_sch)", encoding="utf-8")
        for doc in docs:
            write_primary_run(str(adir), json.dumps(doc), analyzer="schematic", source_path=str(src),
                              script_name="s.py", **kw)
        return sorted(p.name for p in Path(adir).iterdir() if p.is_dir())

    def test_retention_prunes_only_when_positive(self):
        docs = [{"analyzer_type": "schematic", "components": [{"reference": f"R{i}"}]} for i in range(3)]
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(len(self._runs(Path(d) / "a", docs)), 3)
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(len(self._runs(Path(d) / "a", docs, retention=1)), 1)

    def test_diff_threshold_all_creates_a_run_on_a_minor_change_only(self):
        minor = [{"analyzer_type": "schematic", "statistics": {"total_wires": n}} for n in (1, 2)]
        same = [{"analyzer_type": "schematic"}] * 2
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(len(self._runs(Path(d) / "a", minor)), 1)
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(len(self._runs(Path(d) / "a", minor, diff_threshold="all")), 2)
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(len(self._runs(Path(d) / "a", same, diff_threshold="all")), 1)

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


class RefusedDerivedCopy(unittest.TestCase):
    """A derived output whose current-run file is a planted symlink is not copied, and
    nothing reports it as written."""

    def _plant(self, d, adir, name):
        from analysis_cache import load_manifest
        leaf = adir / load_manifest(str(adir))["current"] / name
        leaf.unlink()
        outside = Path(d) / "outside"
        outside.write_text("secret", encoding="utf-8")
        leaf.symlink_to(outside)
        return outside

    def test_write_derived_output_returns_none(self):
        import contextlib, io
        from output_io import write_derived_output
        with tempfile.TemporaryDirectory() as d:
            adir = Path(d) / "analysis"
            self.assertIsNotNone(write_derived_output(str(adir), "{}", analyzer="thermal"))
            outside = self._plant(d, adir, "thermal.json")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertIsNone(write_derived_output(str(adir), "{}", analyzer="thermal"))
            self.assertEqual(outside.read_text(encoding="utf-8"), "secret")

    def test_derived_clis_do_not_name_an_unwritten_file(self):
        import subprocess
        scripts = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "g").mkdir()
            (d / "sch.json").write_text('{"analyzer_type": "schematic", "components": []}',
                                        encoding="utf-8")
            (d / "pcb.json").write_text('{"analyzer_type": "pcb", "footprints": []}',
                                        encoding="utf-8")
            pair = ["-s", str(d / "sch.json"), "-p", str(d / "pcb.json")]
            runs = {"thermal.json": ["analyze_thermal.py", *pair],
                    "cross_analysis.json": ["cross_analysis.py", *pair],
                    "gerber.json": ["analyze_gerbers.py", str(d / "g")]}
            adir = d / "analysis"
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            for name, argv in runs.items():
                with self.subTest(name=name):
                    cmd = [sys.executable, str(scripts / argv[0]), *argv[1:],
                           "--analysis-dir", str(adir)]
                    first = subprocess.run(cmd, capture_output=True, text=True, env=env,
                                           timeout=120)
                    self.assertEqual(first.returncode, 0, first.stderr)
                    self.assertIn(name, first.stderr)
                    outside = self._plant(d, adir, name)
                    second = subprocess.run(cmd, capture_output=True, text=True, env=env,
                                            timeout=120)
                    self.assertEqual(second.returncode, 0, second.stderr)
                    self.assertIn("file not copied", second.stderr)
                    self.assertNotIn(" -> ", second.stderr)
                    self.assertNotIn("Written to", second.stderr)
                    self.assertEqual(outside.read_text(encoding="utf-8"), "secret")


if __name__ == "__main__":
    unittest.main()
