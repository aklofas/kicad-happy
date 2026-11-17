"""A converter's switch pin named OUT or VOUT (KiCad's LM2596/LM2576/XL1509 symbols, LM2675) drives
the inductor and the catch diode: the output rail is the inductor's far side, not the switch node.
An LDO output that also carries an inductor or a diode keeps its own pin as the output."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from schematic.pipeline import detect_topologies  # noqa: E402


def _part(ref, kind, value, lib_id, pins):
    return {"reference": ref, "type": kind, "value": value, "lib_id": lib_id, "footprint": "",
            "properties": {}, "pins": [{"number": n, "name": nm} for n, nm, _ in pins]}


def _regulator(ic, others, rails):
    """The U1 record of a design made of *ic* and the two-pin *others* ``(ref, kind, value, n1, n2)``."""
    (reg,) = _records(ic, others, rails)
    return reg


def _records(ic, others, rails):
    """Every U1 regulator record of the design (see ``_regulator``)."""
    comps = [ic]
    nets = {}
    for num, name, net in ic["_nets"]:
        nets.setdefault(net, []).append(dict(component="U1", pin_number=num, pin_name=name,
                                             pin_type="passive"))
    for ref, kind, value, n1, n2 in others:
        lib = {"capacitor": "Device:C", "inductor": "Device:L", "diode": "Device:D_Schottky",
               "ferrite_bead": "Device:FerriteBead"}[kind]
        comps.append(_part(ref, kind, value, lib, [("1", "", n1), ("2", "", n2)]))
        for num, net in (("1", n1), ("2", n2)):
            nets.setdefault(net, []).append(dict(component=ref, pin_number=num, pin_name="",
                                                 pin_type="passive"))
    full = {n: {"name": n, "pins": ps, "point_count": 0, "no_connect": False, "has_pwr_flag": False,
                "labels": []} for n, ps in nets.items()}
    ctx = build_analysis_context(comps, full, {}, known_power_rails=set(rails), source="test")
    topo = detect_topologies(ctx)
    return [r for r in topo["power_regulators"] if r["ref"] == "U1"]


def _ic(value, lib_id, pins):
    ic = _part("U1", "ic", value, lib_id, pins)
    ic["_nets"] = pins
    return ic


def _buck(value, lib_id, out_name, sw_net):
    """A non-synchronous buck: OUT/VOUT -> L1 + catch diode D1, output caps on +5V after L1."""
    ic = _ic(value, lib_id, [("1", "VIN", "+12V"), ("2", out_name, sw_net), ("3", "GND", "GND"),
                             ("4", "FB", "+5V"), ("5", "~{ON}", "GND")])
    return _regulator(ic, [
        ("C1", "capacitor", "100u", "+12V", "GND"),
        ("L1", "inductor", "33u", sw_net, "+5V"),
        ("D1", "diode", "SS34", "GND", sw_net),
        ("C2", "capacitor", "220u", "+5V", "GND"),
    ], {"+12V", "+5V", "GND"})


class SwitchPinNamedOut(unittest.TestCase):
    def test_lm2596_out_pin_is_the_switch_node(self):
        reg = _buck("LM2596S-5", "Regulator_Switching:LM2596S-5", "OUT", "__unnamed_2")
        self.assertEqual(reg["output_rail"], "+5V")
        self.assertEqual(reg["sw_net"], "__unnamed_2")
        self.assertEqual(reg["inductor"], "L1")
        self.assertEqual(reg["topology"], "switching")

    def test_lm2675_vout_pin_is_the_switch_node(self):
        reg = _buck("LM2675M-5.0", "Regulator_Switching:LM2675M-5", "VOUT", "SWNODE")
        self.assertEqual(reg["output_rail"], "+5V")
        self.assertEqual(reg["sw_net"], "SWNODE")
        self.assertEqual(reg["topology"], "switching")
        self.assertEqual(reg["estimated_vout"], 5.0)


class LdoOutputStays(unittest.TestCase):
    def _ldo(self, out_net, others, rails=("+5V", "GND")):
        ic = _ic("AMS1117-3.3", "Regulator_Linear:AMS1117-3.3",
                 [("1", "GND", "GND"), ("2", "VO", out_net), ("3", "VI", "+5V")])
        return _regulator(ic, [("C1", "capacitor", "10u", "+5V", "GND")] + others, rails)

    def test_ldo_with_an_output_inductor_but_no_diode_keeps_its_pin(self):
        reg = self._ldo("__unnamed_5", [("L1", "inductor", "10u", "__unnamed_5", "+3V3A")])
        self.assertEqual(reg["output_rail"], "__unnamed_5")
        self.assertEqual(reg["topology"], "LDO")

    def test_ldo_with_an_inductor_and_protection_diode_and_cap_keeps_its_pin(self):
        reg = self._ldo("__unnamed_5", [("L1", "inductor", "10u", "__unnamed_5", "+3V3A"),
                                        ("D1", "diode", "1N4148", "__unnamed_5", "+5V"),
                                        ("C2", "capacitor", "10u", "__unnamed_5", "GND")])
        self.assertEqual(reg["output_rail"], "__unnamed_5")
        self.assertEqual(reg["topology"], "LDO")
        self.assertNotIn("sw_net", reg)

    def test_ldo_output_on_a_named_rail_keeps_it(self):
        reg = self._ldo("+3V3", [("L1", "inductor", "10u", "+3V3", "+3V3A"),
                                 ("D1", "diode", "1N4148", "+3V3", "+5V"),
                                 ("C2", "capacitor", "10u", "+3V3A", "GND")],
                        rails=("+5V", "+3V3", "GND"))
        self.assertEqual(reg["output_rail"], "+3V3")
        self.assertEqual(reg["topology"], "LDO")

    def test_ldo_with_output_caps_on_its_own_unrecognised_ground_keeps_its_pin(self):
        # The caps return to the net the regulator's GND pin sits on, whatever its name
        ic = _ic("L7805", "Regulator_Linear:LM7805_TO220",
                 [("1", "IN", "+12V"), ("2", "GND", "Earth_Protective"), ("3", "OUT", "__unnamed_5")])
        reg = _regulator(ic, [("C1", "capacitor", "330n", "+12V", "Earth_Protective"),
                              ("L1", "inductor", "10u", "__unnamed_5", "AVCC"),
                              ("D1", "diode", "1N4007", "__unnamed_5", "+12V"),
                              ("C2", "capacitor", "100n", "__unnamed_5", "Earth_Protective")],
                         {"+12V", "AVCC"})
        self.assertEqual(reg["output_rail"], "__unnamed_5")
        self.assertEqual(reg["topology"], "LDO")
        self.assertNotIn("sw_net", reg)

    def test_part_with_input_and_output_on_one_net_is_not_a_switcher(self):
        # A broken import that merges VIN, VOUT and GND on one net
        ic = _ic("REG1117", "eagle-import:REG1117",
                 [("1", "GND", "__unnamed_0"), ("2", "VOUT", "__unnamed_0"), ("3", "VIN", "__unnamed_0")])
        recs = _records(ic, [("L1", "inductor", "10u", "__unnamed_0", "__unnamed_1"),
                             ("D1", "diode", "1N4148", "__unnamed_0", "__unnamed_2"),
                             ("C1", "capacitor", "10u", "__unnamed_0", "__unnamed_0")], set())
        self.assertEqual([r for r in recs if r.get("sw_net")], [])
        self.assertEqual(recs, [])


if __name__ == "__main__":
    unittest.main()
