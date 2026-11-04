# tools/tests/test_regulator_phases.py
"""Pins detect_power_regulators behaviour across its screen/build phases and post-loop passes."""
import copy, sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import detect_power_regulators  # noqa: E402

_TYPES = {"U": "ic", "L": "inductor", "R": "resistor", "C": "capacitor"}


def _ctx(parts):
    """Build a context from ``(ref, lib_id, value, {pin_num: (pin_name, net)})`` tuples."""
    components, nets = [], {}
    for ref, lib_id, value, pins in parts:
        components.append({
            "reference": ref, "lib_id": lib_id, "value": value,
            "type": _TYPES[ref.rstrip("0123456789")],
            "pins": [{"number": n, "name": name} for n, (name, _) in pins.items()],
        })
        for num, (name, net) in pins.items():
            nets.setdefault(net, {"pins": []})["pins"].append(
                {"component": ref, "pin_number": num, "pin_name": name})
    return build_analysis_context(components, nets, {})


def _divider(top, mid, bottom):
    return {"r_top": {"ref": "R1", "ohms": 10000.0, "value": "10k"},
            "r_bottom": {"ref": "R2", "ohms": 10000.0, "value": "10k"},
            "top_net": top, "mid_net": mid, "bottom_net": bottom, "ratio": 0.5}


_BUCK_PINS = {"1": ("SW", "SW_NODE"), "2": ("FB", "FB"), "3": ("VIN", "+12V")}
_INDUCTOR = ("L1", "Device:L", "10uH", {"1": ("1", "SW_NODE")})


class RegulatorPhases(unittest.TestCase):
    def test_keyword_pmic_without_pins_yields_keyword_only_record(self):
        ctx = _ctx([("U1", "Regulator_Linear:AMS1117-3.3", "LDO PMIC", {})])
        regs = detect_power_regulators(ctx, [])
        self.assertEqual([r["ref"] for r in regs], ["U1"])
        self.assertEqual(regs[0]["detector"], "detect_power_regulators")
        self.assertEqual(regs[0]["rule_id"], "PR-DET")
        self.assertEqual(regs[0]["topology"], "unknown")
        self.assertNotIn("vref_source", regs[0])

    def test_fixed_suffix_ldo_estimates_vout_and_ldo_topology(self):
        ctx = _ctx([("U2", "Regulator_Linear:AMS1117-3.3", "AMS1117-3.3",
                     {"1": ("GND", "GND"), "2": ("VOUT", "+3V3"), "3": ("VIN", "+5V")})])
        r = detect_power_regulators(ctx, [])[0]
        self.assertEqual(r["topology"], "LDO")
        self.assertEqual(r["estimated_vout"], 3.3)
        self.assertEqual(r["vref_source"], "fixed_suffix")
        self.assertEqual(r["input_rail"], "+5V")
        self.assertEqual(r["output_rail"], "+3V3")

    def test_inverting_regulator_negates_vout_and_fb_at_top_cross_reference(self):
        ctx = _ctx([("U3", "Regulator_Switching:LT3581", "LT3581", _BUCK_PINS), _INDUCTOR])
        r = detect_power_regulators(ctx, [_divider("FB", "X", "GND")])[0]
        self.assertEqual(r["topology"], "switching")
        self.assertEqual(r["inductor"], "L1")
        self.assertEqual(r["feedback_divider"]["topology"], "fb_at_top")
        self.assertEqual(r["output_rail"], "FB")

        ctx = _ctx([("U3", "Regulator_Switching:LT3581", "LT3581 inverting", _BUCK_PINS), _INDUCTOR])
        r = detect_power_regulators(ctx, [_divider("OUT", "FB", "GND")])[0]
        self.assertTrue(r["inverting"])
        self.assertLess(r["estimated_vout"], 0)

    def test_phase_functions_are_the_only_mutators(self):
        ctx = _ctx([("U2", "Regulator_Linear:AMS1117-3.3", "AMS1117-3.3",
                     {"1": ("GND", "GND"), "2": ("VOUT", "+3V3"), "3": ("VIN", "+5V")})])
        components, nets = copy.deepcopy(ctx.components), copy.deepcopy(ctx.nets)
        detect_power_regulators(ctx, [])
        self.assertEqual(ctx.components, components)
        self.assertEqual(ctx.nets, nets)


if __name__ == "__main__":
    unittest.main()
