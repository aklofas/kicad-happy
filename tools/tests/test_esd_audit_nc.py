"""KiCad 5 schematics type a no-connect pin 'unconnected'. The ESD audits (EP-AUD, EG-001) treat
it like a KiCad 6+ 'no_connect' pin: alone on its net it is not an unprotected signal. A
passive pin alone on its net is still a signal."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
from domain_detectors import audit_esd_protection  # noqa: E402
import cross_analysis as ca  # noqa: E402

_CONN = {"reference": "J1", "type": "connector", "value": "USB_B",
         "lib_id": "conn:USB_B"}


def _nets(lone_pin_type):
    return {
        "DP": [("J1", "3", "D+", "bidirectional"), ("U1", "5", "USB_DP", "bidirectional")],
        "Net-(J1-Pad5)": [("J1", "5", "SHIELD", lone_pin_type)],
    }


def _ep_aud(nets):
    comps = [dict(_CONN), {"reference": "U1", "type": "ic", "value": "MCU"}]
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    return audit_esd_protection(build_analysis_context(comps, full, {}, known_power_rails=set()), [])


def _eg001(nets):
    pin_nets = {p: n for n, pins in nets.items() for r, p, _, _ in pins if r == "J1"}
    sch = {"components": [dict(_CONN, pin_nets=pin_nets), {"reference": "U1", "type": "ic"}],
           "nets": {n: {"pins": [{"component": r, "pin_number": p, "pin_type": t}
                                 for r, p, _, t in pins]} for n, pins in nets.items()},
           "findings": []}
    return ca.check_esd_coverage_gaps(sch, None)


class EpAudLegacyNoConnect(unittest.TestCase):
    def test_lone_unconnected_pin_is_not_a_signal_net(self):
        f = _ep_aud(_nets("unconnected"))
        self.assertEqual([(x["signal_nets"], x["unprotected_nets"]) for x in f], [(["DP"], ["DP"])])

    def test_connector_with_only_unconnected_pins_gets_no_record(self):
        self.assertEqual(_ep_aud({"Net-(J1-Pad5)": [("J1", "5", "~", "unconnected")]}), [])

    def test_lone_passive_pin_stays_a_signal_net(self):
        f = _ep_aud(_nets("passive"))
        self.assertEqual([x["signal_nets"] for x in f], [["DP", "Net-(J1-Pad5)"]])


class Eg001LegacyNoConnect(unittest.TestCase):
    def test_lone_unconnected_pin_is_not_a_gap(self):
        f = _eg001(_nets("unconnected"))
        self.assertEqual([x["nets"] for x in f], [["DP"]])

    def test_connector_with_only_unconnected_pins_gets_no_finding(self):
        self.assertEqual(_eg001({"Net-(J1-Pad5)": [("J1", "5", "~", "unconnected")]}), [])

    def test_lone_passive_pin_is_still_a_gap(self):
        f = _eg001(_nets("passive"))
        self.assertEqual([x["nets"] for x in f], [["DP", "Net-(J1-Pad5)"]])


if __name__ == "__main__":
    unittest.main()
