"""USB-PD controller CC resistors, Ethernet jacks with integrated magnetics, VBOOT pins.

Expected values come from the USB Type-C specification and vendor datasheets:
- A sink presents Rd = 5.1 kohm to GND on CC. A source presents Rp to its pull-up rail:
  56k / 22k / 10k to 5 V, or 36k / 12k / 4.7k to 3.3 V (default USB / 1.5 A / 3 A).
- FUSB302, STUSB4500 and the other listed PD controllers present Rd/Rp internally
  (their datasheets), so a bare CC net on them is not a missing resistor.
- HanRun HR911105A integrates the 1:1 Ethernet transformers in the jack (HR911105A datasheet).
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
