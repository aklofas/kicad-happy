"""SPICE phases are reported in degrees, op-amp results carry the phase at
their -3 dB bandwidth, and a bench with no acceptance criterion reports
`info`, counted in summary.info."""
import os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPICE = ROOT / "skills" / "spice" / "scripts"
sys.path.insert(0, str(SPICE))

import spice_results as R  # noqa: E402

# +/-5 V rails on the op-amp's power pins
_DUAL = {"nets": {"+5V": {"pins": [{"component": "U1", "pin_name": "V+", "pin_type": "power_in"}]},
                  "-5V": {"pins": [{"component": "U1", "pin_name": "V-", "pin_type": "power_in"}]}},
         "components": []}


def _run(gen, ev, det, tmp, **kw):
    """Render the bench, run ngspice in *tmp*, evaluate."""
    from spice_simulator import NgspiceBackend
    tb = gen(det, "b.out", **kw)
    with open(os.path.join(tmp, "b.cir"), "w", encoding="utf-8") as f:
        f.write(tb.render(NgspiceBackend(), "b.out"))
    subprocess.run(["ngspice", "-b", "b.cir"], cwd=tmp, capture_output=True, timeout=60)
    sim = R.parse_output_file(os.path.join(tmp, "b.out"))
    for k, v in tb.extra_vars.items():
        sim.setdefault(k, v)
    return ev(det, sim)


def _opamp(det, ctx=_DUAL):
    import spice_templates as T
    from spice_model_cache import ModelOptions
    with tempfile.TemporaryDirectory() as tmp:
        return _run(T.generate_opamp_circuit, R.evaluate_opamp_circuit, det, tmp, context=ctx,
                    model_options=ModelOptions(cache_dir=tmp, offline=True))


def _rc(ftype):
    import spice_templates as T
    # 1 k / 10 nF: fc = 1/(2*pi*R*C) = 15,915 Hz; first-order phase at fc is -45 deg (low-pass), +45 deg (high-pass)
    det = {"resistor": {"ref": "R1", "ohms": 1000.0}, "capacitor": {"ref": "C1", "farads": 10e-9},
           "cutoff_hz": 15915.49, "type": ftype, "input_net": "IN", "output_net": "OUT",
           "ground_net": "GND"}
    with tempfile.TemporaryDirectory() as tmp:
        return _run(T.generate_rc_filter, R.evaluate_rc_filter, det, tmp)


# An empty value resolves no part model, so the bench uses the ideal op-amp
# (single pole, GBW ~10 MHz): the phase at -3 dB is the closed-loop pole's -45 deg.
_INVERTING = {"reference": "U1", "value": "", "configuration": "inverting",
              "output_net": "OUT", "inverting_input_net": "INN", "non_inverting_input_net": "REF",
              "gain": -10.0, "gain_dB": 20.0,
              "feedback_resistor": {"ref": "R2", "ohms": 100e3},
              "input_resistor": {"ref": "R1", "ohms": 10e3}}


@unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
class PhaseInDegreesTest(unittest.TestCase):
    def test_rc_low_pass_phase_at_fc(self):
        r = _rc("low-pass")
        self.assertEqual(r["status"], "pass")
        self.assertAlmostEqual(r["simulated"]["phase_at_fc_deg"], -45.0, delta=0.5)

    def test_rc_high_pass_phase_at_fc(self):
        r = _rc("high-pass")
        self.assertEqual(r["status"], "pass")
        self.assertAlmostEqual(r["simulated"]["phase_at_fc_deg"], 45.0, delta=0.5)

    def test_inverting_phase_at_bandwidth(self):
        # single-pole closed loop: -45 deg at -3 dB on top of the 180 deg inversion
        r = _opamp(_INVERTING)
        self.assertAlmostEqual(r["simulated"]["phase_at_bw_deg"], 135.0, delta=1.0)

    def test_buffer_phase_at_bandwidth(self):
        det = {"reference": "U1", "value": "", "configuration": "buffer",
               "output_net": "OUT", "inverting_input_net": "OUT", "non_inverting_input_net": "IN",
               "gain": 1.0, "gain_dB": 0.0}
        r = _opamp(det)
        self.assertAlmostEqual(r["simulated"]["phase_at_bw_deg"], -45.0, delta=1.0)


@unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
class OpampStatusTest(unittest.TestCase):
    def test_transimpedance_reports_info(self):
        det = {"reference": "U1", "value": "", "configuration": "transimpedance_or_buffer",
               "output_net": "OUT", "inverting_input_net": "INN", "non_inverting_input_net": "REF",
               "feedback_resistor": {"ref": "R2", "ohms": 100e3}}
        r = _opamp(det)
        self.assertIn("gain_dB", r["simulated"])
        self.assertEqual(r["status"], "info")

    def test_expected_gain_keeps_its_gain_check(self):
        # -100k/10k = -10 = 20 dB; the bench measures 20 dB, so the gain check passes
        r = _opamp(_INVERTING)
        self.assertEqual(r["status"], "pass")
        self.assertEqual(r["delta"]["gain_error_dB"], 0.0)

    def test_behavioral_model_with_expected_gain_is_not_info(self):
        r = _opamp(dict(_INVERTING, value="LM358"))
        self.assertTrue(r["model_note"].startswith("LM358 behavioral"))
        self.assertIn(r["status"], ("pass", "warn"))
        self.assertIn("gain_error_dB", r["delta"])


class InfoStatusTest(unittest.TestCase):
    _SIM = {"gain_1k": 20.0, "bw_3db": 9.0e4, "model_source": "ideal", "model_gbw": "0"}

    def test_no_expected_gain_is_info(self):
        # a gain network with a pot leaves the configuration but no gain
        det = {"reference": "U1", "value": "TL072", "configuration": "non_inverting"}
        r = R.evaluate_opamp_circuit(det, dict(self._SIM))
        self.assertEqual(r["status"], "info")

    def test_expected_gain_is_not_info(self):
        det = {"reference": "U1", "value": "TL072", "configuration": "inverting",
               "gain": -10.0, "gain_dB": 20.0}
        self.assertEqual(R.evaluate_opamp_circuit(det, dict(self._SIM))["status"], "pass")
        det["gain_dB"] = 26.0
        self.assertEqual(R.evaluate_opamp_circuit(det, dict(self._SIM))["status"], "fail")

    def test_summary_info_always_present(self):
        empty = R.build_report([])["summary"]
        self.assertEqual(empty["info"], 0)
        self.assertEqual(empty["by_severity"]["info"], 0)
        runs = [{"subcircuit_type": "opamp_circuit", "components": ["U1"], "status": "info"},
                {"subcircuit_type": "rc_filter", "components": ["R1", "C1"], "status": "pass"},
                {"subcircuit_type": "rc_filter", "components": ["R2", "C2"], "status": "skip"}]
        rep = R.build_report(runs)
        s = rep["summary"]
        self.assertEqual((s["info"], s["pass"], s["skip"]), (1, 1, 1))
        self.assertEqual(s["by_severity"]["info"], 3)
        self.assertEqual(rep["findings"], [])

    def test_summary_line_counts_info(self):
        import simulate_subcircuits as ss
        rep = R.build_report([{"subcircuit_type": "opamp_circuit", "components": ["U1"], "status": "info"}])
        self.assertIn("1 info", ss._summary_line(rep))


class PhaseUnitTest(unittest.TestCase):
    """ngspice vp() returns radians and is converted once, where its output is
    parsed; a backend whose phase unit is not established is passed through."""
    _RC = {"resistor": {"ref": "R1", "ohms": 1000.0}, "capacitor": {"ref": "C1", "farads": 10e-9},
           "cutoff_hz": 15915.49, "type": "low-pass", "input_net": "IN", "output_net": "OUT"}

    def test_ngspice_output_is_read_in_degrees(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "b.out")
            with open(out, "w", encoding="utf-8") as f:
                f.write("fc_sim=1.58777e+04 phase_fc=-7.853982e-01 phase_at_bw=2.356194e+00")
            sim = R.parse_output_file(out)
        self.assertAlmostEqual(sim["phase_fc"], -45.0, places=4)
        self.assertAlmostEqual(sim["phase_at_bw"], 135.0, places=4)
        self.assertEqual(R.evaluate_rc_filter(self._RC, sim)["simulated"]["phase_at_fc_deg"], -45.0)

    def test_other_backends_are_not_converted(self):
        from spice_simulator import LtspiceBackend, XyceBackend
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "b.out")
            with open(os.path.join(tmp, "b.mt0"), "w", encoding="utf-8") as f:
                f.write("fc_sim = 15877.7\nphase_fc = -45.0\n")
            with open(os.path.join(tmp, "b.log"), "w", encoding="utf-8") as f:
                f.write("fc_sim: vdb(out)=-3 AT=15877.7\nphase_fc: vp(out)=-45.0\n")
            for backend in (XyceBackend(), LtspiceBackend()):
                sim = backend.parse_results(out, "", "")
                self.assertEqual(sim["phase_fc"], -45.0)
                self.assertEqual(R.evaluate_rc_filter(self._RC, sim)["simulated"]["phase_at_fc_deg"], -45.0)


class DiffInfoTest(unittest.TestCase):
    def test_diff_reports_info_count(self):
        sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
        from diff_engine import diff_spice
        run = {"subcircuit_type": "opamp_circuit", "components": ["U1"]}
        base = R.build_report([dict(run, status="pass")])
        head = R.build_report([dict(run, status="info")])
        delta = diff_spice(base, head, 0)["summary"]
        self.assertEqual(delta["summary.pass"]["delta"], -1)
        self.assertEqual(delta["summary.info"], {"base": 0, "head": 1, "delta": 1})


if __name__ == "__main__":
    unittest.main()
