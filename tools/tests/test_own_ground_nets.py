"""A regulator's GND-pin net is its own ground for the switch-output and decoupling checks
alike, unless that net is not ground and is named for a voltage (an inverting converter's -5V)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
import signal_detectors as sd  # noqa: E402


def _ctx(gnd_net):
    """U1 (GND pin on gnd_net, SW on SW, VIN on VIN_RAW); L1 + D1 + C1 on SW, C1 to gnd_net;
    C2 from OUT to gnd_net."""
    comps = [
        {"reference": "U1", "type": "ic", "value": "TPS54620", "lib_id": "", "pins": [],
         "footprint": ""},
        {"reference": "L1", "type": "inductor", "value": "10u", "lib_id": "", "pins": [],
         "footprint": ""},
        {"reference": "D1", "type": "diode", "value": "SS34", "lib_id": "", "pins": [],
         "footprint": ""},
        {"reference": "C1", "type": "capacitor", "value": "100n", "lib_id": "", "pins": [],
         "footprint": ""},
        {"reference": "C2", "type": "capacitor", "value": "10u", "lib_id": "", "pins": [],
         "footprint": ""},
    ]
    nets = {
        "VIN_RAW": [("U1", "1", "VIN", "power_in")],
        "SW": [("U1", "2", "SW", "output"), ("L1", "1", "1", "passive"),
               ("D1", "1", "K", "passive"), ("C1", "1", "1", "passive")],
        "OUT": [("L1", "2", "2", "passive"), ("C2", "1", "1", "passive")],
        gnd_net: [("U1", "3", "GND", "power_in"), ("C1", "2", "2", "passive"),
                  ("C2", "2", "2", "passive"), ("D1", "2", "A", "passive")],
    }
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    return build_analysis_context(comps, full, {}, known_power_rails={"VIN_RAW"})


class OwnGroundIsOneRule(unittest.TestCase):
    def test_own_ground_is_one_rule(self):
        negative = _ctx("-5V")
        self.assertEqual(sd._own_ground_nets(negative, "U1"), set())
        self.assertTrue(sd._is_switch_output(negative, "U1", "SW"))
        self.assertFalse(sd._has_cap_to_ground(negative, "OUT", "U1"))

        named = _ctx("5V_GND")
        self.assertEqual(sd._own_ground_nets(named, "U1"), {"5V_GND"})
        self.assertFalse(sd._is_switch_output(named, "U1", "SW"))
        self.assertTrue(sd._has_cap_to_ground(named, "OUT", "U1"))

    def test_gnd_pin_on_a_plain_ground_net_is_own_ground(self):
        ctx = _ctx("GND")
        self.assertEqual(sd._own_ground_nets(ctx, "U1"), {"GND"})


if __name__ == "__main__":
    unittest.main()
