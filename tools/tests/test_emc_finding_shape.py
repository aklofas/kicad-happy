"""EMC findings take make_finding's key set and order (no `title`); finding_id and --text unchanged."""
import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from tools.tests._fixtures import fixture_path, have

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
EMC = ROOT / "skills" / "emc" / "scripts"
FX = fixture_path("simple-project")
# Frozen pre-change export (git archive 0490c49): EMC findings there still carry `title`.
OLD = Path(os.environ.get("KH_OLD_TREE", "/tmp/kh-r8"))
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(EMC))

from emc_rules import _make_finding  # noqa: E402
from finding_schema import make_finding  # noqa: E402


def run(tree, rel, *args, cwd):
    return subprocess.run([sys.executable, str(Path(tree) / rel), *args], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8")


class FactoryShape(unittest.TestCase):
    def test_emc_finding_key_order_matches_make_finding(self):
        f = _make_finding("ground_plane", "HIGH", "GP-001", "t", "d", recommendation="r", components=["U1"])
        kicad = make_finding(detector="x", rule_id="GP-001", category="ground_plane", summary="t",
                             description="d", severity="error", components=["U1"], recommendation="r")
        self.assertEqual([k for k in f], [k for k in kicad if k != "finding_id"])
        self.assertNotIn("title", f)
        self.assertEqual(f["summary"], "t")
        self.assertEqual(f["detector"], "emc_ground_plane")
        self.assertEqual(f["severity"], "error")

    def test_fix_params_and_extra_land_where_make_finding_puts_them(self):
        f = _make_finding("pdn", "MEDIUM", "PD-001", "t", "d", fix_params={"a": 1}, net_count=3)
        kicad = make_finding(detector="x", rule_id="PD-001", category="pdn", summary="t", description="d",
                             severity="warning", fix_params={"a": 1}, net_count=3)
        self.assertEqual([k for k in f], [k for k in kicad if k != "finding_id"])
        self.assertEqual(list(f)[-3:], ["fix_params", "report_context", "net_count"])


@unittest.skipUnless(have(FX / "simple.kicad_sch") and (OLD / "skills/emc/scripts/analyze_emc.py").is_file(),
                     "frozen fixtures or the pre-change export not present")
class VersusBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        d = Path(cls._tmp.name)
        proj = d / "proj"
        shutil.copytree(FX, proj)
        cls.sch, cls.pcb = proj / "sch.json", proj / "pcb.json"
        for script, src, out in (("analyze_schematic.py", "simple.kicad_sch", cls.sch),
                                 ("analyze_pcb.py", "simple.kicad_pcb", cls.pcb)):
            r = run(ROOT, f"skills/kicad/scripts/{script}", str(proj / src), "--output", str(out), cwd=d)
            assert r.returncode == 0, r.stderr
        cls.docs, cls.texts = {}, {}
        for label, tree in (("old", OLD), ("new", ROOT)):
            out = d / f"emc-{label}.json"
            r = run(tree, "skills/emc/scripts/analyze_emc.py", "--schematic", str(cls.sch), "--pcb", str(cls.pcb),
                    "--output", str(out), cwd=d)
            assert r.returncode == 0, r.stderr
            cls.docs[label] = json.loads(out.read_text(encoding="utf-8"))
            r = run(tree, "skills/emc/scripts/analyze_emc.py", "--schematic", str(cls.sch), "--pcb", str(cls.pcb),
                    "--text", cwd=d)
            assert r.returncode == 0, r.stderr
            cls.texts[label] = r.stdout

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_emc_finding_ids_unchanged_vs_base(self):
        old, new = self.docs["old"]["findings"], self.docs["new"]["findings"]
        self.assertTrue(old)
        self.assertEqual([f["finding_id"] for f in new], [f["finding_id"] for f in old])
        for o, n in zip(old, new):
            self.assertEqual(o["title"], o["summary"])
            self.assertNotIn("title", n)
            self.assertEqual({k: v for k, v in o.items() if k != "title"}, {k: v for k, v in n.items() if k != "schema_era"})

    def test_text_report_identical_vs_base(self):
        self.assertTrue(self.texts["old"])
        self.assertEqual(self.texts["new"], self.texts["old"])


if __name__ == "__main__":
    unittest.main()
