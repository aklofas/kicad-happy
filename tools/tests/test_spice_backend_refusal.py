"""Generated testbenches run on ngspice only: with LTspice or Xyce selected (by flag,
SPICE_SIMULATOR or auto-detection) simulate_subcircuits.py stops with exit 1 and a message
that says how to select or install ngspice, and a library call records one skip
diagnostic instead of running the benches. ngspice runs as before, and the report names
the binary of the backend that ran."""
import json, os, stat, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPICE = ROOT / "skills" / "spice" / "scripts"
SIM = SPICE / "simulate_subcircuits.py"
sys.path.insert(0, str(SPICE))

RC = {"detector": "detect_rc_filters", "type": "low-pass",
      "resistor": {"ref": "R1", "ohms": 1000.0},
      "capacitor": {"ref": "C1", "farads": 1e-7},
      "cutoff_hz": 1591.5, "input_net": "IN", "output_net": "OUT",
      "ground_net": "GND"}


def _analysis(tmp):
    p = os.path.join(tmp, "analysis.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"findings": [RC]}, f)
    return p


def _file(tmp, name, body=""):
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    return p


def _fake_ngspice(tmp):
    p = _file(tmp, "ngspice", "#!/bin/sh\nexit 0\n")
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
    return p


def _env(tmp, **extra):
    """No simulator on PATH or in the environment except the ones passed in."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("NGSPICE_PATH", "LTSPICE_PATH", "XYCE_PATH", "SPICE_SIMULATOR")}
    empty = os.path.join(tmp, "empty-path")
    os.makedirs(empty, exist_ok=True)
    env["PATH"] = empty
    env.update(extra)
    return env


def _run(tmp, env, *args):
    wd = os.path.join(tmp, "wd")
    out = os.path.join(tmp, "report.json")
    r = subprocess.run([sys.executable, str(SIM), _analysis(tmp), "--workdir", wd,
                        "-o", out, "--offline", *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env)
    return r, wd, out


@unittest.skipIf(os.name == "nt", "uses a POSIX shell script as the fake simulator")
class CliRefusalTest(unittest.TestCase):
    def _assert_refused(self, r, wd, out, display):
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("ngspice only", r.stderr)
        self.assertIn(display, r.stderr)
        self.assertFalse(os.path.exists(out))
        self.assertFalse(os.path.isdir(wd) and os.listdir(wd))

    def test_explicit_ltspice_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(tmp, LTSPICE_PATH=_file(tmp, "LTspice"))
            r, wd, out = _run(tmp, env, "--simulator", "ltspice")
            self._assert_refused(r, wd, out, "LTspice")

    def test_explicit_xyce_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(tmp, XYCE_PATH=_file(tmp, "Xyce"))
            r, wd, out = _run(tmp, env, "--simulator", "xyce")
            self._assert_refused(r, wd, out, "Xyce")

    def test_auto_with_only_ltspice_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(tmp, LTSPICE_PATH=_file(tmp, "LTspice"))
            r, wd, out = _run(tmp, env)
            self._assert_refused(r, wd, out, "LTspice")

    def test_spice_simulator_env_with_ngspice_installed_says_how_to_select_ngspice(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(tmp, LTSPICE_PATH=_file(tmp, "LTspice"),
                       NGSPICE_PATH=_fake_ngspice(tmp), SPICE_SIMULATOR="ltspice")
            r, wd, out = _run(tmp, env)
            self._assert_refused(r, wd, out, "LTspice")
            self.assertIn("SPICE_SIMULATOR", r.stderr)
            self.assertIn("--simulator ngspice", r.stderr)
            self.assertIn("install ngspice", r.stderr)

    def test_spice_simulator_env_naming_a_missing_simulator_says_how_to_select_ngspice(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(tmp, NGSPICE_PATH=_fake_ngspice(tmp), SPICE_SIMULATOR="xyce")
            r, wd, out = _run(tmp, env)
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn("SPICE_SIMULATOR", r.stderr)
            self.assertIn("--simulator ngspice", r.stderr)
            self.assertFalse(os.path.exists(out))

    def test_ngspice_still_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            ng = _fake_ngspice(tmp)
            env = _env(tmp, NGSPICE_PATH=ng, LTSPICE_PATH=_file(tmp, "LTspice"))
            r, wd, out = _run(tmp, env)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out, encoding="utf-8") as f:
                report = json.load(f)
            self.assertEqual(report["simulator"], ng)
            self.assertEqual(report["ngspice"], ng)


class LibraryRefusalTest(unittest.TestCase):
    def test_library_call_with_ltspice_is_a_recorded_skip(self):
        import simulate_subcircuits as ss
        import spice_simulator
        with tempfile.TemporaryDirectory() as wd, \
                mock.patch.object(spice_simulator.LtspiceBackend, "find",
                                  return_value="/x/LTspice"), \
                mock.patch.object(spice_simulator.subprocess, "run") as run:
            report = ss.simulate_subcircuits({"findings": [dict(RC)]}, workdir=wd,
                                             simulator_backend=spice_simulator.LtspiceBackend())
            self.assertEqual(os.listdir(wd), [])
        run.assert_not_called()
        self.assertEqual(report["summary"]["total"], 0)
        self.assertEqual(report["diagnostics"], [{
            "source": "simulate_subcircuits.simulate_subcircuits",
            "exception": "RuntimeError",
            "message": ss._NGSPICE_ONLY,
            "effect": "simulation skipped"}])

    def test_report_names_the_backend_that_ran(self):
        import simulate_subcircuits as ss
        import spice_simulator

        class _Ng(spice_simulator.NgspiceBackend):
            def find(self):
                return "/opt/ng/bin/ngspice"

        done = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as wd, \
                mock.patch.object(spice_simulator.subprocess, "run", return_value=done):
            report = ss.simulate_subcircuits({"findings": [dict(RC)]}, workdir=wd,
                                             types=["rc_filters"], simulator_backend=_Ng())
        self.assertEqual(report["simulator"], "/opt/ng/bin/ngspice")
        self.assertEqual(report["ngspice"], "/opt/ng/bin/ngspice")

    def test_backend_that_is_not_a_simulator_backend_keeps_the_ngspice_lookup(self):
        import simulate_subcircuits as ss

        def gen(det, out_file, context=None, parasitics=None):
            raise ValueError("stop")

        for backend in (None, object(), "stub"):
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as wd, \
                    mock.patch.dict(ss.TEMPLATE_REGISTRY, {"rc_filters": gen}):
                report = ss.simulate_subcircuits({"findings": [dict(RC)]}, workdir=wd,
                                                 types=["rc_filters"], simulator_backend=backend)
                self.assertEqual(report["simulator"], ss.find_ngspice() or None)
                self.assertEqual(report["diagnostics"], [])


if __name__ == "__main__":
    unittest.main()
