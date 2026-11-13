"""Power, ground and VSS name rules: V<number> names, escaped slashes, control-prefix tails."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from kicad_core.netnames import (is_ground_name, is_pin_guarded_signal,  # noqa: E402
                                 is_power_net_name, is_vss_name)

RAILS = ["V12", "V33", "V3V3", "V1P8", "V3.3", "V3_3", "V33IO", "V3P3D", "V36_PROTECTED",
         "V1P8_SW", "V7.5V", "V5reg_1", "V16", "V128", "5V{slash}3V3",
         "ADC_AVDD", "DAC_VDD", "SWD_VCC"]
SIGNALS = ["/V1AMP1", "V24.rx", "V24:TX", "V2FREQ", "V1OUT", "V1a", "V1_CLK1", "V4_OUT",
           "V2V_0", "V16F", "V1", "V2+", "SDIO_CMD{slash}3V3", "+E{slash}A", "+5V{slash}4",
           "EN_EXT_VDD", "EN_VCC", "/VCC{slash}2"]


class PowerNetName(unittest.TestCase):
    def test_rails_by_name(self):
        for name in RAILS:
            with self.subTest(name=name):
                self.assertTrue(is_power_net_name(name))

    def test_signals_are_not_rails(self):
        for name in SIGNALS:
            with self.subTest(name=name):
                self.assertFalse(is_power_net_name(name))

    def test_rail_signal_suffixes_are_public(self):
        from kicad_core.netnames import RAIL_SIGNAL_SUFFIXES
        self.assertIn("PGOOD", RAIL_SIGNAL_SUFFIXES)
        self.assertIn("EN", RAIL_SIGNAL_SUFFIXES)


class EscapedSlashOnTheGroundSide(unittest.TestCase):
    PIN_NETS = ["Net-(VR1-ADJ{slash}GND)", "unconnected-(IC2-DNU{slash}VSSQ_1-Pad25)"]

    def test_pin_named_nets_are_not_ground(self):
        for name in self.PIN_NETS:
            with self.subTest(name=name):
                self.assertFalse(is_ground_name(name))
                self.assertFalse(is_vss_name(name))

    def test_sheet_path_ground_stays_ground(self):
        for name in ["/Power/GND", "Board_0-/GND_IR"]:
            with self.subTest(name=name):
                self.assertTrue(is_ground_name(name))

    def test_escaped_slash_label_is_not_pin_guarded(self):
        pins = [("input", True)]
        self.assertFalse(is_pin_guarded_signal("~{MCLR}{slash}VPP", pins))
        self.assertTrue(is_pin_guarded_signal("/sheet/VPP", pins))


if __name__ == "__main__":
    unittest.main()
