"""Manifest run ids are folder names inside the analysis dir: an absolute, dotted or nested id
is never deleted by pruning and never written into."""
import io, json, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
FX = Path(os.environ.get("KH_FIXTURES", "/tmp/harness-pin/tests/fixtures")) / "simple-project"
sys.path.insert(0, str(SCRIPTS))

import analysis_cache  # noqa: E402


def _write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _outputs(tmp):
    d = os.path.join(tmp, "outputs")
    os.makedirs(d)
    _write(os.path.join(d, "schematic.json"), {"analyzer_type": "schematic"})
    return d


class RunIdTest(unittest.TestCase):
    def test_only_a_plain_child_name_is_a_run_id(self):
        with tempfile.TemporaryDirectory() as ad:
            self.assertTrue(analysis_cache._is_run_id(ad, "2026-10-24_1709"))
            for bad in ("", ".", "..", "../x", "a/b", "/tmp", os.path.abspath(ad), None, 7):
                self.assertFalse(analysis_cache._is_run_id(ad, bad), bad)


class PruneTest(unittest.TestCase):
    def test_prune_never_deletes_outside_the_analysis_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = os.path.join(tmp, "analysis")
            victim = os.path.join(tmp, "victim")
            os.makedirs(ad)
            os.makedirs(victim)
            Path(victim, "keep.txt").write_text("precious", encoding="utf-8")
            os.makedirs(os.path.join(ad, "old"))
            os.makedirs(os.path.join(ad, "new"))
            _write(os.path.join(ad, "manifest.json"), {"current": "new", "runs": {
                victim: {"generated": "0000", "outputs": {}},
                "../victim": {"generated": "0001", "outputs": {}},
                "old": {"generated": "0002", "outputs": {}},
                "new": {"generated": "0003", "outputs": {}}}})
            err = io.StringIO()
            with redirect_stderr(err):
                pruned = analysis_cache.prune_runs(ad, retention=1)
            self.assertEqual(pruned, ["old"])
            self.assertTrue(os.path.isfile(os.path.join(victim, "keep.txt")))
            self.assertFalse(os.path.exists(os.path.join(ad, "old")))
            self.assertTrue(os.path.isdir(os.path.join(ad, "new")))
            self.assertIn("analysis_cache.prune_runs", err.getvalue())
            self.assertIn("run id ignored", err.getvalue())


class WriteTest(unittest.TestCase):
    def test_overwrite_current_never_writes_outside(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = os.path.join(tmp, "a", "b")
            os.makedirs(ad)
            _write(os.path.join(ad, "manifest.json"), {"current": "../../etc", "runs": {"../../etc": {}}})
            err = io.StringIO()
            with redirect_stderr(err):
                analysis_cache.overwrite_current(ad, _outputs(tmp))
            self.assertFalse(os.path.exists(os.path.join(tmp, "etc")))
            current = analysis_cache.get_current_run(ad)
            self.assertIsNotNone(current)
            self.assertEqual(os.path.dirname(current[0]), ad)
            self.assertTrue(os.path.isfile(os.path.join(current[0], "schematic.json")))
            self.assertIn("analysis_cache.overwrite_current", err.getvalue())

    def test_get_current_run_ignores_an_escaping_id(self):
        with tempfile.TemporaryDirectory() as ad:
            _write(os.path.join(ad, "manifest.json"), {"current": "/etc", "runs": {"/etc": {}}})
            self.assertIsNone(analysis_cache.get_current_run(ad))
            self.assertEqual(analysis_cache.list_runs(ad), [])


@unittest.skipUnless(FX.is_dir(), "harness fixtures not present")
class CliTest(unittest.TestCase):
    def _run(self, *args, cwd):
        env = dict(os.environ, PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, str(SCRIPTS / "analyze_schematic.py"), *args],
                              capture_output=True, text=True, encoding="utf-8", cwd=cwd, env=env)

    def test_retention_with_a_hostile_manifest_keeps_the_victim(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = os.path.join(tmp, "proj")
            ad = os.path.join(proj, "analysis")
            victim = os.path.join(tmp, "victim")
            os.makedirs(ad)
            os.makedirs(victim)
            Path(victim, "keep.txt").write_text("precious", encoding="utf-8")
            Path(proj, "simple.kicad_sch").write_bytes((FX / "simple.kicad_sch").read_bytes())
            _write(os.path.join(ad, "manifest.json"),
                   {"current": None, "runs": {victim: {"generated": "0000", "outputs": {}}}})
            _write(os.path.join(proj, ".kicad-happy.json"), {"analysis": {"retention": 1}})
            r = self._run(os.path.join(proj, "simple.kicad_sch"), "--analysis-dir", ad, cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.isfile(os.path.join(victim, "keep.txt")))
            self.assertIn("run id ignored", r.stderr)

    def test_hostile_current_does_not_steer_the_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = os.path.join(tmp, "ad", "7")
            os.makedirs(ad)
            _write(os.path.join(ad, "manifest.json"), {"current": "../../etc", "runs": {"../../etc": {}}})
            r = self._run(str(FX / "simple.kicad_sch"), "--analysis-dir", ad, cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(os.path.exists(os.path.join(tmp, "etc")))
            self.assertIn("run id ignored", r.stderr)


if __name__ == "__main__":
    unittest.main()
