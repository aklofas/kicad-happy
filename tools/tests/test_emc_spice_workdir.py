"""EMC SPICE testbenches run inside their workdir with bare filenames, so a
temp directory whose path has a space cannot split an ngspice redirect."""
import os, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "skills" / "emc" / "scripts", ROOT / "skills" / "spice" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import emc_spice  # noqa: E402
from spice_simulator import NgspiceBackend  # noqa: E402

CAP = {"farads": 1e-6, "esr_ohm": 0.01, "esl_h": 1e-9}


def _calls():
    """(calls list, fake subprocess.run) — the fake checks every redirect target in the .cir."""
    calls = []

    def fake(cmd, **kw):
        cir = os.path.join(kw["cwd"], cmd[-1])
        with open(cir, encoding="utf-8") as f:
            text = f.read()
        targets = re.findall(r'" > (\S+)', text) + re.findall(r"^wrdata (\S+)", text, re.M)
        calls.append((cmd, kw, targets))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return calls, fake


class EmcSpiceWorkdirTest(unittest.TestCase):
    def test_redirect_targets_are_bare_and_cwd_is_workdir(self):
        runs = {
            "run_pdn_spice": lambda b: emc_spice.run_pdn_spice([CAP], backend=b),
            "run_filter_spice": lambda b: emc_spice.run_filter_spice(10e-6, 1e-6, 100e3, backend=b),
            "run_switching_fft": lambda b: emc_spice.run_switching_fft(5.0, 0.5, 5e-9, 1e6, backend=b),
            "run_distributed_pdn_spice": lambda b: emc_spice.run_distributed_pdn_spice(
                {"output_caps": [CAP]}, backend=b),
        }
        backend = NgspiceBackend()
        for name, run in runs.items():
            with self.subTest(name):
                calls, fake = _calls()
                with mock.patch.object(NgspiceBackend, "find", return_value="ngspice"), \
                        mock.patch("spice_simulator.subprocess.run", side_effect=fake):
                    run(backend)
                self.assertEqual(len(calls), 1)
                cmd, kw, targets = calls[0]
                self.assertEqual(cmd[-1], os.path.basename(cmd[-1]))
                self.assertTrue(cmd[-1].endswith(".cir"))
                self.assertTrue(os.path.isabs(kw["cwd"]))
                self.assertTrue(targets)
                for t in targets:
                    self.assertNotIn("/", t)
                    self.assertNotIn("\\", t)

    @unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
    def test_space_in_tmpdir_same_as_without(self):
        saved = tempfile.tempdir
        out = []
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("tmp a", "tmp_b"):
                d = os.path.join(tmp, name)
                os.makedirs(d)
                tempfile.tempdir = d
                try:
                    out.append(emc_spice.run_filter_spice(10e-6, 1e-6, 100e3, backend=NgspiceBackend()))
                finally:
                    tempfile.tempdir = saved
        self.assertTrue(out[0][0], out[0])
        self.assertTrue(out[1][0], out[1])
        self.assertEqual(out[0], out[1])


if __name__ == "__main__":
    unittest.main()
