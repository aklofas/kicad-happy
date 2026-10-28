# tools/tests/test_diff_pair_esd.py
"""A differential pair's ESD credit comes from protection parts on each leg (TVS/ESD diodes and
arrays, varistors); an MCU, bridge or clock buffer wired to both lines is the protected device."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
from schematic.net_analysis import _detect_differential_pairs  # noqa: E402


def _comp(ref, ctype, value, lib_id, pins=()):
    return {"reference": ref, "type": ctype, "value": value, "lib_id": lib_id,
            "pins": [{"number": n, "name": nm, "type": t} for n, nm, t in pins]}


def _pairs(components, nets):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "labels": []}
            for n, pins in nets.items()}
    ctx = build_analysis_context(components, full, {}, known_power_rails={"+5V", "VBUS"})
    return {(p["positive"], p["negative"]): p for p in _detect_differential_pairs(ctx)}


MCU = _comp("U1", "ic", "STM32F103C8Tx", "MCU_ST_STM32F1:STM32F103C8Tx",
            [("1", "PA12", "bidirectional"), ("2", "PA11", "bidirectional"), ("3", "VSS", "power_in"),
             ("4", "PA0", "bidirectional")])
USBLC6 = _comp("U_esd", "ic", "USBLC6-2SC6", "Power_Protection:USBLC6-2SC6",
               [("1", "I/O1", "passive"), ("2", "GND", "passive"), ("3", "I/O2", "passive"),
                ("5", "VBUS", "passive")])
CH340 = _comp("U2", "ic", "CH340G", "Interface_USB:CH340G",
              [("5", "UD+", "bidirectional"), ("6", "UD-", "bidirectional"), ("1", "GND", "power_in"),
               ("2", "TXD", "output")])


def _usb(extra_dp=(), extra_dm=(), extra_gnd=()):
    return {"USB_D+": [("U1", "1", "PA12", "bidirectional"), *extra_dp],
            "USB_D-": [("U1", "2", "PA11", "bidirectional"), *extra_dm],
            "GND": [("U1", "3", "VSS", "power_in"), *extra_gnd],
            "LED": [("U1", "4", "PA0", "bidirectional")]}


class DiffPairEsdCredit(unittest.TestCase):
    def test_esd_array_on_both_legs_is_credited_mcu_is_not(self):
        nets = _usb([("U_esd", "1", "I/O1", "passive")], [("U_esd", "3", "I/O2", "passive")],
                    [("U_esd", "2", "GND", "passive")])
        nets["VBUS"] = [("U_esd", "5", "VBUS", "passive")]
        p = _pairs([MCU, USBLC6], nets)[("USB_D+", "USB_D-")]
        self.assertTrue(p["has_esd"])
        self.assertEqual(p["esd_protection"], ["U_esd"])

    def test_mcu_and_usb_bridge_only_are_not_protection(self):
        nets = _usb([("U2", "5", "UD+", "bidirectional")], [("U2", "6", "UD-", "bidirectional")],
                    [("U2", "1", "GND", "power_in")])
        p = _pairs([MCU, CH340], nets)[("USB_D+", "USB_D-")]
        self.assertFalse(p["has_esd"])
        self.assertNotIn("esd_protection", p)
        self.assertEqual(p["shared_ics"], ["U1", "U2"])

    def test_one_tvs_diode_per_leg_is_credited(self):
        d1 = _comp("D1", "diode", "ESD5Z5.0T1G", "Diode:ESD5Zxx", [("1", "K", "passive"), ("2", "A", "passive")])
        d2 = _comp("D2", "diode", "ESD5Z5.0T1G", "Diode:ESD5Zxx", [("1", "K", "passive"), ("2", "A", "passive")])
        nets = _usb([("D1", "1", "K", "passive")], [("D2", "1", "K", "passive")],
                    [("D1", "2", "A", "passive"), ("D2", "2", "A", "passive")])
        p = _pairs([MCU, d1, d2], nets)[("USB_D+", "USB_D-")]
        self.assertTrue(p["has_esd"])
        self.assertEqual(p["esd_protection"], ["D1", "D2"])

    def test_tvs_on_one_leg_only_is_not_credited(self):
        d1 = _comp("D1", "diode", "ESD5Z5.0T1G", "Diode:ESD5Zxx", [("1", "K", "passive"), ("2", "A", "passive")])
        nets = _usb([("D1", "1", "K", "passive")], (), [("D1", "2", "A", "passive")])
        p = _pairs([MCU, d1], nets)[("USB_D+", "USB_D-")]
        self.assertFalse(p["has_esd"])
        self.assertNotIn("esd_protection", p)

    def test_usb_filter_with_esd_clamps_between_connector_and_mcu_is_credited(self):
        # USBUF02W6 (ST): series filter with clamps; its connector-side nets carry no pair suffix.
        filt = _comp("U5", "ic", "USBUF02W6", "project_library:USBUF",
                     [("1", "D1", "bidirectional"), ("2", "GND", "power_in"), ("3", "D2", "bidirectional"),
                      ("4", "D3", "bidirectional"), ("6", "D4", "bidirectional")])
        nets = _usb([("U5", "6", "D4", "bidirectional")], [("U5", "4", "D3", "bidirectional")],
                    [("U5", "2", "GND", "power_in")])
        nets["USB_M"] = [("U5", "3", "D2", "bidirectional")]
        nets["USB_P"] = [("U5", "1", "D1", "bidirectional")]
        p = _pairs([MCU, filt], nets)[("USB_D+", "USB_D-")]
        self.assertTrue(p["has_esd"])
        self.assertEqual(p["esd_protection"], ["U5"])

    def _four_line(self, ref, value, io_type):
        part = _comp(ref, "ic", value, "custom:" + value,
                     [("1", "GND", "passive"), ("2", "IO1", io_type), ("3", "IO2", io_type),
                      ("4", "IO3", io_type), ("5", "IO4", io_type)])
        nets = _usb([(ref, "2", "IO1", io_type)], [(ref, "3", "IO2", io_type)],
                    [(ref, "1", "GND", "passive")])
        nets["ETH_TX+"] = [(ref, "4", "IO3", io_type)]
        nets["ETH_TX-"] = [(ref, "5", "IO4", io_type)]
        return _pairs([MCU, part], nets)

    def test_unnamed_array_with_only_ground_and_pair_lines_is_credited(self):
        pairs = self._four_line("U3", "BDFN3310A056R", "passive")
        for key in (("USB_D+", "USB_D-"), ("ETH_TX+", "ETH_TX-")):
            self.assertTrue(pairs[key]["has_esd"], key)
            self.assertEqual(pairs[key]["esd_protection"], ["U3"])

    def test_clock_buffer_with_output_pins_is_not_credited(self):
        # Same topology, but the part drives its pair pins: a fan-out buffer, not a clamp.
        pairs = self._four_line("U4", "SY75602", "output")
        for key in (("USB_D+", "USB_D-"), ("ETH_TX+", "ETH_TX-")):
            self.assertFalse(pairs[key]["has_esd"], key)
            self.assertNotIn("esd_protection", pairs[key])


if __name__ == "__main__":
    unittest.main()
