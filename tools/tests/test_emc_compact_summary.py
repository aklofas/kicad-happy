"""EMC `--compact`: the summary, category rollup and stderr count describe the findings emitted."""
import collections
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.tests._fixtures import fixture_path, have

ROOT = Path(__file__).resolve().parents[2]
EMC = ROOT / "skills" / "emc" / "scripts" / "analyze_emc.py"
PCB = ROOT / "skills" / "kicad" / "scripts" / "analyze_pcb.py"
SCH = ROOT / "skills" / "kicad" / "scripts" / "analyze_schematic.py"
FX = fixture_path("simple-project")


def _run(script, *args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(script), *args], capture_output=True,
                          text=True, encoding="utf-8", env=env)


@unittest.skipUnless(have(FX / "simple.kicad_sch"), "fixtures absent")
class CompactSummaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        t = Path(cls._tmp.name)
        r = _run(SCH, str(FX / "simple.kicad_sch"), "--output", str(t / "sch.json"))
        assert r.returncode == 0, r.stderr
        r = _run(PCB, str(FX / "simple.kicad_pcb"), "--output", str(t / "pcb.json"))
        assert r.returncode == 0, r.stderr
        cls.runs = {}
        for name, extra in (("full", []), ("compact", ["--compact"])):
            out = t / f"emc_{name}.json"
            r = _run(EMC, "--schematic", str(t / "sch.json"), "--pcb", str(t / "pcb.json"),
                     "--output", str(out), *extra)
            assert r.returncode == 0, r.stderr
            cls.runs[name] = (json.loads(out.read_text(encoding="utf-8")), r.stderr)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_fixture_has_info_findings(self):
        sev = collections.Counter(f["severity"] for f in self.runs["full"][0]["findings"])
        self.assertTrue(sev["info"] and (sev["warning"] or sev["error"]), sev)

    def test_compact_findings_are_the_non_info_findings(self):
        full = [f["finding_id"] for f in self.runs["full"][0]["findings"] if f["severity"] != "info"]
        self.assertEqual([f["finding_id"] for f in self.runs["compact"][0]["findings"]], full)

    def test_compact_summary_counts_emitted_findings(self):
        d = self.runs["compact"][0]
        fs = d["findings"]
        summary = d["summary"]
        suppressed = sum(1 for f in fs if f.get("suppressed"))
        self.assertEqual(summary["total_findings"], len(fs))
        self.assertEqual(summary["suppressed"], suppressed)
        self.assertEqual(summary["active"], len(fs) - suppressed)
        cats = collections.Counter(f.get("category", "other") for f in fs)
        self.assertEqual(summary["categories_checked"], len(cats))
        self.assertEqual({c: v["count"] for c, v in d["category_summary"].items()}, dict(cats))

    def test_stderr_count_matches_emitted_findings(self):
        for name in ("full", "compact"):
            d, err = self.runs[name]
            m = re.search(r"EMC analysis complete: (\d+) findings", err)
            self.assertIsNotNone(m, err)
            self.assertEqual(int(m.group(1)), len(d["findings"]), name)


if __name__ == "__main__":
    unittest.main()
