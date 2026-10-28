"""A SPICE `pass` means the check's measurement was taken and is in
tolerance: inrush measures its current, regulator feedback is compared
against the part's reference voltage, RF networks the bench cannot model are
skipped, the half bridge powers its low-side switch, P-channel switches
report their on-state current, and passives whose designator names another
element type still simulate as passives. Expected values are hand-derived."""
import os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPICE = ROOT / "skills" / "spice" / "scripts"
sys.path.insert(0, str(SPICE))

import spice_results as R  # noqa: E402
import spice_templates as T  # noqa: E402


def _run(gen, ev, det, **kw):
    """Render the bench, run ngspice in a temp dir, evaluate."""
    from spice_simulator import NgspiceBackend
    with tempfile.TemporaryDirectory() as tmp:
        tb = gen(det, "b.out", **kw)
        with open(os.path.join(tmp, "b.cir"), "w", encoding="utf-8") as f:
            f.write(tb.render(NgspiceBackend(), "b.out"))
        run = subprocess.run(["ngspice", "-b", "b.cir"], cwd=tmp, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60)
        if run.returncode != 0:
            raise AssertionError(f"ngspice exited {run.returncode}:\n{run.stdout[-2000:]}{run.stderr[-2000:]}")
        sim = R.parse_output_file(os.path.join(tmp, "b.out"))
    return ev(det, sim)


def _simulate(findings, types):
    """Run the full simulate_subcircuits path (records, generator skips)."""
    import simulate_subcircuits as S
    from spice_model_cache import ModelOptions
    with tempfile.TemporaryDirectory() as tmp:
        report = S.simulate_subcircuits({"findings": findings}, workdir=tmp, types=types,
                                        model_options=ModelOptions(cache_dir=tmp, offline=True))
    return report["simulation_results"]


def _regulator(r_top, r_bot, rail, vref, vref_source, reference=None, value="TPS54160"):
    fd = {"r_top": {"ref": "R1", "ohms": r_top}, "r_bottom": {"ref": "R2", "ohms": r_bot},
          "ratio": r_bot / (r_top + r_bot)}
    if reference:
        fd["reference"] = reference
    return {"detector": "detect_power_regulators", "ref": "U1", "value": value,
            "output_rail": rail, "assumed_vref": vref, "vref_source": vref_source,
            "estimated_vout": round(vref / (fd["ratio"] if not reference else 1 - fd["ratio"]), 3),
            "feedback_divider": fd}


@unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
class InrushTest(unittest.TestCase):
    def test_inrush_current_measured(self):
        # I = C*dV/dt = 100 uF * 3.3 V / 0.5 ms = 0.660 A; with the 0.1 ohm LDO source
        # (tau = 10 us) the current reaches 99.9 % after 6.9 tau, ramp starts at 10 us -> 79 us
        det = {"regulator": "U1", "output_voltage": 3.3, "topology": "LDO",
               "output_caps": [{"ref": "C1", "farads": 100e-6}], "assumed_soft_start_ms": 0.5,
               "estimated_inrush_A": 0.66}
        r = _run(T.generate_inrush, R.evaluate_inrush, det)
        self.assertEqual(r["status"], "pass")
        self.assertAlmostEqual(r["simulated"]["i_peak_A"], 0.660, delta=0.0066)
        self.assertAlmostEqual(r["simulated"]["t_peak_us"], 79.0, delta=3.0)

    def test_inrush_without_current_is_not_a_pass(self):
        r = R.evaluate_inrush({"regulator": "U1", "output_caps": []},
                              {"v_settled": 3.3, "v_target": "3.3"})
        self.assertEqual(r["status"], "warn")
        self.assertTrue(r["note"].startswith("not measured"))


@unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
class RegulatorVrefTest(unittest.TestCase):
    def _eval(self, det):
        return _run(T.generate_regulator_feedback, R.evaluate_regulator_feedback, det)

    def test_divider_off_vref_fails(self):
        # TPS54160 FB = 0.8 V; Vfb = 3.3 * 10k/92k = 0.3587 V: 55.16 % off
        r = self._eval(_regulator(82e3, 10e3, "+3V3", 0.8, "lookup"))
        self.assertEqual(r["status"], "fail")
        self.assertAlmostEqual(r["delta"]["vfb_vs_vref_pct"], 55.16, delta=0.01)
        self.assertNotIn("vfb_error_pct", r["delta"])

    def test_divider_at_vref_passes(self):
        # Vfb = 3.3 * 10k/41.6k = 0.7933 V: 0.84 % from 0.8 V
        r = self._eval(_regulator(31.6e3, 10e3, "+3V3", 0.8, "lookup"))
        self.assertEqual(r["status"], "pass")
        self.assertAlmostEqual(r["delta"]["vfb_vs_vref_pct"], 0.84, delta=0.01)

    def test_out_adj_compares_across_out_and_adj(self):
        # LM317: Vref 1.25 V across OUT-ADJ; 5 - 5*820/1090 = 1.2385 V, 0.92 % from 1.25 V
        r = self._eval(_regulator(270, 820, "+5V", 1.25, "lookup", reference="out_adj", value="LM317"))
        self.assertEqual(r["status"], "pass")
        self.assertAlmostEqual(r["delta"]["vfb_vs_vref_pct"], 0.92, delta=0.01)

    def test_rail_without_voltage_in_name_is_info(self):
        # VCC is a guess (3.3 V), not a voltage the designer wrote
        r = self._eval(_regulator(56e3, 10e3, "VCC", 0.595, "lookup", value="TPS61023"))
        self.assertEqual(r["status"], "info")
        self.assertNotIn("vfb_vs_vref_pct", r["delta"])

    def test_heuristic_vref_is_info(self):
        r = self._eval(_regulator(31.6e3, 10e3, "+3V3", 0.8, "heuristic"))
        self.assertEqual(r["status"], "info")

    def test_carrier_board_lm338_does_not_fail(self):
        # cl3m3nt0n1 Bridge---Canyon-on-Hardware carrier_board, as the analyzer reports it:
        # Vout = 1.25 * (1 + 820/270) = 5.05 V, the +5V rail. The 1.25 V is the LM337 symbol's
        # (a negative regulator); the value names an LM338, so it is not this part's criterion.
        det = {"ref": "U2", "value": "LM338_TO220", "lib_id": "Regulator_Linear:LM337_TO220",
               "topology": "LDO", "output_rail": "+5V",
               "assumed_vref": 1.25, "vref_source": "lookup", "estimated_vout": 5.046,
               "feedback_divider": {"r_top": {"ref": "R1", "ohms": 270.0, "value": "270"},
                                    "r_bottom": {"ref": "R3", "ohms": 820.0, "value": "820"},
                                    "ratio": 0.752294, "reference": "out_adj"}}
        r = self._eval(det)
        self.assertEqual(r["status"], "info")
        self.assertIn("Vref from the symbol; the value names another part", r["note"])
        self.assertNotIn("vfb_vs_vref_pct", r["delta"])

    def test_value_and_symbol_naming_the_same_part_is_judged(self):
        # LM317 value on the LM317 symbol: 5 - 5*820/1090 = 1.2385 V, 0.92 % from 1.25 V
        det = _regulator(270, 820, "+5V", 1.25, "lookup", reference="out_adj", value="LM317_TO220")
        det["lib_id"] = "Regulator_Linear:LM317_TO220"
        self.assertEqual(self._eval(det)["status"], "pass")

    def test_rt6150_reference_from_its_datasheet(self):
        # RT6150A/B datasheet (DS6150A/B-06): VFB = 0.5 V; hackquad U7's 487k/86.6k on +3V3:
        # 3.3 * 86.6/573.6 = 0.4982 V, 0.36 % from 0.5 V
        from kicad_core.parts import lookup_regulator_vref
        vref, source = lookup_regulator_vref("RT6150AGQW", "")
        self.assertEqual((vref, source), (0.5, "lookup"))
        det = _regulator(487e3, 86.6e3, "+3V3", vref, source, value="RT6150AGQW")
        r = self._eval(det)
        self.assertEqual(r["status"], "pass")
        self.assertAlmostEqual(r["delta"]["vfb_vs_vref_pct"], 0.36, delta=0.01)

    def test_key_must_cover_the_part_number(self):
        from kicad_core.parts import vref_key_covers_part
        self.assertTrue(vref_key_covers_part("TPS61023", "TPS61023DRLR"))
        self.assertTrue(vref_key_covers_part("RT6150", "RT6150AGQW"))
        self.assertFalse(vref_key_covers_part("TPS6103", "TPS61032"))
        self.assertFalse(vref_key_covers_part("TPS6102", "TPS61025"))
        self.assertFalse(vref_key_covers_part("LT860", "LT8606"))

    def test_shorter_table_key_is_info(self):
        # TPS61032 (FB 0.5 V) on the 'TPS6103' 0.595 V row; LT8606 (FB 0.778 V) on 'LT860' 0.97 V:
        # a design correct for its part stays unjudged instead of failing
        for value, vref, r_top, r_bot in (("TPS61032PWPR", 0.595, 90.9e3, 10e3),
                                          ("LT8606EMSE", 0.97, 324e3, 100e3)):
            r = self._eval(_regulator(r_top, r_bot, "+5V", vref, "lookup", value=value))
            self.assertEqual(r["status"], "info", value)
            self.assertNotIn("vfb_vs_vref_pct", r["delta"])

    def test_family_default_reference_is_info(self):
        # 'SY8' names a family by one member's 0.6 V, not this part's datasheet value:
        # a match (100k/22k: 0.595 V) and a miss (82k/10k: 0.359 V) both stay unjudged
        for r_top, r_bot in ((100e3, 22e3), (82e3, 10e3)):
            r = self._eval(_regulator(r_top, r_bot, "+3V3", 0.6, "lookup", value="SY8253ADC"))
            self.assertEqual(r["status"], "info")
            self.assertIn("family", r["note"])
            self.assertNotIn("vfb_vs_vref_pct", r["delta"])

    def test_adjustable_arm_is_info(self):
        # a trimmer's setting is not its full value: 31.6k/10k would pass, but the top is RV1
        det = _regulator(31.6e3, 10e3, "+3V3", 0.8, "lookup")
        det["feedback_divider"]["r_top"]["ref"] = "RV1"
        self.assertEqual(self._eval(det)["status"], "info")
        # a pot symbol with an R designator, seen through the analysis's components
        det = _regulator(31.6e3, 10e3, "+3V3", 0.8, "lookup")
        det["_context"] = {"components": [{"reference": "R2", "lib_id": "Device:R_Potentiometer_Trim"}]}
        self.assertEqual(self._eval(det)["status"], "info")

    def test_no_feedback_divider_never_passes(self):
        # the analyzer drops feedback_divider when a trimmer sets the output
        det = {"ref": "U1", "value": "LM317", "output_rail": "+5V", "assumed_vref": 1.25,
               "vref_source": "lookup"}
        self.assertIsNone(T.generate_regulator_feedback(det, "b.out"))
        self.assertEqual(R.evaluate_regulator_feedback(det, {})["status"], "skip")
        self.assertEqual(_simulate([dict(det, detector="detect_power_regulators")],
                                   ["power_regulators"]), [])


@unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
class RfMatchingTest(unittest.TestCase):
    _COMPS = [{"ref": "C1", "type": "capacitor", "farads": 1e-12},
              {"ref": "L1", "type": "inductor", "henries": 3.3e-9},
              {"ref": "C2", "type": "capacitor", "farads": 1e-12}]

    def test_pi_match_is_skipped(self):
        res = _simulate([{"detector": "detect_rf_matching", "topology": "pi_match",
                          "components": self._COMPS}], ["rf_matching"])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["status"], "skip")
        self.assertIn("pi_match has shunt elements", res[0]["note"])

    def test_other_network_reports_info(self):
        det = {"topology": "matching_network", "components": self._COMPS}
        r = _run(T.generate_rf_matching, R.evaluate_rf_matching, det)
        self.assertEqual(r["status"], "info")
        self.assertIn("z_min_ohms", r["simulated"])


@unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
class HalfBridgeTest(unittest.TestCase):
    def _det(self, lo_type="NMOS"):
        return {"topology": "half_bridge",
                "half_bridges": [{"high_side": "Q1", "low_side": "Q2", "power_net": "+12V",
                                  "ground_net": "GND", "high_side_type": "NMOS",
                                  "low_side_type": lo_type}]}

    def test_low_side_switch_measured(self):
        # generic NMOS Vth 1.5 V; on-state current = 12 V / 100 ohm load = 120 mA.
        # Both are the generic model's, not the part's: info, not pass
        r = _run(T.generate_bridge_circuit, R.evaluate_bridge_circuit, self._det())
        self.assertEqual(r["status"], "info")
        self.assertAlmostEqual(r["simulated"]["vth_low_side_V"], 1.5, delta=0.1)
        self.assertAlmostEqual(r["simulated"]["id_on_mA"], 120.0, delta=2.0)

    def test_p_channel_high_side_stays_off(self):
        # source at the supply, gate tied to it: only the 100 ohm load carries current
        det = self._det()
        det["half_bridges"][0]["high_side_type"] = "PMOS"
        r = _run(T.generate_bridge_circuit, R.evaluate_bridge_circuit, det)
        self.assertEqual(r["status"], "info")
        self.assertAlmostEqual(r["simulated"]["id_on_mA"], 120.0, delta=2.0)

    def test_pmos_low_side_is_skipped(self):
        with self.assertRaises(ValueError):
            T.generate_bridge_circuit(self._det("PMOS"), "b.out")

    def test_threshold_not_found_is_not_a_pass(self):
        r = R.evaluate_bridge_circuit(self._det(), {"vth_lo": None, "id_on": 0.12})
        self.assertEqual(r["status"], "warn")
        self.assertTrue(r["note"].startswith("not measured"))


@unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
class TransistorGenericModelTest(unittest.TestCase):
    # The bench runs the generic FET/BJT model with a fixed 1 k load and a full gate
    # (base) sweep, so its threshold and on-current describe the model, not the part

    def test_p_channel_on_state_current(self):
        # P-channel high-side: 3.3 V across the 1 k load when on -> 3.3 mA
        det = {"reference": "Q1", "type": "mosfet", "value": "AO3401", "is_pchannel": True,
               "gate_net": "G", "drain_net": "D", "source_net": "+3V3", "load_type": "unknown"}
        r = _run(T.generate_transistor_circuit, R.evaluate_transistor_circuit, det)
        self.assertEqual(r["status"], "info")
        self.assertAlmostEqual(r["simulated"]["i_on_mA"], 3.3, delta=0.05)

    def test_npn_switch_is_info(self):
        # generic NPN: VBE at 1 mA ~0.65 V, inside the 0.5-0.8 V window
        det = {"reference": "Q2", "type": "bjt", "value": "MMBT3904", "lib_id": "Transistor_BJT:MMBT3904",
               "base_net": "B", "collector_net": "C", "emitter_net": "GND", "load_type": "unknown"}
        r = _run(T.generate_transistor_circuit, R.evaluate_transistor_circuit, det)
        self.assertEqual(r["status"], "info")
        self.assertTrue(0.5 < r["simulated"]["vbe_on_V"] < 0.8)


class PnpBenchTest(unittest.TestCase):
    # dvhx smd-soldering-exercise Q11: the PNP bench measures VBE(on) 2.647 V and IC 2.54e16 mA,
    # values no silicon PNP reaches (VBE ~0.65 V), so the bench did not reach an on-state
    _SIM = {"vbe_on": 2.647, "ic_on": 2.54e13}

    def test_pnp_bench_is_not_measured(self):
        det = {"reference": "Q11", "type": "bjt", "value": "MMBT3906", "lib_id": "Device:Q_PNP_BEC",
               "base_net": "B", "collector_net": "C", "emitter_net": "+5V"}
        r = R.evaluate_transistor_circuit(det, dict(self._SIM))
        self.assertEqual(r["status"], "warn")
        self.assertEqual(r["note"], "not measured: the PNP bench does not reach a valid on-state")
        self.assertEqual(r["simulated"], {})
        self.assertIn("generic PNP model", r["model_note"])

    def test_npn_label_and_values_unchanged(self):
        det = {"reference": "Q2", "type": "bjt", "value": "MMBT3904", "lib_id": "Device:Q_NPN_BEC",
               "base_net": "B", "collector_net": "C", "emitter_net": "GND"}
        r = R.evaluate_transistor_circuit(det, {"vbe_on": 0.65, "ic_on": 3.3e-3})
        self.assertEqual(r["status"], "info")
        self.assertIn("generic NPN model", r["model_note"])
        self.assertEqual(r["simulated"], {"vbe_on_V": 0.65, "ic_on_mA": 3.3})


@unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
class PassiveElementNameTest(unittest.TestCase):
    def test_potentiometer_top_is_a_resistor(self):
        # Vout = 5 V * 1000 / (890 + 1000) = 2.6455 V
        det = {"r_top": {"ref": "VR1", "ohms": 890.0}, "r_bottom": {"ref": "R2", "ohms": 1000.0},
               "top_net": "+5V", "mid_net": "MID", "bottom_net": "GND", "ratio": 1000 / 1890}
        tb = T.generate_voltage_divider(det, "b.out")
        self.assertIn("\nR_VR1 ", tb.circuit)
        self.assertIn("\nR2 ", tb.circuit)
        r = _run(T.generate_voltage_divider, R.evaluate_voltage_divider, det)
        self.assertEqual(r["status"], "pass")
        self.assertAlmostEqual(r["simulated"]["vout_V"], 2.6455, delta=0.001)


class RcCutoffTest(unittest.TestCase):
    # 1 Mohm / 1.5 uF: fc = 1/(2*pi*1e6*1.5e-6) = 0.106103 Hz; the analyzer rounds cutoff_hz to 0.11
    _DET = {"resistor": {"ref": "R1", "ohms": 1e6}, "capacitor": {"ref": "C1", "farads": 1.5e-6},
            "cutoff_hz": 0.11, "type": "low-pass", "input_net": "IN", "output_net": "OUT",
            "ground_net": "GND"}

    def test_sub_hz_cutoff_compared_with_the_exact_value(self):
        r = R.evaluate_rc_filter(dict(self._DET), {"fc_sim": 0.10612})
        self.assertEqual(r["status"], "pass")
        self.assertEqual(r["expected"]["cutoff_hz"], 0.11)
        self.assertLess(r["delta"]["fc_error_pct"], 1)

    def test_simulated_cutoff_off_the_rc_value_still_warns(self):
        # 3 % above 1/(2*pi*R*C), as a loaded or mis-read network would measure
        r = R.evaluate_rc_filter(dict(self._DET), {"fc_sim": 0.106103 * 1.03})
        self.assertEqual(r["status"], "warn")
        self.assertAlmostEqual(r["delta"]["fc_error_pct"], 3.0, delta=0.01)

    def test_missing_part_values_fall_back_to_the_cutoff(self):
        det = dict(self._DET, resistor={"ref": "R1"})
        r = R.evaluate_rc_filter(det, {"fc_sim": 0.10612})
        self.assertEqual(r["status"], "warn")

    @unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
    def test_sub_hz_bench_passes(self):
        r = _run(T.generate_rc_filter, R.evaluate_rc_filter, dict(self._DET))
        self.assertEqual(r["status"], "pass")


class RailNameVoltageTest(unittest.TestCase):
    def test_voltage_written_in_the_name(self):
        cases = {
            "+3V3": 3.3, "12VAA": 12.0, "0V9": 0.9, "VCC-5V": 5.0, "/Power/+1V8": 1.8,
            "USB2VBUS": None,   # USB 2.0 VBUS: the '2' is the USB version
            "-5V": None,        # a negative rail is not a positive regulator output
            "0V": None,         # ground
            "CONN_21": None,    # a connector pin number
            "VBUS": None, "VCC": None,
            "ATX_-5V": None, "analog_-15V": None,   # '-' before the voltage after a separator
            "3V3-5V": 3.3, "+5V-ISO": 5.0, "VCC-IO": None,
            "F-15V": 15.0,      # a bare letter before '-' is ambiguous (like VCC-5V): read as a separator
        }
        for name, volts in cases.items():
            self.assertEqual(T._rail_name_voltage(name), volts, name)


class NoExpectedValueTest(unittest.TestCase):
    _DIV = {"r_top": {"ref": "R1", "ohms": 10e3}, "r_bottom": {"ref": "R2", "ohms": 10e3},
            "ratio": 0.5}

    def test_divider_without_expected_is_info(self):
        r = R.evaluate_voltage_divider(dict(self._DIV), {"vout_sim": 1.65})
        self.assertEqual(r["status"], "info")

    def test_feedback_network_without_expected_is_info(self):
        r = R.evaluate_feedback_network(dict(self._DIV), {"vout_sim": 1.65})
        self.assertEqual(r["status"], "info")

    def test_current_sense_without_expected_is_info(self):
        # 0.1 ohm: I = V/R gives 0.5 A at 50 mV, but the record carries no current to compare
        det = {"shunt": {"ref": "R1", "ohms": 0.1}}
        r = R.evaluate_current_sense(det, {"i_at_50mV": 0.5, "i_at_100mV": 1.0})
        self.assertEqual(r["status"], "info")

    def test_current_sense_with_expected_keeps_its_verdict(self):
        det = {"shunt": {"ref": "R1", "ohms": 0.1}, "max_current_50mV_A": 0.5}
        self.assertEqual(R.evaluate_current_sense(det, {"i_at_50mV": 0.5})["status"], "pass")
        self.assertEqual(R.evaluate_current_sense(det, {"i_at_50mV": 0.6})["status"], "fail")

    def test_snubber_without_time_constant_is_info(self):
        det = {"reference": "Q1", "snubber_data": {"resistor_ref": "R1", "capacitor_ref": "C1"}}
        r = R.evaluate_snubber(det, {"z_min": 10.0, "f_at_zmin": 1e6})
        self.assertEqual(r["status"], "info")

    def test_snubber_with_time_constant_keeps_its_verdict(self):
        # 10 ohm x 1 nF = 10 ns, inside 1 ns-100 us
        det = {"reference": "Q1", "snubber_data": {"resistor_ref": "R1", "capacitor_ref": "C1"}}
        r = R.evaluate_snubber(det, {"z_min": 10.0, "tau": "1e-8", "f_analytical": "15.9e6"})
        self.assertEqual(r["status"], "pass")

    def test_rf_chain_on_heuristic_gains_is_info(self):
        det = {"stage_gains": {"U1": {"role": "lna", "gain_dB": 15}}, "frequency_band": "2.4GHz",
               "component_roles": {"U1": "lna"}}
        r = R.evaluate_rf_chain(det, {"gain_budget": "15", "freq_hz": "2.4e9", "n_stages": "1"})
        self.assertEqual(r["status"], "info")

    def test_divider_with_expected_keeps_its_verdict(self):
        # 3.3 V * 0.5 = 1.65 V expected, 1.65 simulated
        r = R.evaluate_voltage_divider(dict(self._DIV), {"vout_sim": 1.65, "expected": "1.65"})
        self.assertEqual(r["status"], "pass")
        r = R.evaluate_voltage_divider(dict(self._DIV), {"vout_sim": 1.80, "expected": "1.65"})
        self.assertEqual(r["status"], "fail")


if __name__ == "__main__":
    unittest.main()
