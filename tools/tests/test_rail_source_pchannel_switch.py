# tools/tests/test_rail_source_pchannel_switch.py
"""A P-channel high-side switch passes the rail on its source on to its drain, so the drain
rail is sourced when the source rail is. A reverse-polarity, ideal-diode or power-path FET
(gate tied or pulled to ground, driven by a controller's GATE pin, or a drain that is a USB
bus-power input) has its input on the drain and sources nothing."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
import signal_detectors as sd  # noqa: E402

TYPES = {"Q": "transistor", "R": "resistor", "D": "diode", "U": "ic", "J": "connector",
         "JP": "jumper"}


def _findings(gate_pins, *, fet="AO3401A", source_flag=True, drain_pins=(), jumper=None,
              gate_net="GATE", drain_net="5V_SW"):
    """(rule, rail) rail-source findings for Q1 with its source on +5V and its drain on
    drain_net, which feeds U2's VDD. gate_pins: [(ref, pin, pin_name, other_net or None)];
    a resistor or diode gets its other pin on other_net."""
    nets = {"+5V": [("Q1", "2", "S", "passive")],
            drain_net: [("Q1", "3", "D", "passive"), ("U2", "1", "VDD", "power_in")],
            "GATE": [],
            "GND": [("U2", "2", "GND", "power_in")]}
    nets[gate_net].append(("Q1", "1", "G", "input"))
    for ref, pin, name, other in gate_pins:
        nets[gate_net].append((ref, pin, name, "output" if ref.startswith("U") else "passive"))
        if other:
            nets.setdefault(other, []).append((ref, "2", name, "passive"))
    for ref, pin, name in drain_pins:
        nets[drain_net].append((ref, pin, name, "input"))
    if jumper:
        nets["+5V"].append(("JP1", "1", "", "passive"))
        nets[drain_net].append(("JP1", "2", "", "passive"))
    refs = sorted({r for pins in nets.values() for r, _, _, _ in pins})
    comps = [{"reference": r, "type": TYPES["JP" if r.startswith("JP") else r[0]],
              "value": fet if r == "Q1" else "10k" if r[0] == "R" else r,
              "lib_id": ("Transistor_FET:" + fet) if r == "Q1" else "", "pins": [], "footprint": ""}
             for r in refs]
    full = {n: {"name": n, "point_count": 0, "no_connect": False, "labels": [],
                "has_pwr_flag": n == "+5V" and source_flag,
                "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                         for r, p, pn, t in pins]}
            for n, pins in nets.items() if pins}
    ctx = build_analysis_context(comps, full, {})
    _, matched, fet_pins = sd.detect_bridge_circuits(ctx)
    tcs = sd.detect_transistor_circuits(ctx, matched, fet_pins)
    jumpers = ([{"reference": "JP1", "default_state": jumper, "nets": ["+5V", drain_net]}]
               if jumper else None)
    found = sd.audit_rail_sources(ctx, solder_jumpers=jumpers, transistor_circuits=tcs)
    return sorted((f["rule_id"], f["summary"].split()[0]) for f in found)


GPIO_WITH_PULL_UP = [("U1", "4", "PB3", None), ("R1", "1", "~", "+5V")]


class PChannelSwitchSourcesItsDrain(unittest.TestCase):
    def test_switch_driven_by_a_gpio_with_a_pull_up_to_its_source_sources_its_drain(self):
        self.assertEqual(_findings(GPIO_WITH_PULL_UP), [])

    def test_switch_driven_by_an_n_channel_driver_sources_its_drain(self):
        self.assertEqual(_findings([("Q2", "3", "D", None), ("R1", "1", "~", "+5V")]), [])

    def test_switch_from_an_unsourced_rail_sources_nothing(self):
        self.assertEqual(_findings(GPIO_WITH_PULL_UP, source_flag=False),
                         [("RS-001", "+5V"), ("RS-001", "5V_SW")])

    def test_open_jumper_beside_the_switch_is_no_longer_the_only_source(self):
        self.assertEqual(_findings(GPIO_WITH_PULL_UP, jumper="open"), [])

    def test_n_channel_part_sources_nothing(self):
        self.assertEqual(_findings(GPIO_WITH_PULL_UP, fet="AO3400A"), [("RS-001", "5V_SW")])


class InputSideFetsSourceNothing(unittest.TestCase):
    def test_reverse_polarity_fet_with_its_gate_pulled_to_ground(self):
        gate = [("R1", "1", "~", "GND"), ("D1", "1", "A", "+5V")]
        self.assertEqual(_findings(gate), [("RS-001", "5V_SW")])

    def test_gate_tied_to_ground(self):
        self.assertEqual(_findings([], gate_net="GND"), [("RS-001", "5V_SW")])

    def test_ideal_diode_controller_gate(self):
        self.assertEqual(_findings([("U1", "4", "GATE", None)]), [("RS-001", "5V_SW")])

    def test_drain_named_vbus_is_a_usb_input(self):
        self.assertEqual(_findings(GPIO_WITH_PULL_UP, drain_net="VBUS"), [("RS-001", "VBUS")])

    def test_drain_feeding_an_ic_vbus_pin_is_a_usb_input(self):
        self.assertEqual(_findings(GPIO_WITH_PULL_UP, drain_pins=[("U3", "5", "VBUS")]),
                         [("RS-001", "5V_SW")])


if __name__ == "__main__":
    unittest.main()
