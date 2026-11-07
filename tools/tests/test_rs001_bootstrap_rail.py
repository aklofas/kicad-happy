"""RS-001 on a rail whose only power_in pins are bootstrap pins is name-based, not deterministic."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import audit_rail_sources  # noqa: E402


def _rs001(nets):
    comps = [{"reference": "U1", "type": "ic", "value": "BUCK"}]
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    ctx = build_analysis_context(comps, full, {}, known_power_rails={"+5V"})
    return {f["nets"][0]: f for f in audit_rail_sources(ctx) if f["rule_id"] == "RS-001"}


class BootstrapOnlyRail(unittest.TestCase):
    def test_bootstrap_only_rail_is_heuristic_with_its_own_wording(self):
        f = _rs001({"19V_BST": [("U1", "4", "BST", "power_in")]})["19V_BST"]
        self.assertEqual(f["confidence"], "heuristic")
        self.assertEqual(f["provenance"]["confidence"], "heuristic")
        self.assertIn("only power_in pins are bootstrap pins", f["description"])
        self.assertEqual(f["pins"], ["U1.4"])

    def test_supply_pin_keeps_the_rail_deterministic(self):
        f = _rs001({"19V_BST": [("U1", "4", "BST", "power_in"),
                                ("U1", "1", "VIN", "power_in")]})["19V_BST"]
        self.assertEqual(f["confidence"], "deterministic")
        self.assertIn("carries power_in pins", f["description"])

    def test_power_symbol_pin_named_after_a_boot_net_is_not_bootstrap(self):
        f = _rs001({"+5V_USB_BOOT": [("#PWR1", "1", "+5V_USB_BOOT", "power_in")]})["+5V_USB_BOOT"]
        self.assertEqual(f["confidence"], "deterministic")
        self.assertIn("carries power_in pins", f["description"])

    def test_one_vin_pin_rail_is_unchanged(self):
        f = _rs001({"+5V_X": [("U1", "1", "VIN", "power_in")]})["+5V_X"]
        self.assertEqual(f["confidence"], "deterministic")


if __name__ == "__main__":
    unittest.main()
