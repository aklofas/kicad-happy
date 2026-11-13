"""Ground names: COM by power symbol, virtual grounds, 0-10 V interface nets, ground tokens."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from kicad_core.netnames import is_ground_name, is_virtual_ground_name, is_vss_name  # noqa: E402
from pcb.routing import analyze_ground_domains  # noqa: E402

GROUNDS = ["AVSS", "DVSS", "GROUND", "ground", "AGND_CODEC", "PGND_3V3", "HEATER_GND_1",
           "ESP_GND2", "AGND1", "V+_GND_CH1", "0VA", "0V_A", "/Codec/AGND_CODEC"]
NOT_GROUNDS = ["VGND", "HP_VGND", "VGND1", "Virtual_Ground", "/Audio/VGND", "0V_10V", "0V_32V",
               "Net-(U1-GND)", "DAC_VSS", "REFGND_0.5V", "Earth"]


class GroundName(unittest.TestCase):
    def test_com_is_ground_only_when_a_power_symbol_names_it(self):
        self.assertTrue(is_ground_name("COM", {"COM"}))
        self.assertFalse(is_ground_name("COM"))
        self.assertFalse(is_ground_name("COM", {"GND"}))

    def test_grounds(self):
        for name in GROUNDS:
            with self.subTest(name=name):
                self.assertTrue(is_ground_name(name))

    def test_not_grounds(self):
        for name in NOT_GROUNDS:
            with self.subTest(name=name):
                self.assertFalse(is_ground_name(name))

    def test_virtual_grounds(self):
        for name in ("VGND", "HP_VGND", "VGND1", "Virtual_Ground", "/Audio/VGND"):
            with self.subTest(name=name):
                self.assertTrue(is_virtual_ground_name(name))
        for name in ("GND", "AGND", "", None, "Net-(VR1-ADJ{slash}VGND)"):
            with self.subTest(name=name):
                self.assertFalse(is_virtual_ground_name(name))

    def test_avss_and_dvss_are_vss(self):
        self.assertTrue(is_vss_name("AVSS"))
        self.assertTrue(is_vss_name("/ADC/DVSS"))
        self.assertFalse(is_vss_name("DAC_VSS"))


class PcbGroundDomains(unittest.TestCase):
    def test_substring_grounds_stay_domains_and_virtual_grounds_leave(self):
        gd = analyze_ground_domains([], {1: "GND", 2: "PVSS1", 3: "ISOGND12", 4: "VGND1",
                                         5: "HP_VGND"}, [])
        self.assertEqual(sorted(d["net"] for d in gd["domains"]), ["GND", "ISOGND12", "PVSS1"])


if __name__ == "__main__":
    unittest.main()
