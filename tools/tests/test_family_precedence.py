# tools/tests/test_family_precedence.py
"""A part's family within one detector is the family of its longest keyword, read from the part
number first, then the value, then the library id; a tie between families leaves it unclassified.
Each detector ranks only its own families, so a part can still be both an RF transceiver and a
WiFi/BLE module."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
from detector_helpers import match_family  # noqa: E402
from domain_detectors import (  # noqa: E402
    detect_lvds_interfaces, detect_reset_supervisors, detect_rf_chains,
    detect_sensor_interfaces, detect_wireless_modules)


def _comp(ref, value, lib_id, mpn="", ctype="ic"):
    return {"reference": ref, "type": ctype, "value": value, "lib_id": lib_id, "mpn": mpn,
            "pins": []}


def _ctx(components):
    return build_analysis_context(components, {}, {})


class MatchFamily(unittest.TestCase):
    FAMS = {"a": ("ab",), "b": ("abc",), "c": ("xy",)}

    def test_longest_keyword_wins(self):
        self.assertEqual(match_family({"value": "ABC1"}, self.FAMS), "b")

    def test_tie_between_families_is_none(self):
        self.assertIsNone(match_family({"value": "AB XY"}, self.FAMS))

    def test_part_number_before_value_before_lib_id(self):
        self.assertEqual(match_family({"mpn": "XY1", "value": "ABC", "lib_id": "ab"}, self.FAMS), "c")
        self.assertEqual(match_family({"mpn": "Q", "value": "AB", "lib_id": "xy"}, self.FAMS), "a")
        self.assertEqual(match_family({"mpn": "", "value": "Q", "lib_id": "lib:XY"}, self.FAMS), "c")

    def test_no_hit_is_none(self):
        self.assertIsNone(match_family({"value": "Q", "lib_id": "R"}, self.FAMS))


class DetectorFamilies(unittest.TestCase):
    def test_lis3mdl_is_magnetic_not_motion(self):
        out = detect_sensor_interfaces(_ctx([_comp("U1", "LIS3MDL", "Sensor_Magnetic:LIS3MDL")]))
        self.assertEqual([(s["ref"], s["type"]) for s in out], [("U1", "magnetic")])

    def test_tps3823_is_a_watchdog(self):
        out = detect_reset_supervisors(_ctx([_comp("U1", "TPS3823-33", "Power_Supervisor:TPS3823")]))
        self.assertEqual([(r["ref"], r["type"]) for r in out], [("U1", "watchdog")])

    def test_lpc_lqfp48_part_number_is_not_a_bd48_supervisor(self):
        out = detect_reset_supervisors(_ctx([_comp("U1", "LPC11U1X", "LPC11U1X", mpn="LPC11U14FBD48/201")]))
        self.assertEqual(out, [])
        out = detect_reset_supervisors(_ctx([_comp("U2", "BD48K60G", "Lib:BD48K60G")]))
        self.assertEqual([(r["ref"], r["type"]) for r in out], [("U2", "voltage_supervisor")])

    def test_stm32wle5_is_lora(self):
        out = detect_wireless_modules(_ctx([_comp("U1", "STM32WLE5JC", "MCU_ST_STM32WL:STM32WLE5JCIx")]))
        self.assertEqual([(w["reference"], w["wireless_type"]) for w in out], [("U1", "lora")])

    def test_mpn_names_the_family_when_the_value_does_not(self):
        out = detect_wireless_modules(_ctx([_comp("U1", "X", "Lib:Module", mpn="RFM95W")]))
        self.assertEqual([(w["reference"], w["wireless_type"]) for w in out], [("U1", "lora")])

    def test_hmc544_is_an_rf_switch(self):
        out = detect_rf_chains(_ctx([_comp("U1", "HMC544AE", "RF_Switch:HMC544AE"),
                                     _comp("U2", "SKY13350", "RF_Switch:SKY13350")]))
        self.assertEqual(len(out), 1)
        self.assertEqual(sorted(c["reference"] for c in out[0]["switches"]), ["U1", "U2"])
        self.assertEqual(out[0]["attenuators"], [])
        self.assertEqual(out[0]["component_roles"]["U1"], "switch")

    def test_hmc5883l_is_not_an_rf_amplifier(self):
        out = detect_rf_chains(_ctx([_comp("U1", "HMC5883L", "Sensor_Magnetic:HMC5883L"),
                                     _comp("U2", "SKY13350", "RF_Switch:SKY13350")]))
        self.assertEqual(out, [])

    def test_deserializer_word_names_the_role(self):
        out = detect_lvds_interfaces(_ctx([_comp("U1", "DS90UB924 deserializer", "Interface:LVDS")]))
        self.assertEqual([(r["reference"], r["role"]) for r in out], [("U1", "deserializer")])

    def test_esp32_keeps_both_rf_transceiver_and_wifi_ble(self):
        esp = _comp("U1", "ESP32-WROOM-32", "RF_Module:ESP32-WROOM-32")
        rf = detect_rf_chains(_ctx([esp, _comp("U2", "SKY13350", "RF_Switch:SKY13350")]))
        self.assertEqual([c["reference"] for c in rf[0]["transceivers"]], ["U1"])
        wl = detect_wireless_modules(_ctx([esp]))
        self.assertEqual([(w["reference"], w["wireless_type"]) for w in wl], [("U1", "wifi_ble")])


if __name__ == "__main__":
    unittest.main()
