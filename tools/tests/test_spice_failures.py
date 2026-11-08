"""SPICE testbenches are written as UTF-8 whatever the locale, and a simulator run that fails
is a skip with exit code 0 and one diagnostics record carrying the simulator's first error lines."""
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
            r, report, wd = _simulate(tmp, 'cat "$3"\nexit 0\n', {"LC_ALL": "C", "LANG": "C",
                                                       "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("Traceback", r.stderr)
            run_dir = report["workdir"]
            cirs = [n for n in os.listdir(run_dir) if n.endswith(".cir")]
            self.assertTrue(cirs)
            with open(os.path.join(run_dir, cirs[0]), encoding="utf-8") as f:
                self.assertIn(VALUE, f.read())

    def _failed(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            r, report, _ = _simulate(tmp, body)
            cirs = sorted(n for n in os.listdir(report["workdir"]) if n.endswith(".cir"))
            self.assertNotIn(tmp, json.dumps(report["diagnostics"]))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([x["status"] for x in report["simulation_results"]], ["skip"])
        self.assertEqual(report["simulation_results"][0]["note"], "Simulation failed")
        runs = [d for d in report["diagnostics"] if d["source"] == "simulate_subcircuits.run"]
        self.assertEqual(len(cirs), 1)
        return runs, cirs[0]

    def test_failed_run_is_a_skip_with_the_simulators_error(self):
        runs, cir = self._failed('echo "fatal: boom" >&2\nexit 3\n')
        self.assertEqual(runs, [{"source": "simulate_subcircuits.run", "exception": "RuntimeError",
                                 "message": f"{cir}: fatal: boom", "effect": "simulation skipped"}])

    def test_failed_run_keeps_the_first_three_error_lines(self):
        # the first line alone ("Error on line 8 or its substitute:") does not say what failed
        runs, cir = self._failed('printf "Error on line 8:\\n\\n  r_esr_c1 a b 10m\\n'
                                 'device already exists\\nfourth\\n" >&2\nexit 1\n')
        self.assertEqual([d["message"] for d in runs],
                         [f"{cir}: Error on line 8: r_esr_c1 a b 10m device already exists"])

    def test_failed_run_without_stderr_still_records(self):
        runs, cir = self._failed("exit 2\n")
        self.assertEqual([d["message"] for d in runs], [f"{cir}: simulator exited with an error"])

    def test_successful_run_records_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, report, _ = _simulate(tmp, "exit 0\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([d for d in report["diagnostics"]
                          if d["source"] == "simulate_subcircuits.run"], [])


class ParseResultsExponentTest(unittest.TestCase):
    """Signed exponents parse in LTspice and Xyce output; a non-number is skipped."""
    def test_signed_exponents(self):
        sys.path.insert(0, str(SIM.parent))
        from spice_simulator import LtspiceBackend, XyceBackend
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "x.out")
            with open(os.path.join(tmp, "x.log"), "w") as f:
                f.write("fc: v(out)=1.58e+04 at 5\nfb: v(out)=1.5917e+04\n"
                        "fn: v(out)=-3.2E-05\nbad: v(out)=...\n")
            with open(os.path.join(tmp, "x.mt0"), "w") as f:
                f.write("fc = 1.58e+04\nfb = 1.5917e+04\nfn = -3.2E-05\nbad = ...\n")
            for r in (LtspiceBackend().parse_results(out, "", ""),
                      XyceBackend().parse_results(out, "", "")):
                self.assertEqual(r["fc"], 15800.0)
                self.assertEqual(r["fb"], 15917.0)
                self.assertEqual(r["fn"], -3.2e-05)
                self.assertNotIn("bad", r)


class ParseResultsEncodingTest(unittest.TestCase):
    """A simulator log that is not UTF-8 (LTspice writes UTF-16) never crashes the parse."""
    def test_ltspice_log_and_xyce_mt0_with_bad_bytes(self):
        sys.path.insert(0, str(SIM.parent))
        from spice_simulator import LtspiceBackend, XyceBackend
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "x.out")
            with open(os.path.join(tmp, "x.log"), "wb") as f:
                f.write(b"fc: v(out)=1234 at 5\n\xff\xfe\x81\n")
            with open(os.path.join(tmp, "x.mt0"), "wb") as f:
                f.write(b"gain = 2.5\n\xff\xfe\x81\n")
            self.assertEqual(LtspiceBackend().parse_results(out, "", "").get("fc"), 1234.0)
            self.assertEqual(XyceBackend().parse_results(out, "", "").get("gain"), 2.5)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "y.out")
            with open(os.path.join(tmp, "y.log"), "w", encoding="utf-16") as f:
                f.write("fc: v(out)=1 at 5\n")
            self.assertIsInstance(LtspiceBackend().parse_results(out, "", ""), dict)


if __name__ == "__main__":
    unittest.main()
