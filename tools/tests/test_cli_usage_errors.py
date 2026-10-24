"""A missing, directory or non-JSON input is a usage error (exit 2), not a traceback."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"


def _run(script, *args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                          capture_output=True, text=True, encoding="utf-8", cwd=cwd)


class LifecycleInputTest(unittest.TestCase):
    def test_lifecycle_missing_input_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _run("lifecycle_audit.py", os.path.join(tmp, "nope.json"))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("usage:", r.stderr)
        self.assertIn("nope.json", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_lifecycle_non_json_input_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "bad.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write("not json")
            r = _run("lifecycle_audit.py", p)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("not JSON", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_lifecycle_binary_input_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "bin.json")
            with open(p, "wb") as f:
                f.write(b"\xff\xfe\x00")
            r = _run("lifecycle_audit.py", p)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("not JSON", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_lifecycle_directory_input_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _run("lifecycle_audit.py", tmp)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("is a directory", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


class GerberDirTest(unittest.TestCase):
    def test_gerbers_missing_dir_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _run("analyze_gerbers.py", os.path.join(tmp, "missing") + os.sep, cwd=tmp)
            self.assertFalse(os.path.exists(os.path.join(tmp, "analysis")))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("no such file or directory", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_gerbers_empty_dir_still_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.join(tmp, "empty")
            os.makedirs(d)
            r = _run("analyze_gerbers.py", d, cwd=tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        json.loads(r.stdout)


if __name__ == "__main__":
    unittest.main()
