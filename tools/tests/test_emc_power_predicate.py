"""IO-001, IO-002, BE-001 and RP-001 classify power and ground nets with the shared name rules."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from emc_rules import _is_power_or_ground  # noqa: E402

POWER_OR_GROUND = ["MCU3V3", "/sheet/VCC", "+3V3", "VBUS", "V+", "GND", "EARTH", "/5V",
                   "+BATT", "USB_5V", "5V PCIE", "PWR", "V-", "VMOT", "/sub/3V3"]
SIGNALS = ["VCC_EN", "3V3_PG", "VBUS_SENSE", "VBAT_PGOOD", "+5V_EN", "/sub/VCC_EN", "/pwr/3V3_PG", "SDA", "BIT0", ""]


class PowerPredicate(unittest.TestCase):
    def test_rails_and_grounds(self):
        for name in POWER_OR_GROUND:
            with self.subTest(name=name):
                self.assertTrue(_is_power_or_ground(name))

    def test_control_and_status_nets_are_signals(self):
        for name in SIGNALS:
            with self.subTest(name=name):
                self.assertFalse(_is_power_or_ground(name))


if __name__ == "__main__":
    unittest.main()
