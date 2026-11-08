"""KiCad stops reading a stackup at the first board layer listed a second time
(PCB_IO_KICAD_SEXPR_PARSER::parseBoardStackup); dielectric names may repeat. Expected stacks are
the ones `kicad-cli pcb upgrade --force` (10.0.8) writes back for the same files. A board with one
copper layer and no stackup gets a single dielectric on the copper's inner side."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.sexp import parse  # noqa: E402
from pcb.pipeline import _infer_stackup  # noqa: E402
from pcb.reader import extract_setup  # noqa: E402

LAYER = {
    "F.Mask": '(layer "F.Mask" (type "Top Solder Mask") (thickness 0.01))',
    "F.Cu": '(layer "F.Cu" (type "copper") (thickness 0.035))',
    "In1.Cu": '(layer "In1.Cu" (type "copper") (thickness 0.035))',
    "In2.Cu": '(layer "In2.Cu" (type "copper") (thickness 0.035))',
    "B.Cu": '(layer "B.Cu" (type "copper") (thickness 0.035))',
    "B.Mask": '(layer "B.Mask" (type "Bottom Solder Mask") (thickness 0.01))',
}


def diel(name, kind="core"):
    return f'(layer "{name}" (type "{kind}") (thickness 0.2) (material "FR4") (epsilon_r 4.5))'


def stack_names(items):
    root = parse('(kicad_pcb (version 20221018) (generator pcbnew) (general (thickness 1.6))\n'
                 '  (setup (stackup ' + " ".join(items) + ')))\n')
    return [l["name"] for l in extract_setup(root)["stackup"]]


class StackupRepeat(unittest.TestCase):
    def test_two_layer_stack_written_twice_keeps_the_first_copy(self):
        one = [LAYER["F.Mask"], LAYER["F.Cu"], diel("dielectric 1"), LAYER["B.Cu"], LAYER["B.Mask"]]
        self.assertEqual(stack_names(one + one),
                         ["F.Mask", "F.Cu", "dielectric 1", "B.Cu", "B.Mask"])

    def test_reading_stops_at_a_repeated_inner_layer(self):
        items = [LAYER["F.Mask"], LAYER["F.Cu"], diel("dielectric 1"), LAYER["In1.Cu"],
                 diel("dielectric 2", "prepreg"), LAYER["In1.Cu"], diel("dielectric 3"),
                 LAYER["B.Cu"], LAYER["B.Mask"]]
        self.assertEqual(stack_names(items),
                         ["F.Mask", "F.Cu", "dielectric 1", "In1.Cu", "dielectric 2"])

    def test_repeated_dielectric_names_are_all_kept(self):
        items = [LAYER["F.Cu"], diel("1080x1"), LAYER["In1.Cu"], diel("core"), LAYER["In2.Cu"],
                 diel("1080x1"), LAYER["B.Cu"]]
        self.assertEqual(stack_names(items),
                         ["F.Cu", "1080x1", "In1.Cu", "core", "In2.Cu", "1080x1", "B.Cu"])


class SingleCopperInference(unittest.TestCase):
    def test_back_copper_only_gets_a_dielectric_above_it(self):
        stack = _infer_stackup(["B.Cu"], 1.6)
        self.assertEqual([(l["name"], l["type"]) for l in stack],
                         [("dielectric 1", "core"), ("B.Cu", "copper")])
        self.assertAlmostEqual(stack[0]["thickness"], 1.545)

    def test_front_copper_only_gets_a_dielectric_below_it(self):
        stack = _infer_stackup(["F.Cu"], 1.6)
        self.assertEqual([(l["name"], l["type"]) for l in stack],
                         [("F.Cu", "copper"), ("dielectric 1", "core")])
        self.assertAlmostEqual(stack[1]["thickness"], 1.545)


if __name__ == "__main__":
    unittest.main()
