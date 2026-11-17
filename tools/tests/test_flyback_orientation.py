# tools/tests/test_flyback_orientation.py
"""A low-side N-channel switch's flyback diode runs from the drain (anode) to the supply
(cathode); a P-channel high-side switch's runs from ground (anode) to the drain (cathode).
A diode across drain and source counts when it is reverse-biased in the off state. A zener
or TVS clamp, or a diode the wrong way round, is not one. Diodes whose pins carry no A/K
names, or whose pins come from the built-in fallback symbol, keep the orientation-blind
reading."""
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
            fet_value="2N7002", source="GND", load_to="+12V", diode_nets=None):
    """Q1 switches a relay coil K1 (load_to -> DRAIN); its source sits on `source`. D1 sits
    across the coil unless diode_nets gives its (anode, cathode) nets."""
    a_net, k_net = ("+12V", "DRAIN") if anode_on_supply else ("DRAIN", "+12V")
    if diode_nets:
        a_net, k_net = diode_nets
    comps = [
        {"reference": "Q1", "type": "transistor", "value": fet_value, "lib_id": fet_lib},
        {"reference": "K1", "type": "relay", "value": "G5V-1", "lib_id": "Relay:G5V-1"},
        {"reference": "D1", "type": "diode", "value": diode_value, "lib_id": diode_lib,
         "_pin_source": pin_source},
    ]
    nets = {"+12V": [], "GND": [], "GATE": [("Q1", "1", "G", "input")],
            "DRAIN": [("Q1", "3", "D", "passive"), ("K1", "2", "~", "passive")]}
    nets[load_to].append(("K1", "1", "~", "passive"))
    nets[source].append(("Q1", "2", "S", "passive"))
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
    fet_pins = {"Q1": {"gate": "GATE", "drain": "DRAIN", "source": source,
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

    def test_p_channel_diode_from_drain_to_supply_is_not_a_flyback(self):
        self.assertEqual(_switch(anode_on_supply=True, fet_lib="Device:Q_PMOS_GDS",
                                 fet_value="AO3401A"), (False, None))

    def test_p_channel_diode_from_ground_to_drain_is_a_flyback(self):
        self.assertEqual(_switch(fet_lib="Device:Q_PMOS_GDS", fet_value="AO3401A",
                                 source="+12V", load_to="GND",
                                 diode_nets=("GND", "DRAIN")), (True, "D1"))

    def test_p_channel_part_number_diode_from_ground_to_drain_is_a_flyback(self):
        self.assertEqual(_switch(fet_lib="Transistor_FET:AO3400A", fet_value="AO3401A",
                                 source="+12V", load_to="GND",
                                 diode_nets=("GND", "DRAIN")), (True, "D1"))

    def test_p_channel_diode_from_drain_to_ground_is_not_a_flyback(self):
        self.assertEqual(_switch(fet_lib="Device:Q_PMOS_GDS", fet_value="AO3401A",
                                 source="+12V", load_to="GND",
                                 diode_nets=("DRAIN", "GND")), (False, None))

    def test_p_channel_zener_from_ground_to_drain_is_not_a_flyback(self):
        self.assertEqual(_switch(diode_value="BZT52C27", fet_lib="Device:Q_PMOS_GDS",
                                 fet_value="AO3401A", source="+12V", load_to="GND",
                                 diode_nets=("GND", "DRAIN")), (False, None))

    def test_p_channel_drain_source_diode_cathode_on_source_is_a_flyback(self):
        self.assertEqual(_switch(fet_lib="Device:Q_PMOS_GDS", fet_value="AO3401A",
                                 source="+12V", load_to="GND",
                                 diode_nets=("DRAIN", "+12V")), (True, "D1"))

    def test_p_channel_drain_source_diode_cathode_on_drain_is_not_a_flyback(self):
        self.assertEqual(_switch(fet_lib="Device:Q_PMOS_GDS", fet_value="AO3401A",
                                 source="+12V", load_to="GND",
                                 diode_nets=("+12V", "DRAIN")), (False, None))

    def test_drain_source_schottky_cathode_on_drain_is_a_flyback(self):
        self.assertEqual(_switch(diode_value="BAT54", diode_nets=("GND", "DRAIN")),
                         (True, "D1"))

    def test_drain_source_diode_cathode_on_source_is_not_a_flyback(self):
        self.assertEqual(_switch(diode_value="BAT54", diode_nets=("DRAIN", "GND")),
                         (False, None))

    def test_drain_source_zener_is_not_a_flyback(self):
        self.assertEqual(_switch(diode_value="BZT52C27", diode_nets=("GND", "DRAIN")),
                         (False, None))

    def test_drain_source_tvs_is_not_a_flyback(self):
        self.assertEqual(_switch(diode_value="SMAJ28A", diode_lib="Device:D_TVS",
                                 diode_nets=("GND", "DRAIN")), (False, None))

    def test_drain_source_unnamed_pins_keep_the_orientation_blind_reading(self):
        self.assertEqual(_switch(names=("~", "~"), diode_nets=("DRAIN", "GND")),
                         (True, "D1"))


if __name__ == "__main__":
    unittest.main()
