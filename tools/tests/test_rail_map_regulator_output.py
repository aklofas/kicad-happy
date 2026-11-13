import sys, unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from schematic.pipeline import build_rail_map  # noqa: E402


def _ctx(nets):
    # Only the names the rail map reads; no net counts as a power net by name here.
    return SimpleNamespace(nets=dict.fromkeys(nets, []), vss_supply_rails=set(),
                           rail_overrides={}, rail_ignore=(),
                           is_power_net=lambda n, by_pins=True: False,
                           is_ground=lambda n: False)


def _reg(out, inverting=False):
    return {"output_rail": out, "estimated_vout": None, "inverting": inverting,
            "topology": "ldo"}


class RegulatorOutputNameVoltageTest(unittest.TestCase):
    def test_regulator_output_gets_its_name_voltage(self):
        by_net = build_rail_map(_ctx(["3V3_OFF"]), [_reg("3V3_OFF")])
        self.assertEqual(by_net.get("3V3_OFF"), 3.3)

    def test_sign_disagreeing_with_inverting_regulator_is_skipped(self):
        # The parser reads only a leading minus, so F-15V parses positive.
        by_net = build_rail_map(_ctx(["F-15V"]), [_reg("F-15V", inverting=True)])
        self.assertNotIn("F-15V", by_net)
        by_net = build_rail_map(_ctx(["-15V_OUT"]), [_reg("-15V_OUT", inverting=False)])
        self.assertNotIn("-15V_OUT", by_net)

    def test_matching_sign_on_inverting_regulator_is_kept(self):
        by_net = build_rail_map(_ctx(["-15V_OUT"]), [_reg("-15V_OUT", inverting=True)])
        self.assertEqual(by_net.get("-15V_OUT"), -15.0)

    def test_comma_decimal_is_skipped(self):
        by_net = build_rail_map(_ctx(["3,3V"]), [_reg("3,3V")])
        self.assertNotIn("3,3V", by_net)

    def test_non_regulator_net_is_unchanged(self):
        by_net = build_rail_map(_ctx(["3V3_OFF"]), [])
        self.assertNotIn("3V3_OFF", by_net)


if __name__ == "__main__":
    unittest.main()
