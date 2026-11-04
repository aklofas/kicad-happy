import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context
from signal_detectors import audit_rail_sources, audit_power_pin_dc_paths


def _ctx(components, nets):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name="", pin_type=t) for r, p, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    return build_analysis_context(components, full, {}, known_power_rails={"+3V3", "VBUS"})


U = {"reference": "U1", "type": "ic", "value": "MCU"}
C = {"reference": "C1", "type": "capacitor", "value": "100n"}


class RailSources(unittest.TestCase):
    def test_open_jumper_is_rs002_and_bridged_is_rs003(self):
        comps = [U, {"reference": "JP1", "type": "jumper", "value": "SJ"}]
        nets = {"VBUS": [("JP1", "2", "passive")], "N_SYS": [("U1", "1", "power_in"), ("JP1", "1", "passive")]}
        ctx = _ctx(comps, nets)
        ctx.nets["VBUS"]["has_pwr_flag"] = True
        for state, rule in (("open", "RS-002"), ("bridged", "RS-003")):
            f = audit_rail_sources(ctx, solder_jumpers=[{"reference": "JP1", "default_state": state, "nets": ["N_SYS", "VBUS"]}])
            self.assertEqual([x["rule_id"] for x in f if x["nets"][0] == "N_SYS"], [rule], state)

    def test_three_net_jumper_is_ignored(self):
        comps = [U, {"reference": "JP1", "type": "jumper", "value": "SJ3"}]
        nets = {"VBUS": [("JP1", "2", "passive")], "N_SYS": [("U1", "1", "power_in"), ("JP1", "1", "passive")]}
        ctx = _ctx(comps, nets); ctx.nets["VBUS"]["has_pwr_flag"] = True
        f = audit_rail_sources(ctx, solder_jumpers=[{"reference": "JP1", "default_state": "bridged", "nets": ["N_SYS", "VBUS", "X"]}])
        self.assertEqual([x["rule_id"] for x in f if x["nets"][0] == "N_SYS"], ["RS-001"])

    def test_net_tie_makes_a_sourced_net_the_rail_source(self):
        comps = [U, {"reference": "NT1", "type": "net_tie", "value": "Net-Tie_2"}]
        nets = {"VDD": [("U1", "1", "power_in"), ("NT1", "2", "passive")],
                "Net-(C2-Pad2)": [("U1", "2", "power_out"), ("NT1", "1", "passive")]}
        ctx = _ctx(comps, nets)
        self.assertEqual([x["rule_id"] for x in audit_rail_sources(ctx) if x["nets"][0] == "VDD"], [])

    def test_net_tie_to_a_jumper_sourced_net_is_rs003(self):
        comps = [U, {"reference": "NT1", "type": "net_tie"}, {"reference": "JP1", "type": "jumper", "value": "SJ"}]
        nets = {"VDD": [("U1", "1", "power_in"), ("NT1", "2", "passive")],
                "N_T": [("NT1", "1", "passive"), ("JP1", "1", "passive")],
                "VBUS": [("JP1", "2", "passive")]}
        ctx = _ctx(comps, nets)
        ctx.nets["VBUS"]["has_pwr_flag"] = True
        f = audit_rail_sources(ctx, solder_jumpers=[{"reference": "JP1", "default_state": "bridged", "nets": ["N_T", "VBUS"]}])
        self.assertEqual([x["rule_id"] for x in f if x["nets"][0] == "VDD"], ["RS-003"])

    def test_duplicate_net_tie_reference_does_not_source(self):
        nt = {"reference": "NT?", "type": "net_tie"}
        nets = {"VDD": [("U1", "1", "power_in"), ("NT?", "2", "passive")],
                "Net-(C2-Pad2)": [("U1", "2", "power_out"), ("NT?", "1", "passive")]}
        ctx = _ctx([U, nt, dict(nt)], nets)
        self.assertEqual([x["rule_id"] for x in audit_rail_sources(ctx) if x["nets"][0] == "VDD"], ["RS-001"])


class PowerPinPaths(unittest.TestCase):
    def _board(self, bridge):
        comps = [U, C, bridge]
        nets = {"+3V3": [(bridge["reference"], "1", "passive")],
                "N_U1": [("U1", "1", "power_in"), (bridge["reference"], "2", "passive"), ("C1", "1", "passive")],
                "GND": [("C1", "2", "passive")]}
        return _ctx(comps, nets)

    def test_bridge_kinds(self):
        for comp, expect in (
            ({"reference": "R1", "type": "resistor", "value": "0R"}, 0),
            ({"reference": "R1", "type": "resistor", "value": "1"}, 0),
            ({"reference": "R1", "type": "resistor", "value": "1.1"}, 1),
            ({"reference": "R1", "type": "resistor", "value": "DNP"}, 1),
            ({"reference": "L1", "type": "inductor", "value": "10u"}, 0),
            ({"reference": "FB1", "type": "ferrite_bead", "value": "600R"}, 0),
            ({"reference": "F1", "type": "fuse", "value": "1A"}, 0),
        ):
            f = audit_power_pin_dc_paths(self._board(comp))
            self.assertEqual(len([x for x in f if x["rule_id"] == "PP-001"]), expect, comp)

    def test_net_tie_bridges_and_a_ground_tied_pin_is_a_ground_pin(self):
        f = audit_power_pin_dc_paths(self._board({"reference": "NT1", "type": "net_tie"}))
        self.assertEqual(len([x for x in f if x["rule_id"] == "PP-001"]), 0)
        comps = [U, C, {"reference": "NT1", "type": "net_tie"}]
        ctx = _ctx(comps, {"GND": [("C1", "2", "passive"), ("NT1", "1", "passive")],
                           "AGND": [("U1", "1", "power_in"), ("NT1", "2", "passive"), ("C1", "1", "passive")]})
        self.assertEqual([x for x in audit_power_pin_dc_paths(ctx) if x["rule_id"] == "PP-001"], [])

    def test_jumper_bridges_only_when_detected_bridged(self):
        jp = {"reference": "JP1", "type": "jumper", "value": "SJ"}
        for sj, expect in (([{"reference": "JP1", "default_state": "bridged", "nets": ["+3V3", "N_U1"]}], 0),
                           ([{"reference": "JP1", "default_state": "open", "nets": ["+3V3", "N_U1"]}], 1),
                           ([], 1)):
            f = audit_power_pin_dc_paths(self._board(jp), solder_jumpers=sj)
            self.assertEqual(len([x for x in f if x["rule_id"] == "PP-001"]), expect, sj)

    def test_duplicate_ref_is_last_wins(self):
        res = {"reference": "R1", "type": "resistor", "value": "0R"}
        dio = {"reference": "R1", "type": "diode", "value": "1N4148"}
        for comps, expect in (([U, C, res, dio], 1), ([U, C, dio, res], 0)):
            ctx2 = _ctx(comps, {"+3V3": [("R1", "1", "passive")],
                                "N_U1": [("U1", "1", "power_in"), ("R1", "2", "passive"), ("C1", "1", "passive")],
                                "GND": [("C1", "2", "passive")]})
            f = audit_power_pin_dc_paths(ctx2)
            self.assertEqual(len([x for x in f if x["rule_id"] == "PP-001"]), expect, [c["type"] for c in comps])


if __name__ == "__main__":
    unittest.main()
