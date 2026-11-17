# tools/tests/test_certification_names.py
"""Certification hints name the parts they are about: an RF chain by its transceivers, or
by its parts when it has none, and an Espressif module named only WROOM or WROVER is a
wireless module."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
import domain_detectors as dd  # noqa: E402

FCC = "FCC Part 15"
CE_RED = "CE RED (Radio Equipment Directive)"


def _ctx(components):
    for c in components:
        c.setdefault("pins", [])
        c.setdefault("footprint", "")
    return build_analysis_context(components, {}, {}, known_power_rails={"+3V3", "GND"})


def _cert(signal, components=()):
    return {s["standard"]: s for s in dd.suggest_certifications(_ctx(list(components)), signal)}


def _chain(transceivers, components):
    return {"transceivers": [{"reference": r, "value": "SX1276", "lib_id": ""} for r in transceivers],
            "components": list(components)}


class CertificationNames(unittest.TestCase):
    def test_rf_chain_names_its_transceiver(self):
        s = _cert({"rf_chains": [_chain(["U3"], ["U3", "U4"])]})
        self.assertEqual(s[FCC]["components"], ["U3"])
        self.assertEqual(s[CE_RED]["components"], ["U3"])

    def test_rf_chain_without_transceiver_names_its_parts(self):
        s = _cert({"rf_chains": [_chain([], ["U3", "U4"])]})
        self.assertEqual(s[FCC]["components"], ["U3", "U4"])
        self.assertEqual(s[CE_RED]["components"], ["U3", "U4"])

    def test_parts_shared_by_chains_are_named_once(self):
        s = _cert({"rf_chains": [_chain(["U3"], ["U3", "U4"]), _chain([], ["U4", "U5"])]})
        self.assertEqual(s[FCC]["components"], ["U3", "U4", "U5"])

    def test_wroom_module_is_a_radio(self):
        comps = [{"reference": "M401", "type": "other", "value": "WROOM32", "lib_id": "esp32:WROOM32"}]
        self.assertEqual(_cert({}, comps)[FCC]["reason"], "Wireless module detected: M401")

    def test_wroom_and_wrover_modules_are_wifi_ble(self):
        for value in ("ESP-C3-WROOM-02", "WROVER-B"):
            with self.subTest(value=value):
                comps = [{"reference": "U1", "type": "ic", "value": value, "lib_id": "parts:" + value}]
                wl = dd.detect_wireless_modules(_ctx(comps))
                self.assertEqual([(w["reference"], w["wireless_type"]) for w in wl], [("U1", "wifi_ble")])

    def test_wroom_in_a_library_nickname_is_not_a_radio(self):
        comps = [{"reference": "U1", "type": "ic", "value": "AMS1117-3.3",
                  "lib_id": "wroom_parts:AMS1117-3.3"}]
        self.assertEqual(dd.detect_wireless_modules(_ctx(comps)), [])
        self.assertNotIn(FCC, _cert({}, comps))


if __name__ == "__main__":
    unittest.main()
