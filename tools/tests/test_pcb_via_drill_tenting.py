# tools/tests/test_pcb_via_drill_tenting.py
"""Via drill and tenting as KiCad 10 loads a board.

Drill: a via saved without (drill) takes its net class's via drill (micro vias the micro-via
drill) -- PCB_VIA::GetDrillValue. Setup (via_drill)/(uvia_drill) set the Default class; a
(net_class Default ...) replaces it; a file with no (net_class) at all keeps none of it
(BOARD::SetProject takes the project's classes); a class value the file does not give is
KiCad 10's NETCLASS default 0.3 / 0.1 mm.

Tenting: a via without its own setting inherits the board default (PCB_VIA::IsTented). The
board default is tented both sides; setup (tenting ...) sets both sides (an unnamed side is
untented); a KiCad <= 8 pcbplotparams (viasonmask X) sets both to not X; later entries win. A
flat via (tenting none) clears both sides back to "inherit" (parseFrontBackOptBool), nested
(front yes|no|none) sets one side.

Every expected value was checked against kicad-cli 10.0.6 on the same board text: the drill
in `pcb export drill` and the via flash in the F/B mask layers of `pcb export gerbers`."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.sexp import parse  # noqa: E402
from pcb.copper import analyze_thermal_pad_vias, analyze_via_in_pad  # noqa: E402
from pcb.reader import extract_footprints, extract_vias, extract_zones  # noqa: E402


def board_text(setup="", classes="", vias="", version=20171130):
    host = '(host pcbnew 5.1.9)' if version < 20220000 else '(generator pcbnew)'
    return (
        f'(kicad_pcb (version {version}) {host}\n'
        ' (general (thickness 1.6))\n'
        ' (layers (0 F.Cu signal) (31 B.Cu signal) (32 B.Adhes user) (33 F.Adhes user)\n'
        '  (34 B.Paste user) (35 F.Paste user) (36 B.SilkS user) (37 F.SilkS user)\n'
        '  (38 B.Mask user) (39 F.Mask user) (44 Edge.Cuts user))\n'
        f' (setup {setup})\n'
        ' (net 0 "") (net 1 GND) (net 2 VCC) (net 3 SIG)\n'
        f' {classes}\n'
        ' (gr_line (start 0 0) (end 30 0) (layer Edge.Cuts) (width 0.1))\n'
        ' (gr_line (start 30 0) (end 30 30) (layer Edge.Cuts) (width 0.1))\n'
        ' (gr_line (start 30 30) (end 0 30) (layer Edge.Cuts) (width 0.1))\n'
        ' (gr_line (start 0 30) (end 0 0) (layer Edge.Cuts) (width 0.1))\n'
        f' {vias})\n')


def _via(x, net, extra="", kind=""):
    return f'(via {kind} (at {x} 10) (size 0.8) {extra} (layers F.Cu B.Cu) (net {net}))'


DRILL_CLASSES = (
    '(net_class Default "" (clearance 0.2) (via_dia 0.8) (via_drill 0.381) (add_net GND)'
    ' (add_net SIG))'
    ' (net_class Power "" (clearance 0.2) (via_dia 1.0) (via_drill 0.5) (uvia_drill 0.15)'
    ' (add_net VCC))')
DRILL_SETUP = '(via_drill 0.4) (uvia_drill 0.127)'


def _drills(setup, classes, vias):
    return [v["drill"] for v in extract_vias(parse(board_text(setup, classes, vias)))["vias"]]


class LegacyViaDrill(unittest.TestCase):
    def test_via_without_drill_takes_its_net_class_drill(self):
        vias = _via(5, 2) + _via(10, 1) + _via(15, 3) + _via(20, 0)
        self.assertEqual(_drills(DRILL_SETUP, DRILL_CLASSES, vias), [0.5, 0.381, 0.381, 0.381])

    def test_explicit_drill_is_kept(self):
        self.assertEqual(_drills(DRILL_SETUP, DRILL_CLASSES, _via(5, 2, "(drill 0.3)")), [0.3])

    def test_setup_drill_sets_the_default_class_when_the_file_has_net_classes(self):
        classes = '(net_class Power "" (via_drill 0.5) (add_net VCC))'
        vias = _via(5, 2) + _via(10, 1) + _via(15, 1, kind="micro")
        self.assertEqual(_drills(DRILL_SETUP, classes, vias), [0.5, 0.4, 0.127])

    def test_setup_drill_alone_is_dropped(self):
        # With no (net_class) in the file KiCad 10 takes the project's net classes.
        self.assertEqual(_drills(DRILL_SETUP, "", _via(5, 2) + _via(10, 1, kind="micro")),
                         [0.3, 0.1])

    def test_micro_via_takes_the_class_micro_drill(self):
        # The Default net class replaces the setup values; it gives no uvia_drill -> 0.1.
        vias = _via(5, 2, kind="micro") + _via(10, 1, kind="micro")
        self.assertEqual(_drills(DRILL_SETUP, DRILL_CLASSES, vias), [0.15, 0.1])

    def test_kicad10_defaults_without_setup_or_classes(self):
        self.assertEqual(_drills("", "", _via(5, 1) + _via(10, 1, kind="micro")), [0.3, 0.1])

    def test_size_distribution_uses_the_resolved_drill(self):
        out = extract_vias(parse(board_text(DRILL_SETUP, DRILL_CLASSES, _via(5, 2))))
        self.assertEqual(out["size_distribution"], {"0.8/0.5": 1})


def _tenting(setup, vias, version=20171130):
    out = extract_vias(parse(board_text(setup, "", vias, version)))
    return [v.get("tenting", []) for v in out["vias"]]


BOTH = ["front", "back"]
V9 = 20241229
V10 = 20250926


class ViaTenting(unittest.TestCase):
    def test_no_board_setting_is_tented(self):
        self.assertEqual(_tenting("", _via(5, 1, "(drill 0.4)")), [BOTH])

    def test_viasonmask_false_is_tented(self):
        setup = '(pcbplotparams (viasonmask false))'
        self.assertEqual(_tenting(setup, _via(5, 1, "(drill 0.4)")), [BOTH])

    def test_viasonmask_true_is_untented(self):
        setup = '(pcbplotparams (viasonmask true))'
        self.assertEqual(_tenting(setup, _via(5, 1, "(drill 0.4)")), [[]])

    def test_later_setup_entry_wins(self):
        setup = '(tenting none) (pcbplotparams (viasonmask false))'
        self.assertEqual(_tenting(setup, _via(5, 1, "(drill 0.4)"), V9), [BOTH])

    def test_board_flat_one_side(self):
        setup = '(tenting front)'
        self.assertEqual(_tenting(setup, _via(5, 1, "(drill 0.4)"), V9), [["front"]])

    def test_kicad9_via_tenting_none_inherits_the_board(self):
        # KiCad 9 wrote (tenting none) for "not tented"; KiCad 10 reads it as "board default".
        setup = '(tenting front back)'
        vias = _via(5, 1, "(drill 0.4) (tenting none)")
        self.assertEqual(_tenting(setup, vias, V9), [BOTH])

    def test_via_flat_side_over_untented_board(self):
        setup = '(tenting none)'
        vias = _via(5, 1, "(drill 0.4) (tenting back)") + _via(10, 1, "(drill 0.4)")
        self.assertEqual(_tenting(setup, vias, V9), [["back"], []])

    def test_kicad10_nested_via_tenting(self):
        setup = '(tenting (front yes) (back yes))'
        vias = (_via(5, 1, "(drill 0.4) (tenting (front no) (back none))")
                + _via(10, 1, "(drill 0.4) (tenting (front yes) (back no))"))
        self.assertEqual(_tenting(setup, vias, V10), [["back"], ["front"]])


def _fp(ref, x, pad_layers, ep_layers=None, side="F"):
    """Four 0.3 x 0.8 signal pads and a 3 x 3 pad 5 (an exposed pad when ep_layers is given)."""
    pads = "".join(
        f' (pad {n} smd rect (at {dx} -2.5) (size 0.3 0.8) (layers {pad_layers}) (net 3 SIG))'
        for n, dx in ((1, -0.75), (2, -0.25), (3, 0.25), (4, 0.75)))
    big = ep_layers if ep_layers is not None else pad_layers
    pads += f' (pad 5 smd rect (at 0 0) (size 3 3) (layers {big}) (net 1 GND))'
    return f'(module Test:QFN (layer {side}.Cu) (at {x} 10) (fp_text reference {ref} (at 0 4) (layer {side}.SilkS)){pads})'


def _vp001(setup, fp, vias):
    root = parse(board_text(setup, "", fp + vias))
    return analyze_via_in_pad(extract_footprints(root), extract_vias(root), set())


def _tv001(setup, fp, vias):
    root = parse(board_text(setup, "", fp + vias))
    zones, fills = extract_zones(root)
    return analyze_thermal_pad_vias(extract_footprints(root), extract_vias(root), zones, fills)


SMD = "F.Cu F.Paste F.Mask"
NO_MASK = "F.Cu F.Paste"


def _gnd_via(x, y=10, extra=""):
    return f'(via (at {x} {y}) (size 0.6) (drill 0.3) {extra} (layers F.Cu B.Cu) (net 1))'


class ViaInPadExposure(unittest.TestCase):
    """KiCad plots a pad's mask opening whatever the tenting of a via inside it; the tented via
    only loses its own flash (plot_board_layers.cpp, PCB_VIA::GetLayerSet)."""

    def test_tented_via_in_a_pad_mask_opening_is_exposed(self):
        f = _vp001("", _fp("U1", 15, SMD), _gnd_via(15.5))
        self.assertEqual(len(f), 1)
        self.assertTrue(f[0]["tented"])
        self.assertEqual(f[0]["severity"], "warning")
        self.assertIn("exposed by the pad's mask opening", f[0]["summary"])

    def test_tented_via_in_a_pad_without_mask_is_covered(self):
        f = _vp001("", _fp("U1", 15, NO_MASK), _gnd_via(15.5))
        self.assertEqual((f[0]["tented"], f[0]["severity"]), (True, "info"))

    def test_untented_via_in_a_pad_without_mask_is_exposed(self):
        f = _vp001("(pcbplotparams (viasonmask true))", _fp("U1", 15, NO_MASK), _gnd_via(15.5))
        self.assertEqual((f[0]["tented"], f[0]["severity"]), (False, "warning"))

    def test_back_pad_opening_exposes_a_through_via(self):
        f = _vp001("", _fp("U1", 15, "B.Cu B.Paste B.Mask", side="B"), _gnd_via(15.5))
        self.assertEqual(f[0]["severity"], "warning")

    def test_mask_opening_on_the_other_side_exposes_a_through_via(self):
        # KiCad opens B.Mask at an F.Cu pad that lists B.Mask; the through via shows there.
        f = _vp001("", _fp("U1", 15, "F.Cu B.Mask"), _gnd_via(15.5))
        self.assertEqual(f[0]["severity"], "warning")

    def test_blind_via_not_reaching_the_opening_side_is_covered(self):
        via = '(via blind (at 15.5 10) (size 0.6) (drill 0.3) (layers F.Cu In1.Cu) (net 1))'
        f = _vp001("", _fp("U1", 15, "F.Cu B.Mask"), via)
        self.assertEqual(f[0]["severity"], "info")


class ThermalPadViaExposure(unittest.TestCase):
    def test_tented_via_inside_the_thermal_pad_is_exposed(self):
        tv = _tv001("", _fp("U1", 15, SMD), _gnd_via(15.5))
        self.assertEqual(len(tv), 1)
        self.assertIn("tenting_note", tv[0])
        self.assertTrue(tv[0]["tenting_note"].startswith("1 via(s)"))

    def test_tented_via_in_the_margin_is_covered(self):
        # 1.8 mm from the centre: outside the 1.5 mm half-width, inside the 1.5x margin.
        tv = _tv001("", _fp("U1", 15, SMD), _gnd_via(16.8))
        self.assertEqual(tv[0]["via_count"], 1)
        self.assertNotIn("tenting_note", tv[0])

    def test_untented_via_in_the_margin_is_exposed(self):
        tv = _tv001("(pcbplotparams (viasonmask true))", _fp("U1", 15, SMD), _gnd_via(16.8))
        self.assertIn("tenting_note", tv[0])

    def test_via_inside_a_thermal_pad_without_mask_follows_tenting(self):
        tv = _tv001("", _fp("U1", 15, SMD, ep_layers=NO_MASK), _gnd_via(15.5))
        self.assertNotIn("tenting_note", tv[0])


if __name__ == "__main__":
    unittest.main()
