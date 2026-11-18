"""A net name written with spaces reads like its underscore form, unless a word says it
describes a reference or a signal rather than a rail."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from kicad_core.netnames import is_power_net_name  # noqa: E402

RAILS = ["12V IN", "5V PCIE", "3.3v from USB", "5v OUT", "Usb 5V", "5V ", " 12V IN",
         "SWITCHED 5V", "3.3V Rail Out", "/Power/12V IN"]
NOT_RAILS = ["3V3 REF", "5V Reference", "3.3v reference", "DATA 5V", "+5V Data",
             "5V RETURN", "24v LED return", "1.65V for 12VDC", "5v tach signal from megasquirt",
             "5v PwrGood", "Vref 5V"]


class SpacedNames(unittest.TestCase):
    def test_spaced_rails_read_like_their_underscore_form(self):
        for name in RAILS:
            with self.subTest(name=name):
                self.assertTrue(is_power_net_name(name))

    def test_reference_and_signal_words_keep_a_spaced_name_a_signal(self):
        for name in NOT_RAILS:
            with self.subTest(name=name):
                self.assertFalse(is_power_net_name(name))

    def test_underscore_names_with_those_words_are_unchanged(self):
        for name in ["5V_REF", "VREF_5V", "5V_DATA", "5V_RETURN"]:
            with self.subTest(name=name):
                self.assertEqual(is_power_net_name(name), is_power_net_name(name.upper()))
        self.assertTrue(is_power_net_name("VCC_FOR_IO"))


if __name__ == "__main__":
    unittest.main()
