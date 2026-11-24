"""A single-supply SN74LVC or SN74AVC buffer is not a level shifter.

TI SN74LVC1G11 (SCES214, rev. AA): inputs and outputs tolerate 5.5 V at any VCC.
TI SN74AVC16244 (SCES135, rev. K): single VCC, 3.6 V-tolerant inputs. A dual-supply part
(VCCA / VCCB) and a part whose input is pulled above its own VCC still translate.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import domain_detectors as dd  # noqa: E402
import validation_detectors as vd  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402

GND = ("9", "GND", "power_in", "GND")


def ctx_of(parts, rails, pull_ups=()):
    """*parts*: ``{ref: (value, lib_id, [(number, pin_name, pin_type, net), ...])}``.
    *pull_ups*: ``(ref, signal net, rail)`` resistors."""
    nets: dict[str, dict] = {}
    comps = []

    def add(ref, number, name, pin_type, net):
        nets.setdefault(net, {"name": net, "pins": [], "point_count": 0, "no_connect": False,
                              "has_pwr_flag": False, "labels": []})["pins"].append(
            dict(component=ref, pin_number=number, pin_name=name, pin_type=pin_type))

    for ref, (value, lib_id, pins) in parts.items():
        for number, name, pin_type, net in pins:
            add(ref, number, name, pin_type, net)
        comps.append({"reference": ref, "type": "ic", "value": value, "lib_id": lib_id,
                      "footprint": "", "unit": 1,
                      "pins": [{"number": n, "name": pn, "type": t} for n, pn, t, _ in pins]})
    for ref, net, rail in pull_ups:
        add(ref, "1", "1", "passive", net)
        add(ref, "2", "2", "passive", rail)
        comps.append({"reference": ref, "type": "resistor", "value": "10k", "lib_id": "Device:R",
                      "footprint": "", "unit": 1,
                      "pins": [{"number": "1", "name": "1", "type": "passive"},
                               {"number": "2", "name": "2", "type": "passive"}]})
    return build_analysis_context(comps, nets, {}, known_power_rails=set(rails))


def buffer(value, vcc_net="+3V3", lib_id="", extra=()):
    return (value, lib_id, [("1", "A", "input", "IN"), ("2", "Y", "output", "OUT"),
                            ("3", "VCC", "power_in", vcc_net), GND, *extra])


def shifters(ctx):
    return [r for r in dd.detect_level_shifters(ctx) if r["type"] == "level_shifter_ic"]


def vm001(ctx, level_shifters=None):
    with patch.object(vd, "get_regulator_features", return_value=None):
        return [f for f in vd.validate_voltage_levels(ctx, level_shifters or [])
                if f["rule_id"] == "VM-001"]


RAILS = {"+5V", "+3V3", "+1V8", "GND"}


class SingleSupplyLvc(unittest.TestCase):

    def test_single_supply_sn74lvc_is_not_a_level_shifter(self):
        ctx = ctx_of({"U1": buffer("SN74LVC125")}, RAILS)
        self.assertEqual(shifters(ctx), [])

    def test_single_supply_sn74avc_is_not_a_level_shifter(self):
        ctx = ctx_of({"U1": buffer("SN74AVC16244")}, RAILS)
        self.assertEqual(shifters(ctx), [])

    def test_dual_supply_sn74lvc_stays(self):
        ctx = ctx_of({"U1": ("SN74LVC8T245", "", [
            ("1", "VCCA", "power_in", "+1V8"), ("2", "VCCB", "power_in", "+3V3"),
            ("3", "A1", "bidirectional", "IN"), ("4", "B1", "bidirectional", "OUT"), GND])}, RAILS)
        self.assertEqual(len(shifters(ctx)), 1)

    def test_dual_supply_with_decorated_supply_pin_names_stays(self):
        ctx = ctx_of({"U1": ("SN74LVC245A", "", [
            ("1", "V_{CCA}", "power_in", "+5V"), ("2", "VCCB(3V)", "power_in", "+3V3"),
            ("3", "A1", "bidirectional", "IN"), ("4", "B1", "bidirectional", "OUT"), GND])}, RAILS)
        self.assertEqual(len(shifters(ctx)), 1)

    def test_translating_part_number_stays_without_supply_pins(self):
        ctx = ctx_of({"U1": ("SN74LVC4245A", "", [
            ("3", "A1", "bidirectional", "IN"), ("4", "B1", "bidirectional", "OUT"), GND])}, RAILS)
        self.assertEqual(len(shifters(ctx)), 1)

    def test_lv1t126_on_an_lvc_symbol_stays_a_shifter(self):
        ctx = ctx_of({"U1": buffer("SN74LV1T126", lib_id="Logic:SN74LVC1G125DBV")}, RAILS)
        self.assertEqual(len(shifters(ctx)), 1)

    def test_empty_value_reads_the_lib_id(self):
        ctx = ctx_of({"U1": buffer("", lib_id="Logic:SN74LVC1G17DBV")}, RAILS)
        self.assertEqual(shifters(ctx), [])

    def test_lvc_with_an_input_pulled_above_vcc_stays_a_shifter(self):
        ctx = ctx_of({"U1": buffer("SN74LVC1G11", vcc_net="+1V8")}, RAILS,
                     pull_ups=[("R1", "IN", "+3V3")])
        self.assertEqual(len(shifters(ctx)), 1)

    def test_input_pulled_to_its_own_vcc_does_not_keep_it(self):
        ctx = ctx_of({"U1": buffer("SN74LVC1G11")}, RAILS, pull_ups=[("R1", "IN", "+3V3")])
        self.assertEqual(shifters(ctx), [])

    def test_its_nets_stay_exempt_from_vm001(self):
        ctx = ctx_of({
            "U1": ("MCU5V", "", [("1", "VDD", "power_in", "+5V"), ("2", "IO", "output", "IN"), GND]),
            "U2": buffer("SN74LVC125"),
            "U3": ("MCU3V3", "", [("1", "VDD", "power_in", "+3V3"), ("2", "IO", "input", "OUT"),
                                  GND]),
        }, RAILS)
        self.assertEqual(shifters(ctx), [])
        self.assertEqual(vm001(ctx, shifters(ctx)), [])


if __name__ == "__main__":
    unittest.main()
