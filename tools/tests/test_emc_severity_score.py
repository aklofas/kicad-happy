"""`analyze_emc.py --severity` filters only the emitted findings: the risk score, per-net
scores, test plan and regulatory coverage cover every unsuppressed finding."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from tools.tests._fixtures import fixture_path, have

ROOT = Path(__file__).resolve().parents[2]
EMC = ROOT / "skills" / "emc" / "scripts" / "analyze_emc.py"
PCB = ROOT / "skills" / "kicad" / "scripts" / "analyze_pcb.py"
FX = fixture_path()


def _run(script, *args):
    return subprocess.run([sys.executable, str(script), *args],
                          capture_output=True, text=True, encoding="utf-8")


@unittest.skipUnless(have(FX / "kh412" / "pad_drill_min.kicad_pcb"), "fixtures absent")
class SeverityScoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        pcb = os.path.join(cls._tmp.name, "pcb.json")
        r = _run(PCB, str(FX / "kh412" / "pad_drill_min.kicad_pcb"), "--output", pcb)
        assert r.returncode == 0, r.stderr
        cls.out = {}
        for sev in ("all", "high"):
            out = os.path.join(cls._tmp.name, f"emc_{sev}.json")
            r = _run(EMC, "-p", pcb, "--severity", sev, "-o", out)
            assert r.returncode == 0, r.stderr
            with open(out, encoding="utf-8") as f:
                cls.out[sev] = json.load(f)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_fixture_has_a_warning(self):
        self.assertTrue(any(f["severity"] == "warning" for f in self.out["all"]["findings"]))

    def test_score_and_derived_blocks_ignore_the_filter(self):
        a, h = self.out["all"], self.out["high"]
        self.assertEqual(a["summary"]["emc_risk_score"], h["summary"]["emc_risk_score"])
        for key in ("per_net_scores", "test_plan", "regulatory_coverage"):
            self.assertEqual(a[key], h[key], key)

    def test_emitted_list_and_counts_follow_the_filter(self):
        h = self.out["high"]
        self.assertFalse([f for f in h["findings"] if f["severity"] != "error"])
        self.assertEqual(h["summary"]["by_severity"]["warning"], 0)
        self.assertEqual(h["summary"]["total_findings"], len(h["findings"]))


if __name__ == "__main__":
    unittest.main()
