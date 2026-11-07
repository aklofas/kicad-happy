"""ESD audits (EP-AUD, EG-001) leave out a connector pin typed no-connect that sits alone on
its net; a no-connect-typed pin wired to another part is still audited."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
from domain_detectors import audit_esd_protection  # noqa: E402
import cross_analysis as ca  # noqa: E402

_CONN = {"reference": "J1", "type": "connector", "value": "USB_C",
         "lib_id": "Connector:USB_C_Receptacle"}


def _nets(nc_wired_to_part):
    nets = {
        "DP": [("J1", "1", "D+", "bidirectional"), ("U1", "5", "USB_DP", "bidirectional")],
        "unconnected-(J1-NC-Pad2)": [("J1", "2", "NC", "no_connect")],
    }
    if nc_wired_to_part:
        nets["SBU"] = [("J1", "3", "SBU", "no_connect"), ("R1", "1", "~", "passive")]
    return nets


def _ep_aud(nets):
    comps = [dict(_CONN), {"reference": "U1", "type": "ic", "value": "MCU"},
             {"reference": "R1", "type": "resistor", "value": "10k"}]
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    return audit_esd_protection(build_analysis_context(comps, full, {}, known_power_rails=set()), [])


def _eg001(nets):
    pin_nets = {p: n for n, pins in nets.items() for r, p, _, _ in pins if r == "J1"}
    sch = {"components": [dict(_CONN, pin_nets=pin_nets), {"reference": "U1", "type": "ic"},
                          {"reference": "R1", "type": "resistor"}],
           "nets": {n: {"pins": [{"component": r, "pin_number": p, "pin_type": t}
                                 for r, p, _, t in pins]} for n, pins in nets.items()},
           "findings": []}
    return ca.check_esd_coverage_gaps(sch, None)


class EpAudNoConnectPins(unittest.TestCase):
    def test_lone_no_connect_pin_is_not_an_unprotected_signal(self):
        f = _ep_aud(_nets(False))
        self.assertEqual([(x["signal_nets"], x["unprotected_nets"]) for x in f], [(["DP"], ["DP"])])

    def test_no_connect_pin_wired_to_a_part_is_still_audited(self):
        f = _ep_aud(_nets(True))
        self.assertEqual([x["signal_nets"] for x in f], [["DP", "SBU"]])

    def test_connector_with_only_no_connect_pins_gets_no_record(self):
        self.assertEqual(_ep_aud({"unconnected-(J1-NC-Pad2)": [("J1", "2", "NC", "no_connect")]}), [])


class Eg001NoConnectPins(unittest.TestCase):
    def test_lone_no_connect_pin_is_not_an_unprotected_signal(self):
        f = _eg001(_nets(False))
        self.assertEqual([(x["nets"], x["summary"]) for x in f],
                         [(["DP"], "Connector J1: 1 unprotected signal pin(s)")])

    def test_no_connect_pin_wired_to_a_part_is_still_a_gap(self):
        f = _eg001(_nets(True))
        self.assertEqual([x["nets"] for x in f], [["DP", "SBU"]])

    def test_connector_with_only_no_connect_pins_gets_no_finding(self):
        self.assertEqual(_eg001({"unconnected-(J1-NC-Pad2)": [("J1", "2", "NC", "no_connect")]}), [])


if __name__ == "__main__":
    unittest.main()
