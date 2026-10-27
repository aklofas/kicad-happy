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
        # A sheet-local label is its own net; it is not the rail of the same leaf name.
        self.assertFalse(is_power_net_name("/Sheet/3V3_EN", {"3V3_EN"}))
        self.assertFalse(is_power_net_name("/Sheet/3V3_EN"))
        self.assertTrue(is_power_net_name("/pwr/vcc_io"))


class RailSetMatchesFullName(unittest.TestCase):
    # KiCad joins a global power pin's net by name, but a local label only within its own
    # sheet (eeschema connection_graph.cpp), so a local `X` on sheet A and a power symbol `X`
    # elsewhere are two nets and only the power symbol's is a rail.
    def test_local_label_named_like_a_rail_elsewhere_is_not_that_rail(self):
        self.assertFalse(is_power_net_name("/A/X", {"X"}))
        self.assertFalse(is_power_net_name("/HVIL/HVIL_N", {"HVIL_N"}))

    def test_rail_by_its_full_name(self):
        self.assertTrue(is_power_net_name("X", {"X"}))

    def test_leaf_name_heuristics_still_apply(self):
        self.assertTrue(is_power_net_name("/pwr/vcc_io", {"X"}))
        self.assertTrue(is_power_net_name("/Power/3V3", {"3V3"}))


if __name__ == "__main__":
    unittest.main()
