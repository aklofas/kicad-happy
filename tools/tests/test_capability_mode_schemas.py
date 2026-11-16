import json, os, subprocess, sys, tempfile, unittest
from unittest import mock
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

    def test_legacy_distributor_index_counts(self):
        sys.path.insert(0, str(SCRIPTS))
        import capability_mode
        with tempfile.TemporaryDirectory() as d:
            ext = self._project(d, None, ["A"])
            (ext.parent / "index.json").write_text(
                json.dumps({"parts": {p: {} for p in "ABCD"}}), encoding="utf-8")
            self.assertEqual(capability_mode._compute_coverage_pct(ext), 25)

    def test_manifest_wins_over_legacy_index(self):
        sys.path.insert(0, str(SCRIPTS))
        import capability_mode
        with tempfile.TemporaryDirectory() as d:
            ext = self._project(d, ["A", "B"], ["A"])
            (ext.parent / "index.json").write_text(
                json.dumps({"parts": {p: {} for p in "ABCD"}}), encoding="utf-8")
            self.assertEqual(capability_mode._compute_coverage_pct(ext), 50)

    def test_unreadable_manifest_is_zero(self):
        sys.path.insert(0, str(SCRIPTS))
        import capability_mode
        with tempfile.TemporaryDirectory() as d:
            ext = self._project(d, None, ["A"])
            (ext.parent / "manifest.json").write_text('{"parts": {"A": "x"}}', encoding="utf-8")
            self.assertEqual(capability_mode._compute_coverage_pct(ext), 0)


class Platform(unittest.TestCase):
    def _platform(self, **env):
        sys.path.insert(0, str(SCRIPTS))
        import capability_mode
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, env):
            if "CLAUDECODE" not in env:
                os.environ.pop("CLAUDECODE", None)
            return capability_mode.get_or_create_capability_mode(d)["platform"]

    def test_unknown_outside_claude_code(self):
        self.assertEqual(self._platform(), "unknown")

    def test_claude_code_detected(self):
        self.assertEqual(self._platform(CLAUDECODE="1"), "claude-code")

    def test_other_value_is_unknown(self):
        self.assertEqual(self._platform(CLAUDECODE="0"), "unknown")


class CacheDirFromSource(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    SCH = Path(__file__).resolve().parent / "fixtures" / "datasheet_cache" / "opamp.kicad_sch"
    PCB = '(kicad_pcb (version 20240108) (generator "pcbnew") (generator_version "8.0"))\n'

    def _run(self, cwd, script, *args):
        env = dict(os.environ, CLAUDECODE="1")
        return subprocess.run([sys.executable, str(self.ROOT / script), *map(str, args)],
                              cwd=cwd, capture_output=True, text=True, env=env)

    def _project(self, root, extractions=True):
        proj = Path(root) / "proj"
        proj.mkdir()
        (proj / "board.kicad_sch").write_text(self.SCH.read_text(encoding="utf-8"), encoding="utf-8")
        (proj / "board.kicad_pcb").write_text(self.PCB, encoding="utf-8")
        if extractions:
            ext = proj / "datasheets" / "extracted"
            ext.mkdir(parents=True)
            (ext / "LM358.json").write_text("{}", encoding="utf-8")
        return proj

    def _status(self, out_dir):
        return json.loads((Path(out_dir) / "capability_mode.json").read_text(encoding="utf-8"))["datasheet_extraction"]

    def test_schematic_sidecar_counts_the_projects_extractions(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as cwd:
            proj = self._project(d)
            r = self._run(cwd, "skills/kicad/scripts/analyze_schematic.py", proj / "board.kicad_sch",
                          "-o", Path(d) / "out" / "s.json")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self._status(Path(d) / "out"), "partial")

    def test_cwd_cache_is_not_the_projects(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as cwd:
            proj = self._project(d, extractions=False)
            (Path(cwd) / "datasheets" / "extracted").mkdir(parents=True)
            (Path(cwd) / "datasheets" / "extracted" / "X.json").write_text("{}", encoding="utf-8")
            r = self._run(cwd, "skills/kicad/scripts/analyze_schematic.py", proj / "board.kicad_sch",
                          "-o", Path(d) / "out" / "s.json")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self._status(Path(d) / "out"), "unavailable")

    def test_pcb_and_chained_analyzers_follow_the_source(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as cwd:
            proj = self._project(d)
            out = Path(d) / "out"
            out2 = Path(d) / "out2"
            out3 = Path(d) / "out3"
            self.assertEqual(self._run(cwd, "skills/kicad/scripts/analyze_schematic.py",
                                       proj / "board.kicad_sch", "-o", out / "s.json").returncode, 0)
            r = self._run(cwd, "skills/kicad/scripts/analyze_pcb.py", proj / "board.kicad_pcb",
                          "-o", out / "p.json")
            self.assertEqual(r.returncode, 0, r.stderr)
            (out / "capability_mode.json").unlink()
            r = self._run(cwd, "skills/kicad/scripts/analyze_pcb.py", proj / "board.kicad_pcb",
                          "-o", out / "p.json")
            self.assertEqual(self._status(out), "partial")
            r = self._run(cwd, "skills/kicad/scripts/analyze_thermal.py", "--schematic", out / "s.json",
                          "--pcb", out / "p.json", "-o", out2 / "t.json")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self._status(out2), "partial")
            r = self._run(cwd, "skills/emc/scripts/analyze_emc.py", "--schematic", out / "s.json",
                          "--pcb", out / "p.json", "-o", out3 / "e.json")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self._status(out3), "partial")

    def test_no_cache_dir_still_reads_the_cwd(self):
        sys.path.insert(0, str(SCRIPTS))
        import capability_mode
        with tempfile.TemporaryDirectory() as cwd:
            (Path(cwd) / "datasheets" / "extracted").mkdir(parents=True)
            (Path(cwd) / "datasheets" / "extracted" / "X.json").write_text("{}", encoding="utf-8")
            old = os.getcwd()
            os.chdir(cwd)
            try:
                rec = capability_mode.get_or_create_capability_mode(Path(cwd) / "a")
            finally:
                os.chdir(old)
        self.assertEqual(rec["datasheet_extraction"], "partial")

    @unittest.skipIf(os.name == "nt", "symlinks")
    def test_linked_datasheets_folder_is_unavailable(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
            proj = self._project(d, extractions=False)
            (Path(other) / "extracted").mkdir()
            (Path(other) / "extracted" / "X.json").write_text("{}", encoding="utf-8")
            os.symlink(other, proj / "datasheets")
            r = self._run(d, "skills/kicad/scripts/analyze_schematic.py", proj / "board.kicad_sch",
                          "-o", Path(d) / "out" / "s.json")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self._status(Path(d) / "out"), "unavailable")

    @unittest.skipIf(os.name == "nt", "symlinks")
    def test_thermal_reads_a_linked_folder_named_with_datasheets(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
            proj = self._project(d, extractions=False)
            (Path(other) / "X.json").write_text("{}", encoding="utf-8")
            link = Path(d) / "ext"
            os.symlink(other, link)
            out, out2 = Path(d) / "out", Path(d) / "out2"
            for script, src, name in (("analyze_schematic.py", "board.kicad_sch", "s.json"),
                                      ("analyze_pcb.py", "board.kicad_pcb", "p.json")):
                r = self._run(d, "skills/kicad/scripts/" + script, proj / src, "-o", out / name)
                self.assertEqual(r.returncode, 0, r.stderr)
            r = self._run(d, "skills/kicad/scripts/analyze_thermal.py", "--schematic", out / "s.json",
                          "--pcb", out / "p.json", "--datasheets", link, "-o", out2 / "t.json")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("symlink", r.stderr)
            self.assertEqual(self._status(out2), "partial")

    def _gerber_status(self, proj, gerber_dir, cwd, arg):
        (proj / "datasheets" / "extracted").mkdir(parents=True)
        (proj / "datasheets" / "extracted" / "X.json").write_text("{}", encoding="utf-8")
        gerber_dir.mkdir(exist_ok=True)
        (gerber_dir / "b-F_Cu.gtl").write_text("G04 x*\n%FSLAX46Y46*%\n%MOMM*%\nM02*\n",
                                               encoding="utf-8")
        out = proj.parent / "out"
        r = self._run(cwd, "skills/kicad/scripts/analyze_gerbers.py", arg, "-o", out / "g.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        return self._status(out)

    def test_gerbers_run_in_the_project_folder_read_its_cache(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / "proj"
            proj.mkdir()
            self.assertEqual(self._gerber_status(proj, proj, proj, "."), "partial")

    def test_gerber_subfolder_reads_the_projects_cache(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as cwd:
            proj = Path(d) / "proj"
            proj.mkdir()
            self.assertEqual(self._gerber_status(proj, proj / "gerbers", cwd, proj / "gerbers"),
                             "partial")


if __name__ == "__main__":
    unittest.main()
