"""A VSS-named net that a regulator output drives is a supply below ground.

The regulator keeps it as its output rail, the rail map gives it no 0 V (and no positive
part-number voltage), and the regulator-capacitor observation makes no claim on it. The
parts on the net still read it as their ground. A VSS net with only IC VSS pins stays
ground at 0 V.
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context, vss_supply_rail_nets  # noqa: E402
from schematic.pipeline import build_rail_map  # noqa: E402
from signal_detectors import (  # noqa: E402
    detect_decoupling, detect_design_observations, detect_power_regulators,
)


def _pin(ref, num, name, pin_type):
    return dict(component=ref, pin_number=num, pin_name=name, pin_type=pin_type)


def _part(ref, typ, value, lib_id, pin_names):
    return {"reference": ref, "type": typ, "value": value, "lib_id": lib_id, "footprint": "",
            "properties": {}, "pins": [{"number": n, "name": nm} for n, nm in pin_names]}


def _cap(ref):
    return _part(ref, "capacitor", "10u", "Device:C", [("1", "~"), ("2", "~")])


def _ctx(comps, nets, rails):
    full = {n: {"name": n, "pins": ps, "point_count": 0, "no_connect": False,
                "has_pwr_flag": False, "labels": []} for n, ps in nets.items()}
    return build_analysis_context(comps, full, {}, known_power_rails=rails, source="test")


def _negative_ldo(out_net="VSS", value="LM2990S-5.0"):
    """A negative LDO from -12V onto *out_net*, both decoupled; the default is a -5 V fixed
    part whose part number carries the voltage without its sign."""
    comps = [_part("U1", "ic", value, "Regulator_Linear:" + value,
                   [("1", "GND"), ("2", "IN"), ("3", "OUT")]),
             _cap("C1"), _cap("C2")]
    nets = {
        "GND": [_pin("U1", "1", "GND", "power_in"), _pin("C1", "2", "~", "passive"),
                _pin("C2", "2", "~", "passive")],
        "-12V": [_pin("U1", "2", "IN", "power_in"), _pin("C1", "1", "~", "passive")],
        out_net: [_pin("U1", "3", "OUT", "power_out"), _pin("C2", "1", "~", "passive")],
    }
    return _ctx(comps, nets, {"GND", "-12V", out_net})


def _mcu_vss():
    """An MCU whose only ground is VSS."""
    comps = [_part("U1", "ic", "MCU", "MCU:MCU", [("1", "VDD"), ("2", "VSS"), ("3", "VCAP")]),
             _cap("C1")]
    nets = {
        "+3V3": [_pin("U1", "1", "VDD", "power_in"), _pin("C1", "1", "~", "passive")],
        "VSS": [_pin("U1", "2", "VSS", "power_in"), _pin("C1", "2", "~", "passive")],
        "VCAP": [_pin("U1", "3", "VCAP", "power_out")],
    }
    return _ctx(comps, nets, {"+3V3", "VSS"})


class RegulatorDrivenVss(unittest.TestCase):
    def setUp(self):
        self.ctx = _negative_ldo()
        self.regs = detect_power_regulators(self.ctx, [])

    def test_vss_is_a_supply_rail_and_still_ground_to_its_parts(self):
        self.assertEqual(self.ctx.vss_supply_rails, {"VSS"})
        self.assertEqual(vss_supply_rail_nets(self.ctx), {"VSS"})
        self.assertTrue(self.ctx.is_ground("VSS"))

    def test_regulator_keeps_the_vss_output_rail(self):
        self.assertEqual([r["output_rail"] for r in self.regs], ["VSS"])

    def test_rail_map_gives_it_no_voltage_and_ignores_the_positive_estimate(self):
        self.assertEqual(self.regs[0]["estimated_vout"], 5.0)
        by_net = build_rail_map(self.ctx, self.regs)
        self.assertNotIn("VSS", by_net)
        self.assertEqual(by_net["GND"], 0)

    def test_no_missing_capacitor_claim_on_the_regulator(self):
        results = {"power_regulators": self.regs, "decoupling_analysis": detect_decoupling(self.ctx)}
        obs = detect_design_observations(self.ctx, results)
        self.assertEqual([o for o in obs if o["category"] == "regulator_caps"], [])

    def test_vssa_output_is_read_the_same_way(self):
        ctx = _negative_ldo("VSSA")
        regs = detect_power_regulators(ctx, [])
        self.assertEqual(ctx.vss_supply_rails, {"VSSA"})
        self.assertEqual(regs[0]["output_rail"], "VSSA")
        self.assertNotIn("VSSA", build_rail_map(ctx, regs))

    def test_adjustable_regulator_keeps_the_vss_output_rail(self):
        ctx = _negative_ldo(value="LT3094")
        regs = detect_power_regulators(ctx, [])
        self.assertEqual([r["output_rail"] for r in regs], ["VSS"])
        self.assertNotIn("VSS", build_rail_map(ctx, regs))


class GroundVss(unittest.TestCase):
    def test_vss_with_only_ic_vss_pins_stays_ground_at_zero(self):
        ctx = _mcu_vss()
        self.assertEqual(ctx.vss_supply_rails, frozenset())
        self.assertTrue(ctx.is_ground("VSS"))
        self.assertEqual(build_rail_map(ctx, [])["VSS"], 0)

    def test_power_out_pin_named_vss_does_not_make_a_supply(self):
        # a converter's own VSS output pin is its ground return, not an output
        comps = [_part("U1", "ic", "CONV", "C:C", [("1", "VSS"), ("2", "GND"), ("3", "VIN")])]
        nets = {"VSS": [_pin("U1", "1", "VSS", "power_out")],
                "GND": [_pin("U1", "2", "GND", "power_in")],
                "+5V": [_pin("U1", "3", "VIN", "power_in")]}
        self.assertEqual(_ctx(comps, nets, {"VSS", "GND", "+5V"}).vss_supply_rails, frozenset())

    def test_power_out_without_another_ground_does_not_make_a_supply(self):
        # no reference ground on the part: nothing says VSS sits away from its ground
        comps = [_part("U1", "ic", "REG", "R:R", [("1", "OUT"), ("2", "IN")])]
        nets = {"VSS": [_pin("U1", "1", "OUT", "power_out")],
                "+5V": [_pin("U1", "2", "IN", "power_in")]}
        self.assertEqual(_ctx(comps, nets, {"VSS", "+5V"}).vss_supply_rails, frozenset())


class NotAVssSupply(unittest.TestCase):
    def test_regulator_output_on_a_vss_named_rail_that_is_not_ground(self):
        # DVSS_1V8 is a VSS-family name but no ground: a positive supply rail.
        ctx = _negative_ldo("DVSS_1V8")
        self.assertFalse(ctx.is_ground("DVSS_1V8"))
        self.assertEqual(ctx.vss_supply_rails, frozenset())


class SheetNameOnAVssSupply(unittest.TestCase):
    def test_no_positive_voltage_from_a_5v_sheet_name(self):
        # An adjustable part (no estimate) on a sheet named "5V": the sheet's voltage is
        # not the VSS supply's.
        ctx = _negative_ldo("/5V/VSS", value="LT3094")
        regs = detect_power_regulators(ctx, [])
        self.assertEqual(ctx.vss_supply_rails, {"/5V/VSS"})
        self.assertIsNone(regs[0].get("estimated_vout"))
        self.assertNotIn("/5V/VSS", build_rail_map(ctx, regs))


if __name__ == "__main__":
    unittest.main()
