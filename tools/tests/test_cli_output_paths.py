import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from tools.tests._fixtures import fixture_path, have
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
FX = fixture_path("simple-project")


def run(script, *args, cwd):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8")


@unittest.skipUnless(have(FX / "simple.kicad_pcb"), "frozen fixtures not present")
class AnalysisDirRoundTrips(unittest.TestCase):
    def test_pcb_caches_then_updates_current_run(self):
        with tempfile.TemporaryDirectory() as d:
            r1 = run("analyze_pcb.py", str(FX / "simple.kicad_pcb"), "--analysis-dir", "adir", cwd=d)
            r2 = run("analyze_pcb.py", str(FX / "simple.kicad_pcb"), "--analysis-dir", "adir", cwd=d)
            self.assertEqual((r1.returncode, r2.returncode), (0, 0), r1.stderr + r2.stderr)
            self.assertIn("Analysis cached: ", r1.stderr)
            self.assertIn("Analysis cache updated (current run)", r2.stderr)
            self.assertTrue((Path(d) / "adir" / ".gitignore").is_file())

    def test_derived_chain_lands_in_the_current_run(self):
        with tempfile.TemporaryDirectory() as d:
            for s, f in (("analyze_schematic.py", "simple.kicad_sch"), ("analyze_pcb.py", "simple.kicad_pcb")):
                self.assertEqual(run(s, str(FX / f), "--analysis-dir", "adir", cwd=d).returncode, 0)
            th = run("analyze_thermal.py", "--analysis-dir", "adir", cwd=d)
            cx = run("cross_analysis.py", "--analysis-dir", "adir", cwd=d)
            self.assertEqual((th.returncode, cx.returncode), (0, 0), th.stderr + cx.stderr)
            m = json.loads((Path(d) / "adir" / "manifest.json").read_text(encoding="utf-8"))
            run_dir = Path(d) / "adir" / m["current"]
            self.assertTrue((run_dir / "thermal.json").is_file())
            self.assertTrue((run_dir / "cross_analysis.json").is_file())
            self.assertIn(os.path.join(m["current"], "thermal.json"), th.stderr)
            self.assertIn(os.path.join(m["current"], "cross_analysis.json"), cx.stderr)

    def test_gerber_output_wins_over_analysis_dir(self):
        gerbers = FX / "gerbers"
        with tempfile.TemporaryDirectory() as d:
            r = run("analyze_gerbers.py", str(gerbers), "-o", "g.json", "--analysis-dir", "adir", cwd=d)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((Path(d) / "g.json").is_file())
            self.assertEqual(list((Path(d) / "adir").rglob("gerber.json")), [])
            self.assertIn("Written to g.json", r.stderr)

    def _assert_no_run(self, adir):
        self.assertFalse((adir / "manifest.json").exists())
        self.assertEqual([p for p in adir.iterdir() if p.is_dir()] if adir.is_dir() else [], [])

    def test_schematic_output_wins_over_analysis_dir(self):
        with tempfile.TemporaryDirectory() as d:
            r = run("analyze_schematic.py", str(FX / "simple.kicad_sch"), "-o", "s.json",
                    "--analysis-dir", "adir", cwd=d)
            self.assertEqual(r.returncode, 0, r.stderr)
            json.loads((Path(d) / "s.json").read_text(encoding="utf-8"))
            self._assert_no_run(Path(d) / "adir")

    def test_emc_output_wins_over_analysis_dir(self):
        with tempfile.TemporaryDirectory() as d:
            for s, f, o in (("analyze_schematic.py", "simple.kicad_sch", "sch.json"),
                            ("analyze_pcb.py", "simple.kicad_pcb", "pcb.json")):
                self.assertEqual(run(s, str(FX / f), "-o", o, cwd=d).returncode, 0)
            emc = SCRIPTS.parents[1] / "emc" / "scripts" / "analyze_emc.py"
            r = subprocess.run([sys.executable, str(emc), "--schematic", "sch.json", "--pcb", "pcb.json",
                                "--output", "emc.json", "--analysis-dir", "adir"], cwd=d,
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            json.loads((Path(d) / "emc.json").read_text(encoding="utf-8"))
            self._assert_no_run(Path(d) / "adir")

    @unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
    def test_spice_output_wins_over_analysis_dir(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run("analyze_schematic.py", str(FX / "simple.kicad_sch"),
                                 "--analysis-dir", "adir", cwd=d).returncode, 0)
            sim = SCRIPTS.parents[1] / "spice" / "scripts" / "simulate_subcircuits.py"
            env = {k: v for k, v in os.environ.items()
                   if k not in ("DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET", "MOUSER_SEARCH_API_KEY")}
            r = subprocess.run([sys.executable, str(sim), "--analysis-dir", "adir", "--output", "sp.json",
                                "--offline"], cwd=d, capture_output=True, text=True, encoding="utf-8",
                               env=env, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            json.loads((Path(d) / "sp.json").read_text(encoding="utf-8"))
            self.assertEqual(list((Path(d) / "adir").rglob("spice.json")), [])


if __name__ == "__main__":
    unittest.main()
