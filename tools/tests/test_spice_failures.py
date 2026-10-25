"""SPICE testbenches are written as UTF-8 whatever the locale, and a simulator run that fails
records a diagnostic naming the backend's error (the result stays a skip, the exit code 0)."""
import json, os, stat, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "skills" / "spice" / "scripts" / "simulate_subcircuits.py"
VALUE = "8MHz ±30ppm Ω"


def _analysis(tmp):
    xtal = {"detector": "detect_crystal_circuits", "reference": "Y1", "value": VALUE,
            "frequency": 8e6, "type": "passive", "effective_load_pF": 12.0,
            "load_caps": [{"ref": "C1", "farads": 22e-12, "net": "XIN"},
                          {"ref": "C2", "farads": 22e-12, "net": "XOUT"}]}
    p = os.path.join(tmp, "analysis.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"findings": [xtal]}, f)
    return p


def _fake_ngspice(tmp, body):
    p = os.path.join(tmp, "ngspice")
    with open(p, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\n" + body)
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
    return p


def _simulate(tmp, ngspice_body, extra_env=None):
    wd = os.path.join(tmp, "wd")
    out = os.path.join(tmp, "report.json")
    env = dict(os.environ, NGSPICE_PATH=_fake_ngspice(tmp, ngspice_body), **(extra_env or {}))
    r = subprocess.run([sys.executable, str(SIM), _analysis(tmp), "--offline",
                        "--types", "crystal_circuits", "--workdir", wd, "-o", out],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    report = None
    if os.path.isfile(out):
        with open(out, encoding="utf-8") as f:
            report = json.load(f)
    return r, report, wd


@unittest.skipIf(os.name == "nt", "uses a POSIX shell script as the fake simulator")
class SpiceFailureTest(unittest.TestCase):
    def test_testbench_is_utf8_under_an_ascii_locale(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Like ngspice, the fake echoes the testbench (its title carries the value) to stdout.
            r, report, wd = _simulate(tmp, 'cat "$2"\nexit 0\n', {"LC_ALL": "C", "LANG": "C",
                                                       "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("Traceback", r.stderr)
            cirs = [n for n in os.listdir(wd) if n.endswith(".cir")]
            self.assertTrue(cirs)
            with open(os.path.join(wd, cirs[0]), encoding="utf-8") as f:
                self.assertIn(VALUE, f.read())

    def test_failed_run_records_a_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, report, _ = _simulate(tmp, 'echo "fatal: boom" >&2\nexit 3\n')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([x["status"] for x in report["simulation_results"]], ["skip"])
        self.assertEqual(report["simulation_results"][0]["note"], "Simulation failed")
        runs = [d for d in report["diagnostics"] if d["source"] == "simulate_subcircuits.run"]
        self.assertEqual(len(runs), 1, report["diagnostics"])
        self.assertEqual(runs[0]["exception"], "RuntimeError")
        self.assertIn("fatal: boom", runs[0]["message"])
        self.assertEqual(runs[0]["effect"], "simulation skipped")
        self.assertIn("fatal: boom", r.stderr)

    def test_successful_run_records_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, report, _ = _simulate(tmp, "exit 0\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([d for d in report["diagnostics"]
                          if d["source"] == "simulate_subcircuits.run"], [])


if __name__ == "__main__":
    unittest.main()
