# tools/tests/test_bus_cs_can_i2c.py
"""SPI chip-select conflicts count slave CS inputs only; CAN termination is judged per bus with
one protocol result per bus; an I2C line slower than Standard mode is not reported as Standard."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
from detector_helpers import can_line  # noqa: E402
from schematic.net_analysis import (  # noqa: E402
    _analyze_bus_protocols, _detect_can_buses, _detect_differential_pairs, _detect_i2c_buses)
from schematic.system_analyses import analyze_protocol_compliance  # noqa: E402
from validation_detectors import validate_can_bus  # noqa: E402


def _comp(ref, ctype, value, lib_id, pins=()):
    return {"reference": ref, "type": ctype, "value": value, "lib_id": lib_id,
            "pins": [{"number": n, "name": nm, "type": t} for n, nm, t in pins]}


def _res(ref, value):
    return _comp(ref, "resistor", value, "Device:R", [("1", "~", "passive"), ("2", "~", "passive")])


def _ctx(components, nets):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "labels": []}
            for n, pins in nets.items()}
    return build_analysis_context(components, full, {}, known_power_rails={"+3V3", "GND"})


MCU = _comp("U1", "ic", "STM32F103C8Tx", "MCU_ST_STM32F1:STM32F103C8Tx",
            [("1", "PA4", "bidirectional"), ("2", "PA5", "bidirectional"), ("3", "PA6", "bidirectional"),
             ("4", "PA7", "bidirectional"), ("5", "PB0", "bidirectional")])


def _flash(ref):
    return _comp(ref, "ic", "W25Q128JVS", "Memory_Flash:W25Q128JVS",
                 [("1", "~{CS}", "input"), ("2", "DO", "output"), ("5", "DI", "input"), ("6", "CLK", "input")])


def _spi_nets(cs_nets, flashes):
    """MCU SPI1 to the given flashes; ``cs_nets`` maps a CS net to (ref, pin, name, type) rows."""
    nets = {"SCK": [("U1", "2", "PA5", "bidirectional")] + [(f, "6", "CLK", "input") for f in flashes],
            "MISO": [("U1", "3", "PA6", "bidirectional")] + [(f, "2", "DO", "output") for f in flashes],
            "MOSI": [("U1", "4", "PA7", "bidirectional")] + [(f, "5", "DI", "input") for f in flashes]}
    nets.update(cs_nets)
    return nets


def _spi(components, nets):
    buses = _analyze_bus_protocols(_ctx(components, nets))["spi"]
    return next(b for b in buses if "SCK" in b["signals"])


class SpiChipSelect(unittest.TestCase):
    def test_controller_and_one_flash_on_a_cs_net_is_not_a_conflict(self):
        nets = _spi_nets({"FLASH_CS": [("U1", "1", "PA4", "bidirectional"), ("U2", "1", "~{CS}", "input")]},
                         ["U2"])
        spi = _spi([MCU, _flash("U2")], nets)
        self.assertEqual(spi["chip_select_count"], 1)
        self.assertNotIn("cs_conflicts", spi)

    def test_two_flashes_on_one_cs_net_conflict(self):
        nets = _spi_nets({"CS0": [("U1", "1", "PA4", "bidirectional"), ("U3", "1", "~{CS}", "input"),
                                  ("U2", "1", "~{CS}", "input")]}, ["U2", "U3"])
        spi = _spi([MCU, _flash("U2"), _flash("U3")], nets)
        self.assertEqual([c["devices"] for c in spi["cs_conflicts"]], [["U2", "U3"]])
        self.assertEqual(spi["cs_conflicts"][0]["net"], "CS0")

    def test_vss_and_ssp_clock_names_are_not_chip_selects(self):
        dac = _comp("U4", "ic", "MCP4921", "Analog_DAC:MCP4921",
                    [("1", "VSS", "input"), ("2", "SCK", "input")])
        adc = _comp("U5", "ic", "MCP3201", "Analog_ADC:MCP3201",
                    [("1", "VSS", "input"), ("2", "SCK", "input")])
        nets = _spi_nets({"FLASH_CS": [("U1", "1", "PA4", "bidirectional"), ("U2", "1", "~{CS}", "input")],
                          "DAC_VSS": [("U4", "1", "VSS", "input"), ("U5", "1", "VSS", "input")],
                          "SSP1_SCK": [("U4", "2", "SCK", "input"), ("U5", "2", "SCK", "input")]},
                         ["U2"])
        spi = _spi([MCU, _flash("U2"), dac, adc], nets)
        self.assertEqual(spi["chip_select_count"], 1)
        self.assertNotIn("cs_conflicts", spi)

    def test_one_part_with_two_cs_pins_is_listed_once(self):
        dual = _comp("U6", "ic", "DUAL_CS_PART", "custom:DUAL",
                     [("1", "CS1", "input"), ("2", "CS2", "input")])
        nets = _spi_nets({"CS": [("U1", "1", "PA4", "bidirectional"), ("U6", "1", "CS1", "input"),
                                 ("U6", "2", "CS2", "input"), ("U2", "1", "~{CS}", "input")]}, ["U2"])
        spi = _spi([MCU, _flash("U2"), dual], nets)
        self.assertEqual([c["devices"] for c in spi["cs_conflicts"]], [["U2", "U6"]])


    def test_latch_and_load_inputs_on_a_cs_net_are_not_slaves(self):
        # 74HC595 RCLK and MAX7219 LOAD are latch inputs, not chip selects.
        sr = _comp("U6", "ic", "74HC595", "74xx:74HC595", [("1", "RCLK", "input")])
        led = _comp("U7", "ic", "MAX7219", "Driver_LED:MAX7219", [("1", "LOAD", "input")])
        nets = _spi_nets({"LATCH_CS": [("U1", "1", "PA4", "bidirectional"), ("U6", "1", "RCLK", "input"),
                                       ("U7", "1", "LOAD", "input")]}, [])
        spi = _spi([MCU, sr, led], nets)
        self.assertNotIn("cs_conflicts", spi)

    def test_select_named_pins_still_conflict_beside_a_latch(self):
        sr = _comp("U6", "ic", "74HC595", "74xx:74HC595", [("1", "RCLK", "input")])
        nets = _spi_nets({"CS0": [("U1", "1", "PA4", "bidirectional"), ("U6", "1", "RCLK", "input"),
                                  ("U2", "1", "~{CS}", "input"), ("U3", "1", "~{CS}", "input")]},
                         ["U2", "U3"])
        spi = _spi([MCU, sr, _flash("U2"), _flash("U3")], nets)
        self.assertEqual([c["devices"] for c in spi["cs_conflicts"]], [["U2", "U3"]])

    def test_soft_start_net_is_not_a_chip_select(self):
        reg1 = _comp("U6", "ic", "TPS54331", "Regulator_Switching:TPS54331", [("1", "SS/TR", "passive")])
        reg2 = _comp("U7", "ic", "AP62600", "Regulator_Switching:AP62600", [("1", "SS", "power_in")])
        nets = _spi_nets({"FLASH_CS": [("U1", "1", "PA4", "bidirectional"), ("U2", "1", "~{CS}", "input")],
                          "CS_SS": [("U6", "1", "SS/TR", "passive"), ("U7", "1", "SS", "power_in")]},
                         ["U2"])
        spi = _spi([MCU, _flash("U2"), reg1, reg2], nets)
        self.assertEqual(spi["chip_select_count"], 1)

    def test_master_select_pin_typed_output_stays_a_chip_select(self):
        ft = _comp("U6", "ic", "FT4222H", "Interface_USB:FT4222H", [("1", "SS", "output")])
        nets = _spi_nets({"CS_N": [("U6", "1", "SS", "output"), ("U2", "1", "~{CS}", "input")]}, ["U2"])
        spi = _spi([MCU, _flash("U2"), ft], nets)
        self.assertEqual(spi["chip_select_count"], 1)
        self.assertNotIn("cs_conflicts", spi)


CAN_XCVR = [("1", "TXD", "input"), ("4", "RXD", "output"), ("7", "CANH", "bidirectional"),
            ("6", "CANL", "bidirectional")]


def _can_findings(components, nets):
    ctx = _ctx(components, nets)
    can = _detect_can_buses(ctx)
    da = {"bus_analysis": {"can": can}, "differential_pairs": _detect_differential_pairs(ctx)}
    pc = analyze_protocol_compliance(components, ctx.nets, da, {}, ctx.pin_net, ctx=ctx)
    return ({e["net"]: e["termination"] for e in can},
            [f for f in pc.get("findings", []) if f["protocol"] == "can"])


class CanTerminationPerBus(unittest.TestCase):
    def test_each_bus_gets_its_own_terminator(self):
        x1 = _comp("U7", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)
        x2 = _comp("U8", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)
        nets = {"CANH1": [("U7", "7", "CANH", "bidirectional"), ("R1", "1", "~", "passive")],
                "CANL1": [("U7", "6", "CANL", "bidirectional"), ("R1", "2", "~", "passive")],
                "CANH2": [("U8", "7", "CANH", "bidirectional")],
                "CANL2": [("U8", "6", "CANL", "bidirectional")]}
        term, findings = _can_findings([x1, x2, _res("R1", "120")], nets)
        self.assertEqual(term, {"CANH1": "120Ω (R1)", "CANL1": "120Ω (R1)",
                                "CANH2": None, "CANL2": None})
        self.assertEqual(len(findings), 2)
        by_nets = {tuple(f["nets"]): f for f in findings}
        self.assertTrue(by_nets[("CANH1", "CANL1")]["has_termination"])
        self.assertIsNone(by_nets[("CANH1", "CANL1")]["issues"])
        self.assertFalse(by_nets[("CANH2", "CANL2")]["has_termination"])
        self.assertIsNone(by_nets[("CANH2", "CANL2")]["issues"])
        self.assertEqual(by_nets[("CANH2", "CANL2")]["observations"],
                         ["No CAN termination found on this board (a bus-end node needs 120Ω)"])

    def test_single_bus_logic_side_nets_keep_the_value_and_get_no_finding(self):
        x1 = _comp("U7", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)
        nets = {"CAN_H": [("U7", "7", "CANH", "bidirectional"), ("R1", "1", "~", "passive")],
                "CAN_L": [("U7", "6", "CANL", "bidirectional"), ("R1", "2", "~", "passive")],
                "CAN_TX": [("U1", "1", "PA4", "bidirectional"), ("U7", "1", "TXD", "input")],
                "CAN_RX": [("U1", "2", "PA5", "bidirectional"), ("U7", "4", "RXD", "output")]}
        term, findings = _can_findings([MCU, x1, _res("R1", "120")], nets)
        self.assertEqual(set(term.values()), {"120Ω (R1)"})
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["nets"], ["CAN_H", "CAN_L"])
        self.assertTrue(findings[0]["has_termination"])

    def test_lone_resistor_side_can_net_gets_no_finding(self):
        # CAN_L_RES1 has no CANH partner and is one of two CANL candidates: its bus is ambiguous.
        x1 = _comp("U7", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)
        nets = {"CAN_H1": [("U7", "7", "CANH", "bidirectional")],
                "CAN_L1": [("U7", "6", "CANL", "bidirectional"), ("R2", "1", "~", "passive")],
                "CAN_L_RES1": [("R2", "2", "~", "passive")]}
        term, findings = _can_findings([x1, _res("R2", "120")], nets)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["nets"], ["CAN_H1", "CAN_L1"])


    def test_bus_only_as_a_diff_pair_beside_tx_rx_is_still_judged(self):
        x1 = _comp("U7", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)
        nets = {"CAN_P": [("U7", "7", "CANH", "bidirectional")],
                "CAN_N": [("U7", "6", "CANL", "bidirectional")],
                "CAN_TX": [("U1", "1", "PA4", "bidirectional"), ("U7", "1", "TXD", "input")],
                "CAN_RX": [("U1", "2", "PA5", "bidirectional"), ("U7", "4", "RXD", "output")]}
        _, findings = _can_findings([MCU, x1], nets)
        self.assertEqual([(f["nets"], f["issues"], f["observations"]) for f in findings],
                         [(["CAN_P", "CAN_N"], None,
                           ["No CAN termination found on this board (a bus-end node needs 120Ω)"])])

    def test_dnp_terminator_on_a_diff_pair_is_an_unfitted_option(self):
        # A placed-but-DNP 120 ohm is the per-node option (only the bus-end nodes fit it)
        x1 = _comp("U7", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)
        nets = {"CAN_P": [("U7", "7", "CANH", "bidirectional"), ("R1", "1", "~", "passive")],
                "CAN_N": [("U7", "6", "CANL", "bidirectional"), ("R1", "2", "~", "passive")]}
        _, findings = _can_findings([x1, dict(_res("R1", "120"), dnp=True)], nets)
        self.assertEqual(len(findings), 1)
        self.assertFalse(findings[0]["has_termination"])
        self.assertIsNone(findings[0]["issues"])
        self.assertEqual(findings[0]["observations"],
                         ["CAN termination R1 (120) is DNP (fit it on the bus-end nodes)"])

    def test_dnp_terminator_on_a_named_pair_is_an_unfitted_option(self):
        x1 = _comp("U7", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)
        nets = {"CAN_H": [("U7", "7", "CANH", "bidirectional"), ("R1", "1", "~", "passive")],
                "CAN_L": [("U7", "6", "CANL", "bidirectional"), ("R1", "2", "~", "passive")]}
        term, findings = _can_findings([x1, dict(_res("R1", "120"), dnp=True)], nets)
        self.assertEqual(term, {"CAN_H": None, "CAN_L": None})
        self.assertFalse(findings[0]["has_termination"])
        self.assertIsNone(findings[0]["issues"])
        self.assertEqual(findings[0]["observations"],
                         ["CAN termination R1 (120) is DNP (fit it on the bus-end nodes)"])

    def test_dnp_terminator_observation_names_its_own_value(self):
        # A DNP 60 ohm across a CAN differential pair is not a 120 ohm terminator.
        x1 = _comp("U7", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)
        nets = {"CAN_P": [("U7", "7", "CANH", "bidirectional"), ("R1", "1", "~", "passive")],
                "CAN_N": [("U7", "6", "CANL", "bidirectional"), ("R1", "2", "~", "passive")]}
        _, findings = _can_findings([x1, dict(_res("R1", "60"), dnp=True)], nets)
        self.assertEqual(findings[0]["observations"],
                         ["CAN termination R1 (60) is DNP (fit it on the bus-end nodes)"])

    def test_bias_resistor_across_the_pair_is_not_a_terminator(self):
        x1 = _comp("U7", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)
        nets = {"CAN_P": [("U7", "7", "CANH", "bidirectional"), ("R1", "1", "~", "passive")],
                "CAN_N": [("U7", "6", "CANL", "bidirectional"), ("R1", "2", "~", "passive")]}
        _, findings = _can_findings([x1, _res("R1", "100k")], nets)
        self.assertFalse(findings[0]["has_termination"])

    def test_unparsed_value_across_the_pair_is_not_a_terminator(self):
        x1 = _comp("U7", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)
        nets = {"CAN_P": [("U7", "7", "CANH", "bidirectional"), ("R1", "1", "~", "passive")],
                "CAN_N": [("U7", "6", "CANL", "bidirectional"), ("R1", "2", "~", "passive")]}
        _, findings = _can_findings([x1, _res("R1", "see note")], nets)
        self.assertFalse(findings[0]["has_termination"])

    def test_unannotated_resistors_are_read_by_their_own_value(self):
        x1 = _comp("U7", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)
        nets = {"CAN_P": [("U7", "7", "CANH", "bidirectional")] + [("R?", "1", "~", "passive")] * 2,
                "CAN_N": [("U7", "6", "CANL", "bidirectional")] + [("R?", "2", "~", "passive")] * 2}
        _, findings = _can_findings([x1, _res("R?", "120"), _res("R?", "100k")], nets)
        self.assertTrue(findings[0]["has_termination"])
        pair = _detect_differential_pairs(_ctx([x1, _res("R?", "120"), _res("R?", "100k")], nets))[0]
        self.assertEqual([(t["value"], t["ohms"]) for t in pair["termination"]], [("120", 120.0)])

    def test_fitted_beside_dnp_terminator_is_present(self):
        x1 = _comp("U7", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)
        for h, l in (("CAN_H", "CAN_L"), ("CAN_P", "CAN_N")):
            nets = {h: [("U7", "7", "CANH", "bidirectional"), ("R1", "1", "~", "passive"),
                        ("R2", "1", "~", "passive")],
                    l: [("U7", "6", "CANL", "bidirectional"), ("R1", "2", "~", "passive"),
                        ("R2", "2", "~", "passive")]}
            _, findings = _can_findings([x1, dict(_res("R1", "120"), dnp=True), _res("R2", "120")], nets)
            self.assertEqual(len(findings), 1, h)
            self.assertTrue(findings[0]["has_termination"], h)
            self.assertIsNone(findings[0]["issues"], h)
            self.assertEqual(findings[0]["observations"],
                             ["CAN 120\u03a9 termination present (verify remote end has matching termination)"], h)


def _cap(ref, value="100n"):
    return _comp(ref, "capacitor", value, "Device:C", [("1", "~", "passive"), ("2", "~", "passive")])


def _can_nets(extra=None, mid_pins=(("R1", "2", "~", "passive"), ("R2", "2", "~", "passive"),
                                    ("C1", "1", "~", "passive"))):
    nets = {"CAN_H": [("U7", "7", "CANH", "bidirectional"), ("R1", "1", "~", "passive")],
            "CAN_L": [("U7", "6", "CANL", "bidirectional"), ("R2", "1", "~", "passive")],
            "SPLIT_MID": list(mid_pins),
            "GND": [("C1", "2", "~", "passive")]}
    nets.update(extra or {})
    return nets


def _pr003(components, nets):
    ctx = _ctx(components, nets)
    return [f for f in validate_can_bus(ctx) if f["rule_id"] == "PR-003"]


class CanSplitTermination(unittest.TestCase):
    """Split termination: two 60 ohm resistors from the bus lines to a decoupled midpoint
    (NXP TJA1042 data sheet, Rev. 12, section 7.3.1 on p. 7 and Figure 4 on p. 8, which draws
    two 60 ohm resistors from CANH and CANL to the SPLIT pin of the transceiver)."""

    def _xcvr(self):
        return _comp("U7", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)

    def test_two_60_ohm_resistors_to_a_decoupled_midpoint_are_a_termination(self):
        comps = [self._xcvr(), _res("R1", "60"), _res("R2", "60"), _cap("C1")]
        term, findings = _can_findings(comps, _can_nets())
        self.assertEqual(term, {"CAN_H": "120\u03a9 split (R1+R2)", "CAN_L": "120\u03a9 split (R1+R2)"})
        self.assertTrue(findings[0]["has_termination"])
        self.assertIsNone(findings[0]["issues"])
        self.assertEqual(_pr003(comps, _can_nets()), [])

    def test_midpoint_on_the_transceiver_split_pin_is_still_split(self):
        split = _comp("U7", "ic", "TJA1042T", "Interface_CAN_LIN:TJA1042T",
                      CAN_XCVR + [("5", "SPLIT", "output")])
        nets = _can_nets(mid_pins=(("R1", "2", "~", "passive"), ("R2", "2", "~", "passive"),
                                   ("C1", "1", "~", "passive"), ("U7", "5", "SPLIT", "output")))
        comps = [split, _res("R1", "62"), _res("R2", "62"), _cap("C1", "4.7n")]
        term, _ = _can_findings(comps, nets)
        self.assertEqual(term["CAN_H"], "124\u03a9 split (R1+R2)")
        self.assertEqual(_pr003(comps, nets), [])

    def test_60_ohm_resistors_to_ground_are_not_split(self):
        nets = {"CAN_H": [("U7", "7", "CANH", "bidirectional"), ("R1", "1", "~", "passive")],
                "CAN_L": [("U7", "6", "CANL", "bidirectional"), ("R2", "1", "~", "passive")],
                "GND": [("R1", "2", "~", "passive"), ("R2", "2", "~", "passive")]}
        comps = [self._xcvr(), _res("R1", "60"), _res("R2", "60")]
        term, _ = _can_findings(comps, nets)
        self.assertEqual(term, {"CAN_H": None, "CAN_L": None})
        self.assertEqual(len(_pr003(comps, nets)), 1)

    def test_midpoint_with_a_bias_resistor_is_not_split(self):
        nets = _can_nets(mid_pins=(("R1", "2", "~", "passive"), ("R2", "2", "~", "passive"),
                                   ("R3", "1", "~", "passive")),
                         extra={"+3V3": [("R3", "2", "~", "passive")]})
        comps = [self._xcvr(), _res("R1", "60"), _res("R2", "60"), _res("R3", "1k")]
        term, _ = _can_findings(comps, nets)
        self.assertEqual(term, {"CAN_H": None, "CAN_L": None})

    def test_midpoint_with_a_choke_pin_is_not_split(self):
        choke = _comp("L1", "inductor", "CMC", "Device:L_Coupled", [("1", "1", "passive")])
        nets = _can_nets(mid_pins=(("R1", "2", "~", "passive"), ("R2", "2", "~", "passive"),
                                   ("L1", "1", "1", "passive")))
        comps = [self._xcvr(), _res("R1", "60"), _res("R2", "60"), choke]
        term, _ = _can_findings(comps, nets)
        self.assertEqual(term, {"CAN_H": None, "CAN_L": None})

    def test_unfitted_split_is_an_option_not_a_termination(self):
        comps = [self._xcvr(), dict(_res("R1", "60"), dnp=True), _res("R2", "60"), _cap("C1")]
        term, findings = _can_findings(comps, _can_nets())
        self.assertEqual(term, {"CAN_H": None, "CAN_L": None})
        self.assertEqual(findings[0]["observations"],
                         ["CAN termination R1 (60) is DNP (fit it on the bus-end nodes)"])
        (f,) = _pr003(comps, _can_nets())
        self.assertIn("R1 is placed but not fitted", f["description"])

    def test_reference_pin_of_another_part_on_the_midpoint_is_not_split(self):
        adc = _comp("U9", "ic", "ADS1115", "Analog_ADC:ADS1115", [("1", "REF", "input")])
        nets = _can_nets(mid_pins=(("R1", "2", "~", "passive"), ("R2", "2", "~", "passive"),
                                   ("C1", "1", "~", "passive"), ("U9", "1", "REF", "input")))
        comps = [self._xcvr(), _res("R1", "60"), _res("R2", "60"), _cap("C1"), adc]
        term, _ = _can_findings(comps, nets)
        self.assertEqual(term, {"CAN_H": None, "CAN_L": None})

    def test_dnp_pair_is_reported_unfitted_not_as_termination(self):
        comps = [self._xcvr(), dict(_res("R1", "60"), dnp=True), dict(_res("R2", "60"), dnp=True),
                 _cap("C1")]
        ctx = _ctx(comps, _can_nets())
        entries = _detect_can_buses(ctx)
        self.assertTrue(all(e["termination"] is None and e["termination_dnp"] == "R1" for e in entries))

    def test_fitted_pair_wins_over_an_unfitted_pair_on_the_same_lines(self):
        nets = _can_nets(extra={"MID2": [("R3", "2", "~", "passive"), ("R4", "2", "~", "passive")],
                                "CAN_H": [("U7", "7", "CANH", "bidirectional"), ("R3", "1", "~", "passive"),
                                          ("R1", "1", "~", "passive")],
                                "CAN_L": [("U7", "6", "CANL", "bidirectional"), ("R4", "1", "~", "passive"),
                                          ("R2", "1", "~", "passive")]})
        comps = [self._xcvr(), _res("R1", "60"), _res("R2", "60"), _cap("C1"),
                 dict(_res("R3", "60"), dnp=True), dict(_res("R4", "60"), dnp=True)]
        term, _ = _can_findings(comps, nets)
        self.assertEqual(term["CAN_H"], "120\u03a9 split (R1+R2)")

    def test_fitted_120_ohm_keeps_its_value(self):
        nets = {"CAN_H": [("U7", "7", "CANH", "bidirectional"), ("R1", "1", "~", "passive")],
                "CAN_L": [("U7", "6", "CANL", "bidirectional"), ("R1", "2", "~", "passive")]}
        comps = [self._xcvr(), _res("R1", "120")]
        term, _ = _can_findings(comps, nets)
        self.assertEqual(term["CAN_H"], "120\u03a9 (R1)")
        self.assertEqual(_pr003(comps, nets), [])


class CanNumberedLineNames(unittest.TestCase):
    def test_numbered_names_are_bus_lines(self):
        for name, side in (("CAN1_H", "H"), ("CAN1_L", "L"), ("CAN1H", "H"), ("CAN_2_L", "L"),
                           ("MCU1_CAN2_H+", "H"), ("MCAN0_L-", "L"), ("CANH", "H"), ("CAN_H", "H"),
                           ("CAN_HIGH", "H"), ("CANL", "L")):
            self.assertTrue(can_line(name, side), name)
            self.assertFalse(can_line(name, "L" if side == "H" else "H"), name)

    def test_other_can_signals_are_not_bus_lines(self):
        for name in ("CAN1_HS", "CAN0_LED", "CAN2_LOAD", "CAN_TX", "CAN1_TX"):
            self.assertFalse(can_line(name, "H"), name)
            self.assertFalse(can_line(name, "L"), name)

    def test_names_that_only_end_in_a_can_word_are_not_bus_lines(self):
        for name in ("SCAN1_H", "JTAG_SCAN3_L", "ISCAN2_H", "TCAN1_L"):
            self.assertFalse(can_line(name, "H") or can_line(name, "L"), name)

    def test_fdcan_peripheral_names_are_bus_lines(self):
        self.assertTrue(can_line("FDCAN1_H", "H"))
        self.assertTrue(can_line("FDCAN1_L", "L"))
        self.assertFalse(can_line("SCAN1_H", "H"))

    def test_high_and_low_words_after_a_bus_number_are_bus_lines(self):
        self.assertTrue(can_line("CAN1_HIGH", "H"))
        self.assertTrue(can_line("CAN1_LOW", "L"))
        self.assertFalse(can_line("CAN1_HIGH", "L"))

    def test_polarity_suffixed_numbered_buses_are_paired(self):
        x1 = _comp("U7", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)
        x2 = _comp("U8", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)
        nets = {"CAN1_H+": [("U7", "7", "CANH", "bidirectional"), ("R1", "1", "~", "passive")],
                "CAN1_L-": [("U7", "6", "CANL", "bidirectional"), ("R1", "2", "~", "passive")],
                "CAN2_H+": [("U8", "7", "CANH", "bidirectional")],
                "CAN2_L-": [("U8", "6", "CANL", "bidirectional")]}
        term, findings = _can_findings([x1, x2, _res("R1", "120")], nets)
        self.assertEqual(term["CAN1_H+"], "120Ω (R1)")
        self.assertEqual(term["CAN1_L-"], "120Ω (R1)")
        self.assertIsNone(term["CAN2_H+"])
        self.assertEqual(sorted(tuple(f["nets"]) for f in findings),
                         [("CAN1_H+", "CAN1_L-"), ("CAN2_H+", "CAN2_L-")])

    def test_numbered_pair_is_one_bus_with_its_terminator(self):
        x1 = _comp("U7", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)
        nets = {"CAN1_H": [("U7", "7", "CANH", "bidirectional"), ("R1", "1", "~", "passive")],
                "CAN1_L": [("U7", "6", "CANL", "bidirectional"), ("R1", "2", "~", "passive")],
                "CAN0_LED": [("U1", "1", "PA4", "bidirectional")]}
        term, findings = _can_findings([MCU, x1, _res("R1", "120")], nets)
        self.assertEqual(term["CAN1_H"], "120Ω (R1)")
        self.assertEqual(term["CAN1_L"], "120Ω (R1)")
        self.assertNotIn("CAN0_LED", term)
        self.assertEqual([f["nets"] for f in findings], [["CAN1_H", "CAN1_L"]])

    def test_two_numbered_buses_are_paired_by_number(self):
        x1 = _comp("U7", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)
        x2 = _comp("U8", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)
        nets = {"CAN1_H": [("U7", "7", "CANH", "bidirectional"), ("R1", "1", "~", "passive")],
                "CAN1_L": [("U7", "6", "CANL", "bidirectional"), ("R1", "2", "~", "passive")],
                "CAN2_H": [("U8", "7", "CANH", "bidirectional")],
                "CAN2_L": [("U8", "6", "CANL", "bidirectional")]}
        term, findings = _can_findings([x1, x2, _res("R1", "120")], nets)
        self.assertEqual(term, {"CAN1_H": "120Ω (R1)", "CAN1_L": "120Ω (R1)",
                                "CAN2_H": None, "CAN2_L": None})
        self.assertEqual(sorted(tuple(f["nets"]) for f in findings),
                         [("CAN1_H", "CAN1_L"), ("CAN2_H", "CAN2_L")])


class CanTransceiverOnUnnamedNets(unittest.TestCase):
    def _xcvr(self, ref="U7"):
        return _comp(ref, "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)

    def _nets(self, extra=()):
        nets = {"Net-(U7-Pad7)": [("U7", "7", "CANH", "bidirectional"), ("R1", "1", "~", "passive")],
                "Net-(U7-Pad6)": [("U7", "6", "CANL", "bidirectional"), ("R1", "2", "~", "passive")]}
        nets.update(dict(extra))
        return nets

    def test_terminator_between_the_transceiver_pin_nets_is_read(self):
        term, findings = _can_findings([self._xcvr(), _res("R1", "120")], self._nets())
        self.assertEqual(term, {"CAN": "120Ω (R1)"})
        self.assertEqual([(f["nets"], f["has_termination"], f["issues"]) for f in findings],
                         [(["Net-(U7-Pad7)", "Net-(U7-Pad6)"], True, None)])

    def test_split_termination_on_the_pin_nets_is_read(self):
        nets = self._nets({"MID": [("R2", "2", "~", "passive"), ("R3", "2", "~", "passive"),
                                   ("C1", "1", "~", "passive")],
                           "GND": [("C1", "2", "~", "passive")]})
        nets["Net-(U7-Pad7)"] = [("U7", "7", "CANH", "bidirectional"), ("R2", "1", "~", "passive")]
        nets["Net-(U7-Pad6)"] = [("U7", "6", "CANL", "bidirectional"), ("R3", "1", "~", "passive")]
        comps = [self._xcvr(), _res("R2", "60"), _res("R3", "60"), _cap("C1")]
        term, findings = _can_findings(comps, nets)
        self.assertEqual(term, {"CAN": "120Ω split (R2+R3)"})
        self.assertTrue(findings[0]["has_termination"])

    def test_unterminated_transceiver_names_its_own_pin_nets(self):
        nets = {"Net-(U7-Pad7)": [("U7", "7", "CANH", "bidirectional"), ("J1", "1", "1", "passive")],
                "Net-(U7-Pad6)": [("U7", "6", "CANL", "bidirectional"), ("J1", "2", "2", "passive")]}
        term, findings = _can_findings([self._xcvr()], nets)
        self.assertEqual(term, {"CAN": None})
        self.assertEqual([f["nets"] for f in findings], [["Net-(U7-Pad7)", "Net-(U7-Pad6)"]])
        self.assertFalse(findings[0]["has_termination"])

    def test_two_transceivers_on_one_pair_share_one_bus(self):
        nets = self._nets({"Net-(U7-Pad7)": [("U7", "7", "CANH", "bidirectional"),
                                             ("U8", "7", "CANH", "bidirectional"),
                                             ("R1", "1", "~", "passive")],
                           "Net-(U7-Pad6)": [("U7", "6", "CANL", "bidirectional"),
                                             ("U8", "6", "CANL", "bidirectional"),
                                             ("R1", "2", "~", "passive")]})
        term, findings = _can_findings([self._xcvr(), self._xcvr("U8"), _res("R1", "120")], nets)
        self.assertEqual(term, {"CAN": "120Ω (R1)"})
        self.assertEqual(len(findings), 1)

    def test_two_transceivers_on_two_pairs_are_two_buses(self):
        nets = self._nets({"Net-(U8-Pad7)": [("U8", "7", "CANH", "bidirectional"), ("J2", "1", "1", "passive")],
                           "Net-(U8-Pad6)": [("U8", "6", "CANL", "bidirectional"), ("J2", "2", "2", "passive")]})
        _, findings = _can_findings([self._xcvr(), self._xcvr("U8"), _res("R1", "120")], nets)
        by_nets = {tuple(f["nets"]): f["has_termination"] for f in findings}
        self.assertEqual(by_nets, {("Net-(U7-Pad7)", "Net-(U7-Pad6)"): True,
                                   ("Net-(U8-Pad7)", "Net-(U8-Pad6)"): False})

    def test_each_transceiver_on_its_own_terminated_pair_is_judged(self):
        # the pin nets are a differential pair named by polarity only, with a terminator each
        nets = {"CANA+": [("U7", "7", "CANH", "bidirectional"), ("R1", "1", "~", "passive")],
                "CANA-": [("U7", "6", "CANL", "bidirectional"), ("R1", "2", "~", "passive")],
                "CANB+": [("U8", "7", "CANH", "bidirectional"), ("R2", "1", "~", "passive")],
                "CANB-": [("U8", "6", "CANL", "bidirectional"), ("R2", "2", "~", "passive")]}
        comps = [self._xcvr(), self._xcvr("U8"), _res("R1", "120"), _res("R2", "120")]
        for order in (comps, comps[::-1]):
            _, findings = _can_findings(order, nets)
            self.assertEqual(sorted((tuple(f["nets"]), f["has_termination"]) for f in findings),
                             [(("CANA+", "CANA-"), True), (("CANB+", "CANB-"), True)])

    def test_unterminated_transceiver_is_not_credited_by_another_pair(self):
        nets = {"CANA+": [("U7", "7", "CANH", "bidirectional"), ("J1", "1", "1", "passive")],
                "CANA-": [("U7", "6", "CANL", "bidirectional"), ("J1", "2", "2", "passive")],
                "CANB+": [("U8", "7", "CANH", "bidirectional"), ("R2", "1", "~", "passive")],
                "CANB-": [("U8", "6", "CANL", "bidirectional"), ("R2", "2", "~", "passive")]}
        _, findings = _can_findings([self._xcvr(), self._xcvr("U8"), _res("R2", "120")], nets)
        self.assertEqual(sorted((tuple(f["nets"]), f["has_termination"]) for f in findings),
                         [(("CANA+", "CANA-"), False), (("CANB+", "CANB-"), True)])

    def test_a_controller_without_bus_pins_is_not_a_second_bus(self):
        ctl = _comp("U2", "ic", "MCP2515-I/SO", "Interface_CAN_LIN:MCP2515-xSO",
                    [("1", "TXCAN", "output"), ("2", "RXCAN", "input")])
        nets = {"Net-(U7-Pad7)": [("U7", "7", "CANH", "bidirectional"), ("J1", "1", "1", "passive")],
                "Net-(U7-Pad6)": [("U7", "6", "CANL", "bidirectional"), ("J1", "2", "2", "passive")],
                "CTL_TXD": [("U2", "1", "TXCAN", "output"), ("U7", "1", "TXD", "input")]}
        for comps in ([ctl, self._xcvr()], [self._xcvr(), ctl]):
            _, findings = _can_findings(comps, nets)
            self.assertEqual([f["nets"] for f in findings], [["Net-(U7-Pad7)", "Net-(U7-Pad6)"]])

    def test_transceiver_bus_pins_that_go_nowhere_are_no_bus(self):
        nets = {"Net-(U7-Pad7)": [("U7", "7", "CANH", "bidirectional")],
                "Net-(U7-Pad6)": [("U7", "6", "CANL", "bidirectional")]}
        ctx = _ctx([self._xcvr()], nets)
        ctx.nets["Net-(U7-Pad7)"]["no_connect"] = True
        ctx.nets["Net-(U7-Pad6)"]["no_connect"] = True
        can = _detect_can_buses(ctx)
        self.assertEqual([(e["net"], e["termination"]) for e in can], [("CAN", None)])
        pc = analyze_protocol_compliance([self._xcvr()], ctx.nets,
                                         {"bus_analysis": {"can": can}, "differential_pairs": []},
                                         {}, ctx.pin_net, ctx=ctx)
        self.assertNotIn("Net-(U7-Pad7)", str(pc))

    def test_a_named_bus_line_keeps_the_bus_by_name(self):
        # a choke between the transceiver and the connector: the pin nets are not a second bus
        nets = self._nets({"CAN_H": [("J1", "1", "1", "passive"), ("L1", "1", "~", "passive")],
                           "CAN_L": [("J1", "2", "2", "passive"), ("L1", "2", "~", "passive")]})
        term, findings = _can_findings([self._xcvr(), _res("R1", "120")], nets)
        self.assertNotIn("CAN", term)
        self.assertEqual([f["nets"] for f in findings], [["CAN_H", "CAN_L"]])


class CanNoTerminatorOnBoard(unittest.TestCase):
    def test_transceiver_without_a_terminator_gets_an_info_note(self):
        nets = {"CAN_H": [("U7", "7", "CANH", "bidirectional")],
                "CAN_L": [("U7", "6", "CANL", "bidirectional")]}
        comps = [_comp("U7", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR)]
        (f,) = _pr003(comps, nets)
        self.assertEqual(f["severity"], "info")
        self.assertEqual(f["summary"], "CAN transceiver U7: no termination found on this board")

    def test_dnp_120_ohm_is_named_and_not_counted_as_fitted(self):
        nets = {"CAN_H": [("U7", "7", "CANH", "bidirectional"), ("R1", "1", "~", "passive")],
                "CAN_L": [("U7", "6", "CANL", "bidirectional"), ("R1", "2", "~", "passive")]}
        comps = [_comp("U7", "ic", "MCP2562", "Interface_CAN_LIN:MCP2562", CAN_XCVR),
                 dict(_res("R1", "120"), dnp=True)]
        (f,) = _pr003(comps, nets)
        self.assertEqual(f["severity"], "info")
        self.assertIn("R1 is placed but not fitted", f["description"])


def _i2c_line(pullup_ohms, n_devices):
    devs = [_comp(f"U{i}", "ic", "TMP102", "Sensor_Temperature:TMP102",
                  [("1", "SDA", "bidirectional"), ("2", "V+", "power_in")]) for i in range(1, n_devices + 1)]
    nets = {"BUS_DATA": [(d["reference"], "1", "SDA", "bidirectional") for d in devs]
            + [("R1", "1", "~", "passive")],
            "+3V3": [("R1", "2", "~", "passive")] + [(d["reference"], "2", "V+", "power_in") for d in devs]}
    lines = _detect_i2c_buses(_ctx(devs + [_res("R1", pullup_ohms)], nets))
    return next(e for e in lines if e["net"] == "BUS_DATA")


class I2cRiseTime(unittest.TestCase):
    def test_rise_past_standard_mode_has_no_mode_and_warns(self):
        # UM10204: tr = 0.8473 * Rp * Cb = 0.8473 * 10k * 150p = 1271 ns > 1000 ns (Standard-mode limit)
        e = _i2c_line("10k", 30)
        self.assertEqual(e["rise_time_ns"], 1271.0)
        self.assertIn("max_speed_mode", e)
        self.assertIsNone(e["max_speed_mode"])
        self.assertEqual(e["rise_time_warning"], "Rise time 1271ns exceeds the Standard-mode limit (1000ns)")

    def test_fast_mode_plus_line_is_unchanged(self):
        # 0.8473 * 4.7k * 20p = 79.6 ns: within Fast-mode+ (120 ns), 34 % margin, no warning
        e = _i2c_line("4.7k", 4)
        self.assertEqual(e["max_speed_mode"], "Fast-mode+")
        self.assertNotIn("rise_time_warning", e)


if __name__ == "__main__":
    unittest.main()
