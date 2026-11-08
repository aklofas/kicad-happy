"""ES-001 and ES-002 check discrete TVS diodes, which the protection detector types 'diode'.
ES-002 counts ground vias only for a diode or varistor that clamps to ground."""
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

    def test_varistor_ground_return_check_needs_a_ground_clamp_net(self):
        self.assertEqual(_rules("varistor", 20, "GND"), ["ES-001", "ES-002"])
        self.assertEqual(_rules("varistor", 20, "+9V"), ["ES-001"])
        self.assertEqual(_rules("varistor", 20, "/AC/L2"), ["ES-001"])

    def test_varistor_without_a_clamp_net_keeps_the_ground_via_check(self):
        self.assertEqual(_rules("varistor", 20), ["ES-001", "ES-002"])

    def test_other_types_keep_the_ground_via_check_whatever_the_clamp_net(self):
        self.assertEqual(_rules("tvs", 20, "+9V"), ["ES-001", "ES-002"])


def _findings(connectors, tvs_x=20):
    pcb = {"footprints": connectors + [{"reference": "D1", "value": "SMAJ5.0A", "x": tvs_x, "y": 0}],
           "nets": {"1": {"name": "GND"}},
           "vias": {"vias": [{"x": 90, "y": 90, "net": 1}]}}
    schematic = {"findings": [{"detector": Det.PROTECTION_DEVICES, "reference": "D1", "type": "tvs"}]}
    return sorted((f["rule_id"], tuple(f.get("components") or []))
                  for f in check_esd_protection_path(pcb, schematic))


class EsdPathDnpConnector(unittest.TestCase):
    def test_nearest_connector_dnp_pairs_with_no_farther_fitted_one(self):
        conns = [{"reference": "J1", "value": "USB_C", "x": 0, "y": 0, "dnp": True},
                 {"reference": "J2", "value": "USB_C", "x": -20, "y": 0}]
        self.assertEqual(_findings(conns), [("ES-002", ("D1",))])

    def test_nearest_connector_fitted_is_unchanged(self):
        conns = [{"reference": "J1", "value": "USB_C", "x": 0, "y": 0},
                 {"reference": "J2", "value": "USB_C", "x": -20, "y": 0, "dnp": True}]
        self.assertEqual(_findings(conns), [("ES-001", ("D1", "J1")), ("ES-002", ("D1",))])

    def test_ground_via_check_still_runs_near_a_dnp_only_connector(self):
        conns = [{"reference": "J1", "value": "USB_C", "x": 0, "y": 0, "dnp": True}]
        self.assertEqual(_findings(conns, tvs_x=40), [("ES-002", ("D1",))])
        self.assertEqual(_findings(conns, tvs_x=60), [])
