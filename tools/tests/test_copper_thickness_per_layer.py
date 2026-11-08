"""Trace resistance takes the copper thickness of the segment's own layer.

25.4 mm x 0.254 mm of copper: 1.68e-8 * 0.0254 / (0.000254 * 0.000035) = 48 mOhm at
35 um (outer layers here) and 24 mOhm at 70 um (the inner layer). The EMC power tree uses
1.724e-8 ohm m (annealed copper at 20 C): 49.3 and 24.6 mOhm."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "spice" / "scripts"))

from emc_formulas import enrich_power_tree_with_pcb  # noqa: E402
from extract_parasitics import extract_parasitics  # noqa: E402

STACKUP = [{"name": "F.Cu", "type": "copper", "thickness": 0.035},
           {"name": "dielectric 1", "type": "core", "thickness": 0.2, "epsilon_r": 4.5},
           {"name": "In1.Cu", "type": "copper", "thickness": 0.070},
           {"name": "dielectric 2", "type": "core", "thickness": 1.0, "epsilon_r": 4.5},
           {"name": "B.Cu", "type": "copper", "thickness": 0.035}]


def _seg(layer):
    return {"layer": layer, "length_mm": 25.4, "width_mm": 0.254}


class PowerTreeEnrichment(unittest.TestCase):
    def _r(self, net_length):
        tree = {"VIN": {}}
        enrich_power_tree_with_pcb(tree, {"setup": {"stackup": STACKUP},
                                          "net_lengths": [dict(net_length, net_name="VIN")]})
        return tree["VIN"]["trace_r_total_ohm"]

    def test_segment_on_an_inner_layer_takes_that_layers_copper(self):
        self.assertAlmostEqual(self._r({"trace_segments": [_seg("F.Cu")]}), 0.0493, delta=0.0002)
        self.assertAlmostEqual(self._r({"trace_segments": [_seg("In1.Cu")]}), 0.0246, delta=0.0002)

    def test_layer_lengths_take_their_own_copper_without_segments(self):
        # 0.3 mm default width: 25.4 mm on F.Cu is 41.7 mOhm, the same on In1.Cu 20.9 mOhm
        nl = {"total_length_mm": 50.8,
              "layers": {"F.Cu": {"length_mm": 25.4}, "In1.Cu": {"length_mm": 25.4}}}
        self.assertAlmostEqual(self._r(nl), 0.0417 + 0.0209, delta=0.0002)

    def test_layer_the_stackup_does_not_name_takes_the_first_copper(self):
        self.assertAlmostEqual(self._r({"trace_segments": [_seg("In2.Cu")]}), 0.0493, delta=0.0002)


class SpiceParasitics(unittest.TestCase):
    def test_segment_resistance_follows_its_layer(self):
        pcb = {"setup": {"stackup": STACKUP},
               "net_lengths": [{"net": "VIN", "trace_segments": [_seg("F.Cu"), _seg("In1.Cu")]}]}
        segs = extract_parasitics(pcb)["nets"]["VIN"]["trace_segments"]
        self.assertEqual([s["layer"] for s in segs], ["F.Cu", "In1.Cu"])
        self.assertAlmostEqual(segs[0]["resistance_ohm"], 0.048, delta=0.0005)
        self.assertAlmostEqual(segs[1]["resistance_ohm"], 0.024, delta=0.0005)


if __name__ == "__main__":
    unittest.main()
