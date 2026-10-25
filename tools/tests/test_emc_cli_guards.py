"""EMC `--severity` keeps the findings at or above the threshold (legacy threshold names map
onto error/warning/info), and a missing, directory, non-JSON or wrong-envelope input is a usage
error (exit 2), not a traceback or a clean score."""
import collections, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from tools.tests._fixtures import fixture_path, have

ROOT = Path(__file__).resolve().parents[2]
EMC = ROOT / "skills" / "emc" / "scripts" / "analyze_emc.py"
PCB = ROOT / "skills" / "kicad" / "scripts" / "analyze_pcb.py"
SCH = ROOT / "skills" / "kicad" / "scripts" / "analyze_schematic.py"
FX = fixture_path()


def _run(script, *args):
    return subprocess.run([sys.executable, str(script), *args],
                          capture_output=True, text=True, encoding="utf-8")


@unittest.skipUnless(have(FX / "kh412" / "pad_drill_min.kicad_pcb"), "fixtures absent")
class SeverityFilterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = cls._tmp.name
        cls.pcb = os.path.join(cls.tmp, "pcb.json")
        r = _run(PCB, str(FX / "kh412" / "pad_drill_min.kicad_pcb"), "--output", cls.pcb)
        assert r.returncode == 0, r.stderr
        cls.counts = {}
        for sev in ("all", "critical", "high", "medium", "low"):
            out = os.path.join(cls.tmp, f"emc_{sev}.json")
            r = _run(EMC, "-p", cls.pcb, "--severity", sev, "-o", out)
            assert r.returncode == 0, r.stderr
            with open(out, encoding="utf-8") as f:
                d = json.load(f)
            cls.counts[sev] = (collections.Counter(x["severity"] for x in d["findings"]),
                               d["summary"]["emc_risk_score"])

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_fixture_has_every_severity(self):
        c, _ = self.counts["all"]
        self.assertTrue(c["error"] and c["warning"] and c["info"], c)

    def test_high_and_critical_keep_the_errors(self):
        allc, all_score = self.counts["all"]
        for sev in ("high", "critical"):
            c, score = self.counts[sev]
            self.assertEqual(dict(c), {"error": allc["error"]}, sev)
            self.assertLess(score, 100)

    def test_medium_keeps_errors_and_warnings(self):
        allc, _ = self.counts["all"]
        c, _ = self.counts["medium"]
        self.assertEqual(dict(c), {"error": allc["error"], "warning": allc["warning"]})

    def test_low_keeps_everything(self):
        self.assertEqual(self.counts["low"][0], self.counts["all"][0])


class InputGuardTest(unittest.TestCase):
    def _assert_usage(self, r, *needles):
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("usage:", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        for n in needles:
            self.assertIn(n, r.stderr)

    def test_missing_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _run(EMC, "-s", os.path.join(tmp, "nope.json"), "-o", os.path.join(tmp, "e.json"))
        self._assert_usage(r, "nope.json", "not found")

    def test_directory_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _run(EMC, "-p", tmp, "-o", os.path.join(tmp, "e.json"))
        self._assert_usage(r, "a directory")

    def test_non_json_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "bad.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write("not json")
            r = _run(EMC, "-s", p, "-o", os.path.join(tmp, "e.json"))
        self._assert_usage(r, "not JSON")

    def test_list_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "list.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write("[]")
            r = _run(EMC, "-s", p, "-o", os.path.join(tmp, "e.json"))
        self._assert_usage(r, "not an analyzer envelope")

    def test_swapped_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            sch = os.path.join(tmp, "sch.json")
            pcb = os.path.join(tmp, "pcb.json")
            for d, name in ((sch, "schematic"), (pcb, "pcb")):
                with open(d, "w", encoding="utf-8") as f:
                    json.dump({"analyzer_type": name, "findings": []}, f)
            r = _run(EMC, "-s", pcb, "-p", sch, "-o", os.path.join(tmp, "e.json"))
        self._assert_usage(r, "analyzer_type is 'pcb', not 'schematic'")


if __name__ == "__main__":
    unittest.main()
