"""PU-001 pin-name set.

SPI MISO is driven push-pull (tri-stated when deselected) by the selected peripheral; the
SPI bus needs no pull-up on it. Interrupt outputs (INT) are commonly open-drain and keep
the missing pull-up warning.
"""
import unittest

from tools.tests.test_validation_w4 import ctx_of, ic, rule, vd


def _pu001(pin_name, net):
    ctx = ctx_of([ic("U1", "MCU")], {net: [("U1", "5", pin_name, "bidirectional")]}, set())
    return rule(vd.validate_pullups(ctx), "PU-001")


class PullUpPinNames(unittest.TestCase):
    def test_spi_miso_without_resistor_gets_no_pullup_warning(self):
        self.assertEqual(_pu001("SPI1_MISO", "MISO_LINE"), [])

    def test_bare_miso_pin_gets_no_pullup_warning(self):
        self.assertEqual(_pu001("MISO", "MISO_LINE"), [])

    def test_interrupt_pin_without_resistor_still_warns(self):
        got = _pu001("INT", "SENSOR_IRQ")
        self.assertEqual(len(got), 1)
        self.assertIn("INT", got[0]["summary"])


if __name__ == "__main__":
    unittest.main()
