"""VM-001 reads a part's logic level from its supplies, not from its first rail by pin order.

- A named I/O supply (IOVDD, VDDIO, VCCIO3, VCCO_34, VL, ...) sets the level a part is judged at.
- A peer at any positive voltage the part is seen to take is not a crossing.
- A part on a negative rail only, or whose I/O supply rail has no known voltage, is not judged.
- An FPGA bank drawn as its own unit, with its own VCCIO pin, is judged at that VCCIO.
- A module's VIN / VBAT / VBUS-class input feeds its regulator: it is not the module's I/O level.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import validation_detectors as vd  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402


def ctx_of(parts, rails, units=None):
    """*parts*: ``{ref: (value, [(number, pin_name, pin_type, net), ...])}``.
    *units*: ``{ref: [(unit, {pin numbers}), ...]}`` places *ref* once per unit."""
    nets: dict[str, dict] = {}
    comps = []
    for ref, (value, pins) in parts.items():
        for number, name, pin_type, net in pins:
            nets.setdefault(net, {"name": net, "pins": [], "point_count": 0, "no_connect": False,
                                  "has_pwr_flag": False, "labels": []})["pins"].append(
                dict(component=ref, pin_number=number, pin_name=name, pin_type=pin_type))
        placements = (units or {}).get(ref) or [(1, None)]
        for unit, numbers in placements:
            comp = {"reference": ref, "type": "ic", "value": value, "lib_id": "", "footprint": "",
                    "unit": unit,
                    "pins": [{"number": n, "name": pn, "type": t} for n, pn, t, _ in pins
                             if numbers is None or n in numbers]}
            if numbers is not None:
                comp["_unit_pins"] = set(numbers)
            comps.append(comp)
    return build_analysis_context(comps, nets, {}, known_power_rails=set(rails))


def vm001(ctx):
    with patch.object(vd, "get_regulator_features", return_value=None):
        return [f for f in vd.validate_voltage_levels(ctx) if f["rule_id"] == "VM-001"]


def crossing(f):
    """``"5.0V / 3.3V"`` from a VM-001 summary."""
    return f["summary"].split(": ", 1)[1].split(" domain")[0]


GND = ("9", "GND", "power_in", "GND")


class SupplyLevels(unittest.TestCase):

    def test_single_supply_crossing_stays(self):
        ctx = ctx_of({"U1": ("A5V", [("1", "VCC", "power_in", "+5V"), ("2", "OUT", "output", "SIG"), GND]),
                      "U2": ("B3V3", [("1", "VDD", "power_in", "+3V3"), ("2", "IN", "input", "SIG"), GND])},
                     {"+5V", "+3V3", "GND"})
        (f,) = vm001(ctx)
        self.assertEqual(crossing(f), "5.0V / 3.3V")

    def test_legacy_symbol_all_inputs_keeps_its_finding(self):
        ctx = ctx_of({"U1": ("A5V", [("1", "VCC", "input", "+5V"), ("2", "OUT", "input", "SIG"),
                                     ("9", "GND", "input", "GND")]),
                      "U2": ("B3V3", [("1", "VDD", "input", "+3V3"), ("2", "IN", "input", "SIG"),
                                      ("9", "GND", "input", "GND")])},
                     {"+5V", "+3V3", "GND"})
        (f,) = vm001(ctx)
        self.assertEqual(crossing(f), "5.0V / 3.3V")

    def test_second_supply_at_the_peer_level_is_silent(self):
        a = [("1", "VDD33", "power_in", "+3V3"), ("2", "VDDRGMII", "power_in", "+1V8")]
        b = [("1", "VDDIO", "power_in", "+1V8"), ("2", "VDDCORE", "power_in", "+1V1")]
        for order in (1, -1):
            with self.subTest(order=order):
                ctx = ctx_of({"U1": ("MAC", a[::order] + [("3", "TXD", "output", "SIG"), GND]),
                              "U2": ("PHY", b[::order] + [("3", "RXD", "input", "SIG"), GND])},
                             {"+3V3", "+1V8", "+1V1", "GND"})
                self.assertEqual(vm001(ctx), [])

    def test_io_supply_is_the_reported_level(self):
        ctx = ctx_of({"U1": ("SOC", [("1", "VDD", "power_in", "+3V3"), ("2", "IOVDD", "power_in", "+1V8"),
                                     ("3", "GPIO", "bidirectional", "SIG"), GND]),
                      "U2": ("A5V", [("1", "VCC", "power_in", "+5V"), ("2", "OUT", "output", "SIG"), GND])},
                     {"+5V", "+3V3", "+1V8", "GND"})
        (f,) = vm001(ctx)
        self.assertEqual(crossing(f), "5.0V / 1.8V")

    def test_io_supply_on_an_unnamed_rail_is_not_judged(self):
        ctx = ctx_of({"U1": ("RP2040", [("1", "IOVDD", "power_in", "VCC_MCU"), ("2", "DVDD", "power_in", "MCU_1V1"),
                                        ("3", "GPIO0", "bidirectional", "SIG"), GND]),
                      "U2": ("B3V3", [("1", "VDD", "power_in", "+3V3"), ("2", "OUT", "output", "SIG"), GND])},
                     {"VCC_MCU", "MCU_1V1", "+3V3", "GND"})
        self.assertEqual(vm001(ctx), [])

    def test_bank_unit_is_judged_at_its_own_vccio(self):
        # FS: the per-bank reading adds this finding on purpose.
        fpga = [("1", "VCCIO1", "power_in", "+1V8"), ("2", "IO1", "bidirectional", "SIGA"),
                ("3", "VCCIO2", "power_in", "+3V3"), ("4", "IO2", "bidirectional", "SIGB"), GND]
        ctx = ctx_of({"U1": ("FPGA", fpga),
                      "U2": ("B3V3", [("1", "VDD", "power_in", "+3V3"), ("2", "OA", "output", "SIGA"),
                                      ("3", "OB", "output", "SIGB"), GND])},
                     {"+1V8", "+3V3", "GND"}, units={"U1": [(1, {"1", "2", "9"}), (2, {"3", "4", "9"})]})
        (f,) = vm001(ctx)
        self.assertEqual(f["nets"], ["SIGA"])
        self.assertEqual(crossing(f), "3.3V / 1.8V")

    def test_header_units_of_a_module_are_not_banks(self):
        module = [("1", "5V", "power_out", "+5V"), ("2", "D1", "bidirectional", "SIG"),
                  ("3", "3V3", "power_out", "+3V3"), ("4", "D2", "bidirectional", "SIG2"), GND]
        ctx = ctx_of({"A1": ("MODULE", module),
                      "U2": ("B3V3", [("1", "VDD", "power_in", "+3V3"), ("2", "IN", "input", "SIG"), GND])},
                     {"+5V", "+3V3", "GND"}, units={"A1": [(1, {"1", "2", "9"}), (2, {"3", "4", "9"})]})
        self.assertEqual(vd._ic_logic_domains(ctx, "A1")[2], {})
        self.assertEqual(vm001(ctx), [])

    def test_negative_regulator_enable_is_not_a_domain(self):
        ctx = ctx_of({"U1": ("LM2776", [("1", "VIN", "power_in", "VPP"), ("2", "VOUT", "power_out", "-6V"),
                                        ("3", "EN", "input", "SIG"), GND]),
                      "U2": ("MCU3V3", [("1", "VDD", "power_in", "+3V3"), ("2", "PA0", "output", "SIG"), GND])},
                     {"VPP", "-6V", "+3V3", "GND"})
        self.assertEqual(vm001(ctx), [])
        self.assertIsNone(vd._estimate_rail_voltage_for_ic(ctx, "U1"))

    def test_feedback_pin_on_a_rail_sets_no_level(self):
        ctx = ctx_of({"U1": ("AB1234", [("1", "VIN", "power_in", "VRAW"), ("2", "FB", "input", "V1P1"),
                                        ("3", "EN", "input", "SIG"), GND]),
                      "U2": ("MCU3V3", [("1", "VDD", "power_in", "+3V3"), ("2", "PA0", "output", "SIG"), GND])},
                     {"VRAW", "V1P1", "+3V3", "GND"})
        self.assertEqual(vm001(ctx), [])

    def test_equal_levels_never_cross(self):
        ctx = ctx_of({"U2": ("ADC", [("1", "VDD", "power_in", "+3V3"), ("2", "VBIAS", "input", "+15V"),
                                     ("3", "IN", "input", "SIG"), GND]),
                      "U1": ("OPAMP", [("1", "V+", "power_in", "+15V"), ("2", "OUT", "output", "SIG"), GND])},
                     {"+15V", "+3V3", "GND"})
        self.assertEqual(vm001(ctx), [])

    def test_enable_pin_does_not_steer_the_settle(self):
        # A load switch's enable is filtered out as a compatible endpoint; the two parts left on
        # the net still settle at the level they share.
        ctx = ctx_of({"U2": ("AXP209", [("1", "VCC", "power_in", "+5V"), ("2", "LDO3", "power_out", "+3V3"),
                                        ("3", "GPIO1", "bidirectional", "SIG"), GND]),
                      "U1": ("V3S", [("1", "VCCIO", "power_in", "+3V3"), ("2", "PG1", "bidirectional", "SIG"), GND]),
                      "U3": ("TPS22918", [("1", "VIN", "power_in", "+5V"), ("2", "VOUT", "power_out", "+5V_SW"),
                                          ("3", "ON", "input", "SIG"), GND])},
                     {"+3V3", "+5V", "+5V_SW", "GND"})
        self.assertEqual(vm001(ctx), [])


class ModuleSupplyInputs(unittest.TestCase):
    """A module's VIN feeds its own regulator; its I/O runs from the regulated outputs."""

    NANO = [("1", "VIN", "power_in", "+12V"), ("2", "5V", "power_out", "+5V"),
            ("3", "3V3", "power_out", "+3V3"), ("4", "D10", "bidirectional", "D10"),
            ("5", "D11", "bidirectional", "D11"), GND]

    def test_module_vin_is_not_a_logic_level(self):
        ctx = ctx_of({"A1": ("Arduino_Nano", self.NANO),
                      "U2": ("A5V", [("1", "VCC", "power_in", "+5V"), ("2", "IN", "input", "D10"), GND]),
                      "U3": ("B1V8", [("1", "VDD", "power_in", "+1V8"), ("2", "IN", "input", "D11"), GND])},
                     {"+12V", "+5V", "+3V3", "+1V8", "GND"})
        found = vm001(ctx)
        self.assertEqual([f["nets"] for f in found], [["D11"]])
        self.assertNotIn("12.0V", " ".join(f["summary"] + f["description"] for f in found))

    def test_a_twelve_volt_output_into_the_module_is_still_reported(self):
        ctx = ctx_of({"A1": ("Arduino_Nano", self.NANO),
                      "U2": ("A12V", [("1", "VCC", "power_in", "+12V"), ("2", "OUT", "output", "D10"), GND])},
                     {"+12V", "+5V", "+3V3", "GND"})
        (f,) = vm001(ctx)
        self.assertEqual(crossing(f), "12.0V / 5.0V")

    def test_teensy_vin_is_not_its_io_level(self):
        ctx = ctx_of({"U1": ("Teensy4.1", [("1", "VIN", "power_in", "+5V"), ("2", "3V3", "power_out", "+3V3"),
                                           ("3", "D0", "bidirectional", "SIG"), GND]),
                      "U2": ("A5V", [("1", "VCC", "power_in", "+5V"), ("2", "OUT", "output", "SIG"), GND])},
                     {"+5V", "+3V3", "GND"})
        self.assertEqual(vd._estimate_rail_voltage_for_ic(ctx, "U1"), 3.3)
        (f,) = vm001(ctx)
        self.assertEqual(crossing(f), "5.0V / 3.3V")

    def test_a_part_powered_only_from_vin_keeps_that_level(self):
        ctx = ctx_of({"U1": ("SENSOR", [("1", "VIN", "power_in", "+5V"), ("2", "OUT", "output", "SIG"), GND]),
                      "U2": ("B3V3", [("1", "VDD", "power_in", "+3V3"), ("2", "IN", "input", "SIG"), GND])},
                     {"+5V", "+3V3", "GND"})
        self.assertEqual(vd._estimate_rail_voltage_for_ic(ctx, "U1"), 5.0)
        (f,) = vm001(ctx)
        self.assertEqual(crossing(f), "5.0V / 3.3V")

    def test_untyped_module_reads_its_named_rail(self):
        # Every pin passive (a hand-drawn dev-board symbol): the 3V3 pin names the I/O rail.
        board = [("1", "VIN", "passive", "+5V"), ("2", "3V3", "passive", "+3V3"),
                 ("3", "IO4", "passive", "SIG"), ("9", "GND", "passive", "GND")]
        ctx = ctx_of({"U1": ("ESP32_DEVKIT", board),
                      "U2": ("A5V", [("1", "VCC", "power_in", "+5V"), ("2", "OUT", "output", "SIG"), GND])},
                     {"+5V", "+3V3", "GND"})
        self.assertEqual(vd._estimate_rail_voltage_for_ic(ctx, "U1"), 3.3)
        (f,) = vm001(ctx)
        self.assertEqual(crossing(f), "5.0V / 3.3V")

    def test_untyped_part_with_a_power_out_pin_drops_vin(self):
        switch = [("1", "VOUT", "power_out", "+3V3_SW"), ("4", "EN", "input", "EN"),
                  ("5", "VIN", "input", "+3V3")]
        ctx = ctx_of({"U1": ("LOADSW", switch + [("2", "GND", "input", "GND")])}, {"+3V3", "+3V3_SW", "GND"})
        self.assertEqual([r[1] for r in vd._rail_pins(ctx, "U1")], ["VOUT"])

    def test_strap_on_an_untyped_symbol_is_not_a_second_supply(self):
        # The radio's EN is strapped to +5V; its I/O still runs from VBAT.
        radio = [("15", "VBAT", "unspecified", "+3V3"), ("3", "EN", "unspecified", "+5V"),
                 ("5", "DIO1", "unspecified", "SIG"), ("2", "GND", "unspecified", "GND")]
        ctx = ctx_of({"U2": ("RADIO", radio),
                      "U1": ("MCU3V3", [("1", "VDD", "power_in", "+3V3"), ("2", "PA0", "output", "SIG"), GND])},
                     {"+3V3", "+5V", "GND"})
        self.assertEqual(vm001(ctx), [])

    def test_sense_pin_of_an_untyped_symbol_is_not_a_second_supply(self):
        # A boost LED driver's over-voltage sense pin sits on its 13 V output; CTRL is VIN-referenced.
        driver = [("6", "VIN", "input", "+5V"), ("5", "OV", "input", "+13V"),
                  ("4", "CTRL", "input", "BL_PWM"), ("2", "GND", "input", "GND")]
        ctx = ctx_of({"U15": ("AP3032", driver),
                      "U1": ("MCU3V3", [("1", "VDD", "power_in", "+3V3"), ("2", "PB3", "output", "BL_PWM"), GND])},
                     {"+5V", "+13V", "+3V3", "GND"})
        self.assertEqual(vd._estimate_rail_voltage_for_ic(ctx, "U15"), 5.0)
        self.assertNotIn("13.0V", " ".join(f["summary"] for f in vm001(ctx)))

    def test_supply_input_names(self):
        for name in ("VIN", "VIN1", "VIN_IN", "VBAT", "VBAT2", "VUSB", "VBUS", "VBUS_IN", "VSYS"):
            with self.subTest(name=name):
                self.assertTrue(vd._SUPPLY_INPUT_PIN.fullmatch(vd._compact_pin_name(name)))
        for name in ("VDD", "VCC", "VIO", "VOUT"):
            with self.subTest(name=name):
                self.assertFalse(vd._SUPPLY_INPUT_PIN.fullmatch(vd._compact_pin_name(name)))


class UnitlessParts(unittest.TestCase):

    def test_part_without_a_unit_gets_no_per_unit_levels(self):
        # A sub-sheet read alone has no unit for its placements: each holds every pin.
        fpga = [("1", "VCCIO1", "power_in", "+1V8"), ("2", "IO1", "bidirectional", "SIGA"),
                ("3", "VCCIO2", "power_in", "+3V3"), ("4", "IO2", "bidirectional", "SIGB"), GND]
        peer = ("B3V3", [("1", "VDD", "power_in", "+3V3"), ("2", "OA", "output", "SIGA"), GND])
        for placements in ([(None, {"1", "2", "3", "4", "9"}), (None, {"1", "2", "3", "4", "9"})],
                           [(None, {"1", "2", "3", "4", "9"}), (2, {"3", "4", "9"})],
                           [(None, None), (None, None)]):
            with self.subTest(placements=placements):
                ctx = ctx_of({"U1": ("FPGA", fpga), "U2": peer}, {"+1V8", "+3V3", "GND"},
                             units={"U1": placements})
                self.assertEqual(vd._ic_logic_domains(ctx, "U1")[2], {})
                vm001(ctx)


if __name__ == "__main__":
    unittest.main()
