"""USB-PD controller CC resistors, Ethernet jacks with integrated magnetics, VBOOT pins.

Expected values come from the USB Type-C specification and vendor datasheets:
- A sink presents Rd = 5.1 kohm to GND on CC. A source presents Rp to its pull-up rail:
  56k / 22k / 10k to 5 V, or 36k / 12k / 4.7k to 3.3 V (default USB / 1.5 A / 3 A).
- FUSB302, STUSB4500 and the other listed PD controllers present Rd/Rp internally
  (their datasheets), so a bare CC net on them is not a missing resistor.
- HanRun HR911105A integrates the 1:1 Ethernet transformers in the jack (HR911105A datasheet).
- A jack with built-in magnetics brings the transformer centre taps out beside the line pairs:
  HanRun HR913129A ("Single Port RJ45 Connector with Integrated Magnetics and LED", REV 00,
  p. 1 schematic: 1CT:1CT taps between TD+/TD- and RD+/RD-); the corpus symbol of that part
  (LibrePLC32:HR913129A) names them TCT / RCT. A connector whose only such pin is CT is a
  supervisor drawn as a connector (TL7705A: CT = timing capacitor, TL7705A datasheet pinout).
- HanRun HY931147C is a jack with integrated magnetics ("Single Port RJ45 Connector with LEDs and
  Integrated Magnetics for 10/100Base-TX PoE application", REV.A/1, p. 1).
- Corpus jacks credited by footprint or description: Wurth 7499111446 footprint on the generic
  Connector:RJ45_LED_Shielded symbol; HanRun HR915340A described "LAN Transformer Jack"; the
  KiCad RJ45_JK0654219 symbol described "1 Port RJ45 Magjack Connector"; Amphenol RC01812
  described "RJ45 Receptacle Connector, Low-Profile, with LEDs, No Magnetics".
- A bootstrap capacitor sits between VB and VS (VB1 and VS1, ...); a pin named VBOOT has no VS partner.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import domain_detectors as dd  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402


def ctx_of(components, nets, rails, rail_voltages=None):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    for c in components:
        c.setdefault("lib_id", "")
        c.setdefault("pins", [])
        c.setdefault("footprint", "")
    ctx = build_analysis_context(components, full, {}, known_power_rails=set(rails))
    # The schematic pipeline fills the rail map before the detectors run.
    ctx.rail_by_net = dict(rail_voltages or {})
    return ctx


def ic(ref, value, lib_id=""):
    return {"reference": ref, "type": "ic", "value": value, "lib_id": lib_id}


def res(ref, value):
    return {"reference": ref, "type": "resistor", "value": value}


def pd_entry(ctx, ref):
    (entry,) = [e for e in dd.detect_power_path(ctx) if e["ref"] == ref]
    return entry


def pd_board(value, resistor=None, to_net="GND", rails=("GND", "+5V", "+3V3", "VBUS"),
             rail_voltages=None):
    comps = [ic("U1", value)]
    nets = {"CC1": [("U1", "1", "CC1", "bidirectional")],
            "CC2": [("U1", "2", "CC2", "bidirectional")],
            "VBUS": [("U1", "3", "VBUS", "power_in")],
            "GND": [("U1", "4", "GND", "power_in")]}
    if resistor:
        comps.append(res("R1", resistor))
        nets["CC1"].append(("R1", "1", "~", "passive"))
        nets.setdefault(to_net, []).append(("R1", "2", "~", "passive"))
    voltages = {"+5V": 5.0, "+3V3": 3.3, "VBUS": 5.0, "GND": 0.0}
    voltages.update(rail_voltages or {})
    return ctx_of(comps, nets, rails, voltages)


class UsbPdCcResistors(unittest.TestCase):
    def test_fusb302_bare_cc_has_no_resistor_check(self):
        entry = pd_entry(pd_board("FUSB302BMPX"), "U1")
        self.assertEqual(entry["cc_nets"], ["CC1", "CC2"])
        self.assertNotIn("cc_resistor_check", entry)

    def test_stusb4500_rd_to_gnd_is_correct_sink(self):
        entry = pd_entry(pd_board("STUSB4500QTR", "5.1k"), "U1")
        (check,) = entry["cc_resistor_check"]
        self.assertEqual((check["net"], check["ref"], check["status"]), ("CC1", "R1", "correct_sink"))
        # The record still names the controller, not the resistor.
        self.assertEqual(entry["components"], ["U1"])

    def test_summary_names_the_controller_not_a_cc_resistor(self):
        ctx = pd_board("STUSB4500QTR", "5.1k")
        ctx.nets["CC2"]["pins"].append(
            dict(component="D1", pin_number="1", pin_name="A", pin_type="passive"))
        ctx.comp_lookup["D1"] = {"reference": "D1", "type": "diode", "value": "D_Schottky"}
        entry = pd_entry(ctx, "U1")
        self.assertEqual(entry["summary"],
                         "Power path U1 (STUSB4500QTR) [usb_pd_controller]")

    def test_dead_battery_pins_do_not_repeat_the_cc_nets(self):
        comps = [ic("U1", "STUSB4500QTR"), res("R1", "5.1k")]
        nets = {"CC1": [("U1", "1", "CC1", "bidirectional"),
                        ("U1", "5", "CC1DB", "bidirectional"),
                        ("R1", "1", "~", "passive")],
                "CC2": [("U1", "2", "CC2", "bidirectional"),
                        ("U1", "6", "CC2DB", "bidirectional")],
                "VBUS": [("U1", "3", "VBUS", "power_in")],
                "GND": [("U1", "4", "GND", "power_in"), ("R1", "2", "~", "passive")]}
        ctx = ctx_of(comps, nets, ("GND", "VBUS"), {"VBUS": 5.0, "GND": 0.0})
        entry = pd_entry(ctx, "U1")
        self.assertEqual(entry["cc_nets"], ["CC1", "CC2"])
        (check,) = entry["cc_resistor_check"]
        self.assertEqual(check["ref"], "R1")

    def test_56k_to_5v_is_source_default(self):
        (check,) = pd_entry(pd_board("STUSB4500QTR", "56k", to_net="+5V"), "U1")["cc_resistor_check"]
        self.assertEqual(check["status"], "source_default")

    def test_10k_to_5v_is_source_3a(self):
        (check,) = pd_entry(pd_board("STUSB4500QTR", "10k", to_net="+5V"), "U1")["cc_resistor_check"]
        self.assertEqual(check["status"], "source_3A")

    def test_3v3_rail_uses_the_3v3_rp_table(self):
        # 12k to 3.3 V advertises 1.5 A; 22k to 3.3 V is no Rp at all.
        (check,) = pd_entry(pd_board("STUSB4500QTR", "12k", to_net="+3V3"), "U1")["cc_resistor_check"]
        self.assertEqual(check["status"], "source_1_5A")
        (check,) = pd_entry(pd_board("STUSB4500QTR", "22k", to_net="+3V3"), "U1")["cc_resistor_check"]
        self.assertEqual(check["status"], "unexpected_value")

    def test_10k_to_gnd_is_unexpected_not_a_source(self):
        (check,) = pd_entry(pd_board("STUSB4500QTR", "10k"), "U1")["cc_resistor_check"]
        self.assertEqual(check["status"], "unexpected_value")

    def test_pullup_to_a_signal_net_is_not_rp(self):
        entry = pd_entry(pd_board("FUSB302BMPX", "56k", to_net="GPIO7"), "U1")
        self.assertNotIn("cc_resistor_check", entry)

    def test_pullup_to_a_rail_of_unknown_voltage_is_not_rp(self):
        ctx = pd_board("FUSB302BMPX", "56k", to_net="VDD_IO", rails=("GND", "VDD_IO", "VBUS"))
        self.assertNotIn("cc_resistor_check", pd_entry(ctx, "U1"))

    def test_pullup_to_a_12v_rail_is_not_rp(self):
        ctx = pd_board("FUSB302BMPX", "10k", to_net="+12V", rails=("GND", "+12V", "VBUS"),
                       rail_voltages={"+12V": 12.0})
        self.assertNotIn("cc_resistor_check", pd_entry(ctx, "U1"))

    def test_rp_tolerance_follows_the_type_c_table(self):
        # Default-current Rp is +-20 %, so 45k to 5 V is still a default-USB source.
        (check,) = pd_entry(pd_board("STUSB4500QTR", "45k", to_net="+5V"), "U1")["cc_resistor_check"]
        self.assertEqual(check["status"], "source_default")
        # 1.5 A and 3 A rows are +-5 %: 24k to 5 V is no Rp.
        (check,) = pd_entry(pd_board("STUSB4500QTR", "24k", to_net="+5V"), "U1")["cc_resistor_check"]
        self.assertEqual(check["status"], "unexpected_value")

    def test_a_4v6_rail_uses_the_5v_table(self):
        ctx = pd_board("STUSB4500QTR", "22k", to_net="+5V", rail_voltages={"+5V": 4.6})
        (check,) = pd_entry(ctx, "U1")["cc_resistor_check"]
        self.assertEqual(check["status"], "source_1_5A")

    def test_cypd3175_is_a_pd_controller(self):
        # CYPD3171/3174/3175/3177 are the CCG3PA family.
        for value in ("CYPD3175-24LQXQ", "CYPD3177-24LQXQ"):
            with self.subTest(value=value):
                entry = pd_entry(pd_board(value), "U1")
                self.assertEqual(entry["type"], "usb_pd_controller")
                self.assertEqual(entry["cc_nets"], ["CC1", "CC2"])


def eth_board(connector_value, connector_lib="", magnetics=False):
    comps = [ic("U1", "LAN8720A"),
             {"reference": "J9", "type": "connector", "value": connector_value, "lib_id": connector_lib}]
    nets = {"TXP": [("U1", "1", "TXP", "output"), ("J9", "1", "TD+", "passive")],
            "TXN": [("U1", "2", "TXN", "output"), ("J9", "2", "TD-", "passive")],
            "RXP": [("U1", "3", "RXP", "input"), ("J9", "3", "RD+", "passive")],
            "RXN": [("U1", "4", "RXN", "input"), ("J9", "6", "RD-", "passive")],
            "GND": [("U1", "5", "GND", "power_in")]}
    if magnetics:
        comps.append({"reference": "T1", "type": "transformer", "value": "HX1188NL"})
        nets["TXP"].append(("T1", "1", "~", "passive"))
    return ctx_of(comps, nets, ("GND",))


ETH_NETS = {"TXP": [("U1", "1", "TXP", "output"), ("J9", "1", "TD+", "passive")],
            "TXN": [("U1", "2", "TXN", "output"), ("J9", "2", "TD-", "passive")],
            "RXP": [("U1", "3", "RXP", "input"), ("J9", "3", "RD+", "passive")],
            "RXN": [("U1", "4", "RXN", "input"), ("J9", "6", "RD-", "passive")],
            "GND": [("U1", "5", "GND", "power_in")]}


def jack(ref, value, lib_id="", pin_names=(), **fields):
    comp = {"reference": ref, "type": "connector", "value": value, "lib_id": lib_id,
            "pins": [{"number": str(i), "name": n} for i, n in enumerate(pin_names, 1)]}
    comp.update(fields)
    return comp


def jack_board(conn, more=()):
    """A PHY wired straight to *conn* (no transformer on the sheet)."""
    return ctx_of([ic("U1", "LAN8720A"), conn, *more], {n: list(p) for n, p in ETH_NETS.items()},
                  ("GND",))


class EthernetIntegratedMagnetics(unittest.TestCase):
    def test_hr911105a_counts_as_magnetics(self):
        (eth,) = dd.detect_ethernet_interfaces(eth_board("HR911105A", "Connector:RJ45_Hanrun_HR911105A"))
        self.assertEqual(eth["impedance_advisory"],
                         {"status": "pass", "detail": "Magnetics integrated in connector J9"})
        self.assertEqual(eth["magnetics"], [])

    def test_plain_rj45_without_transformer_keeps_the_warning(self):
        (eth,) = dd.detect_ethernet_interfaces(eth_board("RJ45", "Connector:RJ45_Shielded"))
        self.assertEqual(eth["impedance_advisory"]["status"], "warning")
        self.assertTrue(eth["impedance_advisory"]["detail"].startswith("No magnetics/transformer"))

    def test_discrete_transformer_detail_is_unchanged(self):
        (eth,) = dd.detect_ethernet_interfaces(eth_board("RJ45", "Connector:RJ45", magnetics=True))
        self.assertEqual(eth["impedance_advisory"]["detail"],
                         "Magnetics present for impedance matching and isolation")

    def test_vendor_magjack_part_numbers_count_as_magnetics(self):
        for value, lib in (("RJMG1BD3B8K1ANR", "Connector:RJ45_Amphenol_RJMG1BD3B8K1ANR"),
                           ("7499010121A", "Connector:RJ45_Wuerth_7499010121A"),
                           ("RJ45", "custom:RJ45+MAG"),
                           ("RJ45-TRANSFO", "custom:RJ45-TRANSFO"),
                           ("SI-46001", "Connector:RJ45_Bel_SI-46001")):
            with self.subTest(value=value):
                (eth,) = dd.detect_ethernet_interfaces(eth_board(value, lib))
                self.assertEqual(eth["impedance_advisory"],
                                 {"status": "pass", "detail": "Magnetics integrated in connector J9"})

    def test_magjack_named_only_by_part_number_is_the_ethernet_connector(self):
        for value in ("LPJG0926HENL", "ARJC02-111008D", "TM211Q01FM22", "J1B1211CCD"):
            with self.subTest(value=value):
                (eth,) = dd.detect_ethernet_interfaces(eth_board(value, "custom:" + value))
                self.assertEqual(eth["impedance_advisory"],
                                 {"status": "pass", "detail": "Magnetics integrated in connector J9"})
                self.assertEqual([c["reference"] for c in eth["connectors"]], ["J9"])

    def test_jack_with_centre_tap_pins_counts_as_magnetics(self):
        conn = jack("J9", "HR913129A", "LibrePLC32:HR913129A",
                    ("TD+", "TD-", "RD+", "TCT", "RCT", "RD-", "NC", "CHSGND"))
        (eth,) = dd.detect_ethernet_interfaces(jack_board(conn))
        self.assertEqual(eth["impedance_advisory"],
                         {"status": "pass", "detail": "Magnetics integrated in connector J9"})
        self.assertEqual([c["reference"] for c in eth["connectors"]], ["J9"])

    def test_centre_tap_pins_of_another_unit_count(self):
        conn = jack("J9", "TRJG0926HENL", "custom:TRJG0926HENL", ("TRD0_P", "TRD0_N"))
        conn["unit"] = 1
        other = jack("J9", "TRJG0926HENL", "custom:TRJG0926HENL", ("TRD1_P", "TRD1_N", "TRCT0"))
        other["unit"] = 2
        (eth,) = dd.detect_ethernet_interfaces(jack_board(conn, [other]))
        self.assertEqual(eth["impedance_advisory"]["status"], "pass")

    def test_hy931147c_counts_as_magnetics(self):
        (eth,) = dd.detect_ethernet_interfaces(eth_board("HY931147C", "custom:HY931147C"))
        self.assertEqual(eth["impedance_advisory"],
                         {"status": "pass", "detail": "Magnetics integrated in connector J9"})

    def test_jack_by_footprint_and_by_description(self):
        cases = (
            jack("J9", "RJ45_LED_Shielded", "Connector:RJ45_LED_Shielded",
                 footprint="Connector_RJ:RJ45_Wuerth_7499111446_Horizontal"),
            jack("J9", "JD1_0001NL", "gkl_misc:JD1_0001NL", footprint="gkl_conn:MAGJACK"),
            jack("J9", "RJ45", "Connector:RJ45_Shielded", mpn="7499111446"),
            jack("J9", "HR915340A", "custom:HR915340A", description="LAN Transformer Jack"),
            jack("J9", "RJ45_JK0654219", "Connector:RJ45_JK0654219",
                 description="1 Port RJ45 Magjack Connector Through Hole 10/100/1000 Base-T"),
        )
        for conn in cases:
            with self.subTest(value=conn["value"]):
                (eth,) = dd.detect_ethernet_interfaces(jack_board(conn))
                self.assertEqual(eth["impedance_advisory"],
                                 {"status": "pass", "detail": "Magnetics integrated in connector J9"})
                self.assertEqual([c["reference"] for c in eth["connectors"]], ["J9"])

    def test_no_magnetics_description_still_warns(self):
        conn = jack("J9", "ETHERNET", "BR_Connectors:RJ45_RC01812",
                    ("TD+", "TD-", "RD+", "RD-", "CT"),
                    description="RJ45 Receptacle Connector, Low-Profile, with LEDs, No Magnetics SMD+PTH")
        (eth,) = dd.detect_ethernet_interfaces(jack_board(conn))
        self.assertEqual(eth["impedance_advisory"]["status"], "warning")

    def test_ct_pin_alone_is_not_a_jack(self):
        sup = jack("J5", "TL7705A", "Power_Supervisor:TL7705A",
                   ("CT", "REF", "~{RESIN}", "GND", "~{RESET}", "RESET", "SENSE", "VCC"))
        ctx = ctx_of([ic("U1", "LAN8720A"), sup],
                     {"TXP": [("U1", "1", "TXP", "output")],
                      "TIMING": [("J5", "1", "CT", "passive")],
                      "GND": [("U1", "5", "GND", "power_in"), ("J5", "4", "GND", "power_in")]},
                     ("GND",))
        (eth,) = dd.detect_ethernet_interfaces(ctx)
        self.assertEqual(eth["connectors"], [])
        self.assertEqual(eth["impedance_advisory"]["status"], "warning")

    def test_unwired_transformer_does_not_pass(self):
        # A sonar transformer elsewhere on the sheet is not the Ethernet magnetics.
        ctx = ctx_of([ic("U1", "LAN8720A"),
                      jack("J9", "RJ45", "Connector:RJ45_Shielded"),
                      ic("U3", "TC4427"),
                      {"reference": "T5", "type": "transformer", "value": "TRANSFORMER"}],
                     {**ETH_NETS,
                      "SONAR_A": [("T5", "1", "~", "passive"), ("U3", "7", "OUTA", "output")],
                      "SONAR_B": [("T5", "2", "~", "passive"), ("U3", "5", "OUTB", "output")]},
                     ("GND",))
        (eth,) = dd.detect_ethernet_interfaces(ctx)
        self.assertEqual(eth["impedance_advisory"]["status"], "warning")
        self.assertEqual(eth["magnetics"], [])

    def test_transformer_behind_an_esd_array_still_passes(self):
        # The walk from the PHY stops at the flow-through ESD array; the transformer's line
        # side reaches the jack through a series resistor.
        ctx = ctx_of([ic("U1", "LAN8720A"), ic("U2", "TPD4E05U06"),
                      {"reference": "T1", "type": "transformer", "value": "HX1188NL"},
                      res("R1", "0"), jack("J9", "RJ45", "Connector:RJ45_Shielded")],
                     {"TXP": [("U1", "1", "TXP", "output"), ("U2", "1", "IO1", "passive")],
                      "TXP_P": [("U2", "10", "IO1_OUT", "passive"), ("T1", "1", "~", "passive")],
                      "LINE_TX": [("T1", "16", "~", "passive"), ("R1", "1", "~", "passive")],
                      "LINE_TX_J": [("R1", "2", "~", "passive"), ("J9", "1", "TD+", "passive")],
                      "GND": [("U1", "5", "GND", "power_in")]},
                     ("GND",))
        (eth,) = dd.detect_ethernet_interfaces(ctx)
        self.assertEqual(eth["impedance_advisory"]["status"], "pass")
        self.assertEqual([m["reference"] for m in eth["magnetics"]], ["T1"])

    def test_transformer_without_pin_data_still_counts(self):
        ctx = ctx_of([ic("U1", "LAN8720A"), jack("J9", "RJ45", "Connector:RJ45_Shielded"),
                      {"reference": "T1", "type": "transformer", "value": "HX1188NL"}],
                     dict(ETH_NETS), ("GND",))
        (eth,) = dd.detect_ethernet_interfaces(ctx)
        self.assertEqual(eth["impedance_advisory"]["status"], "pass")
        self.assertEqual([m["reference"] for m in eth["magnetics"]], ["T1"])


class EthernetPhyWords(unittest.TestCase):
    def phys(self, value, lib_id):
        ctx = ctx_of([ic("U1", value, lib_id)],
                     {"GND": [("U1", "5", "GND", "power_in")]}, ("GND",))
        return [e["phy_reference"] for e in dd.detect_ethernet_interfaces(ctx)]

    def test_phy_word_inside_another_word_is_not_a_phy(self):
        for value, lib in (("ESP32-WROOM-32", "esp32node:ESP32-WROOM-32_Phys"),
                           ("ESP32-WROOM-32", "esp32_physlayout:ESP32-WROOM-32"),
                           ("", "Electrophyiological Specific Components:OPA322AID"),
                           ("MAX9000", "PhysikIIIA:MAX9000"),
                           ("", "DavideCustomSymbols:StackedEthernet")):
            with self.subTest(lib=lib):
                self.assertEqual(self.phys(value, lib), [])

    def test_project_library_named_ethernet_is_not_a_phy(self):
        for value, lib in (("OPA690IDBVR", "ethernet:OPA695"),
                           ("LM78M05CT", "ethernet-rescue:LM78M05CT")):
            with self.subTest(lib=lib):
                self.assertEqual(self.phys(value, lib), [])

    def test_interface_ethernet_library_part_is_a_phy(self):
        for value, lib in (("AR8035", "Interface_Ethernet:AR8035"),
                           ("ETH-PHY", "custom:ETH-PHY"),
                           ("U_ETH", "custom:Ethernet_PHY"),
                           ("100BASE-T1", "custom:TJA1101"),
                           ("LAN8720A", "ethernet:LAN8720A")):
            with self.subTest(lib=lib):
                self.assertEqual(self.phys(value, lib), ["U1"])


def driver_board(vb_pin):
    comps = [ic("U1", "IR2104"), {"reference": "C1", "type": "capacitor", "value": "100n"}]
    nets = {"BOOT": [("U1", "8", vb_pin, "power_in"), ("C1", "1", "~", "passive")],
            "SW": [("U1", "6", "VS", "power_in"), ("C1", "2", "~", "passive")],
            "HO": [("U1", "7", "HO", "output")],
            "+12V": [("U1", "1", "VCC", "power_in")],
            "GND": [("U1", "4", "COM", "power_in")]}
    return ctx_of(comps, nets, ("GND", "+12V"), {"+12V": 12.0, "GND": 0.0})


class BootstrapPins(unittest.TestCase):
    def bootstrap(self, vb_pin):
        drivers = dd.detect_motor_drivers(driver_board(vb_pin))
        return [cap for d in drivers for cap in d.get("bootstrap_caps", [])]

    def test_vb_pairs_with_vs(self):
        self.assertEqual(self.bootstrap("VB"),
                         [{"reference": "C1", "value": "100n", "between": ["VB", "VS"]}])

    def test_vboot_has_no_vs_partner(self):
        self.assertEqual(self.bootstrap("VBOOT"), [])


if __name__ == "__main__":
    unittest.main()
