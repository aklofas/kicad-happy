# tools/tests/test_bridge_detection.py
"""A half bridge is two MOSFETs in series across a supply or ground whose middle node drives
a load: another part's pin, or a label (a load on another sheet). Two FETs stacked in a
logic gate (an NMOS NAND pull-down) share a middle node nothing else reaches; they are two
transistor switches, not a bridge."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
import signal_detectors as sd  # noqa: E402


def _stack(top_drain="+12V", low_source="GND", mid_load=None, mid_label=False,
           shunt_on=None, rails=("+12V", "+5V", "GND")):
    """Q1 over Q2: Q1 drain on `top_drain`, Q1 source = Q2 drain = MID, Q2 source on
    `low_source`. `mid_load` adds an inductor L1 from MID to `top_drain`'s rail side;
    `shunt_on` adds a shunt R2 from that net to GND; a top drain that is not a rail gets a
    pull-up R1 to +5V."""
    comps = [
        {"reference": "Q1", "type": "transistor", "value": "2N7002",
         "lib_id": "Device:Q_NMOS_GDS"},
        {"reference": "Q2", "type": "transistor", "value": "2N7002",
         "lib_id": "Device:Q_NMOS_GDS"},
    ]
    nets = {n: [] for n in rails}
    nets.setdefault(top_drain, [])
    nets.setdefault(low_source, [])
    nets["GATE_A"] = [("Q1", "1", "G", "input")]
    nets["GATE_B"] = [("Q2", "1", "G", "input")]
    nets["MID"] = [("Q1", "2", "S", "passive"), ("Q2", "3", "D", "passive")]
    nets[top_drain].append(("Q1", "3", "D", "passive"))
    nets[low_source].append(("Q2", "2", "S", "passive"))
    if top_drain not in rails:
        comps.append({"reference": "R1", "type": "resistor", "value": "10k",
                      "lib_id": "Device:R"})
        nets[top_drain].append(("R1", "1", "~", "passive"))
        nets["+5V"].append(("R1", "2", "~", "passive"))
    if mid_load:
        comps.append({"reference": "L1", "type": "inductor", "value": "10u",
                      "lib_id": "Device:L"})
        nets["MID"].append(("L1", "1", "~", "passive"))
        nets.setdefault(mid_load, []).append(("L1", "2", "~", "passive"))
    if shunt_on:
        comps.append({"reference": "R2", "type": "resistor", "value": "0.01",
                      "lib_id": "Device:R"})
        nets[shunt_on].append(("R2", "1", "~", "passive"))
        nets["GND"].append(("R2", "2", "~", "passive"))
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    if mid_label:
        full["MID"]["labels"] = [{"name": "MID", "type": "global_label"}]
    for c in comps:
        c.setdefault("pins", [])
        c.setdefault("footprint", "")
    ctx = build_analysis_context(comps, full, {}, known_power_rails=set(rails))
    bridges, matched, fet_pins = sd.detect_bridge_circuits(ctx)
    switches = {c["reference"] for c in sd.detect_transistor_circuits(ctx, matched, fet_pins)}
    pairs = [(hb["high_side"], hb["low_side"]) for b in bridges for hb in b["half_bridges"]]
    return pairs, switches


class HalfBridgeDetection(unittest.TestCase):
    def test_logic_stack_with_private_middle_node_is_not_a_bridge(self):
        pairs, switches = _stack(top_drain="Y")
        self.assertEqual(pairs, [])
        self.assertEqual(switches, {"Q1", "Q2"})

    def test_logic_stack_on_ground_with_rail_drain_is_not_a_bridge(self):
        pairs, switches = _stack(top_drain="+12V")
        self.assertEqual(pairs, [])
        self.assertEqual(switches, {"Q1", "Q2"})

    def test_low_side_shunt_bridge_driving_an_inductor_is_kept(self):
        pairs, switches = _stack(low_source="SENSE", shunt_on="SENSE", mid_load="LOAD")
        self.assertEqual(pairs, [("Q1", "Q2")])
        self.assertEqual(switches, set())

    def test_stack_whose_middle_node_carries_a_label_is_kept(self):
        pairs, _ = _stack(top_drain="Y", mid_label=True)
        self.assertEqual(pairs, [("Q1", "Q2")])

    def test_bridge_on_a_supply_without_a_rail_name_is_kept(self):
        pairs, _ = _stack(top_drain="VHIGH", rails=("+5V", "GND"), mid_load="LOAD")
        self.assertEqual(pairs, [("Q1", "Q2")])


if __name__ == "__main__":
    unittest.main()
