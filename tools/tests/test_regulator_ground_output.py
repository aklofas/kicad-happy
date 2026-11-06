"""A fixed-output regulator whose output pin sits on ground gets no output rail and gives ground no voltage."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from schematic.pipeline import detect_topologies  # noqa: E402


def _pin(ref, num, name, ptype):
    return dict(component=ref, pin_number=num, pin_name=name, pin_type=ptype)


def _ic(ref, value, pins):
    return {"reference": ref, "type": "ic", "value": value, "lib_id": "Regulator_Linear:" + value,
            "footprint": "", "properties": {}, "pins": [{"number": n, "name": nm} for n, nm in pins]}


def _ctx(tab_net):
    # U1: a 3.3 V fixed LDO whose tab (a second VO pin) is on *tab_net*.
    comps = [_ic("U1", "AMS1117-3.3", [("1", "GND"), ("2", "VO"), ("3", "VI"), ("4", "VO")])]
    nets = {
        "+12V": [_pin("U1", "3", "VI", "power_in")],
        "VREG": [_pin("U1", "2", "VO", "power_out")],
        "GND": [_pin("U1", "1", "GND", "power_in")],
    }
    nets.setdefault(tab_net, []).append(_pin("U1", "4", "VO", "power_out"))
    full = {n: {"name": n, "pins": ps, "point_count": 0, "no_connect": False, "has_pwr_flag": False,
                "labels": []} for n, ps in nets.items()}
    return build_analysis_context(comps, full, {}, known_power_rails={"+12V", "GND"}, source="test")


class FixedSuffixOutputOnGround(unittest.TestCase):
    def test_output_pin_on_ground_leaves_output_rail_empty(self):
        topo = detect_topologies(_ctx("GND"))
        (reg,) = [r for r in topo["power_regulators"] if r["ref"] == "U1"]
        self.assertIsNone(reg.get("output_rail"))
        self.assertEqual(reg["estimated_vout"], 3.3)

    def test_ground_gets_no_regulator_voltage(self):
        ctx = _ctx("GND")
        topo = detect_topologies(ctx)
        self.assertEqual(topo["rail_voltages"].get("GND"), 0)
        self.assertEqual(ctx.rail_voltage("GND"), 0)

    def test_output_pin_on_a_rail_keeps_it(self):
        topo = detect_topologies(_ctx("VREG"))
        (reg,) = [r for r in topo["power_regulators"] if r["ref"] == "U1"]
        self.assertEqual(reg["output_rail"], "VREG")
        self.assertEqual(topo["rail_voltages"]["VREG"], 3.3)


if __name__ == "__main__":
    unittest.main()
