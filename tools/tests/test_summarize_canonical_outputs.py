"""summarize_findings counts only the analyzer outputs the analysis cache writes."""
import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(os.environ.get("KH_PRODUCT") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import analysis_cache, summarize_findings  # noqa: E402


def _finding(rule):
    return {"findings": [{"rule_id": rule, "severity": "info", "summary": "s"}]}


def _summarize(adir):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        summarize_findings.main([str(adir), "--json"])
    return json.loads(out.getvalue()), err.getvalue()


class CanonicalOutputs(unittest.TestCase):
    def _adir(self, files):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        adir = Path(td.name) / "analysis"
        (adir / "r1").mkdir(parents=True)
        for name, doc in files.items():
            (adir / "r1" / name).write_text(json.dumps(doc), encoding="utf-8")
        (adir / "manifest.json").write_text(json.dumps(
            {"version": 1, "current": "r1", "runs": {"r1": {}}}), encoding="utf-8")
        return adir

    def test_extra_json_in_run_is_not_counted(self):
        adir = self._adir({"schematic.json": _finding("PU-001"),
                           "lifecycle.json": _finding("LC-ACT"),
                           "lifecycle_distributors.json": _finding("LC-004")})
        data, err = _summarize(adir)
        self.assertEqual({r["rule_id"] for r in data["rows"]}, {"PU-001", "LC-ACT"})
        self.assertIn("lifecycle_distributors.json", err)

    def test_every_canonical_output_is_counted(self):
        names = sorted(set(analysis_cache.CANONICAL_OUTPUTS.values()))
        adir = self._adir({n: _finding(f"R-{i}") for i, n in enumerate(names)})
        data, err = _summarize(adir)
        self.assertEqual(len(data["rows"]), len(names))
        self.assertNotIn("Warning", err)


if __name__ == "__main__":
    unittest.main()
