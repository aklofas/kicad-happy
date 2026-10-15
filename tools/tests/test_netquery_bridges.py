# tools/tests/test_netquery_bridges.py
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))
from kicad_core import netquery as nq


def _nets():
    return {
        "+3V3": {"pins": [{"component": "U1", "pin_number": "1", "pin_name": "VDD", "pin_type": "power_in"},
                          {"component": "R1", "pin_number": "2", "pin_name": "~", "pin_type": "passive"}]},
        "VIN":  {"pins": [{"component": "R1", "pin_number": "1", "pin_name": "~", "pin_type": "passive"},
                          {"component": "JP1", "pin_number": "1", "pin_name": "A", "pin_type": "passive"}]},
        "VBUS": {"pins": [{"component": "JP1", "pin_number": "2", "pin_name": "B", "pin_type": "passive"},
                          {"component": "L1", "pin_number": "1", "pin_name": "1", "pin_type": "passive"}]},
        "VRAW": {"pins": [{"component": "L1", "pin_number": "2", "pin_name": "2", "pin_type": "passive"}]},
    }


COMPONENTS = [
    {"reference": "U1", "type": "ic", "value": "MCU"},
    {"reference": "R1", "type": "resistor", "value": "0R"},
    {"reference": "R2", "type": "resistor", "value": "1.1"},
    {"reference": "R3", "type": "resistor", "value": "DNP"},
    {"reference": "JP1", "type": "jumper", "value": "SolderJumper_2_Bridged"},
    {"reference": "L1", "type": "inductor", "value": "10uH"},
    {"reference": "C1", "type": "capacitor", "value": "100n"},
]
JUMPERS = [{"reference": "JP1", "default_state": "bridged", "nets": ["VIN", "VBUS"]},
           {"reference": "JP9", "default_state": "open", "nets": ["A", "B", "C"]}]


class Indexes(unittest.TestCase):
    def test_pin_to_net_map_holds_the_net_record(self):
        nets = _nets()
        m = nq.build_pin_to_net_map(nets)
        self.assertIs(m[("U1", "1")][1], nets["+3V3"])
        self.assertEqual(m[("U1", "1")][0], "+3V3")

    def test_ref_pins_order_and_shape(self):
        rp = nq.build_ref_pins(_nets())
        self.assertEqual(rp["R1"], [("2", "+3V3", "passive"), ("1", "VIN", "passive")])
        self.assertEqual(rp["L1"], [("1", "VBUS", "passive"), ("2", "VRAW", "passive")])


class Bridges(unittest.TestCase):
    def setUp(self):
        self.facts = nq.build_bridge_facts(COMPONENTS, nq.build_ref_pins(_nets()), JUMPERS)

    def test_by_ref_kinds_and_resistance(self):
        f = self.facts.by_ref
        self.assertEqual(f["R1"].resistance, 0.0)          # bare zero-ohm spelling
        self.assertAlmostEqual(f["R2"].resistance, 1.1)
        self.assertIsNone(f["R3"].resistance)               # unparsable, not zero
        self.assertEqual(f["L1"].kind, "inductor")
        self.assertEqual(f["L1"].nets, ("VBUS", "VRAW"))
        self.assertNotIn("C1", f)
        self.assertNotIn("U1", f)

    def test_jumper_state_comes_from_the_detection(self):
        self.assertEqual(self.facts.by_ref["JP1"].kind, "jumper")
        self.assertEqual(self.facts.by_ref["JP1"].default_state, "bridged")
        self.assertEqual(self.facts.by_ref["JP1"].nets, ("VIN", "VBUS"))

    def test_jumpers_view_keeps_detection_order_and_all_detections(self):
        refs = [j.ref for j in self.facts.jumpers]
        self.assertEqual(refs, ["JP1", "JP9"])
        self.assertEqual(self.facts.jumpers[1].nets, ("A", "B", "C"))   # 3-net jumper kept; RS filters it

    def test_component_typed_jumper_without_detection_has_no_state(self):
        facts = nq.build_bridge_facts(COMPONENTS, nq.build_ref_pins(_nets()), [])
        self.assertIsNone(facts.by_ref["JP1"].default_state)
        self.assertEqual(facts.by_ref["JP1"].nets, ("VIN", "VBUS"))
        self.assertEqual(facts.jumpers, [])


if __name__ == "__main__":
    unittest.main()
