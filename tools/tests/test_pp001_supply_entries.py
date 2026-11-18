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


class SeriesResistorSupply(unittest.TestCase):
    def _fed_through(self, r):
        nets = {"+5V": [("R1", "1", "passive")],
                "N_U1": [("U1", "1", "power_in"), ("R1", "2", "passive"), ("C1", "1", "passive")],
                "GND": [("C1", "2", "passive")]}
        return _pp001([U, C, dict({"reference": "R1", "type": "resistor"}, **r)], nets)

    def test_a_filter_resistor_straight_from_a_rail_feeds_the_pin(self):
        for value in ("10", "100", "1k"):
            self.assertEqual(self._fed_through({"value": value}), [], value)

    def test_a_large_resistor_from_a_rail_does_not(self):
        self.assertEqual(len(self._fed_through({"value": "10k"})), 1)

    def test_an_unfitted_resistor_does_not(self):
        self.assertEqual(len(self._fed_through({"value": "100", "dnp": True})), 1)
        self.assertEqual(len(self._fed_through({"value": "100", "on_board": False})), 1)

    def test_the_walk_does_not_go_on_past_the_resistor(self):
        # The pin's own net has no capacitor; one sits past the 240 ohm resistor.
        nets = {"N_ZQ": [("U1", "1", "power_in"), ("R1", "2", "passive")],
                "N_FAR": [("R1", "1", "passive"), ("C1", "1", "passive")],
                "GND": [("C1", "2", "passive")]}
        self.assertEqual(_pp001([U, C, {"reference": "R1", "type": "resistor", "value": "240"}], nets), [])

    def test_a_resistor_to_ground_does_not_feed_even_with_a_connector_on_ground(self):
        parts = [U, C, {"reference": "J1", "type": "connector", "value": "Conn_01x02"},
                 {"reference": "R1", "type": "resistor", "value": "470"}]
        nets = {"N_U1": [("U1", "1", "power_in"), ("R1", "2", "passive"), ("C1", "1", "passive")],
                "GND": [("R1", "1", "passive"), ("C1", "2", "passive"), ("J1", "2", "passive")]}
        self.assertEqual(len(_pp001(parts, nets)), 1)

    def test_a_resistor_to_a_net_that_is_not_a_rail_does_not_feed(self):
        parts = [U, C, {"reference": "C2", "type": "capacitor", "value": "1u"},
                 {"reference": "R1", "type": "resistor", "value": "100"}]
        nets = {"N_FAR": [("R1", "1", "passive"), ("C2", "1", "passive")],
                "N_U1": [("U1", "1", "power_in"), ("R1", "2", "passive"), ("C1", "1", "passive")],
                "GND": [("C1", "2", "passive"), ("C2", "2", "passive")]}
        self.assertEqual(len(_pp001(parts, nets)), 1)


if __name__ == "__main__":
    unittest.main()
