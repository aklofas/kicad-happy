"""A negative rail uses its magnitude where the physics does: a
switching regulator's thermal loss, an LDO's dropout and dissipation, and capacitor DC-bias
derating. The signed value stays in what the reports print."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

import analyze_thermal as at  # noqa: E402
import emc_rules as er  # noqa: E402
from detection_schema import recalc_derived  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from schematic.pipeline import apply_capacitor_derating  # noqa: E402
from schematic.system_analyses import analyze_power_budget  # noqa: E402
from signal_detectors import _estimate_regulator_dissipation  # noqa: E402


def _ctx(rails, overrides=None):
    full = {n: {"name": n, "pins": [], "point_count": 0, "no_connect": False,
                "has_pwr_flag": False, "labels": []} for n in rails}
    cfg = {"voltage_overrides": overrides} if overrides else None
    return build_analysis_context([], full, {}, known_power_rails=set(rails), power_rails_config=cfg)


class ThermalSwitchingLoss(unittest.TestCase):
    def test_negative_switcher_has_a_positive_loss(self):
        # 5.047 V x 0.040 A x (1/0.85 - 1) = 0.0356 W.
        sch = {"findings": [{"detector": "detect_power_regulators", "ref": "IC12", "value": "LM27761",
                             "topology": "switching", "output_rail": "-5V", "estimated_vout": -5.047}],
               "power_budget": {"rails": {"-5V": {"estimated_load_mA": 40}}}}
        results, skipped = at._estimate_all_power_dissipation(sch)
        row = next(r for r in results if r["ref"] == "IC12")
        self.assertAlmostEqual(row["pdiss_w"], 0.0356, places=4)
        self.assertEqual(row["vout_v"], -5.047)
        self.assertEqual([s for s in skipped if s["ref"] == "IC12"], [])


class LdoBudget(unittest.TestCase):
    def test_negative_ldo_drops_the_magnitude_difference(self):
        ctx = _ctx(["-25V", "-15V"])
        sig = {"power_regulators": [{"ref": "U1", "value": "LM337", "topology": "LDO",
                                     "estimated_vout": -15.0, "input_rail": "-25V",
                                     "output_rail": "-15V"}]}
        ldo = analyze_power_budget(ctx, sig)["rails"]["-15V"]["ldo_dissipation"]
        self.assertEqual(ldo["dropout"], 10.0)


class RegulatorDissipation(unittest.TestCase):
    def test_negative_ldo_gets_a_dissipation_estimate(self):
        ctx = _ctx(["VNEG_IN", "VNEG"], {"VNEG_IN": -12.0})
        reg = {"ref": "U1", "topology": "LDO", "input_rail": "VNEG_IN", "estimated_vout": -5.0,
               "output_capacitors": [{"ref": "C1", "farads": 10e-6}]}
        _estimate_regulator_dissipation(ctx, [reg])
        pd = reg["power_dissipation"]
        # dropout 12 - 5 = 7 V at the 0.1 A cap proxy (10 uF): 0.7 W.
        self.assertEqual((pd["vout_V"], pd["dropout_V"], pd["estimated_pdiss_W"]), (-5.0, 7.0, 0.7))

    def test_ldo_whose_rails_differ_in_sign_gets_none(self):
        ctx = _ctx(["VIN", "VNEG"], {"VIN": 12.0})
        reg = {"ref": "U1", "topology": "LDO", "input_rail": "VIN", "estimated_vout": -5.0,
               "output_capacitors": []}
        _estimate_regulator_dissipation(ctx, [reg])
        self.assertNotIn("power_dissipation", reg)

    def test_inverting_switcher_loss_is_positive(self):
        ctx = _ctx(["+12V", "-5V"])
        reg = {"ref": "U2", "topology": "switching", "input_rail": "+12V", "estimated_vout": -5.0,
               "value": "LM2611", "lib_id": "", "output_capacitors": [{"ref": "C2", "farads": 10e-6}]}
        _estimate_regulator_dissipation(ctx, [reg])
        pd = reg["power_dissipation"]
        # 5 V x 0.1 A x (1/0.78 - 1) = 0.141 W; an inverting output is a buck-boost.
        self.assertEqual((pd["sub_topology"], pd["vout_V"], pd["estimated_pdiss_W"]), ("buck-boost", -5.0, 0.141))


class WhatIfNegativeLdo(unittest.TestCase):
    def test_recalc_keeps_a_negative_ldo_block(self):
        # Three-terminal adjustable: Vout = Vref / (1 - ratio). 240/720 gives -5 V; a 1.68k
        # bottom resistor gives 1.25 / (1 - 0.875) = -10 V, 2 V under the -12 V input.
        det = {"detector": "detect_power_regulators", "ref": "U1", "topology": "LDO",
               "estimated_vout": -5.0, "assumed_vref": 1.25,
               "feedback_divider": {"r_top": {"ohms": 240.0}, "r_bottom": {"ohms": 1680.0},
                                    "reference": "out_adj"},
               "power_dissipation": {"vin_estimated_V": -12.0, "vout_V": -5.0, "dropout_V": 7.0,
                                     "estimated_iout_A": 0.1, "estimated_pdiss_W": 0.7}}
        recalc_derived(det, "power_regulators")
        pd = det["power_dissipation"]
        self.assertEqual((det["estimated_vout"], pd["vout_V"], pd["dropout_V"], pd["estimated_pdiss_W"]),
                         (-10.0, -10.0, 2.0, 0.2))


class Derating(unittest.TestCase):
    def _results(self, vout):
        return {"power_regulators": [{"ref": "U1", "estimated_vout": vout, "output_rail": "R",
                                      "output_capacitors": [{"ref": "C1", "farads": 10e-6,
                                                             "package": "0402", "dielectric": "X5R"}]}],
                "decoupling_analysis": [{"rail": "R", "capacitors": [{"ref": "C2", "farads": 1e-6,
                                                                      "package": "0402",
                                                                      "dielectric": "X5R"}]}]}

    def test_negative_rail_caps_derate_as_the_positive_rail(self):
        neg, pos = self._results(-5.0), self._results(5.0)
        apply_capacitor_derating(neg)
        apply_capacitor_derating(pos)
        self.assertEqual(neg["power_regulators"][0]["output_capacitors"][0]["applied_voltage_V"], 5.0)
        self.assertIn("derating_factor", neg["decoupling_analysis"][0]["capacitors"][0])
        self.assertEqual(neg, pos | {"power_regulators": [dict(pos["power_regulators"][0], estimated_vout=-5.0)]})

    def test_th001_fires_on_the_negative_rail_as_on_the_positive(self):
        def sch(v):
            return {"findings": [{"detector": "detect_power_regulators", "ref": "U1", "estimated_vout": v,
                                  "output_rail": "R", "output_capacitors": [
                                      {"ref": "C1", "farads": 10e-6, "package": "0402",
                                       "value": "10uF X5R", "rated_voltage_V": 6.3}]}]}
        pos = [f for f in er.check_thermal_emc(None, sch(5.0)) if f["rule_id"] == "TH-001"]
        neg = [f for f in er.check_thermal_emc(None, sch(-5.0)) if f["rule_id"] == "TH-001"]
        self.assertEqual(len(pos), 1)
        self.assertEqual(len(neg), 1)
        self.assertIn("-5.0V rail", neg[0]["description"])


if __name__ == "__main__":
    unittest.main()
