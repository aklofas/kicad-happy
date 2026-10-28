"""Op-amp benches are biased at mid-supply, and negative supply rails are read
from their net names."""
import shutil, sys, tempfile, unittest

from tools.tests.test_spice_status_units import SPICE, _run

sys.path.insert(0, str(SPICE))

import spice_results as R  # noqa: E402
import spice_templates as T  # noqa: E402


def _rails(vcc_net, vee_net, vee_pin="V-"):
    return {"nets": {vcc_net: {"pins": [{"component": "U1", "pin_name": "V+", "pin_type": "power_in"}]},
                     vee_net: {"pins": [{"component": "U1", "pin_name": vee_pin, "pin_type": "power_in"}]}},
            "components": []}


_SINGLE_5V = _rails("+5V", "GND")

# LM358 (lookup table, GBW 1 MHz): -100k/10k = -10 = 20 dB, closed-loop
# bandwidth GBW/(1 + 10) = 90.9 kHz, phase at -3 dB = 180 - 45 = 135 deg
_INVERTING = {"reference": "U1", "value": "LM358", "configuration": "inverting",
              "output_net": "OUT", "inverting_input_net": "INN", "non_inverting_input_net": "REF",
              "gain": -10.0, "gain_dB": 20.0,
              "feedback_resistor": {"ref": "R2", "ohms": 100e3},
              "input_resistor": {"ref": "R1", "ohms": 10e3}}
_BUFFER = {"reference": "U1", "value": "LM358", "configuration": "buffer",
           "output_net": "OUT", "inverting_input_net": "OUT", "non_inverting_input_net": "IN",
           "gain": 1.0, "gain_dB": 0.0}
# 1 + 90k/10k = 10 = 20 dB; the 10k ground leg is the input_resistor
_NON_INVERTING = {"reference": "U1", "value": "LM358", "configuration": "non_inverting",
                  "output_net": "OUT", "inverting_input_net": "INN", "non_inverting_input_net": "IN",
                  "gain": 10.0, "gain_dB": 20.0,
                  "feedback_resistor": {"ref": "R2", "ohms": 90e3},
                  "input_resistor": {"ref": "R1", "ohms": 10e3}}


def _opamp(det, ctx):
    from spice_model_cache import ModelOptions
    with tempfile.TemporaryDirectory() as tmp:
        return _run(T.generate_opamp_circuit, R.evaluate_opamp_circuit, det, tmp, context=ctx,
                    model_options=ModelOptions(cache_dir=tmp, offline=True))


def _circuit(det, ctx):
    from spice_model_cache import ModelOptions
    with tempfile.TemporaryDirectory() as tmp:
        return T.generate_opamp_circuit(det, "b.out", context=ctx,
                                        model_options=ModelOptions(cache_dir=tmp, offline=True)).circuit


@unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
class SingleSupplyBenchTest(unittest.TestCase):
    def test_inverting_on_5v(self):
        r = _opamp(_INVERTING, _SINGLE_5V)
        self.assertEqual(r["status"], "pass")
        self.assertAlmostEqual(r["simulated"]["gain_dB"], 20.0, delta=0.2)
        self.assertAlmostEqual(r["simulated"]["bandwidth_hz"], 90e3, delta=5e3)
        self.assertAlmostEqual(r["simulated"]["phase_at_bw_deg"], 135.0, delta=1.0)

    def test_buffer_on_5v(self):
        r = _opamp(_BUFFER, _SINGLE_5V)
        self.assertEqual(r["status"], "pass")
        self.assertAlmostEqual(r["simulated"]["gain_dB"], 0.0, delta=0.1)
        # single pole: -45 deg at -3 dB
        self.assertAlmostEqual(r["simulated"]["phase_at_bw_deg"], -45.0, delta=1.0)

    def test_inverting_with_reference_input_on_ground(self):
        r = _opamp(dict(_INVERTING, non_inverting_input_net="GND"), _SINGLE_5V)
        self.assertEqual(r["status"], "pass")
        self.assertAlmostEqual(r["simulated"]["gain_dB"], 20.0, delta=0.2)

    def test_non_inverting_on_5v(self):
        r = _opamp(_NON_INVERTING, _SINGLE_5V)
        self.assertEqual(r["status"], "pass")
        self.assertAlmostEqual(r["simulated"]["gain_dB"], 20.0, delta=0.2)


class MidSupplyNetlistTest(unittest.TestCase):
    def test_single_supply_references_go_to_mid_supply(self):
        cir = _circuit(_INVERTING, _SINGLE_5V)
        self.assertIn("V_MID vmid_ref 0 DC 2.5", cir)
        self.assertIn("Rpos_bias REF vmid_ref 0.001", cir)
        self.assertIn("VAC sig_in 0 DC 2.5 AC 1", cir)

    def test_grounded_reference_input_goes_to_mid_supply(self):
        cir = _circuit(dict(_INVERTING, non_inverting_input_net="GND"), _SINGLE_5V)
        self.assertIn("XU1 vmid_ref INN OUT VCC GND_VEE OPAMP_LM358", cir)

    def test_non_inverting_ground_leg_goes_to_mid_supply(self):
        cir = _circuit(_NON_INVERTING, _SINGLE_5V)
        self.assertIn("R1 INN vmid_ref 10k", cir)
        self.assertIn("VAC IN 0 DC 2.5 AC 1", cir)

    def test_mid_supply_value_is_rounded(self):
        # +3.3 V / -5 V: (3.3 - 5)/2 = -0.85 V
        cir = _circuit(_INVERTING, _rails("+3V3", "-5V"))
        self.assertIn("V_MID vmid_ref 0 DC -0.85\n", cir)
        self.assertIn("VAC sig_in 0 DC -0.85 AC 1", cir)

    def test_symmetric_supply_netlist_unchanged(self):
        # +/-12 V: mid-supply is 0 V, so the bench is the ground-referenced one, byte for byte
        det = dict(_INVERTING, value="")
        want = ("* Auto-generated testbench for opamp: U1 ()\n* Configuration: inverting\n"
                "* Expected gain: -10.000 (20.0 dB)\n"
                "* Model: IDEAL opamp (Aol=1e6, GBW~10MHz) \u2014 real part may have lower GBW\n\n"
                f"{T.get_ideal_opamp()}\n{T.get_generic_models()}\n\n"
                "* Power supplies\nV_VCC VCC 0 DC 12.0\nV_VEE VEE 0 DC -12.0\n\n"
                "* Opamp instance\nXU1 REF INN OUT VCC VEE IDEAL_OPAMP\n\n"
                "* Feedback network\nR2 OUT INN 100k\nR1 sig_in INN 10k\nRpos_bias REF 0 0.001\n\n"
                "* AC stimulus\nVAC sig_in 0 DC 0 AC 1\n")
        self.assertEqual(_circuit(det, _rails("+12V", "-12V")), want)


class NegativeRailTest(unittest.TestCase):
    def test_rails_from_net_names(self):
        for vcc, vee, want in (("+5V", "-5V", (5, -5)), ("+12V", "-12VA", (12, -12)),
                               ("+15V", "NEG15V", (15, -15)), ("+5V", "GND", (5, 0)),
                               ("+5V", "-3V3", (5, -3.3))):
            with self.subTest(vee=vee):
                self.assertEqual(T._infer_opamp_rails({"reference": "U1"}, _rails(vcc, vee)), want)

    def test_named_negative_rail_mirrors_vcc(self):
        info = {}
        self.assertEqual(T._infer_opamp_rails({"reference": "U1"}, _rails("+15V", "VEE"), info), (15, -15))
        self.assertEqual(info, {"vee_assumed": True, "rails_named": False})

    def test_vee_pin_on_ground_is_single_supply(self):
        info = {}
        self.assertEqual(T._infer_opamp_rails({"reference": "U1"}, _rails("+15V", "GND", "VEE"), info), (15, 0))
        self.assertEqual(info, {"vee_assumed": False, "rails_named": True})

    def test_rails_without_a_voltage_in_the_name_are_not_named(self):
        for vcc, vee in (("VAA", "GND"), ("VCC", "GND"), ("+12V", "VEE")):
            with self.subTest(vcc=vcc, vee=vee):
                info = {}
                T._infer_opamp_rails({"reference": "U1"}, _rails(vcc, vee), info)
                self.assertFalse(info["rails_named"])

    def test_mirrored_rail_is_named_in_model_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            from spice_model_cache import ModelOptions
            tb = T.generate_opamp_circuit(_INVERTING, "b.out", context=_rails("+15V", "VEE"),
                                          model_options=ModelOptions(cache_dir=tmp, offline=True))
            tb_extra = dict(tb.extra_vars)
        sim = dict(tb_extra, gain_1k=20.0, bw_3db=9.0e4)
        note = R.evaluate_opamp_circuit(_INVERTING, sim)["model_note"]
        self.assertIn("negative rail assumed", note)
        sim_named = dict(gain_1k=20.0, bw_3db=9.0e4, model_source="lookup:LM358", model_gbw="1000000")
        self.assertNotIn("negative rail", R.evaluate_opamp_circuit(_INVERTING, sim_named)["model_note"])


@unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
class SupplyBelowMinimumTest(unittest.TestCase):
    """A part run below its minimum supply is not a pass: library minimums
    TL074 7 V, NE5532 8 V, LM358 3 V."""

    def test_named_rails_below_minimum_warn(self):
        r = _opamp(dict(_INVERTING, value="TL074"), _rails("+6V", "GND"))
        self.assertEqual(r["status"], "warn")
        self.assertIn("supply 6 V below the part's minimum 7 V", r["model_note"])

    def test_defaulted_rails_below_minimum_are_info(self):
        # VAA carries no voltage: the bench assumes 5 V
        r = _opamp(dict(_INVERTING, value="NE5532"), _rails("VAA", "GND"))
        self.assertEqual(r["status"], "info")
        self.assertIn("supply 5 V below the part's minimum 8 V", r["model_note"])

    def test_part_within_its_supply_range_passes(self):
        r = _opamp(_INVERTING, _SINGLE_5V)
        self.assertEqual(r["status"], "pass")
        self.assertNotIn("minimum", r["model_note"])


class GroundReferenceNoteTest(unittest.TestCase):
    def _note(self, pos_net, ctx):
        with tempfile.TemporaryDirectory() as tmp:
            from spice_model_cache import ModelOptions
            tb = T.generate_opamp_circuit(dict(_INVERTING, non_inverting_input_net=pos_net), "b.out",
                                          context=ctx, model_options=ModelOptions(cache_dir=tmp, offline=True))
        sim = dict(tb.extra_vars, gain_1k=20.0, bw_3db=9.0e4)
        return R.evaluate_opamp_circuit(_INVERTING, sim)["model_note"]

    def test_ground_named_reference_moved_to_mid_supply_is_noted(self):
        self.assertIn("reference input on a ground net re-biased to mid-supply", self._note("GNDA", _SINGLE_5V))

    def test_bench_ground_and_dual_supply_carry_no_note(self):
        self.assertNotIn("re-biased", self._note("GND", _SINGLE_5V))
        self.assertNotIn("re-biased", self._note("GNDA", _rails("+12V", "-12V")))
        self.assertNotIn("re-biased", self._note("REF", _SINGLE_5V))


if __name__ == "__main__":
    unittest.main()
