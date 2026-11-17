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
from detector_helpers import match_family, symbol_name  # noqa: E402
from domain_detectors import (  # noqa: E402
    detect_isolation_barriers, detect_lvds_interfaces, detect_reset_supervisors, detect_rf_chains,
    detect_sensor_interfaces, detect_wireless_modules, suggest_certifications)
from validation_detectors import _is_regulator_like  # noqa: E402

# KiCad rescue names: KiCad 4/5 "<name>-RESCUE-<project>", and "<name>-<lib>" in a
# "<project>-rescue" library (rescued twice: "<name>-<lib>-<project>-rescue").
MCP73833_RESCUED = "ESP32-EVB_Rev_C-rescue:MCP73833(MSOP10)-RESCUE-ESP32-EVB_Rev_B"
TCA8418_RESCUED = "kb5-rescue:TCA8418-tca8418-ESP32-S2-WROOM-rescue"
KEY_SWITCH_RESCUED = "kb5-rescue:SW_Push_45deg-sw_push_45deg-ESP32-S2-WROOM-rescue"


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

    def test_library_nickname_is_not_read(self):
        self.assertIsNone(match_family({"value": "Q", "lib_id": "ab_parts:R"}, self.FAMS))

    def test_rescue_suffix_is_not_read(self):
        self.assertIsNone(match_family({"value": "Q", "lib_id": "p-rescue:R-RESCUE-ab_board"}, self.FAMS))
        self.assertIsNone(match_family({"value": "Q", "lib_id": "p-rescue:R-lib-xy_board-rescue"}, self.FAMS))
        self.assertEqual(match_family({"value": "Q", "lib_id": "p-rescue:XY1-RESCUE-board"}, self.FAMS), "c")


class SymbolName(unittest.TestCase):
    def test_kicad5_rescue_suffix_is_dropped(self):
        self.assertEqual(symbol_name(MCP73833_RESCUED), "MCP73833(MSOP10)")

    def test_twice_rescued_symbol_keeps_its_first_token(self):
        self.assertEqual(symbol_name(TCA8418_RESCUED), "TCA8418")
        self.assertEqual(symbol_name(
            "ESP32-GATEWAY_Rev_I-rescue:+3.3V-OLIMEX_Power-ESP32-GATEWAY_Rev_G-rescue"), "+3.3V")

    def test_symbol_without_a_rescue_suffix_reads_as_before(self):
        self.assertEqual(symbol_name("RF_Module:ESP32-WROOM-32"), "ESP32-WROOM-32")
        self.assertEqual(symbol_name("Smogomierz1-rescue:NodeMCU_1.0_(ESP-12E)-ESP8266"),
                         "NodeMCU_1.0_(ESP-12E)-ESP8266")
        self.assertEqual(symbol_name("GPS02A-rescue:NEO-M8P-RF_GPS"), "NEO-M8P-RF_GPS")
        self.assertEqual(symbol_name("Rescue_Parts:LM1117-3.3"), "LM1117-3.3")
        self.assertEqual(symbol_name("DDR:MT41K128M16JT-125:K"), "MT41K128M16JT-125:K")
        self.assertEqual(symbol_name("TPS22918"), "TPS22918")
        self.assertEqual(symbol_name(""), "")


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

    def test_part_in_a_radio_named_library_is_not_a_radio(self):
        out = detect_wireless_modules(_ctx([_comp("U1", "CH340C", "ESP32-DevKitC:CH340C"),
                                            _comp("U2", "AP2112K-3.3", "Seeed_nRF52840:AP2112K-3.3")]))
        self.assertEqual(out, [])

    def test_radio_modules_named_only_by_module_name_keep_their_family(self):
        out = detect_wireless_modules(_ctx([_comp("U1", "ESP-12F", "ESP8266:ESP-12F"),
                                            _comp("U2", "ESP-01", "ESP8266:ESP-01"),
                                            _comp("U3", "WT32-ETH01", "WT32:WT32-ETH01"),
                                            _comp("U4", "MAX-M8Q", "u-blox_GPS:MAX-M8Q")]))
        self.assertEqual([(w["reference"], w["wireless_type"]) for w in out],
                         [("U1", "wifi_ble"), ("U2", "wifi_ble"), ("U3", "wifi_ble"), ("U4", "gps")])

    def test_certification_names_the_radio_not_a_part_in_its_library(self):
        ctx = _ctx([_comp("R12", "0E", "ESP32-S3_DB:R_Small_US", ctype="resistor"),
                    _comp("U1", "ESP32-S3FH4R2", "ESP32-S3_DB:ESP32-S3")])
        reasons = [s["reason"] for s in suggest_certifications(ctx, {}) if s["standard"] == "FCC Part 15"]
        self.assertEqual(reasons, ["Wireless module detected: U1"])

    def test_certification_skips_a_rescue_power_symbol_before_the_module(self):
        ctx = _ctx([_comp("#PWR042", "+3.3V",
                          "ESP32-GATEWAY_Rev_I-rescue:+3.3V-OLIMEX_Power-ESP32-GATEWAY_Rev_G-rescue",
                          ctype="power_symbol"),
                    _comp("U3", "ESP32-WROOM-32E-N4", "RF_Module:ESP32-WROOM-32E")])
        reasons = [s["reason"] for s in suggest_certifications(ctx, {}) if s["standard"] == "FCC Part 15"]
        self.assertEqual(reasons, ["Wireless module detected: U3"])

    def test_certification_does_not_name_a_connector_from_a_radio_library(self):
        ctx = _ctx([_comp("J9", "USB_A", "KXKM_ESP32_battery_management_board-rescue:"
                          "USB_A-Connector-KXKM_ESP32_battery_management_board-rescue", ctype="connector")])
        self.assertEqual([s for s in suggest_certifications(ctx, {}) if s["standard"] == "FCC Part 15"], [])

    def test_certification_names_a_radio_board_typed_other(self):
        ctx = _ctx([_comp("ESP32_QT_PY1", "microcontroller", "!RCMhardware:ESP32_QT_PY", ctype="other")])
        reasons = [s["reason"] for s in suggest_certifications(ctx, {}) if s["standard"] == "FCC Part 15"]
        self.assertEqual(reasons, ["Wireless module detected: ESP32_QT_PY1"])

    def test_certification_names_a_bare_soc_typed_other(self):
        ctx = _ctx([_comp("U1", "ESP32-S3", "MCU_Espressif:ESP32-S3", ctype="other")])
        reasons = [s["reason"] for s in suggest_certifications(ctx, {}) if s["standard"] == "FCC Part 15"]
        self.assertEqual(reasons, ["Wireless module detected: U1"])

    def test_certification_names_the_module_wl001_found(self):
        # The radio word is only on the antenna connector; the cellular module is the radio.
        ctx = _ctx([_comp("ANT1", "U.FL-R-SMT-1", "NB-IoT-DevKit_Rev_D:WIFI_ANT_ESP8266", ctype="connector"),
                    _comp("U6", "Quectel_NB-IoT_BC66_Module", "OLIMEX_RF:BC66")])
        reasons = [s["reason"] for s in suggest_certifications(ctx, {"wireless_modules": [{"reference": "U6"}]})
                   if s["standard"] == "FCC Part 15"]
        self.assertEqual(reasons, ["Wireless module detected: U6"])

    def test_certification_prefers_the_radio_named_module_among_wl001_finds(self):
        ctx = _ctx([_comp("ANT1", "WIFI_ANT", "ESP32-PRO_Rev_B1:WIFI_ANT_ESP8266", ctype="connector"),
                    _comp("U5", "ESP32-D0WDQ6", "ESP32-PRO_Rev_B1:ESP32-D0WDQ6"),
                    _comp("U6", "ATECC508A-SSHDA-T", "ESP32-PRO_Rev_B1:ATECC508A")])
        found = {"wireless_modules": [{"reference": "U6"}, {"reference": "U5"}]}
        reasons = [s["reason"] for s in suggest_certifications(ctx, found) if s["standard"] == "FCC Part 15"]
        self.assertEqual(reasons, ["Wireless module detected: U5"])

    def test_certification_prefers_a_radio_value_over_a_rescue_symbol_name(self):
        # A KiCad 5 rescue symbol carries the board's name; the charger is not the radio.
        ctx = _ctx([_comp("U1", "MCP73833(MSOP10)", "ESP32-EVB_Rev_C-rescue:MCP73833(MSOP10)-RESCUE-ESP32-EVB_Rev_B"),
                    _comp("U3", "ESP-WROOM-32", "ESP32-EVB_Rev_C:ESP-WROOM-32")])
        found = {"wireless_modules": [{"reference": "U1"}, {"reference": "U3"}]}
        reasons = [s["reason"] for s in suggest_certifications(ctx, found) if s["standard"] == "FCC Part 15"]
        self.assertEqual(reasons, ["Wireless module detected: U3"])

    def test_rescued_part_named_after_a_radio_board_is_not_a_radio(self):
        out = detect_wireless_modules(_ctx([_comp("U1", "MCP73833", MCP73833_RESCUED),
                                            _comp("U2", "TCA8418", TCA8418_RESCUED)]))
        self.assertEqual(out, [])

    def test_rescued_radio_modules_keep_their_family(self):
        out = detect_wireless_modules(_ctx([
            _comp("U1", "NodeMCU V3", "Smogomierz1-rescue:NodeMCU_1.0_(ESP-12E)-ESP8266"),
            _comp("U2", "NEO-M8P", "GPS02A-rescue:NEO-M8P-RF_GPS")]))
        self.assertEqual([(w["reference"], w["wireless_type"]) for w in out],
                         [("U1", "wifi_ble"), ("U2", "gps")])

    def test_key_switches_from_a_rescue_library_are_not_an_rf_chain(self):
        keys = [_comp(f"K{i}", "SW_Push_45deg", KEY_SWITCH_RESCUED, ctype="other") for i in range(1, 4)]
        self.assertEqual(detect_rf_chains(_ctx(keys)), [])

    def test_certification_does_not_name_a_key_switch_from_a_rescue_library(self):
        ctx = _ctx([_comp("K1", "SW_Push_45deg", KEY_SWITCH_RESCUED, ctype="other")])
        self.assertEqual([s for s in suggest_certifications(ctx, {}) if s["standard"] == "FCC Part 15"], [])

    def test_esp32_keeps_both_rf_transceiver_and_wifi_ble(self):
        esp = _comp("U1", "ESP32-WROOM-32", "RF_Module:ESP32-WROOM-32")
        rf = detect_rf_chains(_ctx([esp, _comp("U2", "SKY13350", "RF_Switch:SKY13350")]))
        self.assertEqual([c["reference"] for c in rf[0]["transceivers"]], ["U1"])
        wl = detect_wireless_modules(_ctx([esp]))
        self.assertEqual([(w["reference"], w["wireless_type"]) for w in wl], [("U1", "wifi_ble")])


class SymbolNameReaders(unittest.TestCase):
    def _isolation_refs(self, comps):
        nets = {n: {"name": n, "point_count": 0, "no_connect": False, "has_pwr_flag": False,
                    "labels": [], "pins": []} for n in ("GND", "GND_ISO")}
        ctx = build_analysis_context(comps, nets, {}, known_power_rails={"GND", "GND_ISO"})
        return [[c["reference"] for c in b["isolation_components"]]
                for b in detect_isolation_barriers(ctx)]

    def test_isolation_stem_in_a_library_nickname_is_not_an_isolation_part(self):
        self.assertEqual(self._isolation_refs([
            _comp("U1", "LM1117-3.3", "adum_breakout:LM1117-3.3"),
            _comp("PS1", "CRE1S0505SC", "Converter_DCDC_Isolated:CRE1S0505SC"),
            _comp("U2", "ADuM1201", "Isolator:ADuM1201")]), [["PS1", "U2"]])

    def test_load_switch_stem_in_a_library_nickname_is_not_regulator_like(self):
        ctx = _ctx([_comp("U1", "ATtiny85", "sy6280_breakout:ATtiny85"),
                    _comp("U2", "X", "Power_Management:TPS22918")])
        self.assertFalse(_is_regulator_like(ctx, "U1"))
        self.assertTrue(_is_regulator_like(ctx, "U2"))


if __name__ == "__main__":
    unittest.main()
