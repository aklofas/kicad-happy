"""PU-001 pin-name set.

SPI MISO is driven push-pull (tri-stated when deselected) by the selected peripheral; the
SPI bus needs no pull-up on it. Interrupt outputs (INT) are commonly open-drain and keep
the missing pull-up warning.

A name that merely ends in the letters ``OD`` is not open drain. Datasheet evidence for the
pins that used to match:

- DW01A (Fortune, battery protector): ``OD`` is the discharge-control MOSFET gate drive
  output, listed under "OD output pin voltage" (page 2 of the datasheet).
- TPS22917 (TI SLVSDW8B, page 4): ``QOD``, quick output discharge, takes a resistor to
  VOUT, a tie to VOUT or no connection; it is not pulled to a rail.
- ADuM1401 (Analog Devices, Rev. M, Table 17): pin 6 ``VOD`` is "Logic Output D", a
  push-pull output (VOxH = VDD - 0.1 V at -20 uA).
- i.MX RT1020 data sheet (NXP, Table 5) and i.MX 6Dual/6Quad data sheet (ball H6):
  ``JTAG_MOD`` is an input with an on-chip 100 k pull-down (RT1020) or pull-up (i.MX 6).
"""
import unittest

from tools.tests.test_validation_w4 import ctx_of, ic, rule, vd


def _pu001(pin_name, net):
    ctx = ctx_of([ic("U1", "MCU")], {net: [("U1", "5", pin_name, "bidirectional")]}, set())
    return rule(vd.validate_pullups(ctx), "PU-001")


def _pu001_with_pins(pin_name, net, siblings):
    part = ic("U1", "MCU")
    part["pins"] = [{"number": str(i + 1), "name": n, "type": "output"}
                    for i, n in enumerate([pin_name, *siblings])]
    ctx = ctx_of([part], {net: [("U1", "1", pin_name, "output")]}, set())
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

    def test_pins_whose_name_merely_ends_in_od_get_no_pullup_warning(self):
        for name in ("QOD", "OD", "VOD", "FOD", "LOD-", "CMOD", "JTAG_MOD", "RXTX/RF_MOD",
                     "RF_MOD", "LOADMOD"):
            with self.subTest(pin=name):
                self.assertEqual(_pu001(name, "SIG"), [])

    def test_power_good_and_open_drain_named_pins_still_warn(self):
        for name in ("PWR_GOOD", "PWRGOOD", "PGOOD", "nPG", "PWRONRSTN_OD", "INT/OD", "P903_OD"):
            with self.subTest(pin=name):
                got = _pu001(name, "SIG")
                self.assertEqual(len(got), 1)
                self.assertIn(name, got[0]["summary"])

    def test_channel_d_output_beside_channel_a_gets_no_warning(self):
        self.assertEqual(_pu001_with_pins("V_OD", "SIG", ["V_OA", "V_OB"]), [])

    def test_trailing_od_word_alone_on_its_part_still_warns(self):
        self.assertEqual(len(_pu001_with_pins("V_OD", "SIG", ["V_IA"])), 1)


if __name__ == "__main__":
    unittest.main()
