"""PCB ground domains follow the shared ground-name rule; EMC GP-005 lists the names."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "skills"
sys.path.insert(0, str(ROOT / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "emc" / "scripts"))

from pcb.routing import analyze_ground_domains  # noqa: E402
from emc_rules import check_ground_domains  # noqa: E402


def names(nets, rails=None):
    gd = analyze_ground_domains([], dict(enumerate(nets, 1)), [], power_rails=rails)
    return [d["net"] for d in gd["domains"]]


class GroundDomains(unittest.TestCase):
    def test_pin_named_net_is_not_a_domain(self):
        self.assertEqual(names(["GND", "unconnected-(U1-GND-Pad3)", "Net-(U1-GND)", "Board_0-Net-(U1-GND)"]), ["GND"])

    def test_named_grounds_beyond_the_shared_rule_are_domains(self):
        self.assertEqual(
            names(["GND", "/Audio/AGND_CODEC", "PGND2", "ESP_GND2", "unconnected-(U1-GND-Pad3)"]),
            ["/Audio/AGND_CODEC", "ESP_GND2", "GND", "PGND2"])

    def test_zero_volt_and_battery_negative_are_domains(self):
        self.assertEqual(sorted(names(["0V", "BATT-", "+5V"])), ["0V", "BATT-"])

    def test_com_needs_a_power_symbol(self):
        self.assertEqual(names(["GND", "COM"]), ["GND"])
        self.assertEqual(names(["GND", "COM"], {"COM"}), ["COM", "GND"])

    def test_gp005_lists_domain_names(self):
        gd = analyze_ground_domains([], {1: "GND", 2: "AGND"}, [])
        f = check_ground_domains({"ground_domains": gd})
        self.assertEqual(f[0]["nets"], ["AGND", "GND"])
        self.assertIn("AGND, GND", f[0]["description"])


if __name__ == "__main__":
    unittest.main()
