# tools/tests/test_pcb_layer_identity.py
"""KiCad maps a board's copper layers by their position in the (layers ...) table
(first = F.Cu, last = B.Cu, inner = In<i>.Cu unless already canonical), so a KiCad 5
board whose copper layers were renamed (Top/Bottom, ...) reads exactly like the same
board saved with canonical names. CP-001 judges a pad against the zones on the pad's
own copper side."""
import os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.sexp import parse_file  # noqa: E402
from pcb.pipeline import analyze_pcb, read_board  # noqa: E402
import pcb.reader as reader  # noqa: E402

RENAMED_2L = """(kicad_pcb (version 20171130) (host pcbnew 5.1.12)
  (layers (0 Top signal) (31 Bottom signal) (34 B.Paste user hide))
  (net 0 "") (net 1 N)
  (module R (layer Top) (at 0 0)
    (pad 1 smd rect (at 0 0) (size 1 1) (layers Top F.Paste F.Mask) (net 1 N))
    (pad 2 smd rect (at 2 0) (size 1 1) (layers Top) (net 1 N)))
  (segment (start 0 0) (end 2 0) (width 0.25) (layer Top) (net 1)))
"""

RENAMED_4L = """(kicad_pcb (version 20171130) (host pcbnew 5.1.12)
  (layers (0 Top signal) (1 GND power hide) (2 PWR power) (31 Bottom signal)
          (36 B.SilkS user) (44 Edge.Cuts user))
  (net 0 "") (net 1 N)
  (segment (start 0 0) (end 2 0) (width 0.25) (layer GND) (net 1))
  (segment (start 0 1) (end 2 1) (width 0.25) (layer PWR) (net 1))
  (via (at 2 0) (size 0.6) (drill 0.3) (layers Top Bottom) (net 1)))
"""


def _square(x0, y0, x1, y1):
    return f"(pts (xy {x0} {y0}) (xy {x1} {y0}) (xy {x1} {y1}) (xy {x0} {y1}))"


def _zone(net, name, layer, box):
    return (f'(zone (net {net}) (net_name "{name}") (layer "{layer}") (hatch edge 0.5)'
            f' (connect_pads (clearance 0.2)) (min_thickness 0.2)'
            f' (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))'
            f' (polygon {_square(*box)})'
            f' (filled_polygon (layer "{layer}") {_square(*box)}))')


def _cp_board(zones):
    """A footprint on F.Cu whose only pad is an SMD pad on B.Cu (a hot-swap socket shape)."""
    return f"""(kicad_pcb (version 20221018) (generator pcbnew)
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
  (net 0 "") (net 1 "SIG") (net 2 "GND") (net 3 "OTHER")
  (footprint "SW" (layer "F.Cu") (at 10 10)
    (property "Reference" "SW1")
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "B.Cu" "B.Paste" "B.Mask") (net 1 "SIG")))
  {' '.join(zones)})
"""


def _write(tmp, text):
    p = os.path.join(tmp, "b.kicad_pcb")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


class TestCanonicalizeCopperLayers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_two_layer_mapping_and_hide_is_not_an_alias(self):
        root = parse_file(_write(self.tmp.name, RENAMED_2L))
        self.assertEqual(reader.canonicalize_copper_layers(root), {"Top": "F.Cu", "Bottom": "B.Cu"})
        self.assertEqual(
            [(l["name"], l["alias"]) for l in reader.extract_layers(root)],
            [("F.Cu", "Top"), ("B.Cu", "Bottom"), ("B.Paste", None)])

    def test_quoted_hide_is_a_user_name(self):
        root = parse_file(_write(self.tmp.name, RENAMED_2L.replace("user hide", 'user "hide"')))
        self.assertEqual(reader.extract_layers(root)[-1]["alias"], "hide")

    def test_four_layer_inner_by_position(self):
        root = parse_file(_write(self.tmp.name, RENAMED_4L))
        self.assertEqual(reader.canonicalize_copper_layers(root),
                         {"Top": "F.Cu", "GND": "In1.Cu", "PWR": "In2.Cu", "Bottom": "B.Cu"})
        self.assertEqual([(l["name"], l["alias"]) for l in reader.extract_layers(root)][:4],
                         [("F.Cu", "Top"), ("In1.Cu", "GND"), ("In2.Cu", "PWR"), ("B.Cu", "Bottom")])
        bd = read_board(_write(self.tmp.name, RENAMED_4L))
        self.assertEqual([s["layer"] for s in bd.tracks["segments"]], ["In1.Cu", "In2.Cu"])
        self.assertEqual(bd.vias["vias"][0]["layers"], ["F.Cu", "B.Cu"])

    def test_canonical_board_unchanged(self):
        text = RENAMED_2L.replace("Top", "F.Cu").replace("Bottom", "B.Cu")
        root = parse_file(_write(self.tmp.name, text))
        self.assertEqual(reader.canonicalize_copper_layers(root), {})

    def test_renamed_board_reads_like_its_canonical_twin(self):
        path = _write(self.tmp.name, RENAMED_2L)
        bd = read_board(path)
        fp = bd.footprints[0]
        self.assertEqual(fp["layer"], "F.Cu")
        self.assertEqual(bd.tracks["segments"][0]["layer"], "F.Cu")
        res = analyze_pcb(path, include_trace_segments=True)
        self.assertEqual(res["statistics"]["front_side"], 1)
        self.assertEqual(res["statistics"]["back_side"], 0)
        net = res["connectivity_graph"]["N"]
        self.assertEqual(net["islands"], 1)
        self.assertEqual(sorted(net["components"].values()), [0, 0])  # both pads, one island


class TestCp001PadSide(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _cp001(self, zones):
        res = analyze_pcb(_write(self.tmp.name, _cp_board(zones)))
        return [f for f in res["findings"] if f.get("rule_id") == "CP-001"]

    def test_front_fill_does_not_reach_a_back_pad(self):
        self.assertEqual(self._cp001([_zone(2, "GND", "F.Cu", (8, 8, 12, 12))]), [])

    def test_back_fill_is_checked_against_a_back_pad(self):
        found = self._cp001([_zone(3, "OTHER", "B.Cu", (8, 8, 12, 12))])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["nets"], ["OTHER"])
        self.assertEqual(found[0]["pins"], ["1"])


if __name__ == "__main__":
    unittest.main()
