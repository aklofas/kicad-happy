"""A board file may hold both KiCad 5 `(module ...)` and newer `(footprint ...)` entries (ergogen
writes such files); KiCad loads every one of them, in file order."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.sexp import parse  # noqa: E402
from pcb.reader import extract_footprints, extract_silkscreen  # noqa: E402

BOARD = '''(kicad_pcb (version 20240108) (generator "ergogen")
(layers (0 "F.Cu" signal) (31 "B.Cu" signal) (37 "F.SilkS" user) (44 "Edge.Cuts" user))
(net 0 "") (net 1 "GND")
(module "lib:R_0603" (layer F.Cu) (tedit 5E1ADAC2) (at 10 10)
  (fp_text reference R1 (at 0 -1.5) (layer F.SilkS) (effects (font (size 1 1) (thickness 0.15))))
  (fp_text value 10k (at 0 1.5) (layer F.Fab) (effects (font (size 1 1) (thickness 0.15))))
  (pad 1 smd rect (at -0.8 0) (size 0.8 0.9) (layers F.Cu F.Paste F.Mask) (net 1 "GND"))
  (pad 2 smd rect (at 0.8 0) (size 0.8 0.9) (layers F.Cu F.Paste F.Mask)))
(footprint "C_0603" (version 20240108) (generator "pcbnew") (layer "F.Cu") (at 20 10 0)
  (property "Reference" "C1" (at 0 -1.5 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
  (property "Value" "100n" (at 0 1.5 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))
  (pad "1" smd rect (at -0.8 0) (size 0.8 0.9) (layers "F.Cu" "F.Paste" "F.Mask") (net 1 "GND"))
  (pad "2" smd rect (at 0.8 0) (size 0.8 0.9) (layers "F.Cu" "F.Paste" "F.Mask")))
(module "lib:R_0603" (layer F.Cu) (tedit 5E1ADAC2) (at 30 10)
  (fp_text reference R2 (at 0 -1.5) (layer F.SilkS) (effects (font (size 1 1) (thickness 0.15))))
  (fp_text value 1k (at 0 1.5) (layer F.Fab) (effects (font (size 1 1) (thickness 0.15))))
  (pad 1 smd rect (at -0.8 0) (size 0.8 0.9) (layers F.Cu F.Paste F.Mask))
  (pad 2 smd rect (at 0.8 0) (size 0.8 0.9) (layers F.Cu F.Paste F.Mask) (net 1 "GND")))
)
'''


class MixedModuleFootprintBoard(unittest.TestCase):
    def test_every_part_is_read_in_file_order(self):
        fps = extract_footprints(parse(BOARD))
        self.assertEqual([fp["reference"] for fp in fps], ["R1", "C1", "R2"])
        self.assertEqual([fp["value"] for fp in fps], ["10k", "100n", "1k"])

    def test_silkscreen_counts_references_of_both_forms(self):
        root = parse(BOARD)
        silk = extract_silkscreen(root, extract_footprints(root))
        self.assertEqual(silk["refs_visible_on_silk"], 3)
        self.assertEqual(silk["refs_hidden_on_silk"], 0)


if __name__ == "__main__":
    unittest.main()
