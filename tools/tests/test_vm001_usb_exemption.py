"""VM-001 exempts USB data lines and D+/D- pairs, not every net whose name ends in D+ or D-.

USB 2.0 (7.1.1) drivers swing at most 3.6 V whatever the device supply, so a USB pair is exempt.
A lone HOLD-, LED- or SPEED- is a logic signal and is checked like any other net.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import validation_detectors as vd  # noqa: E402
from kicad_core.netnames import is_usb_data_net_name  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402


def _ctx(nets):
    comps = [{"reference": "U5", "type": "ic", "value": "MCU5V", "lib_id": "", "pins": [], "footprint": ""},
             {"reference": "U6", "type": "ic", "value": "MCU3V3", "lib_id": "", "pins": [], "footprint": ""}]
    nets = dict({"+5V": [("U5", "1", "VDD", "power_in")],
                 "+3V3": [("U6", "1", "VDD", "power_in")],
                 "GND": [("U5", "2", "GND", "power_in"), ("U6", "2", "GND", "power_in")]}, **nets)
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    return build_analysis_context(comps, full, {}, known_power_rails={"+5V", "+3V3", "GND"})


def _vm001(*signal_nets):
    nets = {n: [("U5", str(3 + i), "PA0", "output"), ("U6", str(3 + i), "PB0", "input")]
            for i, n in enumerate(signal_nets)}
    with patch.object(vd, "get_regulator_features", return_value=None):
        found = vd.validate_voltage_levels(_ctx(nets))
    return sorted(f["summary"].split(":")[0] for f in found if f["rule_id"] == "VM-001")


class UsbDataNamePredicate(unittest.TestCase):
    def test_table(self):
        for name, want in [("USB_D+", True), ("USBD-", True), ("USB2D+", True), ("/USB/D-", True),
                           ("MCU-D+", True), ("D+", True), ("D-", True),
                           ("HOLD-", False), ("LED-", False), ("SPEED-", False), ("CMD+", False),
                           ("AUTOFD-", False), ("RTD+", False)]:
            self.assertEqual(is_usb_data_net_name(name.upper()), want, name)


class Vm001Exemption(unittest.TestCase):
    def test_lone_active_low_logic_nets_are_checked(self):
        for name in ("HOLD-", "LED-", "SPEED-"):
            self.assertEqual(_vm001(name), ["Net " + name], name)

    def test_usb_and_differential_pairs_stay_exempt(self):
        self.assertEqual(_vm001("USB_D+", "USB_D-"), [])
        self.assertEqual(_vm001("LsD+", "LsD-"), [])
        self.assertEqual(_vm001("TD+", "TD-"), [])

    def test_pairs_of_words_ending_in_d_are_checked(self):
        self.assertEqual(_vm001("AVDD+", "AVDD-"), ["Net AVDD+", "Net AVDD-"])
        self.assertEqual(_vm001("HOLD+", "HOLD-"), ["Net HOLD+", "Net HOLD-"])
        self.assertEqual(_vm001("MOD+", "MOD-", "SDD+", "SDD-"),
                         ["Net MOD+", "Net MOD-", "Net SDD+", "Net SDD-"])


if __name__ == "__main__":
    unittest.main()
