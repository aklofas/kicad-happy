"""diff_analysis --analysis-dir anchors on the run the manifest marks current."""
import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(os.environ.get("KH_PRODUCT") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import diff_analysis  # noqa: E402

RUNS = ["2026-11-15_1200", "2026-11-15_1300", "2026-11-15_1400"]


def _diff(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = diff_analysis.main(argv)
    return rc, out.getvalue(), err.getvalue()


class RunResolution(unittest.TestCase):
    def _adir(self, current):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        adir = Path(td.name) / "analysis"
        for n, rid in enumerate(RUNS, 1):
            (adir / rid).mkdir(parents=True)
            (adir / rid / "schematic.json").write_text(json.dumps(
                {"analyzer_type": "schematic", "statistics": {"total_components": n},
                 "findings": []}), encoding="utf-8")
        (adir / "manifest.json").write_text(json.dumps(
            {"version": 1, "current": current,
             "runs": {r: {} for r in RUNS}}), encoding="utf-8")
        return str(adir)

    def _files(self, argv):
        rc, out, err = _diff(argv)
        self.assertEqual(rc, 0, err)
        data = json.loads(out)
        return data["base_file"].replace("\\", "/"), data["head_file"].replace("\\", "/")

    def test_previous_and_current_follow_the_manifest_pointer(self):
        base, head = self._files(["--analysis-dir", self._adir(RUNS[1])])
        self.assertTrue(base.endswith("_1200/schematic.json"), base)
        self.assertTrue(head.endswith("_1300/schematic.json"), head)

    def test_single_run_flag_diffs_against_manifest_current(self):
        base, head = self._files(["--analysis-dir", self._adir(RUNS[1]), "--run", RUNS[0]])
        self.assertTrue(base.endswith("_1200/schematic.json"), base)
        self.assertTrue(head.endswith("_1300/schematic.json"), head)

    def test_newest_current_is_unchanged(self):
        base, head = self._files(["--analysis-dir", self._adir(RUNS[2])])
        self.assertTrue(base.endswith("_1300/schematic.json"), base)
        self.assertTrue(head.endswith("_1400/schematic.json"), head)

    def test_current_is_oldest_errors(self):
        rc, _, err = _diff(["--analysis-dir", self._adir(RUNS[0])])
        self.assertEqual(rc, 1)
        self.assertIn("nothing to diff", err)


if __name__ == "__main__":
    unittest.main()
