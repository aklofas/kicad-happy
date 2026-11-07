"""simulate_subcircuits names a JSON input whose top level is not an object instead of crashing."""
import json, os, subprocess, sys, tempfile, unittest

from tools.tests.test_spice_failures import SIM, _analysis, _fake_ngspice


def _run(tmp, analysis, *extra):
    out = os.path.join(tmp, "report.json")
    env = dict(os.environ, NGSPICE_PATH=_fake_ngspice(tmp, "exit 0\n"))
    r = subprocess.run([sys.executable, str(SIM), analysis, "--offline", "--types",
                        "crystal_circuits", "--workdir", os.path.join(tmp, "wd"), "-o", out, *extra],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    return r, out


def _write(tmp, name, value):
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(value, f)
    return p


@unittest.skipIf(os.name == "nt", "uses a POSIX shell script as the fake simulator")
class SpiceInputRoot(unittest.TestCase):
    def test_list_root_analysis_is_a_named_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "a.json", [])
            r, out = _run(tmp, path)
            self.assertEqual(r.returncode, 1)
            self.assertIn("not an object", r.stderr)
            self.assertIn(path, r.stderr)
            self.assertNotIn("Traceback", r.stderr)
            self.assertFalse(os.path.exists(out))

    def test_list_root_parasitics_is_ignored_with_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, _ = _run(tmp, _analysis(tmp), "--parasitics", _write(tmp, "p.json", []))
            plain, _ = _run(tmp, _analysis(tmp))
            self.assertIn("Warning: could not load parasitics", r.stderr)
            self.assertNotIn("Traceback", r.stderr)
            self.assertEqual(r.returncode, plain.returncode)

    def test_object_parasitics_still_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, _ = _run(tmp, _analysis(tmp), "--parasitics", _write(tmp, "p.json", {"nets": {}}))
            self.assertIn("Loaded parasitics for 0 nets", r.stderr)


if __name__ == "__main__":
    unittest.main()
