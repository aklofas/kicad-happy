# tools/tests/test_part_family_tokens.py
"""Part-family words matched as words, not as substrings: an RF matching network starts
at an antenna or a coaxial RF connector, not at a C_Small whose name contains "sma"."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
import domain_detectors as dd  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
