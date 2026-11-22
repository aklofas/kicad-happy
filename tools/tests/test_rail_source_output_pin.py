"""An IC or reference-diode output pin sources the rail it drives; a load switch's output
and an output pin named like a supply input (a symbol typing error) do not."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import audit_rail_sources  # noqa: E402


def _unsourced(comps, pins):
    """RS-001 nets for *pins* = {net: [(ref, number, name, type), ...]}."""
    nets = {n: {"name": n, "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": [],
                "pins": [dict(component=r, pin_number=num, pin_name=name, pin_type=t)
                         for r, num, name, t in ps]}
            for n, ps in pins.items()}
    ctx = build_analysis_context(comps, nets, {})
    return sorted(f["nets"][0] for f in audit_rail_sources(ctx) if f["rule_id"] == "RS-001")


def _rules(comps, pins, jumper=None):
    """[(rule_id, first net)] for every rail-source finding."""
    nets = {n: {"name": n, "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": [],
                "pins": [dict(component=r, pin_number=num, pin_name=name, pin_type=t)
                         for r, num, name, t in ps]}
            for n, ps in pins.items()}
    ctx = build_analysis_context(comps, nets, {})
    sj = [{"reference": "JP6", "default_state": jumper[0], "nets": list(jumper[1])}] if jumper else None
    return sorted((f["rule_id"], f["nets"][0]) for f in audit_rail_sources(ctx, solder_jumpers=sj))


def _jumper(state):
    return {"reference": "JP6", "type": "jumper", "value": f"SolderJumper_2_{state}",
            "lib_id": f"Jumper:SolderJumper_2_{state}"}


def _part(ref, typ, value, lib_id=""):
    return {"reference": ref, "type": typ, "value": value, "lib_id": lib_id}


_LOAD = ("U2", "1", "VDD", "power_in")
_GND = {"GND": [("U2", "2", "GND", "power_in")]}


class OutputPinSource(unittest.TestCase):
    def test_reference_diode_output_sources_its_rail(self):
        comps = [_part("D1", "diode", "LM4040"), _part("U2", "ic", "ADC")]
        self.assertEqual(_unsourced(comps, {"+2V5": [("D1", "1", "K", "output"), _LOAD], **_GND}), [])

    def test_ic_output_pin_sources_its_rail(self):
        comps = [_part("U1", "ic", "W5500"), _part("U2", "ic", "MCU")]
        self.assertEqual(_unsourced(comps, {"+1V2": [("U1", "10", "1V2O", "output"), _LOAD], **_GND}), [])

    def test_output_pin_named_like_a_supply_input_is_not_a_source(self):
        comps = [_part("U1", "ic", "CH340G"), _part("U2", "ic", "MCU")]
        for name in ("VCC", "VDD", "AVDD", "VDDIO", "VCC_IO", "VCCQ2", "VIO", "VIN", "IN", "VS"):
            self.assertEqual(_unsourced(comps, {"+3V3": [("U1", "1", name, "output"), _LOAD], **_GND}),
                             ["+3V3"], name)

    def test_output_pin_of_a_connector_or_resistor_is_not_a_source(self):
        comps = [_part("J1", "connector", "Conn"), _part("R1", "resistor", "10k"), _part("U2", "ic", "MCU")]
        self.assertEqual(_unsourced(comps, {"+5V": [("J1", "1", "OUT", "output"), _LOAD],
                                            "+12V": [("R1", "1", "OUT", "output"),
                                                     ("U2", "3", "VCC", "power_in")], **_GND}),
                         ["+12V", "+5V"])

    def test_load_switch_output_with_an_unsourced_input_is_not_a_source(self):
        comps = [_part("U1", "ic", "MT9700", "Power_Management:MT9700"), _part("U2", "ic", "MCU")]
        self.assertEqual(_unsourced(comps, {"+5V": [("U1", "1", "VIN", "power_in")],
                                            "+5V_SW": [("U1", "2", "VOUT", "output"), _LOAD],
                                            "GND": [("U1", "3", "GND", "power_in"),
                                                    ("U2", "2", "GND", "power_in")]}),
                         ["+5V", "+5V_SW"])


class StrapAndJumperSources(unittest.TestCase):
    def test_strap_named_output_tied_to_a_rail_is_not_its_source(self):
        comps = [_part("U1", "ic", "BNO086"), _part("U2", "ic", "MCU")]
        for name in ("XOUT32/CLKSEL1", "EN", "OE", "~{CLR}", "~{RESET}", "LATCH", "SEL1", "CLKOUT",
                     "PGFB", "*OD", "VSENSE", "FLG1", "~{OVRCUR1}", "~DIS", "COM", "COM1", "~{COM}", "~COM"):
            self.assertEqual(_unsourced(comps, {"+3V3": [("U1", "1", name, "output"), _LOAD], **_GND}),
                             ["+3V3"], name)

    def test_output_with_com_inside_a_longer_name_still_sources_the_rail(self):
        comps = [_part("U1", "ic", "REG"), _part("U2", "ic", "MCU")]
        for name in ("VOUT_COM", "V_COM", "OUT_COM", "COM_1"):
            self.assertEqual(_unsourced(comps, {"+3V3": [("U1", "1", name, "output"), _LOAD], **_GND}),
                             [], name)

    def test_strap_named_output_on_a_signal_net_still_sources_it(self):
        comps = [_part("U1", "ic", "74HC00"), _part("U2", "ic", "MCU")]
        self.assertEqual(_unsourced(comps, {"SUP": [("U1", "1", "NRST", "output"), _LOAD], **_GND}), [])

    def test_ordinary_output_on_a_rail_still_sources_it(self):
        comps = [_part("U1", "ic", "W5500"), _part("U2", "ic", "MCU")]
        self.assertEqual(_unsourced(comps, {"+3V3": [("U1", "1", "3V3OUT", "output"), _LOAD], **_GND}), [])

    def test_data_output_on_a_rail_that_feeds_a_supply_pin_is_not_its_source(self):
        comps = [_part("U1", "ic", "BMI160"), _part("U2", "ic", "MCU")]
        for name in ("SDO", "SDI", "SO", "ASCX"):
            self.assertEqual(_unsourced(comps, {"+3V3": [("U1", "1", name, "output"), _LOAD], **_GND}),
                             ["+3V3"], name)

    def test_logic_output_behind_an_open_jumper_is_no_supply(self):
        comps = [_part("U1", "ic", "74HC00"), _part("U3", "ic", "MCU"), _jumper("Open")]
        pins = {"VCC": [("U3", "1", "VCC", "power_in"), ("JP6", "1", "A", "passive")],
                "__unnamed_3": [("U1", "3", "Y", "output"), ("JP6", "2", "B", "passive")], **_GND}
        self.assertEqual(_rules(comps, pins, ("open", ("VCC", "__unnamed_3"))), [("RS-001", "VCC")])

    def test_power_output_behind_an_open_jumper_is_still_rs002(self):
        comps = [_part("U1", "ic", "LDO"), _part("U3", "ic", "MCU"), _jumper("Open")]
        pins = {"VCC": [("U3", "1", "VCC", "power_in"), ("JP6", "1", "A", "passive")],
                "__unnamed_3": [("U1", "3", "VOUT", "power_out"), ("JP6", "2", "B", "passive")], **_GND}
        self.assertEqual(_rules(comps, pins, ("open", ("VCC", "__unnamed_3"))), [("RS-002", "VCC")])

    def test_output_behind_a_bridged_jumper_is_still_rs003(self):
        comps = [_part("U1", "ic", "LM358"), _part("U3", "ic", "MCU"), _jumper("Bridged")]
        pins = {"VCC": [("U3", "1", "VCC", "power_in"), ("JP6", "1", "A", "passive")],
                "__unnamed_3": [("U1", "1", "OUT", "output"), ("JP6", "2", "B", "passive")], **_GND}
        self.assertEqual(_rules(comps, pins, ("bridged", ("VCC", "__unnamed_3"))), [("RS-003", "VCC")])

    def test_rail_with_a_strap_output_is_sourced_through_a_bridged_jumper(self):
        comps = [_part("U1", "ic", "USB3343"), _part("U2", "ic", "REG"), _part("U3", "ic", "MCU"),
                 _jumper("Bridged")]
        pins = {"ULIP_VDDIO": [("U1", "1", "CLKOUT", "output"), ("U3", "1", "VDDIO", "power_in"),
                               ("JP6", "1", "A", "passive")],
                "VOUT": [("U2", "1", "VOUT", "power_out"), ("JP6", "2", "B", "passive")], **_GND}
        self.assertEqual(_rules(comps, pins, ("bridged", ("ULIP_VDDIO", "VOUT"))), [("RS-003", "ULIP_VDDIO")])


if __name__ == "__main__":
    unittest.main()
