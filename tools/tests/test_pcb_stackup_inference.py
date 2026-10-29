# tools/tests/test_pcb_stackup_inference.py
"""The stackup KiCad 10 uses for a board, and dielectric sublayers.

A board whose file has no (stackup) gets BOARD_STACKUP::BuildDefaultStackupList
(board_stackup.cpp:678-770): copper 0.035 mm per layer, solder mask 0.01 mm per enabled mask
layer, every dielectric = (board thickness - copper - masks) / (copper count - 1), FR4,
epsilon_r 4.5 (BOARD_STACKUP_ITEM constructor), core and prepreg alternating from the top.
Expected thicknesses are the ones kicad-cli 10.0.7 writes into the Gerber job file for the same
boards (4 layers, 1.6 mm: 0.48 each; no mask layers: 0.4867; 2 layers: 1.51).

A dielectric with `addsublayer` is one layer whose thickness is the sum of its sublayers
(BuildBoardThicknessFromStackup, :570-576); its epsilon_r is the thickness-weighted mean."""
import os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parents[1] / "emc" / "scripts"))

from kicad_core.sexp import parse  # noqa: E402
from pcb import pipeline  # noqa: E402
from pcb.reader import extract_setup  # noqa: E402

CU4 = '(0 "F.Cu" signal) (1 "In1.Cu" signal) (2 "In2.Cu" signal) (31 "B.Cu" signal)'
MASKS = '(38 "B.Mask" user) (39 "F.Mask" user)'
FOUR = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]


def board_text(cu=CU4, masks=MASKS, stackup="", thickness="(thickness 1.6)"):
    return (f'(kicad_pcb (version 20240108) (generator "pcbnew") (general {thickness})'
            f' (layers {cu} {masks} (44 "Edge.Cuts" user))'
            f' (setup {stackup} (pad_to_mask_clearance 0)) (net 0 "") (net 1 "SIG")'
            ' (gr_rect (start 0 0) (end 20 20) (stroke (width 0.1) (type default))'
            ' (fill none) (layer "Edge.Cuts"))'
            ' (segment (start 2 2) (end 12 2) (width 0.2) (layer "F.Cu") (net 1))'
            ' (segment (start 2 4) (end 12 4) (width 0.2) (layer "In1.Cu") (net 1)))')


class BoardFile:
    def __init__(self, text):
        self.td = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.td.name, "b.kicad_pcb")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def __enter__(self):
        return self.path

    def __exit__(self, *exc):
        self.td.cleanup()


def dielectrics(stackup):
    return [l for l in stackup if l["type"] in ("core", "prepreg")]


class InferredStackup(unittest.TestCase):
    def test_four_layer_default(self):
        st = pipeline._infer_stackup(FOUR, 1.6)
        self.assertEqual([l["name"] for l in st if l["type"] == "copper"], FOUR)
        self.assertEqual([l["type"] for l in dielectrics(st)], ["core", "prepreg", "core"])
        for d in dielectrics(st):
            self.assertAlmostEqual(d["thickness"], 0.48, places=6)
            self.assertEqual(d["epsilon_r"], 4.5)
        self.assertTrue(all(l["thickness"] == 0.035 for l in st if l["type"] == "copper"))

    def test_mask_layers_count(self):
        d = dielectrics(pipeline._infer_stackup(FOUR, 1.6, mask_layers=0))
        self.assertAlmostEqual(d[0]["thickness"], 0.4867, places=4)
        d = dielectrics(pipeline._infer_stackup(["F.Cu", "B.Cu"], 1.6))
        self.assertAlmostEqual(d[0]["thickness"], 1.51, places=6)

    def test_copper_in_kicad_stack_order(self):
        st = pipeline._infer_stackup(["B.Cu", "In2.Cu", "F.Cu", "In1.Cu"], None)
        self.assertEqual([l["name"] for l in st if l["type"] == "copper"], FOUR)
        self.assertAlmostEqual(dielectrics(st)[0]["thickness"], 0.48, places=6)

    def test_reference_map_and_source(self):
        with BoardFile(board_text()) as path:
            board = pipeline.read_board(path)
            facts = pipeline.run_facts(board, include_trace_segments=False,
                                       return_path_radius_mm=0.5, gp001_debug=False,
                                       resolved_power_rails=None)
        self.assertEqual(facts.ref_layer_map, {"F.Cu": "In1.Cu", "In1.Cu": "F.Cu",
                                               "In2.Cu": "In1.Cu", "B.Cu": "In2.Cu"})
        self.assertEqual(board.setup.get("stackup_source"), "inferred")
        self.assertNotIn("stackup", board.setup)

    def test_inner_layer_gets_impedance_on_inferred_height(self):
        with BoardFile(board_text()) as path:
            out = pipeline.analyze_pcb(path, include_trace_segments=True)
        segs = {s["layer"]: s for nl in out["net_lengths"] for s in nl.get("trace_segments", [])}
        self.assertIn("impedance_ohm", segs["In1.Cu"])


class DesignerStackupUntouched(unittest.TestCase):
    STACK = ('(stackup (layer "F.Cu" (type "copper") (thickness 0.035))'
             ' (layer "dielectric 1" (type "core") (thickness 0.2) (epsilon_r 4.2))'
             ' (layer "In1.Cu" (type "copper") (thickness 0.035))'
             ' (layer "dielectric 2" (type "prepreg") (thickness 1.0) (epsilon_r 4.5))'
             ' (layer "In2.Cu" (type "copper") (thickness 0.035))'
             ' (layer "dielectric 3" (type "core") (thickness 0.2) (epsilon_r 4.2))'
             ' (layer "B.Cu" (type "copper") (thickness 0.035)))')

    def test_file_stackup_wins_and_is_not_marked(self):
        with BoardFile(board_text(stackup=self.STACK)) as path:
            board = pipeline.read_board(path)
            facts = pipeline.run_facts(board, include_trace_segments=False,
                                       return_path_radius_mm=0.5, gp001_debug=False,
                                       resolved_power_rails=None)
        self.assertNotIn("stackup_source", board.setup)
        self.assertEqual(facts.ref_layer_map["In2.Cu"], "B.Cu")


class EmcJudgesOnlyADesignerStackup(unittest.TestCase):
    def test_no_stackup_finding_on_inferred(self):
        from analyze_emc import extract_board_info
        from emc_rules import check_stackup
        with BoardFile(board_text()) as path:
            out = pipeline.analyze_pcb(path)
        self.assertEqual(out["setup"].get("stackup_source"), "inferred")
        self.assertEqual(check_stackup(out), [])
        self.assertFalse(extract_board_info(pcb=out)["has_stackup"])


class Sublayers(unittest.TestCase):
    def setup_of(self, layer):
        return extract_setup(parse(f'(kicad_pcb (general (thickness 1.6)) (setup (stackup {layer})))'))

    def test_sublayers_sum_and_weight(self):
        st = self.setup_of('(layer "dielectric 1" (type "core") (thickness 0.069) (epsilon_r 4.4)'
                           ' addsublayer (thickness 0.069) (epsilon_r 4.6))')["stackup"][0]
        self.assertAlmostEqual(st["thickness"], 0.138, places=9)
        self.assertAlmostEqual(st["epsilon_r"], 4.5, places=9)
        self.assertEqual(st["type"], "core")

    def test_unequal_sublayers_weight_by_thickness(self):
        st = self.setup_of('(layer "dielectric 1" (type "prepreg") (thickness 0.1) (epsilon_r 4.0)'
                           ' addsublayer (thickness 0.3) (epsilon_r 5.0))')["stackup"][0]
        self.assertAlmostEqual(st["thickness"], 0.4, places=9)
        self.assertAlmostEqual(st["epsilon_r"], (0.1 * 4.0 + 0.3 * 5.0) / 0.4, places=9)

    def test_single_layer_unchanged(self):
        st = self.setup_of('(layer "dielectric 1" (type "core") (thickness 0.2) (epsilon_r 4.4)'
                           ' (loss_tangent 0.02))')["stackup"][0]
        self.assertEqual(st, {"name": "dielectric 1", "type": "core", "thickness": 0.2,
                              "epsilon_r": 4.4, "loss_tangent": 0.02})


if __name__ == "__main__":
    unittest.main()
