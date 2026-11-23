"""VM-001 takes a net's level only from the pins that can drive it.

- IRS2304 HIN / LIN are logic inputs with VIH 2.5 V whatever VCC is; an input pin has no output
  stage and cannot put its part's supply level on a net.
- A symbol that types every pin input does not tell its inputs from its outputs: its pins keep
  being read at the part's supply.
- A pull-up to the higher rail puts that level on the net whatever the pins are.
- KiCad 5 libraries type their pins too (the legacy reader maps the .lib codes), so a legacy symbol
  follows the same rule as a KiCad 6+ one.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import validation_detectors as vd  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from schematic.legacy_reader import _parse_legacy_lib  # noqa: E402


def ctx_of(components, nets, rails):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    for c in components:
        c.setdefault("lib_id", "")
        c.setdefault("footprint", "")
        c["pins"] = [{"number": p, "name": pn, "type": t}
                     for pins in nets.values() for r, p, pn, t in pins if r == c["reference"]]
    return build_analysis_context(components, full, {}, known_power_rails=set(rails))


def ic(ref, value):
    return {"reference": ref, "type": "ic", "value": value}


def res(ref):
    return {"reference": ref, "type": "resistor", "value": "10k"}


def vm001(ctx, protection=None):
    with patch.object(vd, "get_regulator_features", return_value=None):
        found = (vd.validate_voltage_levels(ctx, None, protection) if protection
                 else vd.validate_voltage_levels(ctx))
        return [f for f in found if f["rule_id"] == "VM-001"]


def board(high_rail, high_pins, sig_extra=(), parts=(), value="IRS2304", extra_nets=None):
    """U1 (*value*) runs from *high_rail*; U2, a 3.3 V MCU, drives or reads SIG."""
    comps = [ic("U1", value), ic("U2", "MCU3V3"), *parts]
    nets = {high_rail: [("U1", "1", "VCC", "power_in")],
            "+3V3": [("U2", "1", "VDD", "power_in")],
            "GND": [("U1", "2", "GND", "power_in"), ("U2", "2", "GND", "power_in")],
            "SIG": [("U2", "3", "PA0", "bidirectional"), *sig_extra]}
    for number, name, pin_type, net in high_pins:
        nets.setdefault(net, []).append(("U1", number, name, pin_type))
    for n, pins in (extra_nets or {}).items():
        nets.setdefault(n, []).extend(pins)
    return ctx_of(comps, nets, {high_rail, "+3V3", "GND"})


def legacy_pins(symbol, lib_body):
    """Pins of *symbol* as the KiCad 5 reader types them from a .lib definition:
    ``[(number, name, type), ...]``."""
    text = ("EESchema-LIBRARY Version 2.4\n#encoding utf-8\n"
            f"DEF {symbol} U 0 40 Y Y 1 F N\nF0 \"U\" 0 0 50 H V C CNN\nDRAW\n"
            f"{lib_body}ENDDRAW\nENDDEF\n#End Library\n")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "board-cache.lib"
        path.write_text(text, encoding="utf-8")
        sym = _parse_legacy_lib(str(path))[symbol]
    return [(p["number"], p["name"], p["type"]) for p in sym["pins"]]


class DriverPins(unittest.TestCase):
    GATE = [("3", "HIN", "input", "SIG"), ("4", "HO", "output", "HO")]

    def test_logic_input_of_a_higher_domain_is_not_a_driver(self):
        self.assertEqual(vm001(board("+12V", self.GATE)), [])

    def test_output_of_the_higher_domain_is_still_reported(self):
        (f,) = vm001(board("+12V", [("3", "FAULT_OUT", "output", "SIG")]))
        self.assertEqual(f["summary"], "Net SIG: 12.0V / 3.3V domain crossing without level shifter")

    def test_symbol_that_types_every_pin_input_keeps_its_finding(self):
        (f,) = vm001(board("+5V", [("3", "Y1", "input", "SIG"), ("4", "A1", "input", "A1")],
                           value="74HCT125"))
        self.assertEqual(f["summary"], "Net SIG: 5.0V / 3.3V domain crossing without level shifter")

    def test_pull_up_to_the_higher_rail_keeps_the_finding(self):
        ctx = board("+12V", self.GATE, sig_extra=[("R1", "1", "~", "passive")], parts=[res("R1")],
                    extra_nets={"+12V": [("R1", "2", "~", "passive")]})
        (f,) = vm001(ctx)
        self.assertEqual(f["summary"], "Net SIG: 12.0V / 3.3V domain crossing without level shifter")

    def test_pull_up_never_raises_the_level_above_the_endpoints(self):
        # A pull-up to +24V on a 12 V output: the finding names the 12 V level, as before.
        ctx = board("+12V", [("3", "OUT", "output", "SIG")], sig_extra=[("R1", "1", "~", "passive")],
                    parts=[res("R1")], extra_nets={"+24V": [("R1", "2", "~", "passive")]})
        ctx.known_power_rails.add("+24V")
        (f,) = vm001(ctx)
        self.assertEqual(f["summary"], "Net SIG: 12.0V / 3.3V domain crossing without level shifter")

    def test_remaining_driver_names_its_own_level(self):
        ctx = board("+12V", self.GATE, sig_extra=[("U3", "3", "Q", "output")],
                    parts=[ic("U3", "LOGIC5V")], extra_nets={"+5V": [("U3", "1", "VCC", "power_in")]})
        (f,) = vm001(ctx)
        self.assertEqual(f["summary"], "Net SIG: 5.0V / 3.3V domain crossing without level shifter")

    def test_symbol_that_types_only_passive_and_input_pins_keeps_its_finding(self):
        (f,) = vm001(board("+5V", [("3", "Y1", "input", "SIG"), ("4", "A1", "passive", "A1")],
                           value="74HCT125"))
        self.assertEqual(f["summary"], "Net SIG: 5.0V / 3.3V domain crossing without level shifter")

    def test_symbol_typing_only_an_open_collector_pin_counts_as_typing_a_driver(self):
        for kind in ("open_collector", "bidirectional"):
            with self.subTest(kind=kind):
                self.assertEqual(vm001(board("+12V", [("3", "HIN", "input", "SIG"), ("4", "ST", kind, "ST")])), [])

    def test_legacy_symbol_that_types_an_output_follows_the_driver_rule(self):
        pins = legacy_pins("IRS2304", "X VCC 1 -300 200 100 R 50 50 1 1 W\n"
                                      "X HIN 3 -300 0 100 R 50 50 1 1 I\n"
                                      "X HO 4 300 0 100 L 50 50 1 1 O\n")
        self.assertEqual([t for _, _, t in pins], ["power_in", "input", "output"])
        nets = {"1": "+12V", "3": "SIG", "4": "HO"}
        ctx = board("+12V", [(n, name, t, nets[n]) for n, name, t in pins if n != "1"])
        self.assertEqual(vm001(ctx), [])

    def test_legacy_symbol_that_types_every_pin_input_keeps_its_finding(self):
        pins = legacy_pins("74HCT125", "X VCC 14 0 300 100 D 50 50 1 1 W\n"
                                       "X A1 2 -300 0 100 R 50 50 1 1 I\n"
                                       "X Y1 3 300 0 100 L 50 50 1 1 I\n")
        self.assertEqual([t for _, _, t in pins], ["power_in", "input", "input"])
        nets = {"14": "+5V", "2": "A1", "3": "SIG"}
        ctx = board("+5V", [(n, name, t, nets[n]) for n, name, t in pins if n != "14"],
                    value="74HCT125")
        (f,) = vm001(ctx)
        self.assertEqual(f["summary"], "Net SIG: 5.0V / 3.3V domain crossing without level shifter")


class AnalogSwitchPins(unittest.TestCase):
    # One example and its evidence per family of analog_switch regex.
    CITATIONS = {
        "4xxx": (("CD4051B", "4066", "MC14053"),
                 "KiCad 4xxx:4016/4051/4052/4053/4066 'Analog Switches/Multiplexer'; Analog_Switch:CD4051B..CD4097B, HEF4051BT..HEF4067BT"),
        "74HC/HCT/LV": (("74HCT4053D", "CD74HC4067SM96", "74HC4851"),
                        "KiCad 74xx:74HC4051, CD74HC4067M; TI CD74HC405x SCHS122O p. 1; CD74HC4067 SCHS209D p. 1; SN74HC4851 SCLS542C p. 1"),
        "74LVC/AUC single gate": (("74LVC1G3157", "74AUC2G66", "NC7SB3157", "FSA3357L8X"),
                                  "KiCad 74xGxx:74LVC1G3157, 74LVC1G66, 74AUC2G53/2G66; Analog_Switch:NC7SB3157, FSA3157; TI SN74LVC1G3157 SCES424O p. 1; onsemi FSA3357"),
        "TI muxes": (("TMUX4051PWR", "TMUXHS4212IRKSR", "TS5A23166", "TS3A27518E", "TS3USB221RSER", "MUX508"),
                     "TI TMUX405x SCDS445E, TMUXHS4212 SLASEP7A, TS5A23166 SCDS196J, TS3A27518E SCDS260F, TS3USB221 SCDS220M, MUX508/509 SBAS758C, all p. 1"),
        "DG": (("DG442DY-T1-E3", "DG468"),
               "Vishay DG467/DG468 doc. 74413 S12-2269 Rev. D p. 1; DG408/409 doc. 70062 p. 1; KiCad Analog_Switch:DG308..DG9422"),
        "ADG": (("ADG1408YRUZ", "ADG506A"),
                "ADI ADG441/442/444 Rev. B p. 1; ADG506A/507A Rev. C p. 1; KiCad Analog_Switch:ADG1207..ADG884"),
        "MAX": (("MAX306", "MAX314CSE", "MAX4678"),
                "Maxim MAX306/307 19-0270 Rev 5 p. 1; MAX4677-4679 19-1713 Rev 1 p. 1; KiCad Analog_Switch:MAX312..MAX394"),
    }
    NOT_SWITCHES = ("MAX4080", "MAX4466", "MAX4410", "MAX471", "MAX40200AUK", "MAX485", "ADG3304",
                    "74HCT157", "74HC138", "74HC4050", "CD4050", "CD4060", "LTC4053", "XC4016", "LM4051")

    def test_channel_pin_is_not_a_driver_even_on_an_untyped_symbol(self):
        ctx = board("+15V", [("3", "COM", "input", "SIG"), ("4", "NO", "input", "NO")], value="DG468")
        self.assertEqual(vm001(ctx), [])

    def test_channel_pin_is_not_a_driver_even_when_typed_as_an_output(self):
        ctx = board("+15V", [("3", "COM", "output", "SIG"), ("4", "NO", "passive", "NO")], value="DG468")
        self.assertEqual(vm001(ctx), [])

    def test_serial_data_output_of_a_switch_still_drives(self):
        (f,) = vm001(board("+5V", [("3", "SDO", "output", "SIG")], value="ADG1414"))
        self.assertEqual(f["summary"], "Net SIG: 5.0V / 3.3V domain crossing without level shifter")

    def test_higher_level_into_a_switch_is_still_reported(self):
        comps = [ic("U1", "TS5A3159"), ic("U2", "MCU5V")]
        nets = {"+3V3": [("U1", "1", "V+", "power_in")], "+5V": [("U2", "1", "VDD", "power_in")],
                "SIG": [("U1", "3", "IN", "input"), ("U2", "3", "PA0", "output")]}
        (f,) = vm001(ctx_of(comps, nets, {"+3V3", "+5V"}))
        self.assertEqual(f["summary"], "Net SIG: 5.0V / 3.3V domain crossing without level shifter")

    def test_family_names(self):
        from kicad_core.parts import names_analog_switch
        for family, (names, _evidence) in self.CITATIONS.items():
            for name in names:
                self.assertTrue(names_analog_switch(name), f"{family}: {name}")
        for name in self.NOT_SWITCHES:
            self.assertFalse(names_analog_switch(name), name)

    def test_symbol_name_names_the_part(self):
        from kicad_core.parts import names_analog_switch
        self.assertTrue(names_analog_switch("~", "", "DG468"))


class OpenDrainStatus(unittest.TestCase):
    FAULT = [("3", "nFAULT", "output", "SIG"), ("4", "OUT1", "output", "OUT1")]

    def test_fault_flag_with_a_pull_up_is_read_at_the_pull_up_rail(self):
        ctx = board("+12V", self.FAULT, sig_extra=[("R1", "1", "~", "passive")], parts=[res("R1")],
                    extra_nets={"+3V3": [("R1", "2", "~", "passive")]}, value="DRV8873")
        self.assertEqual(vm001(ctx), [])

    def test_fault_flag_without_a_pull_up_keeps_its_supply_level(self):
        (f,) = vm001(board("+12V", self.FAULT, value="DRV8873"))
        self.assertEqual(f["severity"], "error")

    def test_fault_flag_typed_input_with_a_pull_up_keeps_its_supply_level(self):
        ctx = board("+12V", [("3", "nFAULT", "input", "SIG")], sig_extra=[("R1", "1", "~", "passive")],
                    parts=[res("R1")], extra_nets={"+3V3": [("R1", "2", "~", "passive")]},
                    value="DRV8873")
        self.assertEqual(len(vm001(ctx)), 1)

    def test_charger_standby_pin_is_open_drain(self):
        ctx = board("+5V", [("3", "~{STDBY}", "output", "SIG")], sig_extra=[("R1", "1", "~", "passive")],
                    parts=[res("R1")], extra_nets={"+3V3": [("R1", "2", "~", "passive")]}, value="TP4056")
        self.assertEqual(len(vm001(ctx)), 1)             # not known as a charger: read at its supply
        ctx.charger_refs = frozenset({"U1"})
        self.assertEqual(vm001(ctx), [])


class EsdArrays(unittest.TestCase):
    # USBLC6-2 (ST DS2814): the I/O pins are clamp diodes to VBUS and GND; nothing drives them.
    ESD = [{"ref": "U1", "type": "esd_ic"}]

    def test_clamp_pin_of_an_esd_array_is_no_endpoint(self):
        ctx = board("+5V", [("3", "I/O1", "passive", "SIG")], value="USBLC6-2SC6")
        self.assertEqual(len(vm001(ctx)), 1)                 # without the protection record: checked
        self.assertEqual(vm001(ctx, self.ESD), [])

    def test_other_parts_on_the_net_are_still_compared(self):
        ctx = board("+5V", [("3", "I/O1", "passive", "SIG")], value="USBLC6-2SC6",
                    sig_extra=[("U3", "3", "TX", "output")], parts=[ic("U3", "MCU5V")],
                    extra_nets={"+5V": [("U3", "1", "VDD", "power_in")]})
        (f,) = vm001(ctx, self.ESD)
        self.assertEqual(f["components"], ["U2", "U3"])


if __name__ == "__main__":
    unittest.main()
