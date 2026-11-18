import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context
from signal_detectors import audit_power_pin_dc_paths


def _pp001(components, nets, **kw):
    full = {n: {"name": n, "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": [],
                "pins": [dict(component=r, pin_number=p, pin_name="", pin_type=t) for r, p, t in pins]}
            for n, pins in nets.items()}
    ctx = build_analysis_context(components, full, {}, known_power_rails={"+5V"})
    return [f for f in audit_power_pin_dc_paths(ctx, **kw) if f["rule_id"] == "PP-001"]


U = {"reference": "U1", "type": "ic", "value": "RTC"}
C = {"reference": "C1", "type": "capacitor", "value": "100n"}


class BatteryEntry(unittest.TestCase):
    def test_battery_on_the_pin_net_feeds_it(self):
        bt = {"reference": "BT1", "type": "battery", "value": "CR2032"}
        nets = {"Net-(BT1-Pad1)": [("U1", "1", "power_in"), ("BT1", "1", "passive"), ("C1", "1", "passive")],
                "GND": [("BT1", "2", "passive"), ("C1", "2", "passive")]}
        self.assertEqual(_pp001([U, C, bt], nets), [])

    def test_battery_behind_a_ferrite_feeds_the_pin(self):
        bt = {"reference": "BT1", "type": "battery", "value": "18650"}
        fb = {"reference": "FB1", "type": "ferrite_bead", "value": "600R"}
        nets = {"N_CELL": [("BT1", "1", "passive"), ("FB1", "1", "passive")],
                "N_U1": [("U1", "1", "power_in"), ("FB1", "2", "passive"), ("C1", "1", "passive")],
                "GND": [("BT1", "2", "passive"), ("C1", "2", "passive")]}
        self.assertEqual(_pp001([U, C, bt, fb], nets), [])


class RegulatorOutputRail(unittest.TestCase):
    NETS = {"__unnamed_4": [("U3", "2", "output"), ("F1", "1", "passive")],
            "N_U1": [("U1", "1", "power_in"), ("F1", "2", "passive"), ("C1", "1", "passive")],
            "GND": [("C1", "2", "passive")]}
    PARTS = [U, C, {"reference": "U3", "type": "ic", "value": "LM317"},
             {"reference": "F1", "type": "fuse", "value": "500mA"}]

    def test_unnamed_regulator_output_feeds_the_pin_through_a_fuse(self):
        self.assertEqual(_pp001(self.PARTS, self.NETS, power_regulators=[{"output_rail": "__unnamed_4"}]), [])

    def test_the_same_net_without_a_regulator_record_is_not_a_rail(self):
        self.assertEqual(len(_pp001(self.PARTS, self.NETS)), 1)

    def test_a_regulator_record_naming_ground_does_not_make_ground_a_rail(self):
        nets = {"GND": [("U3", "2", "output"), ("F1", "1", "passive"), ("C1", "2", "passive")],
                "N_U1": [("U1", "1", "power_in"), ("F1", "2", "passive"), ("C1", "1", "passive")]}
        self.assertEqual(len(_pp001(self.PARTS, nets, power_regulators=[{"output_rail": "GND"}])), 1)


if __name__ == "__main__":
    unittest.main()
