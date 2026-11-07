"""Capacitor derating reaches LC-filter capacitors, and a capacitor whose two
terminals sit on two rails is judged at the difference between them."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from schematic.pipeline import apply_capacitor_derating  # noqa: E402
from schematic.system_analyses import analyze_voltage_derating  # noqa: E402


def _net_ctx(pins):
    """A context from {(ref, pin): net}."""
    nets = {}
    for (ref, pin), net in pins.items():
        nets.setdefault(net, {"name": net, "pins": [], "point_count": 0, "no_connect": False,
                              "has_pwr_flag": False, "labels": []})
        nets[net]["pins"].append({"component": ref, "pin_number": pin, "pin_name": pin,
                                  "pin_type": "passive"})
    return build_analysis_context([], nets, {}, known_power_rails={"GND"})


def _lc_results(cap):
    return {"power_regulators": [{"ref": "U1", "estimated_vout": 3.3,
                                  "output_rail": "3V3_BUCK", "output_capacitors": []}],
            "lc_filters": [{"inductor": {"ref": "L1", "henries": 2.2e-6},
                            "capacitor": cap, "shared_net": "3V3_BUCK"}]}


class LcFilterDerating(unittest.TestCase):
    PINS = {("L1", "1"): "SW", ("L1", "2"): "3V3_BUCK",
            ("C7", "1"): "3V3_BUCK", ("C7", "2"): "GND",
            ("C8", "1"): "3V3_BUCK", ("C8", "2"): "GND",
            ("C9", "1"): "3V3_BUCK", ("C9", "2"): "FB"}

    def _cap(self, ref, **extra):
        return {"ref": ref, "farads": 22e-6, "package": "0603", "dielectric": "X5R", **extra}

    def test_lc_capacitor_on_a_3v3_regulator_output_is_derated(self):
        cap = self._cap("C7")
        apply_capacitor_derating(_lc_results(cap), _net_ctx(self.PINS))
        self.assertEqual(cap["applied_voltage_V"], 3.3)
        self.assertIn("derating_factor", cap)
        self.assertLess(cap["effective_farads"], 22e-6)

    def test_parallel_lc_capacitors_to_ground_are_derated(self):
        cap = self._cap("C7", parallel_refs=["C7", "C8"])
        apply_capacitor_derating(_lc_results(cap), _net_ctx(self.PINS))
        self.assertEqual(cap["applied_voltage_V"], 3.3)

    def test_feedforward_capacitor_on_the_output_is_not_derated(self):
        # Output node to FB: the cap does not see the rail voltage.
        cap = self._cap("C9")
        apply_capacitor_derating(_lc_results(cap), _net_ctx(self.PINS))
        self.assertNotIn("applied_voltage_V", cap)
        par = self._cap("C7", parallel_refs=["C7", "C9"])
        apply_capacitor_derating(_lc_results(par), _net_ctx(self.PINS))
        self.assertNotIn("applied_voltage_V", par)

    def test_lc_capacitor_on_an_unknown_net_is_left_alone(self):
        cap = self._cap("C7")
        results = _lc_results(cap)
        results["lc_filters"][0]["shared_net"] = "AUDIO_OUT"
        apply_capacitor_derating(results, _net_ctx(self.PINS))
        self.assertNotIn("applied_voltage_V", cap)


def _ctx(cap_nets, value="10uF 10V X7R"):
    """C1 with pin 1 on cap_nets[0] and pin 2 on cap_nets[1]."""
    nets = {}
    for pin, net in zip(("1", "2"), cap_nets):
        nets.setdefault(net, {"name": net, "pins": [], "point_count": 0, "no_connect": False,
                              "has_pwr_flag": False, "labels": []})
        nets[net]["pins"].append({"component": "C1", "pin_number": pin, "pin_name": pin,
                                  "pin_type": "passive"})
    comps = [{"reference": "C1", "type": "capacitor", "value": value,
              "footprint": "Capacitor_SMD:C_0805_2012Metric", "lib_id": "Device:C"}]
    rails = {n for n in cap_nets if n not in ("GND", "SIG")}
    return build_analysis_context(comps, nets, {}, known_power_rails=rails)


def _vd(ctx):
    return [f for f in analyze_voltage_derating(ctx, {}) if f["rule_id"].startswith("VD-")]


class RailToRailDerating(unittest.TestCase):
    def test_cap_between_12v_and_5v_is_stressed_at_7v(self):
        (f,) = _vd(_ctx(["+12V", "+5V"]))
        # 7 V on a 10 V ceramic: over the 50 % working limit, under the rating.
        self.assertEqual((f["rule_id"], f["severity"], f["rail_voltage"]), ("VD-001", "warning", 7.0))
        for text in (f["summary"], f["description"]):
            self.assertIn("+12V", text)
            self.assertIn("+5V", text)
            self.assertIn("7.0V", text)

    def test_cap_between_two_rails_in_either_pin_order(self):
        (a,) = _vd(_ctx(["+12V", "+5V"]))
        (b,) = _vd(_ctx(["+5V", "+12V"]))
        self.assertEqual((a["rail_voltage"], a["margin_pct"]), (b["rail_voltage"], b["margin_pct"]))

    def test_close_rails_read_as_over_designed(self):
        (f,) = _vd(_ctx(["+3V3", "+2V5"], value="10uF 10V X7R"))
        self.assertEqual((f["rule_id"], f["rail_voltage"]), ("VD-004", 0.8))
        self.assertIn("+3V3", f["summary"])
        self.assertIn("+2V5", f["summary"])

    def test_cap_to_ground_keeps_the_rail_voltage(self):
        (f,) = _vd(_ctx(["+12V", "GND"]))
        self.assertEqual((f["rule_id"], f["severity"], f["rail_voltage"]), ("VD-001", "error", 12.0))
        self.assertNotIn("GND", f["summary"])

    def test_cap_to_a_signal_net_keeps_the_rail_voltage(self):
        (f,) = _vd(_ctx(["+12V", "SIG"]))
        self.assertEqual((f["rule_id"], f["rail_voltage"]), ("VD-001", 12.0))
        self.assertNotIn("SIG", f["summary"])


if __name__ == "__main__":
    unittest.main()
