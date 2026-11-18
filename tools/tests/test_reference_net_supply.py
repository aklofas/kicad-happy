"""A reference-named net that powers an IC through a supply pin (V-, VEE, VBAT, VIO, or a
supply-named pin the IC symbol types passive) is a supply rail; a REF net with no supply
pin, or with a supply-named pin on a connector, stays a reference node."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import audit_rail_sources, detect_design_observations  # noqa: E402


def _part(ref, typ, value):
    return {"reference": ref, "type": typ, "value": value, "lib_id": "", "footprint": "",
            "properties": {}, "pins": []}


def _run(nets, comps):
    """RS-001 nets and DO-DET missing-decoupling rails by IC."""
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
_COMPS = [_part("U1", "ic", "OPAMP"), _part("U9", "ic", "LDO")]


class ReferenceNetSupplyPin(unittest.TestCase):
    def test_negative_supply_pin_makes_a_reference_net_a_rail(self):
        for name in ("V-", "VEE", "VBAT", "VIO", "VL", "PVIN"):
            rs, do = _run({**_SUPPLY, "VREF_NEG": [("U1", "5", name, "power_in")],
                           "-2V5_REF": [("U1", "7", name, "power_in")]}, _COMPS)
            self.assertIn("VREF_NEG", rs, name)
            self.assertIn("-2V5_REF", do["U1"], name)

    def test_passive_supply_pin_on_an_ic_makes_a_reference_net_a_rail(self):
        rs, do = _run({**_SUPPLY, "5V_REF": [("U2", "1", "VCCB", "passive"),
                                             ("U1", "3", "REF+", "input")]},
                      _COMPS + [_part("U2", "ic", "TXB0108")])
        self.assertIn("5V_REF", rs)
        self.assertEqual(do["U2"], ["5V_REF"])

    def test_passive_supply_pin_on_a_connector_leaves_a_reference_node(self):
        rs, do = _run({**_SUPPLY, "2V5_REF": [("J1", "1", "VCC", "passive"),
                                              ("U1", "3", "REFIN", "input")]},
                      _COMPS + [_part("J1", "connector", "Conn")])
        self.assertNotIn("2V5_REF", rs)
        self.assertEqual(do["U1"], ["+5V"])

    def test_reference_input_pin_leaves_a_reference_node(self):
        rs, do = _run({**_SUPPLY, "VREF": [("U1", "3", "VREF", "power_in")]}, _COMPS)
        self.assertNotIn("VREF", rs)
        self.assertEqual(do["U1"], ["+5V"])

    def test_reference_net_without_a_supply_pin_stays_a_reference_node(self):
        rs, do = _run({**_SUPPLY, "VREF_NEG": [("U1", "3", "REFIN", "input"),
                                               ("U1", "6", "OUT", "passive")]}, _COMPS)
        self.assertNotIn("VREF_NEG", rs)
        self.assertEqual(do["U1"], ["+5V"])


if __name__ == "__main__":
    unittest.main()
