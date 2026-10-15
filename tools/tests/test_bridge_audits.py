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

    def test_jumper_bridges_only_when_detected_bridged(self):
        jp = {"reference": "JP1", "type": "jumper", "value": "SJ"}
        for sj, expect in (([{"reference": "JP1", "default_state": "bridged", "nets": ["+3V3", "N_U1"]}], 0),
                           ([{"reference": "JP1", "default_state": "open", "nets": ["+3V3", "N_U1"]}], 1),
                           ([], 1)):
            f = audit_power_pin_dc_paths(self._board(jp), solder_jumpers=sj)
            self.assertEqual(len([x for x in f if x["rule_id"] == "PP-001"]), expect, sj)


if __name__ == "__main__":
    unittest.main()
