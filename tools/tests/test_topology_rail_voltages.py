"""A net that is a supply only by its pins gets no voltage parsed from its name in
``rail_voltages``; a regulator that drives such a net still gives it its output voltage."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from schematic.net_analysis import analyze_design_rules  # noqa: E402
from schematic.pipeline import detect_topologies  # noqa: E402


def _pin(ref, num, name, ptype):
    return dict(component=ref, pin_number=num, pin_name=name, pin_type=ptype)


def _comp(ref, ctype, value, pins=()):
    return {"reference": ref, "type": ctype, "value": value, "lib_id": "", "footprint": "",
            "properties": {}, "pins": [{"number": n, "name": nm} for n, nm in pins]}


def _ctx():
    comps = [_comp("U1", "ic", "TCAN1042", [("1", "VCC"), ("2", "GND")]),
             _comp("U2", "ic", "TCAN1042", [("1", "VCC"), ("2", "GND")]),
             _comp("C1", "capacitor", "100n"),
             _comp("U3", "ic", "AMS1117-3.3", [("1", "GND"), ("2", "VO"), ("3", "VI")]),
             _comp("U4", "ic", "MCU", [("1", "VDD"), ("2", "GND")]),
             _comp("C2", "capacitor", "10u")]
    nets = {
        # Two transceivers' VCC pins (typed passive) and a cap to ground: a supply by its pins.
        "CAN_3V3_PROTECTED": [_pin("U1", "1", "VCC", "passive"), _pin("U2", "1", "VCC", "passive"),
                              _pin("C1", "1", "~", "passive")],
        # A regulator output feeding an IC supply pin, with a cap to ground.
        "MCU_SUPPLY": [_pin("U3", "2", "VO", "power_out"), _pin("U4", "1", "VDD", "power_in"),
                       _pin("C2", "1", "~", "passive")],
        "+5V": [_pin("U3", "3", "VI", "power_in")],
        "GND": [_pin("C1", "2", "~", "passive"), _pin("C2", "2", "~", "passive"),
                _pin("U1", "2", "GND", "power_in"), _pin("U2", "2", "GND", "power_in"),
                _pin("U3", "1", "GND", "power_in"), _pin("U4", "2", "GND", "power_in")],
    }
    full = {n: {"name": n, "pins": ps, "point_count": 0, "no_connect": False, "has_pwr_flag": False,
                "labels": []} for n, ps in nets.items()}
    return build_analysis_context(comps, full, {}, known_power_rails={"+5V", "GND"}, source="test")


class TopologyRailVoltages(unittest.TestCase):
    def test_pin_only_supply_is_power_but_has_no_name_parsed_voltage(self):
        ctx = _ctx()
        self.assertIn("CAN_3V3_PROTECTED", ctx.topology_rails)
        topo = detect_topologies(ctx)
        self.assertNotIn("CAN_3V3_PROTECTED", topo["rail_voltages"])
        self.assertIsNone(ctx.rail_voltage("CAN_3V3_PROTECTED"))
        classes = analyze_design_rules(ctx)["net_classification"]
        self.assertEqual(classes["CAN_3V3_PROTECTED"], "power")

    def test_regulator_output_rail_keeps_its_estimate(self):
        ctx = _ctx()
        self.assertIn("MCU_SUPPLY", ctx.topology_rails)
        topo = detect_topologies(ctx)
        self.assertEqual(topo["rail_voltages"]["MCU_SUPPLY"], 3.3)
        self.assertEqual(topo["rail_voltages"]["+5V"], 5.0)


if __name__ == "__main__":
    unittest.main()
