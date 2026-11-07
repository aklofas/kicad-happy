# tools/tests/test_flyback_orientation.py
"""A low-side N-channel switch's flyback diode runs from the drain (anode) to the supply
(cathode). A zener or TVS clamp, or a diode with its anode on the supply, is not one.
Diodes whose pins carry no A/K names, or whose pins come from the built-in fallback
symbol, keep the orientation-blind reading."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
import signal_detectors as sd  # noqa: E402

RAILS = ("+12V", "GND")


def _switch(diode_value="1N4148", diode_lib="Device:D", names=("A", "K"),
            anode_on_supply=False, pin_source="parsed_lib", fet_lib="Device:Q_NMOS_GDS",
            fet_value="2N7002"):
    """Q1 switches a relay coil K1 (+12V -> DRAIN) to ground; D1 sits across the coil."""
    a_net, k_net = ("+12V", "DRAIN") if anode_on_supply else ("DRAIN", "+12V")
    comps = [
        {"reference": "Q1", "type": "transistor", "value": fet_value, "lib_id": fet_lib},
        {"reference": "K1", "type": "relay", "value": "G5V-1", "lib_id": "Relay:G5V-1"},
        {"reference": "D1", "type": "diode", "value": diode_value, "lib_id": diode_lib,
         "_pin_source": pin_source},
    ]
    nets = {
        "+12V": [("K1", "1", "~", "passive")],
        "DRAIN": [("Q1", "3", "D", "passive"), ("K1", "2", "~", "passive")],
        "GATE": [("Q1", "1", "G", "input")],
        "GND": [("Q1", "2", "S", "passive")],
    }
    nets[a_net].append(("D1", "2", names[0], "passive"))
    nets[k_net].append(("D1", "1", names[1], "passive"))
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    for c in comps:
        c.setdefault("pins", [])
        c.setdefault("footprint", "")
    ctx = build_analysis_context(comps, full, {}, known_power_rails=set(RAILS))
    fet_pins = {"Q1": {"gate": "GATE", "drain": "DRAIN", "source": "GND",
                       "value": fet_value, "lib_id": fet_lib}}
    (circuit,) = [c for c in sd.detect_transistor_circuits(ctx, set(), fet_pins)
                  if c["reference"] == "Q1"]
    return circuit["has_flyback_diode"], circuit["flyback_diode"]


class FlybackOrientation(unittest.TestCase):
    def test_plain_diode_cathode_on_supply_is_a_flyback(self):
        self.assertEqual(_switch(), (True, "D1"))

    def test_diode_with_anode_on_supply_is_not_a_flyback(self):
        self.assertEqual(_switch(anode_on_supply=True), (False, None))

    def test_zener_by_value_is_not_a_flyback(self):
        self.assertEqual(_switch(diode_value="BZT52C27"), (False, None))

    def test_zener_by_symbol_is_not_a_flyback(self):
        self.assertEqual(_switch(diode_value="5V1", diode_lib="Device:D_Zener"), (False, None))

    def test_1n5338_zener_is_not_a_flyback(self):
        self.assertEqual(_switch(diode_value="1N5338B"), (False, None))

    def test_1n5399_rectifier_is_a_flyback(self):
        self.assertEqual(_switch(diode_value="1N5399"), (True, "D1"))

    def test_tvs_is_not_a_flyback(self):
        self.assertEqual(_switch(diode_value="SMAJ24A", diode_lib="Device:D_TVS"), (False, None))

    def test_unnamed_pins_keep_the_orientation_blind_reading(self):
        self.assertEqual(_switch(names=("~", "~"), anode_on_supply=True), (True, "D1"))

    def test_built_in_fallback_pins_keep_the_orientation_blind_reading(self):
        self.assertEqual(_switch(anode_on_supply=True, pin_source="builtin"), (True, "D1"))

    def test_built_in_pins_snapped_to_a_wire_keep_the_orientation_blind_reading(self):
        self.assertEqual(_switch(anode_on_supply=True, pin_source="snapped_to_wire"),
                         (True, "D1"))

    def test_p_channel_switch_is_unchanged(self):
        self.assertEqual(_switch(anode_on_supply=True, fet_lib="Device:Q_PMOS_GDS",
                                 fet_value="AO3401A"), (True, "D1"))


if __name__ == "__main__":
    unittest.main()
