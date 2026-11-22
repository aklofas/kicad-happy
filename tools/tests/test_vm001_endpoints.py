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


def vm001(ctx):
    with patch.object(vd, "get_regulator_features", return_value=None):
        return [f for f in vd.validate_voltage_levels(ctx) if f["rule_id"] == "VM-001"]


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


if __name__ == "__main__":
    unittest.main()
