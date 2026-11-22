"""detect_buzzer_speakers: which buzzer pin net is the driven side, and what drives it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "kicad", "scripts"))

from domain_detectors import detect_buzzer_speakers

GROUNDS = {"GND"}
RAILS = {"VUSB", "+5V", "+3V3"}


class _Nq:
    def __init__(self, ctx):
        self.ctx = ctx

    def components_on_net(self, net, exclude_refs=None, comp_type=None):
        out = []
        for ref, pins in self.ctx.pins.items():
            if ref in (exclude_refs or set()):
                continue
            for pin, n in pins.items():
                if n == net:
                    out.append({"reference": ref, "type": self.ctx.types[ref], "pin_number": pin})
        return out


class _Ctx:
    """The slice of AnalysisContext the detector reads."""

    def __init__(self, parts):
        # parts: ref -> (type, {pin: net})
        self.types = {r: t for r, (t, _) in parts.items()}
        self.pins = {r: p for r, (_, p) in parts.items()}
        self.components = [{"reference": r, "type": t, "value": ""} for r, t in self.types.items()]
        self.nq = _Nq(self)

    def is_ground(self, net):
        return net in GROUNDS

    def is_power_net(self, net):
        return net in RAILS

    def get_two_pin_nets(self, ref):
        p = self.pins[ref]
        return p.get("1"), p.get("2")


def _npn(collector, emitter):
    return {"collector_net": collector, "emitter_net": emitter}


def _run(parts, circuits):
    return detect_buzzer_speakers(_Ctx(parts), circuits)


class BuzzerDrivenSideTest(unittest.TestCase):
    def test_second_pin_net_with_the_switching_transistor_is_the_signal_net(self):
        # + pin behind a jumper to the supply, - pin on the collector of an NPN to ground
        parts = {
            "BZ1": ("buzzer", {"1": "BZ_PLUS", "2": "BZ_MINUS"}),
            "JP1": ("jumper", {"1": "BZ_PLUS", "2": "VUSB"}),
            "Q1": ("transistor", {"B": "DRV", "C": "BZ_MINUS", "E": "GND"}),
        }
        (b,) = _run(parts, [_npn("BZ_MINUS", "GND")])
        self.assertEqual(b["signal_net"], "BZ_MINUS")
        self.assertEqual(b["nets"], ["BZ_MINUS"])
        self.assertTrue(b["has_transistor_driver"])

    def test_signal_net_keeps_the_first_net_when_no_transistor_switches_a_rail(self):
        parts = {
            "BZ1": ("buzzer", {"1": "GPIO", "2": "GND"}),
        }
        (b,) = _run(parts, [])
        self.assertEqual(b["signal_net"], "GPIO")

    def test_net_shared_by_transistor_emitters_is_not_the_switched_side(self):
        # The second pin is on an analogue bus that several emitters and a collector whose
        # emitter is on another signal net share: no transistor there switches a rail.
        parts = {
            "BZ1": ("buzzer", {"1": "OUT", "2": "BN"}),
            "Q1": ("transistor", {"B": "A", "C": "X", "E": "BN"}),
            "Q2": ("transistor", {"B": "B", "C": "Y", "E": "BN"}),
            "Q3": ("transistor", {"B": "C", "C": "BN", "E": "Z"}),
        }
        circuits = [_npn("X", "BN"), _npn("Y", "BN"), _npn("BN", "Z")]
        (b,) = _run(parts, circuits)
        self.assertEqual(b["signal_net"], "OUT")

    def test_high_side_buzzer_is_unchanged(self):
        parts = {
            "BZ1": ("buzzer", {"1": "+5V", "2": "COL"}),
            "Q1": ("transistor", {"B": "D", "C": "COL", "E": "GND"}),
        }
        (b,) = _run(parts, [_npn("COL", "GND")])
        self.assertEqual(b["signal_net"], "COL")
        self.assertTrue(b["has_transistor_driver"])


class BuzzerDriverTest(unittest.TestCase):
    def test_ic_on_the_supply_rail_behind_the_resistor_is_not_the_driver(self):
        parts = {
            "BZ1": ("buzzer", {"1": "+5V", "2": "SIG"}),
            "R1": ("resistor", {"1": "SIG", "2": "+5V"}),
            "U1": ("ic", {"VIN": "+5V"}),
            "Q1": ("transistor", {"B": "D", "C": "SIG", "E": "GND"}),
        }
        (b,) = _run(parts, [_npn("SIG", "GND")])
        self.assertNotIn("driver_ic", b)
        self.assertNotIn("direct_gpio_drive", b)
        self.assertEqual(b["series_resistor"]["reference"], "R1")

    def test_ic_on_a_signal_net_behind_the_resistor_is_the_driver(self):
        parts = {
            "BZ1": ("buzzer", {"1": "SIG", "2": "GND"}),
            "R1": ("resistor", {"1": "SIG", "2": "PIN"}),
            "U1": ("ic", {"IO1": "PIN"}),
        }
        (b,) = _run(parts, [])
        self.assertEqual(b["driver_ic"], "U1")
        self.assertTrue(b["direct_gpio_drive"])

    def test_ic_behind_a_resistor_to_ground_is_not_the_driver(self):
        parts = {
            "BZ1": ("buzzer", {"1": "SIG", "2": "GND"}),
            "R1": ("resistor", {"1": "SIG", "2": "GND"}),
            "U1": ("ic", {"GND": "GND"}),
        }
        (b,) = _run(parts, [])
        self.assertNotIn("driver_ic", b)


if __name__ == "__main__":
    unittest.main()
