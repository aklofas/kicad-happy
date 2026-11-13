"""A reference or bias node (VREF, 2V5_REF) is not a rail without a source, and an
undriven one is not a rail missing decoupling; a REF net an IC takes its supply from
still is."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import audit_rail_sources, detect_design_observations  # noqa: E402


def _part(ref, typ, value):
    return {"reference": ref, "type": typ, "value": value, "lib_id": "", "footprint": "",
            "properties": {}, "pins": []}


def _run(nets, comps):
    """RS-001 findings by net and DO-DET missing-decoupling rails by IC."""
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    ctx = build_analysis_context(comps, full, {}, known_power_rails={"+5V", "GND"})
    rs = {f["nets"][0] for f in audit_rail_sources(ctx) if f["rule_id"] == "RS-001"}
    obs = detect_design_observations(ctx, {"decoupling_analysis": [], "power_regulators": []})
    do = {o["component"]: o["rails_without_caps"] for o in obs if o["category"] == "decoupling"}
    return rs, do


_SUPPLY = {"+5V": [("U9", "1", "VOUT", "power_out"), ("U1", "8", "VDD", "power_in")],
           "GND": [("U1", "4", "GND", "power_in")]}
_COMPS = [_part("U1", "ic", "ADC"), _part("U9", "ic", "LDO"),
          _part("R1", "resistor", "10k"), _part("R2", "resistor", "10k")]


class ReferenceNode(unittest.TestCase):
    def test_divider_tap_into_a_vref_pin_is_not_a_rail(self):
        rs, do = _run({"+5V": _SUPPLY["+5V"] + [("R1", "1", "~", "passive")],
                       "GND": _SUPPLY["GND"] + [("R2", "2", "~", "passive")],
                       "VREF": [("R1", "2", "~", "passive"), ("R2", "1", "~", "passive"),
                                ("U1", "3", "VREF", "power_in")]}, _COMPS)
        self.assertNotIn("VREF", rs)
        self.assertEqual(do["U1"], ["+5V"])

    def test_rail_named_divider_tap_into_a_ref_input_is_not_missing_decoupling(self):
        rs, do = _run({"+5V": _SUPPLY["+5V"] + [("R1", "1", "~", "passive")],
                       "GND": _SUPPLY["GND"] + [("R2", "2", "~", "passive")],
                       "0V75_REF": [("R1", "2", "~", "passive"), ("R2", "1", "~", "passive"),
                                    ("U1", "3", "REFIN", "input")]}, _COMPS)
        self.assertNotIn("0V75_REF", rs)
        self.assertEqual(do["U1"], ["+5V"])

    def test_reference_driven_by_an_ic_output_is_sourced_and_kept_as_a_rail(self):
        rs, do = _run({**_SUPPLY,
                       "2V5_REF": [("U2", "1", "OUT", "output"),
                                   ("U1", "3", "REFIN", "input")]},
                      _COMPS + [_part("U2", "ic", "LM4040")])
        self.assertNotIn("2V5_REF", rs)
        self.assertEqual(do["U1"], ["+5V", "2V5_REF"])

    def test_reference_net_an_ic_takes_its_supply_from_stays_a_rail(self):
        rs, do = _run({**_SUPPLY,
                       "+3V3_REF": [("U3", "1", "VCC", "power_in")]},
                      _COMPS + [_part("U3", "ic", "INA4181")])
        self.assertIn("+3V3_REF", rs)
        self.assertEqual(do["U3"], ["+3V3_REF"])

    def test_refrigerator_and_refclk_names_are_not_reference_nodes(self):
        rs, do = _run({**_SUPPLY,
                       "220V_REFRIG": [("K1", "1", "~", "passive")],
                       "MIPI_REFCLK": [("U1", "5", "MIPI_REFCLK", "power_in")],
                       "+1V8_REFCLK": [("U1", "6", "CLKIN", "input")]},
                      _COMPS + [_part("K1", "relay", "RELAY")])
        self.assertIn("220V_REFRIG", rs)
        self.assertIn("MIPI_REFCLK", rs)
        self.assertEqual(do["U1"], ["+1V8_REFCLK", "+5V"])


if __name__ == "__main__":
    unittest.main()
