"""A missing, directory, non-JSON or wrong-envelope input is a usage error (exit 2), not a
traceback; a read-only working directory does not fail a stdout run."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from tools.tests._fixtures import fixture_path, have

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
FX = fixture_path("simple-project")


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


@unittest.skipUnless(have(FX), "harness fixtures not present")
class EnvelopeTypeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.sch = os.path.join(cls._tmp.name, "sch.json")
        cls.pcb = os.path.join(cls._tmp.name, "pcb.json")
        cls.arr = os.path.join(cls._tmp.name, "list.json")
        for script, src, out in (("analyze_schematic.py", "simple.kicad_sch", cls.sch),
                                 ("analyze_pcb.py", "simple.kicad_pcb", cls.pcb)):
            r = _run(script, str(FX / src), "-o", out, cwd=cls._tmp.name)
            assert r.returncode == 0, r.stderr
        with open(cls.arr, "w", encoding="utf-8") as f:
            f.write("[]")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _usage_error(self, script, sch, pcb, needle):
        r = _run(script, "--schematic", sch, "--pcb", pcb, cwd=self._tmp.name)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("usage:", r.stderr)
        self.assertIn(needle, r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_swapped_inputs_are_usage_errors(self):
        for script in ("cross_analysis.py", "analyze_thermal.py"):
            with self.subTest(script=script):
                self._usage_error(script, self.pcb, self.sch,
                                  "--schematic %s: analyzer_type is 'pcb', not 'schematic'" % self.pcb)

    def test_pcb_flag_given_a_schematic_is_a_usage_error(self):
        for script in ("cross_analysis.py", "analyze_thermal.py"):
            with self.subTest(script=script):
                self._usage_error(script, self.sch, self.sch, "--pcb %s: analyzer_type is 'schematic'" % self.sch)

    def test_json_array_input_is_a_usage_error(self):
        for script in ("cross_analysis.py", "analyze_thermal.py"):
            with self.subTest(script=script):
                self._usage_error(script, self.arr, self.arr, "a JSON array, not an analyzer envelope")

    def test_right_order_still_runs(self):
        for script in ("cross_analysis.py", "analyze_thermal.py"):
            with self.subTest(script=script):
                r = _run(script, "--schematic", self.sch, "--pcb", self.pcb, cwd=self._tmp.name)
                self.assertEqual(r.returncode, 0, r.stderr)
                json.loads(r.stdout)


@unittest.skipUnless(have(FX) and os.name == "posix" and os.geteuid() != 0,
                     "needs the fixtures and a non-root POSIX user")
class ReadOnlyCwdTest(unittest.TestCase):
    def test_stdout_run_in_a_read_only_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            ro = os.path.join(tmp, "ro")
            os.makedirs(ro)
            os.chmod(ro, 0o555)
            try:
                for script, src in (("analyze_schematic.py", "simple.kicad_sch"),
                                    ("analyze_pcb.py", "simple.kicad_pcb")):
                    with self.subTest(script=script):
                        r = _run(script, str(FX / src), cwd=ro)
                        self.assertEqual(r.returncode, 0, r.stderr)
                        self.assertNotIn("Traceback", r.stderr)
                        self.assertIn("capability_mode.get_or_create_capability_mode", r.stderr)
                        self.assertIn("in-memory record used", r.stderr)
                        d = json.loads(r.stdout)
                        self.assertEqual(d["inputs"]["run_id"], d["capability_mode_ref"]["run_id"])
                self.assertEqual(os.listdir(ro), [])
            finally:
                os.chmod(ro, 0o755)


class NoHardLinkTest(unittest.TestCase):
    def test_link_failure_degrades_to_the_in_memory_record(self):
        import errno, io
        from contextlib import redirect_stderr
        from unittest import mock
        sys.path.insert(0, str(SCRIPTS))
        import capability_mode
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with mock.patch.object(capability_mode.os, "link",
                                   side_effect=OSError(errno.EPERM, "Operation not permitted")), \
                    redirect_stderr(err):
                rec = capability_mode.get_or_create_capability_mode(tmp)
            self.assertTrue(rec["run_id"])
            self.assertIn("in-memory record used", err.getvalue())
            self.assertEqual(os.listdir(tmp), [])


if __name__ == "__main__":
    unittest.main()
