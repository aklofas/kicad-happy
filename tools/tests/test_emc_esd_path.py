"""ES-001 and ES-002 check discrete TVS diodes, which the protection detector types 'diode'."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from emc_rules import check_esd_protection_path  # noqa: E402
from finding_schema import Det  # noqa: E402


def _rules(ptype, tvs_x, clamp_net=None):
    pcb = {"footprints": [{"reference": "J1", "value": "USB_C", "x": 0, "y": 0},
                          {"reference": "D1", "value": "SMAJ5.0A", "x": tvs_x, "y": 0}],
           "nets": {"1": {"name": "GND"}},
           "vias": {"vias": [{"x": 90, "y": 90, "net": 1}]}}
    schematic = {"findings": [{"detector": Det.PROTECTION_DEVICES, "reference": "D1", "type": ptype,
                             "clamp_net": clamp_net}]}
    return sorted(f["rule_id"] for f in check_esd_protection_path(pcb, schematic))


class EsdPathDiodeType(unittest.TestCase):
    def test_diode_type_tvs_gets_distance_and_ground_via_checks(self):
        self.assertEqual(_rules("diode", 20), ["ES-001", "ES-002"])

    def test_tvs_type_is_unchanged(self):
        self.assertEqual(_rules("tvs", 20), _rules("diode", 20))

    def test_other_types_are_not_checked(self):
        self.assertEqual(_rules("reverse_polarity", 20), [])

    def test_ground_return_check_needs_a_ground_clamp_net(self):
        self.assertEqual(_rules("diode", 20, "GND"), ["ES-001", "ES-002"])
        self.assertEqual(_rules("diode", 20, "/Power/GNDPWR"), ["ES-001", "ES-002"])
        self.assertEqual(_rules("diode", 20, "+9v"), ["ES-001"])

    def test_other_types_keep_the_ground_via_check_whatever_the_clamp_net(self):
        self.assertEqual(_rules("varistor", 20, "+9V"), ["ES-001", "ES-002"])
