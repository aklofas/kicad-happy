import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_core.netnames import is_power_net_name  # noqa: E402


class RailControlSuffix(unittest.TestCase):
    def test_rail_plus_control_suffix_is_a_signal(self):
        for name in ["VCC_EN", "VBUS_DET", "5V_EN", "VDD_PG", "VIN_EN", "3V3_PG",
                     "+5V_EN", "PWR_ON", "VBUS_SENSE", "VCC_PGOOD", "3V3_RESET",
                     "VBAT_SNS", "VBUS_DETECT", "/Power/3V3_EN"]:
            self.assertFalse(is_power_net_name(name), name)

    def test_real_rails_stay_power(self):
        for name in ["VCC_IO", "VDD_CORE", "5V_USB", "VCC_SW", "5V_INT",
                     "+1V2_INT", "+3V3", "VBUS"]:
            self.assertTrue(is_power_net_name(name), name)

    def test_configured_power_rail_keeps_precedence(self):
        self.assertTrue(is_power_net_name("3V3_EN", {"3V3_EN"}))

    def test_configured_rail_under_a_sheet_path(self):
        self.assertTrue(is_power_net_name("/Sheet/3V3_EN", {"3V3_EN"}))
        self.assertFalse(is_power_net_name("/Sheet/3V3_EN"))
        self.assertTrue(is_power_net_name("/pwr/vcc_io"))


if __name__ == "__main__":
    unittest.main()
