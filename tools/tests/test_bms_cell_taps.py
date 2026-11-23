"""BMS cell-voltage pins on supply-named nets.

LTC6803-4 (Analog Devices/Linear Technology datasheet pin table) has cell taps C0-C12; boards
name the taps after the cell stack (+Cell12, VBAT_CELL4), which reads as a supply name. The
BQ76920 (TI SLUSBK2 datasheet, pin functions) repurposes VC3-VC5 on 3/4-cell stacks by tying them
to one rail, so several cell pins on one supply net are not cells.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import domain_detectors as dd  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402


def bms_ctx(ic_value, taps, rails, extra_comps=(), extra_pins=None):
    """taps: list of (pin_number, pin_name, net)."""
    nets = {}
    for num, name, net in taps:
        nets.setdefault(net, []).append(
            dict(component="U1", pin_number=num, pin_name=name, pin_type="input"))
    for net, pins in (extra_pins or {}).items():
        nets.setdefault(net, []).extend(pins)
    full = {n: {"name": n, "pins": pins, "point_count": 0, "no_connect": False,
                "has_pwr_flag": False, "labels": []} for n, pins in nets.items()}
    comps = [{"reference": "U1", "type": "ic", "value": ic_value, "lib_id": "", "pins": [],
              "footprint": ""}]
    for c in extra_comps:
        c = dict(c)
        c.setdefault("lib_id", "")
        c.setdefault("pins", [])
        c.setdefault("footprint", "")
        comps.append(c)
    ctx = build_analysis_context(comps, full, {}, known_power_rails=set(rails))
    ctx.rail_by_net = {}
    return ctx


class BmsCellTapTests(unittest.TestCase):
    def test_cell_tap_on_a_supply_named_net_counts(self):
        ctx = bms_ctx("LTC6803-4",
                      [("1", "C1", "VBAT_CELL1"), ("2", "C2", "VBAT_CELL2"),
                       ("3", "C3", "VBAT_CELL3"), ("4", "C4", "VBAT_CELL4")],
                      rails={"VBAT_CELL1", "VBAT_CELL2", "VBAT_CELL3", "VBAT_CELL4"})
        (sys_,) = dd.detect_bms_systems(ctx)
        self.assertEqual(sys_["cell_count"], 4)
        self.assertEqual(sys_["cell_voltage_pins"], 4)
        self.assertIn("VBAT_CELL4", sys_["cell_nets"])

    def test_repurposed_cell_pins_on_one_rail_do_not_count(self):
        ctx = bms_ctx("BQ76920",
                      [("1", "VC1", "CELL1"), ("2", "VC2", "CELL2"),
                       ("3", "VC3", "VSS_RAIL"), ("4", "VC4", "VSS_RAIL"),
                       ("5", "VC5", "VSS_RAIL")],
                      rails={"VSS_RAIL"})
        (sys_,) = dd.detect_bms_systems(ctx)
        self.assertEqual(sys_["cell_count"], 2)
        self.assertNotIn("VSS_RAIL", sys_["cell_nets"])

    def test_rail_tap_adds_no_balance_resistors(self):
        res = dict(reference="R1", type="resistor", value="100")
        ctx = bms_ctx("LTC6803-4",
                      [("1", "C1", "CELL1"), ("2", "C2", "+Cell2")],
                      rails={"+Cell2"},
                      extra_comps=[res, dict(reference="R2", type="resistor", value="10k")],
                      extra_pins={
                          "CELL1": [dict(component="R1", pin_number="1", pin_name="~",
                                         pin_type="passive")],
                          "+Cell2": [dict(component="R2", pin_number="1", pin_name="~",
                                          pin_type="passive")]})
        (sys_,) = dd.detect_bms_systems(ctx)
        self.assertEqual(sys_["cell_count"], 2)
        self.assertEqual([r["reference"] for r in sys_["balance_resistors"]], ["R1"])


if __name__ == "__main__":
    unittest.main()
