"""A VSS-named net that a regulator output drives is a supply, not ground.

The regulator keeps it as its output rail, the rail map gives it no 0 V (and no positive
part-number voltage), its capacitors are decoupling, and a missing output capacitor is
reported as on any other rail. A project config that gives a VSS net a negative voltage makes
it a supply too. A VSS net with only IC VSS pins stays ground at 0 V, and so does a VSS net
that carries a ground symbol: the symbol ties it to the board ground.
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

import cross_analysis  # noqa: E402
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


def _ctx(comps, nets, rails, power_rails_config=None):
    full = {n: {"name": n, "pins": ps, "point_count": 0, "no_connect": False,
                "has_pwr_flag": False, "labels": []} for n, ps in nets.items()}
    return build_analysis_context(comps, full, {}, known_power_rails=rails, source="test",
                                  power_rails_config=power_rails_config)


def _negative_ldo(out_net="VSS", value="LM2990S-5.0", output_cap=True, extra=()):
    """A negative LDO from -12V onto *out_net*, both decoupled; the default is a -5 V fixed
    part whose part number carries the voltage without its sign. *extra* adds parts and pins
    as ``(part, net, pin)`` triples."""
    comps = [_part("U1", "ic", value, "Regulator_Linear:" + value,
                   [("1", "GND"), ("2", "IN"), ("3", "OUT")]),
             _cap("C1")] + ([_cap("C2")] if output_cap else [])
    nets = {
        "GND": [_pin("U1", "1", "GND", "power_in"), _pin("C1", "2", "~", "passive")],
        "-12V": [_pin("U1", "2", "IN", "power_in"), _pin("C1", "1", "~", "passive")],
        out_net: [_pin("U1", "3", "OUT", "power_out")],
    }
    if output_cap:
        nets["GND"].append(_pin("C2", "2", "~", "passive"))
        nets[out_net].append(_pin("C2", "1", "~", "passive"))
    for part, net, pin in extra:
        comps.append(part)
        nets[net].append(pin)
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

    def test_vss_is_a_supply_rail_not_ground(self):
        self.assertEqual(self.ctx.vss_supply_rails, {"VSS"})
        self.assertEqual(vss_supply_rail_nets(self.ctx), {"VSS"})
        self.assertFalse(self.ctx.is_ground("VSS"))
        self.assertTrue(self.ctx.is_power_net("VSS"))

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

    def test_its_capacitor_is_decoupling_on_the_vss_rail(self):
        rails = {d["rail"]: d for d in detect_decoupling(self.ctx)}
        self.assertIn("VSS", rails)
        self.assertEqual([c["ref"] for c in rails["VSS"]["capacitors"]], ["C2"])

    def test_a_missing_output_capacitor_is_reported(self):
        ctx = _negative_ldo(output_cap=False)
        regs = detect_power_regulators(ctx, [])
        results = {"power_regulators": regs, "decoupling_analysis": detect_decoupling(ctx)}
        obs = [o for o in detect_design_observations(ctx, results)
               if o["category"] == "regulator_caps"]
        self.assertEqual([o["missing_caps"] for o in obs], [{"output": "VSS"}])

    def test_vss_supply_without_a_power_symbol_is_a_power_net_with_decoupling(self):
        # AVSS is a power name only by its regulator: no power symbol sits on it.
        comps = [_part("U1", "ic", "TPS72325", "Regulator_Linear:TPS72325",
                       [("1", "GND"), ("2", "IN"), ("5", "OUT")]),
                 _part("U2", "ic", "ADS1299", "Analog_ADC:ADS1299", [("1", "AVDD"), ("2", "AVSS")]),
                 _cap("C1")]
        nets = {"GNDA": [_pin("U1", "1", "GND", "power_in"), _pin("C1", "2", "~", "passive")],
                "-RAW": [_pin("U1", "2", "IN", "power_in")],
                "AVSS": [_pin("U1", "5", "OUT", "power_out"), _pin("U2", "2", "AVSS", "power_in"),
                         _pin("C1", "1", "~", "passive")],
                "+2V5": [_pin("U2", "1", "AVDD", "power_in")]}
        ctx = _ctx(comps, nets, {"GNDA", "-RAW", "+2V5"})
        self.assertEqual(ctx.vss_supply_rails, {"AVSS"})
        self.assertTrue(ctx.is_power_net("AVSS"))
        rails = {d["rail"]: d for d in detect_decoupling(ctx)}
        self.assertEqual([c["ref"] for c in rails["AVSS"]["capacitors"]], ["C1"])

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

    def test_vss_carrying_a_ground_symbol_stays_ground_though_a_regulator_drives_it(self):
        # A GND symbol on the VSS net joins it to the board ground: it is 0 V whatever
        # drives it, and every part on it keeps its ground.
        gnd = _part("#PWR01", "power_symbol", "GND", "power:GND", [("1", "GND")])
        ctx = _negative_ldo(extra=[(gnd, "VSS", _pin("#PWR01", "1", "GND", "power_in"))])
        self.assertEqual(ctx.vss_supply_rails, frozenset())
        self.assertTrue(ctx.is_ground("VSS"))

    def test_a_vss_symbol_is_no_ground_symbol(self):
        vss = _part("#PWR01", "power_symbol", "VSS", "power:VSS", [("1", "VSS")])
        ctx = _negative_ldo(extra=[(vss, "VSS", _pin("#PWR01", "1", "VSS", "power_in"))])
        self.assertEqual(ctx.vss_supply_rails, {"VSS"})

    def test_single_output_isolated_converter_return_stays_ground(self):
        # -Vout of a converter with no common pin is its output's own return (a gate
        # driver's VSSA); the -Vin input return on GND is not its reference.
        comps = [_part("U1", "ic", "TBA2-2413", "Converter_DCDC:TBA2-2413",
                       [("1", "+Vin"), ("2", "-Vin"), ("4", "-Vout"), ("6", "+Vout")])]
        nets = {"+24V": [_pin("U1", "1", "+Vin", "power_in")],
                "GND": [_pin("U1", "2", "-Vin", "power_in")],
                "VSSA": [_pin("U1", "4", "-Vout", "power_out")],
                "VDDA": [_pin("U1", "6", "+Vout", "power_out")]}
        ctx = _ctx(comps, nets, {"+24V", "GND", "VSSA", "VDDA"})
        self.assertEqual(ctx.vss_supply_rails, frozenset())
        self.assertTrue(ctx.is_ground("VSSA"))

    def test_single_output_module_with_a_gnd_named_input_return_stays_ground(self):
        # The input return named GND is not the output's common: -Vout is still the
        # output's own return.
        comps = [_part("U1", "ic", "MOD", "Custom:MOD",
                       [("1", "+Vin"), ("2", "GND"), ("4", "-Vout"), ("6", "+Vout")])]
        nets = {"+24V": [_pin("U1", "1", "+Vin", "power_in")],
                "GND": [_pin("U1", "2", "GND", "power_in")],
                "VSSA": [_pin("U1", "4", "-Vout", "power_out")],
                "VDDA": [_pin("U1", "6", "+Vout", "power_out")]}
        ctx = _ctx(comps, nets, {"+24V", "GND", "VSSA", "VDDA"})
        self.assertEqual(ctx.vss_supply_rails, frozenset())
        self.assertTrue(ctx.is_ground("VSSA"))

    def test_charge_pump_negative_output_beside_its_ground_is_a_supply(self):
        # One negative output and no positive one: the part's GND is its reference.
        comps = [_part("U1", "ic", "LT1054", "Custom:LT1054",
                       [("1", "VIN"), ("2", "GND"), ("3", "-VOUT")])]
        nets = {"+5V": [_pin("U1", "1", "VIN", "power_in")],
                "GND": [_pin("U1", "2", "GND", "power_in")],
                "VSS": [_pin("U1", "3", "-VOUT", "power_out")]}
        ctx = _ctx(comps, nets, {"+5V", "GND", "VSS"})
        self.assertEqual(ctx.vss_supply_rails, {"VSS"})

    def test_power_out_without_another_ground_does_not_make_a_supply(self):
        # no reference ground on the part: nothing says VSS sits away from its ground
        comps = [_part("U1", "ic", "REG", "R:R", [("1", "OUT"), ("2", "IN")])]
        nets = {"VSS": [_pin("U1", "1", "OUT", "power_out")],
                "+5V": [_pin("U1", "2", "IN", "power_in")]}
        self.assertEqual(_ctx(comps, nets, {"VSS", "+5V"}).vss_supply_rails, frozenset())


class DualOutputConverter(unittest.TestCase):
    def test_negative_output_beside_a_common_pin_is_a_supply(self):
        # A +/-15 V isolated converter: -Vout sits below its 0V common on GND.
        comps = [_part("PS1", "ic", "IA0515D", "Converter_DCDC:IA0515D",
                       [("1", "-Vin"), ("3", "+Vin"), ("4", "-Vout"), ("5", "+Vout"),
                        ("6", "0V")])]
        nets = {"GND": [_pin("PS1", "1", "-Vin", "power_in"), _pin("PS1", "6", "0V", "power_out")],
                "+5V": [_pin("PS1", "3", "+Vin", "power_in")],
                "VSS": [_pin("PS1", "4", "-Vout", "power_out")],
                "VCC": [_pin("PS1", "5", "+Vout", "power_out")]}
        ctx = _ctx(comps, nets, {"GND", "+5V", "VSS", "VCC"})
        self.assertEqual(ctx.vss_supply_rails, {"VSS"})
        self.assertFalse(ctx.is_ground("VSS"))


class ConfiguredVss(unittest.TestCase):
    def test_a_negative_override_makes_a_vss_net_a_supply(self):
        comps = [_part("U1", "ic", "ADC", "A:A", [("1", "AVDD"), ("2", "VSSA")])]
        nets = {"+5V": [_pin("U1", "1", "AVDD", "power_in")],
                "VSSA": [_pin("U1", "2", "VSSA", "power_in")]}
        ctx = _ctx(comps, nets, {"+5V", "VSSA"}, {"voltage_overrides": {"VSSA": -5}})
        self.assertEqual(ctx.vss_supply_rails, {"VSSA"})
        self.assertFalse(ctx.is_ground("VSSA"))
        self.assertEqual(build_rail_map(ctx, [])["VSSA"], -5)

    def test_a_zero_override_keeps_it_ground(self):
        comps = [_part("U1", "ic", "ADC", "A:A", [("1", "AVDD"), ("2", "VSS")])]
        nets = {"+5V": [_pin("U1", "1", "AVDD", "power_in")],
                "VSS": [_pin("U1", "2", "VSS", "power_in")]}
        ctx = _ctx(comps, nets, {"+5V", "VSS"}, {"voltage_overrides": {"VSS": 0}})
        self.assertEqual(ctx.vss_supply_rails, frozenset())
        self.assertTrue(ctx.is_ground("VSS"))


class GroundByEvidence(unittest.TestCase):
    def test_rail_map_gives_com_and_spice_ground_zero(self):
        # An isolated converter's COM return and the SPICE ground 0 are ground by what sits
        # on them, not by name; the rail map lists both at 0 V. AVSS stays out: it can name
        # a negative supply.
        comps = [_part("U1", "ic", "MGJ2", "Converter_DCDC:MGJ2",
                       [("1", "VIN+"), ("2", "VIN-"), ("5", "VOUT-"), ("6", "COM"), ("7", "VOUT+")]),
                 _part("U2", "ic", "ADC", "Analog_ADC:ADC", [("1", "AVSS")]),
                 _part("#GND01", "power_symbol", "0", "Simulation_SPICE:0", [("1", "~")]),
                 _cap("C1"), _cap("C2"), _cap("C3")]
        nets = {
            "COM": [_pin("U1", "6", "COM", "power_out"), _pin("C1", "2", "~", "passive"),
                    _pin("C2", "2", "~", "passive")],
            "+VCC": [_pin("U1", "7", "VOUT+", "power_out"), _pin("C1", "1", "~", "passive")],
            "-VEE": [_pin("U1", "5", "VOUT-", "power_out"), _pin("C2", "1", "~", "passive")],
            "0": [_pin("#GND01", "1", "~", "power_in"), _pin("C3", "2", "~", "passive")],
            "IN": [_pin("C3", "1", "~", "passive")],
            "AVSS": [_pin("U2", "1", "AVSS", "power_in")],
        }
        full = {n: {"name": n, "pins": ps, "point_count": 0, "no_connect": False,
                    "has_pwr_flag": False, "labels": []} for n, ps in nets.items()}
        ctx = build_analysis_context(comps, full, {}, source="test")
        by_net = build_rail_map(ctx, [])
        self.assertEqual(by_net["COM"], 0)
        self.assertEqual(by_net["0"], 0)
        self.assertNotIn("AVSS", by_net)
        self.assertNotIn("IN", by_net)


class EsdGapOnAZeroVoltNet(unittest.TestCase):
    """The ESD gap check reads nets by name; the schematic's 0 V rail entry tells it a net
    named otherwise (the SPICE ground 0, a board ground a label renames) is ground."""

    def _gaps(self, pin_nets, rail_voltages):
        nets = {}
        for pin, net in pin_nets.items():
            nets.setdefault(net, {"pins": []})["pins"].append(
                {"component": "J1", "pin_number": pin, "pin_type": "passive"})
        sch = {"components": [{"reference": "J1", "type": "connector",
                               "value": "Screw_Terminal_01x03",
                               "lib_id": "Connector:Screw_Terminal_01x03", "pin_nets": pin_nets}],
               "nets": nets, "findings": [], "rail_voltages": rail_voltages}
        return [f["nets"] for f in cross_analysis.check_esd_coverage_gaps(sch, None)]

    def test_zero_volt_net_is_not_an_unprotected_signal(self):
        self.assertEqual(self._gaps({"1": "IN", "2": "0"}, {"0": 0}), [["IN"]])

    def test_sheet_net_matches_its_uuid_stripped_entry(self):
        self.assertEqual(self._gaps({"1": "IN", "2": "/2bafda84-de20-41a8-97b9-3c9a21aaa27c/RET"},
                                    {"RET": 0}), [["IN"]])

    def test_net_without_a_zero_volt_entry_is_still_a_signal(self):
        self.assertEqual(self._gaps({"1": "IN", "2": "0"}, {"0": None, "IN": 3.3}), [["IN", "0"]])


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
