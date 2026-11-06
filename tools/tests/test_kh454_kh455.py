# tools/tests/test_kh454_kh455.py
"""RS-001 does not audit a net whose only power_in pins are bootstrap pins; PP-001
dedups on (ref, pin, net) so duplicate / unannotated refs keep every power pin, and a
rail known only by its pins ends the PP-001 walk unless a capacitor is its only link to
another rail."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import audit_rail_sources, audit_power_pin_dc_paths  # noqa: E402


def _ctx(components, nets, flagged=()):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": n in flagged, "labels": []}
            for n, pins in nets.items()}
    return build_analysis_context(components, full, {}, known_power_rails={"+5V", "+3V3"})


def _rules(findings, rule):
    return [f for f in findings if f["rule_id"] == rule]


class BootstrapNetIsNotARail(unittest.TestCase):
    def _buck(self, extra_nets=None):
        comps = [{"reference": "U1", "type": "ic", "value": "BUCK"},
                 {"reference": "C1", "type": "capacitor", "value": "100n"},
                 {"reference": "U2", "type": "ic", "value": "MCU"}]
        nets = {"+5V": [("U1", "1", "VIN", "power_in")],
                "GND": [("U1", "2", "GND", "power_in")],
                "SW": [("U1", "3", "SW", "output"), ("C1", "2", "~", "passive")],
                "BST": [("U1", "4", "BST", "power_in"), ("C1", "1", "~", "passive")]}
        nets.update(extra_nets or {})
        return _ctx(comps, nets, flagged={"+5V"})

    def test_bootstrap_only_net_gets_no_rs001(self):
        f = audit_rail_sources(self._buck())
        self.assertEqual([x["nets"][0] for x in _rules(f, "RS-001")], [])

    def test_non_bootstrap_power_in_net_still_gets_rs001(self):
        f = audit_rail_sources(self._buck({"IO_CTL": [("U2", "7", "VDDIO", "power_in")]}))
        self.assertEqual([x["nets"][0] for x in _rules(f, "RS-001")], ["IO_CTL"])

    def test_mixed_bootstrap_and_supply_pin_is_still_a_rail(self):
        f = audit_rail_sources(self._buck({"BST": [("U1", "4", "BST", "power_in"),
                                                   ("U2", "7", "VDD", "power_in")]}))
        self.assertEqual([x["nets"][0] for x in _rules(f, "RS-001")], ["BST"])


class DuplicateRefPowerPins(unittest.TestCase):
    COMPS = [{"reference": "U?", "type": "ic", "value": "DRV"},
             {"reference": "U?", "type": "ic", "value": "MCU"},
             {"reference": "C1", "type": "capacitor", "value": "100n"},
             {"reference": "C2", "type": "capacitor", "value": "100n"}]

    def test_bootstrap_and_vdd_on_same_ref_and_pin(self):
        nets = {"BST_A": [("U?", "48", "BST_A", "power_in"), ("C2", "1", "~", "passive")],
                "__unnamed_1": [("U?", "48", "VDD", "power_in"), ("C1", "1", "~", "passive")],
                "GND": [("C1", "2", "~", "passive")]}
        f = _rules(audit_power_pin_dc_paths(_ctx(self.COMPS, nets)), "PP-001")
        self.assertEqual([x["pins"] for x in f], [["U?.48 (VDD)"]])

    def test_second_symbol_power_pin_is_not_masked(self):
        # The first U?.48 sits on a named rail (evaluated, no finding); the second, AC-coupled
        # U?.48 shares its (ref, pin) label and was skipped by the old dedup.
        nets = {"+3V3": [("U?", "48", "VCC", "power_in")],
                "__unnamed_1": [("U?", "48", "VDD", "power_in"), ("C1", "1", "~", "passive")],
                "GND": [("C1", "2", "~", "passive")]}
        f = _rules(audit_power_pin_dc_paths(_ctx(self.COMPS, nets)), "PP-001")
        self.assertEqual([x["pins"] for x in f], [["U?.48 (VDD)"]])


class PinRecognisedRail(unittest.TestCase):
    """N_U1 is a rail by its pins (a supply pin and a capacitor to ground)."""
    COMPS = [{"reference": r, "type": "ic", "value": "MCU"} for r in ("U1", "U2")] + \
            [{"reference": r, "type": "capacitor", "value": "100n"} for r in ("C1", "C2", "C10")] + \
            [{"reference": "D1", "type": "diode", "value": "BAT54"},
             {"reference": "U3", "type": "ic", "value": "SENSOR"},
             {"reference": "FB1", "type": "ferrite_bead", "value": "600R"},
             {"reference": "C3", "type": "capacitor", "value": "100n"}]

    def _pp(self, extra=None, power_regulators=None, flagged=()):
        nets = {"N_U1": [("U1", "1", "VCC", "power_in"), ("C1", "1", "~", "passive")],
                "GND": [("C1", "2", "~", "passive"), ("U1", "2", "GND", "power_in")],
                "+3V3": [("U2", "1", "VCC", "power_in")]}
        for net, pins in (extra or {}).items():
            nets.setdefault(net, []).extend(pins)
        ctx = _ctx(self.COMPS, nets, flagged={"GND", "+3V3", *flagged})
        self.assertIn("N_U1", ctx.topology_rails)
        f = audit_power_pin_dc_paths(ctx, power_regulators=power_regulators)
        return [x["start_net"] for x in _rules(f, "PP-001")]

    AC = {"N_U1": [("C2", "1", "~", "passive")], "+3V3": [("C2", "2", "~", "passive")]}

    def test_decoupled_rail_without_source_ends_the_walk(self):
        self.assertEqual(self._pp(), [])

    def test_ac_coupled_rail_gets_pp001(self):
        self.assertEqual(self._pp(self.AC), ["N_U1"])

    def test_power_out_pin_is_a_source(self):
        self.assertEqual(self._pp({**self.AC, "N_U1": self.AC["N_U1"] + [("U2", "5", "VOUT", "power_out")]}), [])

    def test_regulator_output_is_a_source(self):
        self.assertEqual(self._pp(self.AC, power_regulators=[{"output_rail": "N_U1"}]), [])

    def test_diode_fed_rail_ends_the_walk(self):
        self.assertEqual(self._pp({**self.AC, "N_U1": self.AC["N_U1"] + [("D1", "2", "K", "passive")],
                                   "+5V": [("D1", "1", "A", "passive")]}), [])

    def test_stacked_power_out_pin_is_a_source(self):
        self.assertEqual(self._pp({**self.AC, "N_U1": self.AC["N_U1"]
                                   + [("U2", "5", "VOUT", "power_out+passive")]}), [])

    def test_pwr_flag_is_a_source(self):
        self.assertEqual(self._pp(self.AC, flagged={"N_U1"}), [])
        self.assertEqual(self._pp({**self.AC, "N_U1": self.AC["N_U1"]
                                   + [("#FLG01", "1", "pwr", "passive")]}), [])

    def test_ground_cap_alongside_the_coupling_cap_keeps_pp001(self):
        self.assertEqual(self._pp({**self.AC, "N_U1": self.AC["N_U1"] + [("C3", "1", "~", "passive")],
                                   "GND": [("C3", "2", "~", "passive")]}), ["N_U1"])

    # U3 on another sheet takes its supply through FB1 from the sheet where N_U1 is decoupled.
    OTHER_SHEET = {"/sensor/N_U3": [("U3", "1", "VDD", "power_in"), ("FB1", "2", "~", "passive")],
                   "N_U1": [("FB1", "1", "~", "passive")],
                   "GND": [("U3", "2", "GND", "power_in")]}

    def test_rail_reached_from_another_sheet_ends_the_walk(self):
        self.assertEqual(self._pp(self.OTHER_SHEET), [])
        # Without U1's supply pin N_U1 is no rail, and the walk from U3 meets only C1.
        ctx = _ctx(self.COMPS, {**self.OTHER_SHEET,
                                "N_U1": self.OTHER_SHEET["N_U1"] + [("C1", "1", "~", "passive")],
                                "GND": self.OTHER_SHEET["GND"] + [("C1", "2", "~", "passive")]})
        self.assertEqual([x["start_net"] for x in _rules(audit_power_pin_dc_paths(ctx), "PP-001")],
                         ["/sensor/N_U3"])

    def test_duplicate_ref_capacitor_is_not_a_coupling_cap(self):
        # C10 is two symbols sharing one reference: four pins, not a capacitor across the nets.
        self.assertEqual(self._pp({"N_U1": [("C10", "1", "~", "passive")],
                                   "+3V3": [("C10", "2", "~", "passive")],
                                   "GND": [("C10", "3", "~", "passive")],
                                   "N_X": [("C10", "4", "~", "passive")]}), [])


if __name__ == "__main__":
    unittest.main()
