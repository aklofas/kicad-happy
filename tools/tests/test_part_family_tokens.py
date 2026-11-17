# tools/tests/test_part_family_tokens.py
"""Part-family words matched as words, not as substrings: an RF matching network starts
at an antenna or a coaxial RF connector, not at a C_Small whose name contains "sma"."""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
import domain_detectors as dd  # noqa: E402
from detection_schema import compute_detection_id  # noqa: E402
from finding_schema import assign_finding_ids, sort_findings  # noqa: E402


def _ctx(components, nets, rails=("+3V3", "GND")):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    for c in components:
        c.setdefault("lib_id", "")
        c.setdefault("pins", [])
        c.setdefault("footprint", "")
    return build_analysis_context(components, full, {}, known_power_rails=set(rails))


def _p(ref, pin):
    return (ref, pin, "~", "passive")


def _rf_board(port_lib, port_footprint="", port_ref="J1", shunt_lib="Device:C"):
    # port -> 3.9 nH series L -> SX1276 RFO, 1.5 pF shunt C at the port
    comps = [{"reference": port_ref, "type": "connector", "value": "RF", "lib_id": port_lib,
              "footprint": port_footprint},
             {"reference": "L1", "type": "inductor", "value": "3.9nH", "lib_id": "Device:L"},
             {"reference": "C1", "type": "capacitor", "value": "1.5pF", "lib_id": shunt_lib},
             {"reference": "U1", "type": "ic", "value": "SX1276", "lib_id": "RF_Module:SX1276"}]
    nets = {"ANT": [(port_ref, "1", "In", "passive"), _p("L1", "1"), _p("C1", "1")],
            "RFO": [_p("L1", "2"), ("U1", "5", "RFO", "output")],
            "GND": [(port_ref, "2", "Ext", "passive"), _p("C1", "2")]}
    return _ctx(comps, nets)


def _antennas(ctx):
    return sorted(f["antenna"] for f in dd.detect_rf_matching(ctx))


class RfMatchingSeeds(unittest.TestCase):
    def test_small_symbol_is_not_an_antenna(self):
        # The only seed candidate is C1 (Device:C_Small); J1 is a plain 2-pin connector
        self.assertEqual(_antennas(_rf_board("Connector:Conn_01x02", shunt_lib="Device:C_Small")), [])

    def test_sma_connector_keeps_matching_by_word(self):
        for lib in ("Connector:SMA_EDGE", "RF:Conn_SMA", "SMA-J-P-H-ST-TH1:SMA-J-P-H-ST-TH1"):
            with self.subTest(lib=lib):
                self.assertEqual(_antennas(_rf_board(lib)), ["J1"])

    def test_sma_package_diode_word_is_not_sma(self):
        # SMAJ: a letter after "sma" makes another word
        self.assertEqual(_antennas(_rf_board("Diode:SMAJ5.0A")), [])

    def test_coaxial_footprint_is_an_rf_port(self):
        for fp in ("Connector_Coaxial:SMA_Amphenol_132134_Vertical",
                   "Connector_Coaxial:U.FL_Hirose_U.FL-R-SMT-1_Vertical",
                   "Connector_Coaxial:MMCX_Molex_73415-0961_Horizontal_1.0mm-PCB"):
            with self.subTest(footprint=fp):
                self.assertEqual(_antennas(_rf_board("Connector:Conn_Coaxial", fp)), ["J1"])

    def test_bnc_footprint_is_not_an_rf_port(self):
        self.assertEqual(_antennas(_rf_board("Connector:Conn_Coaxial",
                                             "Connector_Coaxial:BNC_Amphenol_B6252HB-NPP3G-50_Horizontal")), [])

    def test_antenna_reference_still_seeds(self):
        self.assertEqual(_antennas(_rf_board("Device:Antenna", port_ref="AE1")), ["AE1"])


def _two_port_board(ports=("J1", "J2")):
    # J1 -> L1 3.9 nH -> U1 SX1276 and J2 -> L2 2.2 nH -> U2 CC1101, each with a shunt C
    fp = "Connector_Coaxial:SMA_Amphenol_132134_Vertical"
    parts = {"J1": ("1", "3.9nH", "1.5pF", "SX1276", "RF_Module:SX1276", "5"),
             "J2": ("2", "2.2nH", "1pF", "CC1101", "RF:CC1101", "12")}
    comps, nets = [], {"GND": []}
    for port in ports:
        n, lval, cval, ic, ic_lib, rf_pin = parts[port]
        comps += [{"reference": port, "type": "connector", "value": "RF", "lib_id": "Connector:Conn_Coaxial",
                   "footprint": fp},
                  {"reference": f"L{n}", "type": "inductor", "value": lval, "lib_id": "Device:L"},
                  {"reference": f"C{n}", "type": "capacitor", "value": cval, "lib_id": "Device:C"},
                  {"reference": f"U{n}", "type": "ic", "value": ic, "lib_id": ic_lib}]
        nets[f"ANT{n}"] = [(port, "1", "In", "passive"), _p(f"L{n}", "1"), _p(f"C{n}", "1")]
        nets[f"RFO{n}"] = [_p(f"L{n}", "2"), (f"U{n}", rf_pin, "RF", "output")]
        nets["GND"] += [(port, "2", "Ext", "passive"), _p(f"C{n}", "2")]
    return _ctx(comps, nets)


def _finding_ids(ctx):
    findings = dd.detect_rf_matching(ctx)
    for f in findings:
        f["detection_id"] = compute_detection_id(f, "rf_matching")
    assign_finding_ids(findings, "schematic")
    return {f["antenna"]: f["finding_id"] for f in findings}


class RfMatchingIdentity(unittest.TestCase):
    def test_two_networks_get_distinct_ids(self):
        ids = _finding_ids(_two_port_board())
        self.assertEqual(sorted(ids), ["J1", "J2"])
        self.assertNotIn("#", ids["J1"] + ids["J2"])
        self.assertNotEqual(ids["J1"], ids["J2"])

    def test_id_does_not_depend_on_other_networks(self):
        # Removing the J1 network leaves the J2 finding's id as it was
        self.assertEqual(_finding_ids(_two_port_board(ports=("J2",)))["J2"], _finding_ids(_two_port_board())["J2"])

    def test_shared_antenna_is_numbered_only_among_its_duplicates(self):
        # An unannotated duplicate reference: a second "J1" with its own network
        def ids():
            findings = dd.detect_rf_matching(_two_port_board())
            dup = copy.deepcopy(next(f for f in findings if f["antenna"] == "J2"))
            dup["antenna"] = "J1"
            findings.append(dup)
            for f in findings:
                f["detection_id"] = compute_detection_id(f, "rf_matching")
            sort_findings(findings)
            assign_finding_ids(findings, "schematic")
            return [(f["antenna"], f["finding_id"]) for f in findings]
        first = ids()
        self.assertEqual(first, ids())
        j1 = sorted(fid for ant, fid in first if ant == "J1")
        self.assertEqual(j1, [j1[0], j1[0] + "#1"])
        self.assertEqual([fid for ant, fid in first if ant == "J2"], [_finding_ids(_two_port_board())["J2"]])


if __name__ == "__main__":
    unittest.main()
