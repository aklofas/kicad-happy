"""cross_domain_signals asks for a level shifter only where VM-001 would.

A regulator enable or power-good pin that VM-001 accepts as a compatible endpoint
is left out of the pairwise domain check; the other ICs on the net still pair up.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import validation_detectors as vd  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from schematic.net_analysis import _detect_cross_domain_signals  # noqa: E402

_PARTS = {
    "MCU33": ("STM32F103C8", "+3V3"),
    "MCU5": ("ATMEGA328P", "+5V"),
    "BUCK": ("TPS62824", "+5V"),
    "LDO": ("AMS1117-3.3", "+3V3"),
}


def _signals(signal_pins):
    """signal_pins: [(ref, part key, pin name)] all on net SIG; returns its needs_level_shifter."""
    comps, nets, domains = [], {"+5V": [], "+3V3": [], "GND": []}, {}
    for ref, key, _ in signal_pins:
        value, rail = _PARTS[key]
        comps.append({"reference": ref, "type": "ic", "value": value, "lib_id": "",
                      "pins": [], "footprint": ""})
        nets[rail].append((ref, "1", "VIN", "power_in"))
        nets["GND"].append((ref, "2", "GND", "power_in"))
        domains[ref] = {"value": value, "power_rails": [rail], "io_rails": None}
    nets["SIG"] = [(ref, "3", pin, "input") for ref, _, pin in signal_pins]
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    ctx = build_analysis_context(comps, full, {}, known_power_rails={"+5V", "+3V3", "GND"})
    with patch.object(vd, "get_regulator_features", return_value=None):
        entries = _detect_cross_domain_signals(ctx, domains)
    (entry,) = [e for e in entries if e["net"] == "SIG"]
    return entry["needs_level_shifter"]


class CrossDomainRegulatorEnable(unittest.TestCase):
    def test_gpio_into_regulator_enable_needs_no_shifter(self):
        self.assertFalse(_signals([("U1", "MCU33", "PA0"), ("U2", "BUCK", "EN")]))

    def test_power_good_into_regulator_enable_needs_no_shifter(self):
        self.assertFalse(_signals([("U2", "BUCK", "PG"), ("U3", "LDO", "EN")]))

    def test_gpio_into_mcu_across_domains_needs_a_shifter(self):
        self.assertTrue(_signals([("U1", "MCU33", "PA0"), ("U4", "MCU5", "PD2")]))

    def test_other_ics_on_an_enable_net_still_pair_up(self):
        self.assertTrue(_signals([("U1", "MCU33", "PA0"), ("U2", "BUCK", "EN"),
                                  ("U4", "MCU5", "PD2")]))

    def test_regulator_signal_pin_that_is_not_enable_still_counts(self):
        self.assertTrue(_signals([("U1", "MCU33", "PA0"), ("U2", "BUCK", "MODE")]))


if __name__ == "__main__":
    unittest.main()
