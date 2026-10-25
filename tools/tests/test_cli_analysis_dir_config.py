# tools/tests/test_cli_analysis_dir_config.py
"""--analysis-dir must tolerate a non-dict ``analysis`` value in .kicad-happy.json (frozen exit-code contract)."""
import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from tools.tests._fixtures import fixture_path, have

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "skills" / "kicad" / "scripts" / "analyze_schematic.py"
FIXTURE = fixture_path("simple-project", "simple.kicad_sch")


@unittest.skipUnless(have(FIXTURE), "harness pin fixtures absent")
class AnalysisDirConfig(unittest.TestCase):
    def _run(self, analysis_value):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            proj = td / "proj"; proj.mkdir()
            cwd = td / "cwd"; cwd.mkdir()
            sch = proj / "simple.kicad_sch"
            shutil.copy(FIXTURE, sch)
            (proj / ".kicad-happy.json").write_text(
                json.dumps({"version": 1, "analysis": analysis_value}), encoding="utf-8")
            adir = td / "adir"
            r = subprocess.run([sys.executable, str(CLI), str(sch), "--analysis-dir", str(adir)],
                               capture_output=True, text=True, cwd=cwd)
            return r, (adir / ".gitignore").exists()

    def test_null_analysis_value(self):
        r, has_ignore = self._run(None)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        self.assertTrue(has_ignore)

    def test_string_analysis_value(self):
        r, _ = self._run("cache")
        self.assertEqual(r.returncode, 0, r.stderr[-400:])


if __name__ == "__main__":
    unittest.main()
