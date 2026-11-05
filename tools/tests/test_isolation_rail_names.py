# tools/tests/test_isolation_rail_names.py
"""A rail counts as an isolated rail only when ISO or a whole _B / _SEC token names it."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from domain_detectors import _is_isolated_rail_name  # noqa: E402


class IsolatedRailName(unittest.TestCase):
    def test_isolated_rail_names(self):
        for name in ["+3V3_ISO", "V_ISOOUT", "/sheet/V_ISOL", "3.3V_B", "3.3V_B_Pre",
                     "BATT_B", "3.3VA_B", "VCC_B2", "5V_SEC", "+12V_SEC_OUT"]:
            self.assertTrue(_is_isolated_rail_name(name), name)

    def test_names_that_only_start_with_b_or_sec(self):
        for name in ["V_BAT", "MIC_BIAS", "INPUT_BATT", "VCC_BATT", "VCCA_BR", "V_BAT_CMD",
                     "ACAP_BATT_OUT", "/power_switch_bbB/ONOFF", "VDD_SECURE", "+5V"]:
            self.assertFalse(_is_isolated_rail_name(name), name)


if __name__ == "__main__":
    unittest.main()
