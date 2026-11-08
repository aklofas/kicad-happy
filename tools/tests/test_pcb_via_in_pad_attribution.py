"""A via inside several pads is listed once under via_in_pad, attributed to the pad on its own net,
else a numbered pad, else the smallest: an unnumbered exposed-pad aperture rectangle drawn over
the numbered exposed pad, or a pin pad that overlaps it, does not take the via."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.sexp import parse  # noqa: E402
from pcb.copper import analyze_vias  # noqa: E402
from pcb.reader import extract_footprints, extract_nets, extract_vias  # noqa: E402


def board(items):
    return parse(
        '(kicad_pcb (version 20221018) (generator pcbnew)\n'
        ' (general (thickness 1.6))\n'
        ' (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (35 "F.Paste" user) (39 "F.Mask" user))\n'
        ' (setup (pad_to_mask_clearance 0))\n'
        ' (net 0 "") (net 1 "GND") (net 2 "SIG")\n' + items + ')\n')


def footprint(ref, x, pads):
    return (f'(footprint "Test:{ref}" (layer "F.Cu") (at {x} 10)\n'
            f' (property "Reference" "{ref}" (at 0 3 0) (layer "F.SilkS")){pads})\n')


def pad(num, at, size, net=None, layers='"F.Cu" "F.Paste" "F.Mask"'):
    n = f' (net {net[0]} "{net[1]}")' if net else ""
    return f' (pad "{num}" smd rect (at {at[0]} {at[1]}) (size {size[0]} {size[1]}) (layers {layers}){n})'


def via(x, y, net):
    return f'(via (at {x} {y}) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net {net}))\n'


def via_in_pad(items):
    root = board(items)
    return analyze_vias(extract_vias(root), extract_footprints(root),
                        extract_nets(root))["via_in_pad"]


GND, SIG = (1, "GND"), (2, "SIG")


class ViaInPadAttribution(unittest.TestCase):
    def test_exposed_pad_aperture_rectangle_does_not_take_the_via(self):
        # the unnumbered paste/mask aperture comes first in the file, the numbered EP after it
        pads = pad("", (0, 0), (2.4, 2.4), layers='"F.Cu" "F.Paste"') + pad("9", (0, 0), (3, 3), GND)
        (entry,) = via_in_pad(footprint("U4", 10, pads) + via(10.5, 10.5, 1))
        self.assertEqual((entry["component"], entry["pad"], entry["same_net"]), ("U4", "9", True))

    def test_pin_pad_of_another_net_overlapping_the_exposed_pad(self):
        pads = pad("1", (1.2, 0), (1.0, 0.4), SIG) + pad("9", (0, 0), (3, 3), GND)
        (entry,) = via_in_pad(footprint("U7", 10, pads) + via(11.1, 10, 1))
        self.assertEqual((entry["pad"], entry["same_net"]), ("9", True))

    def test_overlapping_same_net_pads_take_the_smaller_one(self):
        items = (footprint("J1", 10, pad("10", (0, 0), (3, 2), GND))
                 + footprint("TP16", 10, pad("1", (0, 0), (1, 1), GND))
                 + via(10, 10, 1))
        (entry,) = via_in_pad(items)
        self.assertEqual((entry["component"], entry["pad"]), ("TP16", "1"))


if __name__ == "__main__":
    unittest.main()
