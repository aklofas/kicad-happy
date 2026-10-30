# tools/tests/test_usb_type_c_detect.py
"""A USB connector is Type-C by a token-bounded Type-C name (value, footprint or lib_id) or by a
CC pin; the CC pull-down checks need the CC pins on the symbol. USB Type-C sink: Rd = 5.1 kOhm
from each of CC1 and CC2 to GND."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
from schematic.system_analyses import analyze_usb_compliance  # noqa: E402


def _conn(ref, value, lib_id, footprint="", pins=()):
    return {"reference": ref, "type": "connector", "value": value, "lib_id": lib_id,
            "footprint": footprint, "pins": [{"number": n, "name": nm} for n, nm in pins]}


def _res(ref, value):
    return {"reference": ref, "type": "resistor", "value": value, "lib_id": "Device:R",
            "footprint": "", "pins": [{"number": "1", "name": "~"}, {"number": "2", "name": "~"}]}


def _run(components, nets):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn)
                                    for r, p, pn in pins],
                "point_count": 0, "no_connect": False, "labels": []}
            for n, pins in nets.items()}
    ctx = build_analysis_context(components, full, {}, known_power_rails={"VBUS"})
    return analyze_usb_compliance(ctx, {})


USB2_PINS = (("1", "VBUS"), ("2", "D-"), ("3", "D+"), ("4", "GND"))


def _usb2_nets(ref):
    return {"VBUS": [(ref, "1", "VBUS")], "USB_DM": [(ref, "2", "D-")],
            "USB_DP": [(ref, "3", "D+")], "GND": [(ref, "4", "GND")]}


def _uc003(result):
    return [f for f in result.get("findings", []) if f["rule_id"] == "UC-003"]


class TypeCDetection(unittest.TestCase):
    def test_reporter_usb_b_with_usb_conn_lib_is_not_type_c(self):
        # GitHub #61: 4-pin USB_B whose lib_id Fixture:USB_CONN contains "USB_C".
        j1 = _conn("J1", "USB_B", "Fixture:USB_CONN", pins=USB2_PINS)
        r = _run([j1], _usb2_nets("J1"))
        conn = r["connectors"][0]
        self.assertFalse(conn["is_type_c"])
        self.assertNotIn("cc1_pulldown_5k1", conn["checks"])
        self.assertNotIn("usb_c_cc_status", conn)
        self.assertEqual(_uc003(r), [])

    def test_usb4105_by_cc_pins_runs_cc_checks(self):
        # GCT USB4105: no Type-C token anywhere ("USB_CONNECTOR" is not one); CC1/CC2 pins.
        # CC1 has 5.1k to GND, CC2 floats on the symbol: the sink is missing Rd on CC2.
        j2 = _conn("J2", "USB4105-GF-A", "Connector:USB_CONNECTOR_USB4105-GF-A",
                   "USB4105-GF-A:GCT_USB4105-GF-A",
                   pins=(*USB2_PINS, ("A5", "CC1"), ("B5", "CC2")))
        nets = _usb2_nets("J2")
        nets["CC1"] = [("J2", "A5", "CC1"), ("R1", "1", "~")]
        nets["GND"].append(("R1", "2", "~"))
        r = _run([j2, _res("R1", "5.1k")], nets)
        conn = r["connectors"][0]
        self.assertTrue(conn["is_type_c"])
        self.assertEqual(conn["checks"]["cc1_pulldown_5k1"], "pass")
        self.assertEqual(conn["checks"]["cc2_pulldown_5k1"], "fail")
        self.assertEqual([f["summary"] for f in _uc003(r)], ["CC2 missing 5.1k pull-down at J2"])

    def test_type_c_by_name_without_cc_pins_is_one_info(self):
        # Seeed XIAO-style USB2.0-TYPE-C symbol that carries no CC pins.
        j3 = _conn("J3", "USB2.0-TYPE-C", "Seeed_Studio_XIAO:USB2.0-TYPE-C", pins=USB2_PINS)
        r = _run([j3], _usb2_nets("J3"))
        conn = r["connectors"][0]
        self.assertTrue(conn["is_type_c"])
        self.assertNotIn("cc1_pulldown_5k1", conn["checks"])
        self.assertNotIn("cc2_pulldown_5k1", conn["checks"])
        self.assertEqual(conn["checks"]["cc_pins"], "info")
        self.assertEqual(conn["usb_c_cc_status"]["status"], "skipped")
        self.assertEqual(conn["usb_c_cc_status"]["note"],
                         "CC pins not on this symbol; CC checks skipped")
        # False-output pin: no CC failure reported for this connector.
        self.assertEqual(_uc003(r), [])

    def test_usb_names_that_are_not_type_c(self):
        for value, lib in (("USB_CAN_SW", "Connector_Generic:Conn_02x03_Odd_Even"),
                           ("USB_COMBINED", "Connector:USB_A"),
                           ("USBCON", "components:USBCONN")):
            with self.subTest(value=value):
                j = _conn("J9", value, lib, pins=USB2_PINS)
                r = _run([j], _usb2_nets("J9"))
                self.assertFalse(r["connectors"][0]["is_type_c"])
                self.assertEqual(_uc003(r), [])

    def test_corpus_type_c_spellings_still_match(self):
        # Real spellings from the corpus; each is a Type-C part even with no CC pins.
        for value, lib, fp in (
                ("USB_C_Receptacle_USB2.0", "Connector:USB_C_Receptacle_USB2.0", ""),
                ("USB-C", "Connector:USB_C_Plug_USB2.0", ""),
                ("USB-C", "Connector_Generic:Conn_01x04", ""),
                ("TYPE-C-31-M-12", "MyLib:USB_PORT", ""),
                ("HRO-TYPE-C-31-M-12", "USBType-C:HRO-TYPE-C-31-M-12", ""),
                ("USB4105", "Connector_Generic:Conn_01x04",
                 "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A"),
                ("TYPE-C 16PIN 2MD(073)", "easyeda2kicad:TYPE-C16PIN2MD(073)",
                 "easyeda2kicad:USB-C-SMD_TYPE-C-6PIN-2MD-073"),
                ("USBC", "usbc:1054500101", ""),
                ("USB TypeC", "Connector_Generic:Conn_01x04", ""),
                ("USB_TYPE_C", "Connector_Generic:Conn_01x04", "")):
            with self.subTest(value=value, lib=lib, fp=fp):
                j = _conn("J5", value, lib, fp, pins=USB2_PINS)
                r = _run([j], _usb2_nets("J5"))
                self.assertTrue(r["connectors"][0]["is_type_c"])

    def test_cc_pin_name_variants(self):
        # Pin names carry the receptacle contact before the function (A5/CC1, B5/CC2) or a
        # subscript (CC_{1}); a plug has one CC pin. VCC is not a CC pin.
        for cc1, cc2 in (("A5/CC1", "B5/CC2"), ("CC_{1}", "CC_{2}"), ("CC", None)):
            with self.subTest(cc1=cc1):
                pins = [*USB2_PINS, ("A5", cc1)] + ([("B5", cc2)] if cc2 else [])
                j = _conn("J6", "USB_conn", "MyLib:USB_PORT", pins=pins)
                r = _run([j], _usb2_nets("J6"))
                self.assertTrue(r["connectors"][0]["is_type_c"])
        j = _conn("J7", "USB_conn", "MyLib:USB_PORT", pins=(*USB2_PINS, ("5", "VCC")))
        r = _run([j], _usb2_nets("J7"))
        self.assertFalse(r["connectors"][0]["is_type_c"])


if __name__ == "__main__":
    unittest.main()
