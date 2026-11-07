"""CG-AUD counts a connector's ground-named pin on an unnamed net as a ground pin only
when that net reaches another part; ground pins wired to nothing keep the warning."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
from domain_detectors import audit_connector_ground_distribution  # noqa: E402


def _ctx(nets):
    comps = [{"reference": "J1", "type": "connector", "value": "Conn_01x10"},
             {"reference": "C1", "type": "capacitor", "value": "100n"}]
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type="passive")
                                    for r, p, pn in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    return build_analysis_context(comps, full, {}, known_power_rails=set())


def _signal_nets(count):
    return {f"SIG{i}": [("J1", str(i), f"D{i}")] for i in range(1, count + 1)}


class ConnectorGroundOnUnnamedNet(unittest.TestCase):
    def test_ground_pin_wired_to_a_capacitor_counts_as_ground(self):
        nets = _signal_nets(9)
        nets["__unnamed_0"] = [("J1", "10", "GND"), ("C1", "2", "~")]
        f = audit_connector_ground_distribution(_ctx(nets))
        self.assertEqual([(x["severity"], x["ground_pins"], x["signal_pins"]) for x in f],
                         [("info", 1, 9)])
        self.assertEqual(f[0]["summary"], "Connector J1: 9:1 signal-to-ground ratio")

    def test_ground_pins_wired_only_to_each_other_keep_the_warning(self):
        nets = _signal_nets(8)
        nets["__unnamed_0"] = [("J1", "9", "GND"), ("J1", "10", "GND")]
        f = audit_connector_ground_distribution(_ctx(nets))
        self.assertEqual([(x["severity"], x["ground_pins"], x["signal_pins"]) for x in f],
                         [("warning", 0, 10)])

    def test_ground_pin_beside_a_power_symbol_only_keeps_the_warning(self):
        nets = _signal_nets(9)
        nets["__unnamed_0"] = [("J1", "10", "GND"), ("#FLG01", "1", "pwr")]
        f = audit_connector_ground_distribution(_ctx(nets))
        self.assertEqual([(x["severity"], x["ground_pins"]) for x in f], [("warning", 0)])

    def test_signal_named_pin_on_an_unnamed_net_with_a_part_stays_a_signal(self):
        nets = _signal_nets(9)
        nets["__unnamed_0"] = [("J1", "10", "D10"), ("C1", "2", "~")]
        f = audit_connector_ground_distribution(_ctx(nets))
        self.assertEqual([(x["severity"], x["ground_pins"], x["signal_pins"]) for x in f],
                         [("warning", 0, 10)])


if __name__ == "__main__":
    unittest.main()
