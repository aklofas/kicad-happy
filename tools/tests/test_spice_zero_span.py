"""A transistor bench sweeps its base (gate) across the supply its emitter
(source, drain) net names. A supply that reads 0 V leaves a sweep with no
span, which ngspice never finishes, so the bench is skipped with the reason."""
import shutil, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPICE = ROOT / "skills" / "spice" / "scripts"
sys.path.insert(0, str(SPICE))


def _simulate(det):
    import simulate_subcircuits as S
    from spice_model_cache import ModelOptions
    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.monotonic()
        report = S.simulate_subcircuits(
            {"findings": [dict(det, detector="detect_transistor_circuits")]}, workdir=tmp,
            types=["transistor_circuits"], model_options=ModelOptions(cache_dir=tmp, offline=True))
        wall = time.monotonic() - t0
    return report["simulation_results"], wall


def _pnp(emitter_net):
    return {"reference": "Q1", "type": "bjt", "value": "MMBT3906",
            "lib_id": "Device:Q_PNP_BEC", "base_net": "B", "collector_net": "C",
            "emitter_net": emitter_net, "load_type": "unknown"}


def _pfet(source_net):
    return {"reference": "Q2", "type": "mosfet", "value": "AO3401", "is_pchannel": True,
            "gate_net": "G", "drain_net": "D", "source_net": source_net, "load_type": "unknown"}


@unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
class ZeroSpanSweepTest(unittest.TestCase):
    def test_pnp_on_a_0v_emitter_is_skipped(self):
        res, wall = _simulate(_pnp("0v"))
        self.assertLess(wall, 1.0)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["status"], "skip")
        self.assertEqual(res[0]["elapsed_s"], 0)
        self.assertEqual(res[0]["note"], "testbench generation failed: ValueError: "
                                         "emitter supply 0.0 V from net '0v' leaves no base sweep")

    def test_p_channel_on_a_0v_source_is_skipped(self):
        res, wall = _simulate(_pfet("0V"))
        self.assertLess(wall, 1.0)
        self.assertEqual([r["status"] for r in res], ["skip"])
        self.assertEqual(res[0]["note"], "testbench generation failed: ValueError: "
                                         "source supply 0.0 V from net '0V' leaves no gate sweep")

    def test_n_channel_on_a_0v_drain_is_skipped(self):
        det = dict(_pfet("GND"), is_pchannel=False, drain_net="0V")
        res, wall = _simulate(det)
        self.assertLess(wall, 1.0)
        self.assertEqual(res[0]["note"], "testbench generation failed: ValueError: "
                                         "drain supply 0.0 V from net '0V' leaves no gate sweep")

    def _assert_simulated(self, res):
        self.assertEqual(len(res), 1)
        self.assertNotEqual(res[0]["status"], "skip")
        self.assertGreater(res[0]["elapsed_s"], 0)
        self.assertIn("ic_on_mA", res[0]["simulated"])

    def test_pnp_on_a_positive_rail_simulates(self):
        # +5V: the base sweep runs 2.5-5 V
        self._assert_simulated(_simulate(_pnp("+5V"))[0])

    def test_pnp_on_a_negative_rail_is_not_skipped(self):
        # a negative rail name does not read as 0 V, so its sweep keeps a span
        self._assert_simulated(_simulate(_pnp("-5V"))[0])


if __name__ == "__main__":
    unittest.main()
