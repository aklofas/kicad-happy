"""SPICE runs inside the workdir with bare filenames, so a workdir path with a
space cannot split the ngspice control-language redirect."""
import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPICE = ROOT / "skills" / "spice" / "scripts"
sys.path.insert(0, str(SPICE))


def _analysis(tmp):
    """Minimal analysis JSON with one simulatable RC filter."""
    out = os.path.join(tmp, "analysis.json")
    rc = {"detector": "detect_rc_filters", "type": "low-pass",
          "resistor": {"ref": "R1", "ohms": 1000.0},
          "capacitor": {"ref": "C1", "farads": 1e-7},
          "cutoff_hz": 1591.5, "input_net": "IN", "output_net": "OUT",
          "ground_net": "GND"}
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"findings": [rc]}, f)
    return out


class MeasurementBlockTest(unittest.TestCase):
    def test_bare_filename_in_redirect(self):
        from spice_simulator import NgspiceBackend
        block = NgspiceBackend().format_measurement_block(
            [("ac", "dec 10 1 1k")],
            [("fc", "when", "vdb(out)", "-3")], "x_Q1.out")
        lines = [l for l in block.splitlines() if "> x_Q1.out" in l]
        self.assertTrue(lines, block)
        for l in lines:
            self.assertNotIn("/", l.split(">")[1])
            self.assertNotIn("\\", l.split(">")[1])


class WorkdirTest(unittest.TestCase):
    def test_subprocess_gets_cwd_and_basename(self):
        import simulate_subcircuits as ss
        with tempfile.TemporaryDirectory() as tmp:
            analysis = json.load(open(_analysis(tmp), encoding="utf-8"))
            wd = os.path.join(tmp, "ws a")
            calls = []

            def fake(cmd, **kw):
                calls.append((cmd, kw))
                with open(os.path.join(kw["cwd"], cmd[-1]), encoding="utf-8") as f:
                    echoes = [l for l in f.read().splitlines() if l.startswith("echo ")]
                self.assertTrue(echoes)
                for l in echoes:
                    target = l.rsplit('" >', 1)[1].strip()
                    self.assertNotIn("/", target)
                    self.assertNotIn("\\", target)
                return subprocess.CompletedProcess(cmd, 0, "", "")
            with mock.patch("spice_simulator.subprocess.run", side_effect=fake):
                ss.simulate_subcircuits(analysis, workdir=wd)
            self.assertTrue(calls)
            for cmd, kw in calls:
                self.assertEqual(os.path.normpath(kw["cwd"]), os.path.normpath(wd))
                self.assertEqual(cmd[-1], os.path.basename(cmd[-1]))
                self.assertTrue(cmd[-1].endswith(".cir"))

    @unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
    def test_space_in_workdir_same_as_without(self):
        with tempfile.TemporaryDirectory() as tmp:
            analysis = _analysis(tmp)
            sums = []
            for name in ("ws a", "ws_b"):
                r = subprocess.run(
                    [sys.executable, str(SPICE / "simulate_subcircuits.py"),
                     analysis, "--workdir", os.path.join(tmp, name),
                     "--compact"], capture_output=True, text=True)
                sums.append(json.loads(r.stdout)["summary"])
            self.assertEqual(sums[0].get("skip"), sums[1].get("skip"))
            self.assertEqual(sums[0].get("pass"), sums[1].get("pass"))
            self.assertGreaterEqual(sums[0]["pass"], 1)

    @unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
    def test_relative_simulator_path_survives_workdir_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            analysis = _analysis(tmp)
            env = dict(os.environ,
                       NGSPICE_PATH=os.path.relpath(shutil.which("ngspice"), start=tmp))
            r = subprocess.run(
                [sys.executable, str(SPICE / "simulate_subcircuits.py"),
                 analysis, "--workdir", os.path.join(tmp, "w"), "--compact"],
                capture_output=True, text=True, cwd=tmp, env=env)
            self.assertGreaterEqual(json.loads(r.stdout)["summary"]["pass"], 1, r.stderr)


if __name__ == "__main__":
    unittest.main()
