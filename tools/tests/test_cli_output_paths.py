import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
FX = Path(os.environ.get("KH_FIXTURES", "/tmp/harness-pin/tests/fixtures")) / "simple-project"


def run(script, *args, cwd):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8")


@unittest.skipUnless((FX / "simple.kicad_pcb").is_file(), "frozen fixtures not present")
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


if __name__ == "__main__":
    unittest.main()
