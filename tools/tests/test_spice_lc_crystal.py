"""The LC bench's Q factor is its own assumed inductor ESR, so it never sets the
status; the crystal bench measures series resonance on the crystal alone and
load resonance with the load caps in the loop, and reports them as `info`
(warn only for a calculated CL outside 4-30 pF or an unmeasured series
resonance). Expected values are hand-derived: f0 = 1/(2*pi*sqrt(LC)) and the
crystal pulling formula f_L = f_s * (1 + Cm / (2 * (C0 + CL)))."""
import math, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPICE = ROOT / "skills" / "spice" / "scripts"
sys.path.insert(0, str(SPICE))

import spice_results as R  # noqa: E402
import spice_templates as T  # noqa: E402


def _run(gen, ev, det):
    """Render the bench, run ngspice in a temp dir, evaluate."""
    from spice_simulator import NgspiceBackend
    with tempfile.TemporaryDirectory() as tmp:
        tb = gen(det, "b.out")
        with open(os.path.join(tmp, "b.cir"), "w", encoding="utf-8") as f:
            f.write(tb.render(NgspiceBackend(), "b.out"))
        run = subprocess.run(["ngspice", "-b", "b.cir"], cwd=tmp, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60)
        if run.returncode != 0:
            raise AssertionError(f"ngspice exited {run.returncode}:\n{run.stdout[-2000:]}{run.stderr[-2000:]}")
        sim = R.parse_output_file(os.path.join(tmp, "b.out"))
        for k, v in tb.extra_vars.items():
            sim.setdefault(k, v)
    return ev(det, sim)


def _crystal(freq, caps):
    """Crystal detection with load caps ``[(ref, farads, net), ...]``; CL as the
    analyzer calculates it (per-leg sums in series + 3 pF stray)."""
    legs = {}
    for _ref, farads, net in caps:
        legs[net] = legs.get(net, 0.0) + farads
    c1, c2 = list(legs.values())[:2]
    return {"reference": "Y1", "value": "XTAL", "frequency": freq,
            "load_caps": [{"ref": r, "value": "", "farads": f, "net": n} for r, f, n in caps],
            "effective_load_pF": round(((c1 * c2) / (c1 + c2) + 3e-12) * 1e12, 2)}


# The generic BVD models the bench builds: MHz Cm 20 fF / C0 5 pF / Rm 30 ohm,
# watch crystal Cm 2 fF / C0 1.5 pF / Rm 40 kohm
def _pulling_ppm(freq, cl):
    cm, c0 = (2e-15, 1.5e-12) if freq < 1e6 else (20e-15, 5e-12)
    return cm / (2 * (c0 + cl)) * 1e6


@unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
class LcTest(unittest.TestCase):
    def test_assumed_q_does_not_warn(self):
        # 10 uH / 1 uF: f0 = 1/(2*pi*sqrt(1e-5 * 1e-6)) = 50,329 Hz
        det = {"inductor": {"ref": "L1", "henries": 10e-6}, "capacitor": {"ref": "C1", "farads": 1e-6},
               "resonant_hz": 50329.21, "impedance_ohms": 3.162, "shared_net": "OUT"}
        r = _run(T.generate_lc_filter, R.evaluate_lc_filter, det)
        self.assertEqual(r["status"], "pass")
        self.assertNotIn("warnings", r)
        self.assertIn("Q_factor", r["simulated"])
        self.assertIn("assumed", r["model_note"])
        self.assertLess(r["delta"]["f_error_pct"], 1)


@unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
class CrystalTest(unittest.TestCase):
    def _check(self, freq, c, ppm):
        r = _run(T.generate_crystal_circuit, R.evaluate_crystal_circuit,
                 _crystal(freq, [("C1", c, "X1"), ("C2", c, "X2")]))
        self.assertEqual(r["status"], "info")
        sim = r["simulated"]
        self.assertNotIn("load_capacitance_pF", sim)
        self.assertIn("load_capacitance_pF", r["expected"])
        f_s = sim["f_series_hz"]
        f_l_hand = f_s * (1 + _pulling_ppm(freq, c / 2) / 1e6)
        self.assertLess(abs(sim["f_load_hz"] - f_l_hand) / f_l_hand * 1e6, 50)
        self.assertAlmostEqual(sim["pulling_ppm"], ppm, delta=max(2.0, ppm * 0.005))
        return r

    def test_8mhz_22pf(self):
        # CL = 11 pF: 20 fF / (2 * 16 pF) = 625 ppm
        r = self._check(8e6, 22e-12, 625.0)
        self.assertAlmostEqual(r["simulated"]["motional_resistance_ohm"], 30.0, delta=1.0)

    def test_32k_12pf(self):
        # CL = 6 pF: 2 fF / (2 * 7.5 pF) = 133.3 ppm
        r = self._check(32768, 12e-12, 133.3)
        self.assertAlmostEqual(r["simulated"]["motional_resistance_ohm"], 40000, delta=400)

    def test_16mhz_4p7(self):
        # CL = 2.35 pF: 20 fF / (2 * 7.35 pF) = 1,360.5 ppm
        self._check(16e6, 4.7e-12, 1360.5)

    def test_parallel_caps_form_one_leg(self):
        # C1 10 pF || C3 12 pF on X1, C2 22 pF on X2: 22 pF per leg, CL 11 pF -> 625 ppm
        det = _crystal(8e6, [("C1", 10e-12, "X1"), ("C3", 12e-12, "X1"), ("C2", 22e-12, "X2")])
        self.assertEqual(det["effective_load_pF"], 14.0)
        r = _run(T.generate_crystal_circuit, R.evaluate_crystal_circuit, det)
        self.assertEqual(r["status"], "info")
        self.assertAlmostEqual(r["simulated"]["pulling_ppm"], 625.0, delta=3.125)
        self.assertIn("C3", r["note"])

    def test_misdetected_load_caps_keep_the_range_warn(self):
        # two 100 nF decoupling caps read as load caps: CL = 50 nF + 3 pF = 50,003 pF
        det = _crystal(8e6, [("C1", 100e-9, "X1"), ("C2", 100e-9, "X2")])
        self.assertEqual(det["effective_load_pF"], 50003.0)
        r = _run(T.generate_crystal_circuit, R.evaluate_crystal_circuit, det)
        self.assertEqual(r["status"], "warn")
        self.assertIn("50003", r["note"])


class CrystalUnitTest(unittest.TestCase):
    def test_series_resonance_not_measured_warns(self):
        det = _crystal(8e6, [("C1", 22e-12, "X1"), ("C2", 22e-12, "X2")])
        r = R.evaluate_crystal_circuit(det, {})
        self.assertEqual(r["status"], "warn")
        self.assertTrue(r["note"].startswith("not measured"))

    def test_one_leg_only_is_not_simulated(self):
        # both caps on the same crystal pin: no second leg, no load loop to build
        det = _crystal(8e6, [("C1", 22e-12, "X1"), ("C2", 22e-12, "X1"), ("C3", 1e-12, "X2")])
        det["load_caps"] = det["load_caps"][:2]
        self.assertIsNone(T.generate_crystal_circuit(det, "b.out"))


if __name__ == "__main__":
    unittest.main()
