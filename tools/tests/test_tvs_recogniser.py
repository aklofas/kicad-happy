"""One TVS recogniser: protection-device detection, the USB VBUS check and the flyback clamp
test read a TVS diode the same way: by a protection name, a TVS series (SMF, SM6T, P4KE, ...)
or a description/keywords that call the part a TVS."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402


def _diode(ref, value, lib_id="Device:D", description="", keywords="", mpn=""):
    return {"reference": ref, "type": "diode", "value": value, "lib_id": lib_id,
            "description": description, "keywords": keywords, "mpn": mpn, "footprint": "",
            "pins": [{"number": "1", "name": "K"}, {"number": "2", "name": "A"}]}


def _usb(ref="J15"):
    return {"reference": ref, "type": "connector", "value": "USB_B_Micro",
            "lib_id": "Connector:USB_B_Micro", "footprint": "",
            "pins": [{"number": n, "name": nm} for n, nm in
                     (("1", "VBUS"), ("2", "D-"), ("3", "D+"), ("5", "GND"))]}


def _ctx(components, nets):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type="passive")
                                    for r, p, pn in pins],
                "point_count": 0, "no_connect": False, "labels": []}
            for n, pins in nets.items()}
    return build_analysis_context(components, full, {}, known_power_rails={"VBUS", "GND"})


def _vbus_board(diode):
    """USB connector whose VBUS has one diode from VBUS (cathode, pin 1) to GND (anode, pin 2)."""
    return _ctx([_usb(), diode],
                {"VBUS": [("J15", "1", "VBUS"), (diode["reference"], "1", "K")],
                 "USB_DM": [("J15", "2", "D-")], "USB_DP": [("J15", "3", "D+")],
                 "GND": [("J15", "5", "GND"), (diode["reference"], "2", "A")]})


class IsTvsDiode(unittest.TestCase):
    def test_tvs_parts(self):
        from detector_helpers import is_tvs_diode
        cases = [_diode("D5", "SMF5V0A", "Diode:SMF5V0A"),
                 _diode("D1", "SM6T6V8A", "Device:D_TVS"),
                 _diode("D2", "SM712", "Diode:SM712_SOT23"),
                 _diode("D3", "SMCJ24A", "Project:D_Schottky"),
                 _diode("D4", "H5VUD5BB", "Device:D"),
                 _diode("D6", "SD36_SOD323", "MyLib:SD36_SOD323",
                        keywords="diode TVS voltage suppressor")]
        for comp in cases:
            self.assertTrue(is_tvs_diode(comp), comp["value"])

    def test_parts_that_are_not_tvs(self):
        from detector_helpers import is_tvs_diode
        cases = [_diode("D1", "1N4148", "Diode:1N4148", description="ESD sensitive device"),
                 _diode("D2", "BZT52C5V1", "Diode:BZT52Bxx"),
                 _diode("D3", "1N5819", "Diode:1N5819"),
                 _diode("D4", "SS34 SMA", "Device:D_Schottky")]
        for comp in cases:
            self.assertFalse(is_tvs_diode(comp), comp["value"])


class ProtectionDevices(unittest.TestCase):
    def test_smf_tvs_on_vbus_is_a_protection_device(self):
        from signal_detectors import detect_protection_devices
        ctx = _vbus_board(_diode("D5", "SMF5V0A", "Diode:SMF5V0A"))
        recs = [(r["ref"], r["protected_net"], r["clamp_net"]) for r in detect_protection_devices(ctx)]
        self.assertEqual(recs, [("D5", "VBUS", "GND")])

    def test_rectifier_on_vbus_is_not(self):
        from signal_detectors import detect_protection_devices
        ctx = _vbus_board(_diode("D5", "1N4148", "Diode:1N4148", description="ESD sensitive device"))
        self.assertEqual(detect_protection_devices(ctx), [])


def _usb_result(diode):
    from schematic.system_analyses import analyze_usb_compliance
    return analyze_usb_compliance(_vbus_board(diode), {})


class VbusProtection(unittest.TestCase):
    def test_smf_tvs_on_vbus_passes(self):
        result = _usb_result(_diode("D5", "SMF5V0A", "Diode:SMF5V0A"))
        self.assertEqual(result["connectors"][0]["checks"]["vbus_esd_protection"], "pass")
        self.assertEqual([f for f in result.get("findings", []) if f["rule_id"] == "UC-002"], [])

    def test_schottky_on_vbus_still_fails(self):
        result = _usb_result(_diode("D5", "1N5819", "Diode:1N5819"))
        self.assertEqual(result["connectors"][0]["checks"]["vbus_esd_protection"], "fail")
        self.assertEqual([f["components"] for f in result["findings"] if f["rule_id"] == "UC-002"],
                         [["J15"]])


class FlybackClamp(unittest.TestCase):
    def test_tvs_series_is_a_clamp_not_a_flyback_diode(self):
        from signal_detectors import _is_clamp_diode
        self.assertTrue(_is_clamp_diode(_diode("D1", "SMF24A", "Diode:SMF24A")))
        self.assertTrue(_is_clamp_diode(_diode("D2", "D", "Device:D",
                                               description="Transil Transient Voltage Suppressor")))
        self.assertFalse(_is_clamp_diode(_diode("D3", "1N4007", "Diode:1N4007")))


if __name__ == "__main__":
    unittest.main()
