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


def _res(ref, value, dnp=False):
    return {"reference": ref, "type": "resistor", "value": value, "lib_id": "Device:R",
            "footprint": "", "dnp": dnp,
            "pins": [{"number": "1", "name": "~"}, {"number": "2", "name": "~"}]}


def _run(components, nets, rails=None):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn)
                                    for r, p, pn in pins],
                "point_count": 0, "no_connect": False, "labels": []}
            for n, pins in nets.items()}
    ctx = build_analysis_context(components, full, {}, known_power_rails={"VBUS", "+3V3", "+1V1"},
                                 power_rails_config={"voltage_overrides": rails} if rails else None)
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
                         "no pin named CC/CC1/CC2 on this symbol; CC checks skipped")
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
        # subscript (CC_{1}); each side with 5.1k to GND passes. VCC is not a CC pin.
        for cc1, cc2 in (("A5/CC1", "B5/CC2"), ("CC_{1}", "CC_{2}"), ("CC1", "CC2")):
            with self.subTest(cc1=cc1):
                r = _cc_variant("J6", (("A5", cc1), ("B5", cc2)),
                                {"A5": ("R1", "5.1k", "GND"), "B5": ("R2", "5.1k", "GND")})
                conn = r["connectors"][0]
                self.assertTrue(conn["is_type_c"])
                self.assertEqual((conn["checks"]["cc1_pulldown_5k1"],
                                  conn["checks"]["cc2_pulldown_5k1"]), ("pass", "pass"))
                self.assertEqual(conn["usb_c_cc_status"]["issues"], [])
                self.assertEqual(_uc003(r), [])
        j = _conn("J7", "USB_conn", "MyLib:USB_PORT", pins=(*USB2_PINS, ("5", "VCC")))
        r = _run([j], _usb2_nets("J7"))
        self.assertFalse(r["connectors"][0]["is_type_c"])

    def test_plug_single_cc_is_one_side(self):
        # KiCad USB_C_Plug_USB2.0 has one CC pin (A5): one side, never two missing sides.
        r = _cc_variant("P1", (("A5", "CC"),), {"A5": ("R1", "5.1k", "GND")},
                        lib="Connector:USB_C_Plug_USB2.0")
        conn = r["connectors"][0]
        self.assertEqual(conn["checks"]["cc_pulldown_5k1"], "pass")
        self.assertNotIn("cc1_pulldown_5k1", conn["checks"])
        self.assertNotIn("cc2_pulldown_5k1", conn["checks"])
        self.assertEqual(conn["usb_c_cc_status"]["cc_net"], "NET_A5")
        self.assertEqual(conn["usb_c_cc_status"]["issues"], [])
        self.assertEqual(_uc003(r), [])
        r = _cc_variant("P1", (("A5", "CC"),), {}, lib="Connector:USB_C_Plug_USB2.0")
        self.assertEqual([f["summary"] for f in _uc003(r)], ["CC missing 5.1k pull-down at P1"])
        self.assertEqual(r["connectors"][0]["usb_c_cc_status"]["issues"], ["missing_cc_resistor"])


def _cc_variant(ref, cc_pins, wiring, lib="MyLib:USB_PORT", rails=None):
    """Connector with *cc_pins* (number, name); *wiring* maps a pin number to
    (resistor ref, value, far net). Each CC pin sits on net NET_<number>."""
    j = _conn(ref, "USB_conn", lib, pins=(*USB2_PINS, *cc_pins))
    comps, nets = [j], _usb2_nets(ref)
    for num, name in cc_pins:
        nets["NET_" + num] = [(ref, num, name)]
        if num in wiring:
            rref, value, far = wiring[num]
            comps.append(_res(rref, value))
            nets["NET_" + num].append((rref, "1", "~"))
            nets.setdefault(far, []).append((rref, "2", "~"))
    return _run(comps, nets, rails)


def _type_c_with(cc1, cc2, rails=None, dnp=()):
    """USB4105 with CC1/CC2 each wired through one resistor: (ref, value, far_net) or None."""
    j = _conn("J1", "USB4105-GF-A", "Connector:USB_C_Receptacle_USB2.0",
              pins=(*USB2_PINS, ("A5", "CC1"), ("B5", "CC2")))
    comps, nets = [j], _usb2_nets("J1")
    nets.setdefault("+3V3", [])
    for pin, num, spec in (("CC1", "A5", cc1), ("CC2", "B5", cc2)):
        nets[pin] = [("J1", num, pin)]
        if spec:
            ref, value, far = spec
            comps.append(_res(ref, value, dnp=ref in dnp))
            nets[pin].append((ref, "1", "~"))
            nets.setdefault(far, []).append((ref, "2", "~"))
    return _run(comps, nets, rails)


class CcResistorValues(unittest.TestCase):
    def _conn(self, r):
        return r["connectors"][0]

    def test_unreadable_rd_values_do_not_fail(self):
        # 5k1R 1% and 5.1kR are 5.1 kOhm Rd to GND; neither side may fail.
        r = _type_c_with(("R1", "5k1R 1%", "GND"), ("R2", "5.1kR", "GND"))
        c = self._conn(r)
        self.assertNotIn("fail", (c["checks"]["cc1_pulldown_5k1"], c["checks"]["cc2_pulldown_5k1"]))
        self.assertNotIn("missing_cc1_resistor", c["usb_c_cc_status"]["issues"])
        self.assertNotIn("missing_cc2_resistor", c["usb_c_cc_status"]["issues"])
        self.assertNotIn("wrong_cc_value", c["usb_c_cc_status"]["issues"])
        self.assertEqual(_uc003(r), [])

    def test_rd_written_in_the_symbol_name_is_read(self):
        r = _type_c_with(("R1", "R_5k1_0402", "GND"), ("R2", "5.1k,1%", "GND"))
        c = self._conn(r)
        self.assertNotIn("unread_resistors", c["usb_c_cc_status"])
        self.assertEqual(c["usb_c_cc_status"]["role"], "sink")
        self.assertEqual((c["checks"]["cc1_pulldown_5k1"], c["checks"]["cc2_pulldown_5k1"]),
                         ("pass", "pass"))
        self.assertEqual(_uc003(r), [])

    def test_plain_rd_value_is_unchanged(self):
        c = self._conn(_type_c_with(("R1", "5.1k", "GND"), ("R2", "5.1k", "GND")))
        self.assertEqual(c["usb_c_cc_status"]["role"], "sink")
        self.assertEqual(c["checks"]["cc1_pulldown_5k1"], "pass")

    def test_part_number_value_is_one_info(self):
        # ERA-6ARW512V is a Panasonic 5.1 kOhm part number: no number to read.
        r = _type_c_with(("R1", "5.1k", "GND"), ("R2", "ERA-6ARW512V", "GND"))
        c = self._conn(r)
        self.assertEqual(c["checks"]["cc1_pulldown_5k1"], "pass")
        self.assertEqual(c["checks"]["cc2_pulldown_5k1"], "info")
        unread = c["usb_c_cc_status"]["unread_resistors"]
        self.assertEqual(len(unread), 1)
        self.assertEqual((unread[0]["pin"], unread[0]["ref"], unread[0]["value"]),
                         ("CC2", "R2", "ERA-6ARW512V"))
        self.assertIn("J1", unread[0]["note"])
        self.assertEqual(c["usb_c_cc_status"]["issues"], [])
        self.assertEqual(_uc003(r), [])

    def test_spec_rp_pull_ups_to_vbus(self):
        # Rp to 5 V: 10 kOhm = 3.0 A, 22 kOhm = 1.5 A advertisement.
        for value in ("10k", "22k", "56k"):
            with self.subTest(value=value):
                r = _type_c_with(("R1", value, "VBUS"), ("R2", value, "VBUS"))
                c = self._conn(r)
                self.assertEqual(c["usb_c_cc_status"]["role"], "source")
                self.assertNotIn("wrong_cc_value", c["usb_c_cc_status"]["issues"])
                self.assertEqual(c["usb_c_cc_status"]["issues"], [])
                self.assertEqual(_uc003(r), [])

    def test_spec_rp_pull_up_to_3v3(self):
        # Rp to 3.3 V: 4.7 kOhm = 3.0 A advertisement.
        r = _type_c_with(("R1", "4.7k", "+3V3"), ("R2", "4.7k", "+3V3"))
        c = self._conn(r)
        self.assertNotIn("wrong_cc_value", c["usb_c_cc_status"]["issues"])
        self.assertEqual(c["usb_c_cc_status"]["issues"], [])
        self.assertEqual(_uc003(r), [])

    def test_rp_table_follows_a_known_rail(self):
        # 4.7 kOhm is an Rp only to 3.3 V; to a known 5 V VBUS it advertises nothing.
        rails = {"VBUS": 5.0, "+3V3": 3.3}
        r = _type_c_with(("R1", "4.7k", "+3V3"), ("R2", "4.7k", "+3V3"), rails)
        self.assertEqual(self._conn(r)["usb_c_cc_status"]["role"], "source")
        r = _type_c_with(("R1", "4.7k", "VBUS"), ("R2", "4.7k", "VBUS"), rails)
        self.assertNotEqual(self._conn(r)["usb_c_cc_status"]["role"], "source")

    def test_pull_up_to_the_connector_vbus_net(self):
        # A source with its 10 kOhm Rp (3.0 A) on the connector's unnamed VBUS net.
        j = _conn("J1", "GT-USB-7010ASV", "easyeda2kicad:GT-USB-7010ASV",
                  pins=(*USB2_PINS, ("A5", "CC1"), ("B5", "CC2")))
        nets = _usb2_nets("J1")
        nets["__unnamed_55"] = nets.pop("VBUS") + [("R1", "2", "~"), ("R2", "2", "~")]
        nets["CC1"] = [("J1", "A5", "CC1"), ("R1", "1", "~")]
        nets["CC2"] = [("J1", "B5", "CC2"), ("R2", "1", "~")]
        r = _run([j, _res("R1", "10k"), _res("R2", "10k")], nets)
        c = self._conn(r)
        self.assertEqual(c["usb_c_cc_status"]["role"], "source")
        self.assertEqual(c["usb_c_cc_status"]["issues"], [])
        self.assertEqual(_uc003(r), [])

    def test_rd_on_a_power_rail_is_not_rp(self):
        # 5.1 kOhm is Rd; wired to 3.3 V or 1.1 V it is no Rp (4.7k +-5 % ends at 4935).
        rails = {"VBUS": 5.0, "+3V3": 3.3, "+1V1": 1.1}
        for far in ("+3V3", "+1V1"):
            with self.subTest(far=far):
                r = _type_c_with(("R1", "5.1k", far), ("R2", "5.1k", far), rails)
                self.assertNotEqual(self._conn(r)["usb_c_cc_status"]["role"], "source")
                self.assertEqual(len(_uc003(r)), 2)

    def test_known_rail_outside_5v_and_3v3_is_not_rp(self):
        # 10k to a known 1.1 V rail advertises nothing; the union is for unknown rails only.
        r = _type_c_with(("R1", "10k", "+1V1"), ("R2", "10k", "+1V1"), {"+1V1": 1.1})
        self.assertNotEqual(self._conn(r)["usb_c_cc_status"]["role"], "source")

    def test_dnp_resistor_counts_as_missing(self):
        for spec, dnp in ((("R2", "5.1k", "GND"), ("R2",)), (("R2", "DNI", "GND"), ())):
            with self.subTest(value=spec[1]):
                r = _type_c_with(("R1", "5.1k", "GND"), spec, dnp=dnp)
                c = self._conn(r)
                self.assertNotIn("unread_resistors", c["usb_c_cc_status"])
                self.assertEqual(c["checks"]["cc2_pulldown_5k1"], "fail")
                self.assertEqual([f["summary"] for f in _uc003(r)],
                                 ["CC2 missing 5.1k pull-down at J1"])

    def test_10k_pull_down_is_wrong_value(self):
        # 10 kOhm is an Rp only as a pull-up; to GND it is not Rd (5.1 kOhm).
        r = _type_c_with(("R1", "10k", "GND"), ("R2", "10k", "GND"))
        self.assertIn("wrong_cc_value", self._conn(r)["usb_c_cc_status"]["issues"])
        self.assertEqual(len(_uc003(r)), 2)

    def test_zero_ohm_link_is_not_an_unread_value(self):
        # 0 parses as 0 ohms: a link, not an unreadable value, so the side still fails.
        r = _type_c_with(("R1", "0", "GND"), ("R2", "0", "GND"))
        c = self._conn(r)
        self.assertNotIn("unread_resistors", c["usb_c_cc_status"])
        self.assertEqual(len(_uc003(r)), 2)

    def test_wrong_1k_pull_down_still_fails(self):
        # 1 kOhm to GND is neither Rd (5.1 kOhm) nor any Rp.
        r = _type_c_with(("R1", "1k", "GND"), ("R2", "1k", "GND"))
        c = self._conn(r)
        self.assertIn("wrong_cc_value", c["usb_c_cc_status"]["issues"])
        self.assertEqual(c["checks"]["cc1_pulldown_5k1"], "fail")
        self.assertEqual(len(_uc003(r)), 2)


def _type_c_cc(cc1, cc2, ics=(), rails=None):
    """USB4105 whose CC1/CC2 nets carry the resistors in *cc1* / *cc2*, in net order, each
    (ref, value, far_net); *ics* are (ref, value) parts with a CC pin on each CC net."""
    j = _conn("J1", "USB4105-GF-A", "Connector:USB_C_Receptacle_USB2.0",
              pins=(*USB2_PINS, ("A5", "CC1"), ("B5", "CC2")))
    comps, nets = [j], _usb2_nets("J1")
    for pin, num, specs in (("CC1", "A5", cc1), ("CC2", "B5", cc2)):
        nets[pin] = [("J1", num, pin)]
        for ref, value, far in specs:
            comps.append(_res(ref, value))
            nets[pin].append((ref, "1", "~"))
            nets.setdefault(far, []).append((ref, "2", "~"))
    for ref, value in ics:
        comps.append({"reference": ref, "type": "ic", "value": value, "lib_id": "MyLib:" + value,
                      "footprint": "", "pins": [{"number": "1", "name": "CC1"},
                                                {"number": "2", "name": "CC2"}]})
        nets["CC1"].append((ref, "1", "CC1"))
        nets["CC2"].append((ref, "2", "CC2"))
    return _run(comps, nets, rails)


def _pp_det_types(value):
    from domain_detectors import detect_power_path
    comp = {"reference": "U1", "type": "ic", "value": value, "lib_id": "MyLib:" + value,
            "footprint": "", "pins": [{"number": "1", "name": "CC1"}]}
    nets = {"CC1": {"name": "CC1", "pins": [{"component": "U1", "pin_number": "1",
                                              "pin_name": "CC1"}]}}
    ctx = build_analysis_context([comp], nets, {}, known_power_rails={"GND"})
    return [(e["ref"], e["type"]) for e in detect_power_path(ctx)]


def _tpd_board(value, tied):
    """A port protector between the receptacle and the PD side: C_CC1 / C_CC2 on the connector
    nets; RPD_G1 / RPD_G2 on the same nets when *tied*, else on their own nets."""
    j = _conn("J1", "USB4105-GF-A", "Connector:USB_C_Receptacle_USB2.0",
              pins=(*USB2_PINS, ("A5", "CC1"), ("B5", "CC2")))
    u = {"reference": "U1", "type": "ic", "value": value, "lib_id": "MyLib:" + value,
         "footprint": "", "pins": [{"number": "1", "name": "C_CC1"}, {"number": "2", "name": "C_CC2"},
                                   {"number": "3", "name": "RPD_G1"}, {"number": "4", "name": "RPD_G2"}]}
    nets = _usb2_nets("J1")
    nets["CC1"] = [("J1", "A5", "CC1"), ("U1", "1", "C_CC1")]
    nets["CC2"] = [("J1", "B5", "CC2"), ("U1", "2", "C_CC2")]
    if tied:
        nets["CC1"].append(("U1", "3", "RPD_G1"))
        nets["CC2"].append(("U1", "4", "RPD_G2"))
    else:
        nets["RPD1"] = [("U1", "3", "RPD_G1")]
        nets["RPD2"] = [("U1", "4", "RPD_G2")]
    return _run([j, u], nets)


class CcTermination(unittest.TestCase):
    """Several resistors on one CC pin: the Rd (or Rp) is the one judged, whichever order the
    net lists them in. A 5.1 kOhm that does not return to ground is no sink Rd."""

    def _status(self, r):
        return r["connectors"][0]["usb_c_cc_status"]

    def test_rd_with_a_sense_resistor_is_a_sink(self):
        rd1, rd2 = ("R1", "5.1k", "GND"), ("R2", "5.1k", "GND")
        sense1, sense2 = ("R3", "100k", "CC1_SENSE"), ("R4", "100k", "CC2_SENSE")
        for cc1, cc2 in (((rd1, sense1), (rd2, sense2)), ((sense1, rd1), (sense2, rd2))):
            with self.subTest(order=cc1[0][0]):
                r = _type_c_cc(cc1, cc2)
                st = self._status(r)
                self.assertEqual((st["role"], st["status"], st["issues"]), ("sink", "pass", []))
                self.assertEqual((st["cc1_resistor"]["ref"], st["cc2_resistor"]["ref"]),
                                 ("R1", "R2"))
                checks = r["connectors"][0]["checks"]
                self.assertEqual((checks["cc1_pulldown_5k1"], checks["cc2_pulldown_5k1"]),
                                 ("pass", "pass"))
                self.assertEqual(_uc003(r), [])

    def test_rd_to_a_supply_fails(self):
        rails = {"VBUS": 5.0, "+5V": 5.0}
        r = _type_c_cc((("R1", "5.1k", "+5V"),), (("R2", "5.1k", "+5V"),), rails=rails)
        st = self._status(r)
        self.assertEqual(st["status"], "fail")
        self.assertIn("wrong_cc_value", st["issues"])
        checks = r["connectors"][0]["checks"]
        self.assertEqual((checks["cc1_pulldown_5k1"], checks["cc2_pulldown_5k1"]),
                         ("fail", "fail"))

    def test_rd_to_a_signal_fails(self):
        r = _type_c_cc((("R1", "5.1k", "CC1_SENSE"),), (("R2", "5.1k", "CC2_SENSE"),))
        st = self._status(r)
        self.assertEqual(st["status"], "fail")
        self.assertIn("wrong_cc_value", st["issues"])

    def test_plain_rd_sink_still_passes(self):
        r = _type_c_cc((("R1", "5.1k", "GND"),), (("R2", "5.1k", "GND"),))
        st = self._status(r)
        self.assertEqual((st["role"], st["status"], st["issues"]), ("sink", "pass", []))

    def test_source_with_a_sense_resistor_stays_a_source(self):
        # A host's Rp is not replaced by a resistor that is no termination, so the port is not
        # read as a device.
        rp1, rp2 = ("R1", "56k", "VBUS"), ("R2", "56k", "VBUS")
        extra1, extra2 = ("R3", "5.1k", "CC1_SENSE"), ("R4", "1M", "GND")
        for cc1, cc2 in (((rp1, extra1), (rp2, extra2)), ((extra1, rp1), (extra2, rp2))):
            with self.subTest(order=cc1[0][0]):
                st = self._status(_type_c_cc(cc1, cc2))
                self.assertEqual((st["role"], st["status"], st["issues"]),
                                 ("source", "pass", []))

    def test_self_terminating_cc_controllers(self):
        # CYPD3175 is a CCG3PA part; FUSB303B is an autonomous Type-C port controller. Both
        # present Rd/Rp on CC themselves.
        for value in ("CYPD3175-24LQXQ", "CYPD3171-24LQXQ", "FUSB303BTMX"):
            with self.subTest(value=value):
                r = _type_c_cc((), (), ics=(("U1", value),))
                st = self._status(r)
                self.assertEqual((st["role"], st["pd_controller"], st["status"]),
                                 ("pd_controlled", "U1", "pass"))
                self.assertEqual(_uc003(r), [])

    def test_listed_controllers_terminate_cc_themselves(self):
        # One part per listed stem; each family's data sheet shows the Rd / Rp inside the part.
        for value in ("TUSB320LAIRWBR", "TUSB321AI", "TUSB322I", "HD3SS3220IRNHT",
                      "TPS25730SRSMR", "TPS25750DRJKR", "TPS25751DREFR", "PTN5110NHQ",
                      "HUSB237", "STUSB4700YQTR", "CH224K", "CH224A", "CH224Q", "nPM1300",
                      "nPM1304", "MAX77751"):
            with self.subTest(value=value):
                r = _type_c_cc((), (), ics=(("U1", value),))
                st = self._status(r)
                self.assertEqual((st["role"], st["pd_controller"], st["status"]),
                                 ("pd_controlled", "U1", "pass"))
                self.assertEqual(_uc003(r), [])

    def test_ch221k_on_a_ch224k_symbol_needs_its_rd(self):
        # CH221K and CH224D show external 5.1k resistors on CC; the CH224K symbol is reused.
        for value in ("CH221K", "CH224D"):
            with self.subTest(value=value):
                r = _type_c_cc((), (), ics=(("U1", value),))
                self.assertEqual(self._status(r)["pd_controller"], None)
                self.assertEqual(len(_uc003(r)), 2)

    def test_ap33772_needs_external_rd(self):
        for value in ("AP33772", "AP33772S", "IP2721"):
            with self.subTest(value=value):
                r = _type_c_cc((), (), ics=(("U1", value),))
                self.assertIsNone(self._status(r)["pd_controller"])
                self.assertEqual(len(_uc003(r)), 2)

    def test_hd3ss3202_is_not_a_cc_controller(self):
        from detector_helpers import type_c_cc_controller
        self.assertIsNone(type_c_cc_controller({"value": "HD3SS3202", "lib_id": "Lib:HD3SS3202"}))
        self.assertIs(type_c_cc_controller({"value": "HD3SS3220", "lib_id": "Lib:HD3SS3220"}),
                      False)
        r = _type_c_cc((), (), ics=(("U1", "HD3SS3202"),))
        self.assertEqual(len(_uc003(r)), 2)

    def test_one_controller_table(self):
        # usb_compliance and the power-path detector read the same table: CC-only parts are
        # controllers for the first and make no power-path record in the second.
        from detector_helpers import type_c_cc_controller
        for value, pd in (("FUSB303BTMX", False), ("MAX20342", False), ("TUSB320", False),
                          ("nPM1300", False), ("FUSB302B", True), ("TPS25750D", True),
                          ("CH224K", True)):
            with self.subTest(value=value):
                self.assertIs(type_c_cc_controller({"value": value, "lib_id": "L:" + value}), pd)
        self.assertEqual(_pp_det_types("FUSB303BTMX"), [])
        self.assertEqual(_pp_det_types("FUSB302B"), [("U1", "usb_pd_controller")])

    def test_cc_only_controller_makes_no_pp_det(self):
        for value in ("TUSB320LAIRWBR", "HD3SS3220IRNHT", "nPM1300", "MAX77751"):
            with self.subTest(value=value):
                self.assertEqual(_pp_det_types(value), [])

    def test_pd_controller_makes_a_pp_det(self):
        for value in ("TPS25750DRJKR", "CH224K", "PTN5110NHQ", "HUSB237", "STUSB4700YQTR"):
            with self.subTest(value=value):
                self.assertEqual(_pp_det_types(value), [("U1", "usb_pd_controller")])

    def test_tpd8s300_counts_only_with_rpd_tied(self):
        # TPD8S300 / TPD6S300: RPD_Gx shorted to C_CCx puts the dead-battery Rd on that line.
        for value in ("TPD8S300A", "TPD6S300A"):
            with self.subTest(value=value, rpd="tied"):
                r = _tpd_board(value, tied=True)
                st = self._status(r)
                self.assertEqual((st["role"], st["pd_controller"]), ("pd_controlled", "U1"))
                self.assertEqual(_uc003(r), [])
            with self.subTest(value=value, rpd="open"):
                r = _tpd_board(value, tied=False)
                self.assertIsNone(self._status(r)["pd_controller"])
                self.assertEqual(len(_uc003(r)), 2)

    def test_hub_with_an_unlisted_part_on_cc_is_not_a_controller(self):
        r = _type_c_cc((), (), ics=(("U1", "STM32F072CBT6"),))
        st = self._status(r)
        self.assertEqual((st["role"], st["pd_controller"]), ("unknown", None))
        self.assertEqual(len(_uc003(r)), 2)


class TypeCRpTable(unittest.TestCase):
    """Type-C source Rp: 56k / 22k / 10k to 5 V and 36k / 12k / 4.7k to 3.3 V (default USB,
    1.5 A, 3 A); default-current rows are +-20 %, the others +-5 %."""

    def test_rows(self):
        from detector_helpers import type_c_rp
        self.assertEqual(type_c_rp(22000, 5.0)[2:], ("source_1_5A", "1.5A advertisement"))
        self.assertIsNone(type_c_rp(20000, 5.0))
        self.assertEqual(type_c_rp(45000, 5.0)[2], "source_default")
        self.assertEqual(type_c_rp(4700, 3.3)[2], "source_3A")
        self.assertIsNone(type_c_rp(4700, 5.0))
        self.assertIsNone(type_c_rp(10000, 1.1))

    def test_unknown_rail(self):
        from detector_helpers import type_c_rp
        self.assertIsNone(type_c_rp(12000, None))
        self.assertEqual(type_c_rp(12000, None, any_rail=True)[2], "source_1_5A")

    def test_rail_windows(self):
        # A pull-up rail outside the 5 V and 3.3 V windows has no Rp table.
        from detector_helpers import TYPE_C_RP_BY_RAIL, type_c_rp_rows
        self.assertIs(type_c_rp_rows(5.0), TYPE_C_RP_BY_RAIL[5.0])
        self.assertIs(type_c_rp_rows(3.3), TYPE_C_RP_BY_RAIL[3.3])
        self.assertIsNone(type_c_rp_rows(12.0))
        self.assertIsNone(type_c_rp_rows(None))
        self.assertEqual(len(type_c_rp_rows(None, any_rail=True)), 6)

def _cap(ref, value, dnp=False):
    return {"reference": ref, "type": "capacitor", "value": value, "lib_id": "Device:C",
            "footprint": "", "dnp": dnp,
            "pins": [{"number": "1", "name": "~"}, {"number": "2", "name": "~"}]}


class VbusCapacitanceBound(unittest.TestCase):
    """USB 2.0 Specification section 7.2.4.1: a device presents at most 10 uF at attach."""

    def _port(self, value, lib_id, caps, cc=True, far="GND", rd=True):
        pins = (*USB2_PINS, ("A5", "CC1"), ("B5", "CC2")) if cc else USB2_PINS
        comps = [_conn("J1", value, lib_id, pins=pins)]
        nets = _usb2_nets("J1")
        if cc:
            nets["CC1"] = [("J1", "A5", "CC1")]
            nets["CC2"] = [("J1", "B5", "CC2")]
            if rd:
                for i, cc_net in enumerate(("CC1", "CC2")):
                    comps.append(_res("R%d" % (i + 1), "5.1k"))
                    nets[cc_net].append(("R%d" % (i + 1), "1", "~"))
                    nets["GND"].append(("R%d" % (i + 1), "2", "~"))
        for i, v in enumerate(caps):
            ref = "C%d" % (i + 1)
            comps.append(_cap(ref, v))
            nets["VBUS"].append((ref, "1", "~"))
            nets.setdefault(far, []).append((ref, "2", "~"))
        return _run(comps, nets)

    def _uc004(self, r):
        return [f for f in r.get("findings", []) if f["rule_id"] == "UC-004"]

    def _sink(self, caps, **kw):
        return self._port("USB4105-GF-A", "Connector:USB_C_Receptacle_USB2.0", caps, **kw)

    def test_sink_at_10uf_passes(self):
        r = self._sink(["10u"])
        self.assertEqual(r["connectors"][0]["checks"]["vbus_capacitance"], "pass")
        self.assertEqual(self._uc004(r), [])

    def test_sink_above_10uf_warns(self):
        r = self._sink(["10u", "100n"])
        self.assertEqual(r["connectors"][0]["checks"]["vbus_capacitance"], "warning")
        f = self._uc004(r)
        self.assertEqual(len(f), 1)
        self.assertIn("exceed", f[0]["summary"])
        self.assertEqual(f[0]["confidence"], "heuristic")

    def test_sink_with_4u7_and_100n_passes(self):
        self.assertEqual(self._uc004(self._sink(["4.7u", "100n"])), [])

    def test_22uf_on_a_sink_warns(self):
        self.assertEqual(len(self._uc004(self._sink(["22u"]))), 1)

    def test_micro_b_with_22uf_warns(self):
        r = self._port("USB_B_Micro", "Connector:USB_B_Micro", ["22u"], cc=False)
        self.assertEqual(len(self._uc004(r)), 1)

    def test_type_a_host_never_warns(self):
        r = self._port("USB_A", "Connector:USB_A", ["100u"], cc=False)
        self.assertEqual(self._uc004(r), [])

    def test_otg_port_never_warns(self):
        for val, lib in (("USB_OTG", "Connector:USB_OTG"),
                         ("ZX62-AB-5PA", "Connector:USB_B_Micro")):
            r = self._port(val, lib, ["47u"], cc=False)
            self.assertEqual(self._uc004(r), [], val)

    def test_source_never_warns(self):
        r = self._sink(["47u"], rd=False)
        self.assertEqual(self._uc004(r), [])

    def test_cap_not_returning_to_ground_is_not_counted(self):
        r = self._sink(["10u", "100n"], far="RESET")
        self.assertEqual(self._uc004(r), [])

    def test_unfitted_cap_is_not_counted(self):
        comps = [_conn("J1", "USB_B_Micro", "Connector:USB_B_Micro", pins=USB2_PINS),
                 _cap("C1", "10u"), _cap("C2", "10u", dnp=True)]
        nets = _usb2_nets("J1")
        for ref in ("C1", "C2"):
            nets["VBUS"].append((ref, "1", "~"))
            nets["GND"].append((ref, "2", "~"))
        self.assertEqual(self._uc004(_run(comps, nets)), [])


    def test_port_fed_by_a_switch_output_never_warns(self):
        j = _conn("J1", "USB_B_Micro", "Connector:USB_B_Micro", pins=USB2_PINS)
        sw = {"reference": "U1", "type": "ic", "value": "AP22653", "lib_id": "Lib:AP22653",
              "footprint": "", "pins": [{"number": "1", "name": "OUT"}]}
        comps = [j, sw, _cap("C1", "47u"), _cap("C2", "100u")]
        nets = _usb2_nets("J1")
        nets["VBUS"].append(("U1", "1", "OUT"))
        for ref in ("C1", "C2"):
            nets["VBUS"].append((ref, "1", "~"))
            nets["GND"].append((ref, "2", "~"))
        ctx_nets = {n: {"name": n, "pins": [dict(component=r, pin_number=pn, pin_name=nm,
                                                 pin_type="power_out" if r == "U1" else "passive")
                                            for r, pn, nm in pins],
                        "point_count": 0, "no_connect": False, "labels": []}
                    for n, pins in nets.items()}
        ctx = build_analysis_context(comps, ctx_nets, {}, known_power_rails={"VBUS"})
        self.assertEqual(self._uc004(analyze_usb_compliance(ctx, {})), [])

    def test_port_without_data_lines_never_warns(self):
        comps = [_conn("J1", "USB_C_Receptacle_PowerOnly_6P", "Connector:USB_C_Receptacle_PowerOnly_6P",
                       pins=(("1", "VBUS"), ("2", "GND"), ("A5", "CC1"), ("B5", "CC2"))),
                 _cap("C1", "22u"), _res("R1", "5.1k"), _res("R2", "5.1k")]
        nets = {"VBUS": [("J1", "1", "VBUS"), ("C1", "1", "~")],
                "GND": [("J1", "2", "GND"), ("C1", "2", "~"), ("R1", "2", "~"), ("R2", "2", "~")],
                "CC1": [("J1", "A5", "CC1"), ("R1", "1", "~")],
                "CC2": [("J1", "B5", "CC2"), ("R2", "1", "~")]}
        self.assertEqual(self._uc004(_run(comps, nets)), [])

    def test_cap_to_the_connectors_own_ground_pin_is_counted(self):
        comps = [_conn("J1", "USB_B_Micro", "Connector:USB_B_Micro", pins=USB2_PINS),
                 _cap("C1", "22u")]
        nets = _usb2_nets("J1")
        nets["Gusb"] = nets.pop("GND")
        nets["VBUS"].append(("C1", "1", "~"))
        nets["Gusb"].append(("C1", "2", "~"))
        self.assertEqual(len(self._uc004(_run(comps, nets))), 1)


if __name__ == "__main__":
    unittest.main()
