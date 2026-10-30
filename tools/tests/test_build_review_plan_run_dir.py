"""build_review_plan: the design_context task reads the current run's schematic
(analysis/manifest.json), never a run outside analysis/, and the plan file is
written in one step."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "kicad" / "review" / "scripts" / "build_review_plan.py"
sys.path.insert(0, str(SCRIPT.parent))

import build_review_plan  # noqa: E402


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def _task(analysis_dir):
    plan = build_review_plan.build_plan(analysis_dir)
    return next(t for t in plan["tasks"] if t["task_id"] == "design_context")


class RunDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ad = Path(self._tmp.name) / "proj" / "analysis"
        self.ad.mkdir(parents=True)

    def test_manifest_current_run(self):
        _write(self.ad / "2026-10-22_2246" / "schematic.json", {})
        _write(self.ad / "manifest.json",
               {"current": "2026-10-22_2246", "runs": {"2026-10-22_2246": {}}})
        task = _task(self.ad)
        self.assertEqual(task["input_artifacts"][0],
                         str(self.ad / "2026-10-22_2246" / "schematic.json"))
        # the documented place the Deep Review pass reads it from
        self.assertEqual(task["result_path"], str(self.ad / "design_context.json"))

    def test_flat_layout(self):
        self.assertEqual(_task(self.ad)["input_artifacts"][0], str(self.ad / "schematic.json"))

    def test_escaping_or_unreadable_manifest_stays_in_analysis_dir(self):
        outside = self.ad.parent / "outside"
        _write(outside / "schematic.json", {})
        for manifest in ({"current": "../outside", "runs": {"../outside": {}}},
                         {"current": "r1", "runs": ["r1"]}, [1], "{not json", b"\xff\xfe"):
            with self.subTest(manifest=manifest):
                p = self.ad / "manifest.json"
                if isinstance(manifest, bytes):
                    p.write_bytes(manifest)
                else:
                    _write(p, manifest)
                self.assertEqual(_task(self.ad)["input_artifacts"][0],
                                 str(self.ad / "schematic.json"))

    def test_output_written_whole_with_its_mode(self):
        out = self.ad / "review_plan.json"
        out.write_text("old", encoding="utf-8")
        os.chmod(out, 0o640)
        r = subprocess.run([sys.executable, str(SCRIPT), "--analysis-dir", str(self.ad),
                            "--output", str(out)], capture_output=True, text=True,
                           encoding="utf-8", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["tasks"][0]["task_id"],
                         "design_context")
        self.assertEqual(out.stat().st_mode & 0o777, 0o640)
        self.assertEqual(sorted(p.name for p in self.ad.iterdir()), ["review_plan.json"])

    def test_new_output_gets_the_umask_mode(self):
        out = self.ad / "new_plan.json"
        r = subprocess.run(["sh", "-c", 'umask 027 && exec "$0" "$@"', sys.executable,
                            str(SCRIPT), "--analysis-dir", str(self.ad), "--output", str(out)],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(out.stat().st_mode & 0o777, 0o640)    # 0o666 & ~0o027


if __name__ == "__main__":
    unittest.main()
