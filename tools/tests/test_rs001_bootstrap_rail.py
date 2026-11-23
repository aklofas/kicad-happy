"""RS-001 on a rail whose only power_in pins are bootstrap pins is name-based, not deterministic.
BTST, VBST and CBOOT pins are bootstrap pins: fed by their capacitor, so no PP-001 or RS-001."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import audit_power_pin_dc_paths, audit_rail_sources  # noqa: E402


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
        self.assertEqual(f["confidence"], "heuristic")
        self.assertIn("carries only power-symbol pins (no part's power input)", f["description"])
        self.assertNotIn("bootstrap", f["description"])

    def test_power_symbol_only_rail_is_heuristic(self):
        f = _rs001({"+5V": [("#PWR1", "1", "+5V", "power_in"),
                            ("R1", "1", "1", "passive")]})["+5V"]
        self.assertEqual(f["confidence"], "heuristic")
        self.assertEqual(f["provenance"]["confidence"], "heuristic")
        self.assertIn("carries only power-symbol pins (no part's power input)", f["description"])
        self.assertEqual(f["pins"], ["#PWR1.1"])

    def test_real_power_in_pin_stays_deterministic(self):
        f = _rs001({"+5V": [("#PWR1", "1", "+5V", "power_in"),
                            ("U1", "1", "VDD", "power_in")]})["+5V"]
        self.assertEqual(f["confidence"], "deterministic")
        self.assertIn("carries power_in pins", f["description"])

    def test_one_vin_pin_rail_is_unchanged(self):
        f = _rs001({"+5V_X": [("U1", "1", "VIN", "power_in")]})["+5V_X"]
        self.assertEqual(f["confidence"], "deterministic")


def _bootstrap_pin(pin_name, net="BOOT_NODE"):
    """PP-001 and RS-001 records on *net*: U1's power_in *pin_name* there, fed by C1 from the
    switch node, which L1 joins to +5V."""
    comps = [{"reference": "U1", "type": "ic", "value": "BQ25798"},
             {"reference": "C1", "type": "capacitor", "value": "47n"},
             {"reference": "L1", "type": "inductor", "value": "2.2u"}]
    pins = {net: [("U1", "4", pin_name, "power_in"), ("C1", "1", "", "passive")],
            "SW": [("U1", "5", "SW1", "power_out"), ("C1", "2", "", "passive"),
                   ("L1", "1", "", "passive")],
            "+5V": [("L1", "2", "", "passive"), ("U1", "1", "VBUS", "power_in")]}
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=pn, pin_name=nm, pin_type=t)
                                    for r, pn, nm, t in pp],
                "point_count": 0, "no_connect": False, "has_pwr_flag": n == "+5V", "labels": []}
            for n, pp in pins.items()}
    ctx = build_analysis_context(comps, full, {}, known_power_rails={"+5V"})
    found = [f for f in audit_power_pin_dc_paths(ctx) + audit_rail_sources(ctx)
             if f["rule_id"] in ("PP-001", "RS-001") and net in (f.get("nets") or [])]
    return sorted(f["rule_id"] for f in found)


class BootstrapPinNames(unittest.TestCase):
    def test_charger_and_converter_bootstrap_pins_need_no_rail(self):
        for name in ("BTST1", "BTST2", "VBST", "CBOOT", "CBOOT2"):
            self.assertEqual(_bootstrap_pin(name), [], name)

    def test_other_names_with_those_letters_keep_their_records(self):
        # A 6522's CB1 and a bridge output WF_HB8 are not bootstrap pins
        for name in ("CB1", "WF_HB8", "VDD"):
            self.assertEqual(_bootstrap_pin(name), ["PP-001", "RS-001"], name)


if __name__ == "__main__":
    unittest.main()
