"""Thermal-pad via grading. A pad whose vias meet the recommended count only before drill
weighting is "adequate", never "good". A via counts under the pad only when its copper reaches
the pad's layer: its own span holds that layer, or it sits at the same point and net as a
contiguous stack of vias that does; a staggered blind or buried via does not."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.sexp import parse  # noqa: E402
from pcb.copper import analyze_thermal_pad_vias  # noqa: E402
from pcb.reader import extract_footprints, extract_vias, extract_zones  # noqa: E402


def board(items):
    return parse(
        '(kicad_pcb (version 20221018) (generator pcbnew)\n'
        ' (general (thickness 1.6))\n'
        ' (layers (0 "F.Cu" signal) (1 "In1.Cu" signal) (2 "In2.Cu" signal) (31 "B.Cu" signal)\n'
        '  (34 "B.Paste" user) (35 "F.Paste" user) (38 "B.Mask" user) (39 "F.Mask" user)\n'
        '  (44 "Edge.Cuts" user))\n'
        ' (setup (pad_to_mask_clearance 0))\n'
        ' (net 0 "") (net 1 "GND") (net 3 "SIG")\n' + items + ')\n')


def qfn(side="F"):
    """Four 0.3 x 0.8 signal pads and a 3 x 3 exposed pad on GND (9 mm2: min 5, ideal 9 vias)."""
    lay = f'"{side}.Cu" "{side}.Paste" "{side}.Mask"'
    pads = "".join(f' (pad "{n}" smd rect (at {dx} -2.5) (size 0.3 0.8) (layers {lay}) (net 3 "SIG"))'
                   for n, dx in ((1, -0.75), (2, -0.25), (3, 0.25), (4, 0.75)))
    pads += f' (pad "5" smd rect (at 0 0) (size 3 3) (layers {lay}) (net 1 "GND"))'
    return (f'(footprint "Test:QFN" (layer "{side}.Cu") (at 15 10)\n'
            f' (property "Reference" "U1" (at 0 4 0) (layer "{side}.SilkS")){pads})\n')


def via(x, y, layers=("F.Cu", "B.Cu"), drill=0.3, kind=""):
    names = " ".join(f'"{l}"' for l in layers)
    return f'(via {kind} (at {x} {y}) (size 0.6) (drill {drill}) (layers {names}) (net 1))\n'


GRID = [(14 + 0.5 * i, 9 + 0.5 * j) for i in range(5) for j in range(5)]  # inside the pad


def tv001(side, vias):
    root = board(qfn(side) + "".join(vias))
    zones, fills = extract_zones(root)
    (entry,) = analyze_thermal_pad_vias(extract_footprints(root), extract_vias(root), zones, fills)
    return entry


class DrillWeightedGrade(unittest.TestCase):
    def test_count_met_only_before_drill_weighting_is_adequate(self):
        # 9 vias of 0.2 mm: raw 9 (the ideal), effective 9 x 0.44 = 4 (under the minimum 5)
        e = tv001("F", [via(x, y, drill=0.2) for x, y in GRID[:9]])
        self.assertEqual(e["via_count"], 9)
        self.assertLess(e["total_effective_verified_vias"], e["recommended_min_vias"])
        self.assertEqual(e["adequacy"], "adequate")

    def test_count_met_after_drill_weighting_stays_good(self):
        self.assertEqual(tv001("F", [via(x, y) for x, y in GRID[:9]])["adequacy"], "good")


class ViaReachesThePad(unittest.TestCase):
    def test_blind_via_off_the_pad_layer_is_not_counted(self):
        vias = [via(x, y) for x, y in GRID[:5]]
        vias += [via(x, y, ("In1.Cu", "B.Cu"), kind="blind") for x, y in GRID[5:8]]
        vias += [via(x, y, ("In1.Cu", "In2.Cu"), kind="blind") for x, y in GRID[8:9]]
        self.assertEqual(tv001("F", vias)["via_count"], 5)

    def test_back_pad_does_not_count_front_microvias(self):
        vias = [via(x, y) for x, y in GRID[:5]]
        vias += [via(x, y, ("F.Cu", "In1.Cu"), kind="micro") for x, y in GRID[5:9]]
        self.assertEqual(tv001("B", vias)["via_count"], 5)

    def test_stacked_chain_reaching_the_pad_is_counted(self):
        x, y = GRID[0]
        stack = [via(x, y, ("F.Cu", "In1.Cu"), kind="micro"),
                 via(x, y, ("In1.Cu", "In2.Cu"), kind="blind"),
                 via(x, y, ("In2.Cu", "B.Cu"), kind="micro")]
        staggered = [via(GRID[1][0], GRID[1][1], ("In1.Cu", "In2.Cu"), kind="blind")]
        e = tv001("B", stack + staggered)
        self.assertEqual(e["via_count"], 3)


if __name__ == "__main__":
    unittest.main()
