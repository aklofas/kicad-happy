# tools/tests/test_pcb_footprint_attrs.py
"""Footprint attributes and pad markers as KiCad 10 loads a board.

Attributes (PCB_IO_KICAD_SEXPR_PARSER::parseFOOTPRINT_unchecked, `attr`): `smd` and
`through_hole` set the technology, `virtual` (legacy) sets exclude-from-pos and
exclude-from-bom only, `board_only` sets board-only only. A file older than 20200826 whose
footprint sets no attribute is through-hole; otherwise a footprint with no technology token has
none ("unspecified"). A board without (version) reads as 20201115.

Pad markers (`property`): pad_prop_fiducial_glob / pad_prop_fiducial_loc / pad_prop_testpoint.
FD-001 counts global fiducials only (IPC-7351 keeps local fiducials apart from the three
board-level ones); TE-001 counts a test-point pad like a TP footprint."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.sexp import parse  # noqa: E402
from pcb.assembly import analyze_fiducials, analyze_test_point_coverage  # noqa: E402
from pcb.reader import extract_footprints  # noqa: E402

SMD_PAD = '(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask"){extra})'
THT_PAD = '(pad "1" thru_hole circle (at 0 0) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))'


def modern_fp(ref, attr="", pads=SMD_PAD.format(extra=""), x=10, value="X"):
    return (f'(footprint "Lib:FP" (layer "F.Cu") (at {x} 10)'
            f' (property "Reference" "{ref}") (property "Value" "{value}") {attr} {pads})')


def legacy_module(ref, attr="", pads=SMD_PAD.format(extra="")):
    return (f'(module Lib:FP (layer F.Cu) (at 10 10) (fp_text reference {ref} (at 0 0)'
            f' (layer F.SilkS)) (fp_text value X (at 0 1) (layer F.Fab)) {attr} {pads})')


def board(footprints, version="(version 20240108)"):
    return parse(f'(kicad_pcb {version} (generator "pcbnew") (net 0 "") (net 1 "SIG")'
                 f' {" ".join(footprints)})')


def one_fp(text, version="(version 20240108)"):
    return extract_footprints(board([text], version))[0]


FLAGS = ("board_only", "exclude_from_bom", "exclude_from_pos")


class FootprintAttrs(unittest.TestCase):
    def flags(self, fp):
        return {k: fp[k] for k in FLAGS if k in fp}

    def test_board_only_sets_only_board_only(self):
        fp = one_fp(modern_fp("R1", "(attr smd board_only)"))
        self.assertEqual(fp["type"], "smd")
        self.assertEqual(self.flags(fp), {"board_only": True})

    def test_legacy_virtual_excludes_but_is_not_board_only(self):
        fp = one_fp(legacy_module("G1", "(attr virtual)"), "(version 20171130)")
        self.assertEqual(fp["type"], "unspecified")
        self.assertEqual(self.flags(fp), {"exclude_from_bom": True, "exclude_from_pos": True})

    def test_legacy_no_attr_is_through_hole_even_with_smd_pads(self):
        fp = one_fp(legacy_module("U1"), "(version 20171130)")
        self.assertEqual(fp["type"], "through_hole")
        self.assertEqual(self.flags(fp), {})

    def test_modern_flags_without_technology_are_unspecified(self):
        fp = one_fp(modern_fp("H1", "(attr exclude_from_pos_files exclude_from_bom)",
                              pads=THT_PAD))
        self.assertEqual(fp["type"], "unspecified")
        self.assertEqual(self.flags(fp), {"exclude_from_bom": True, "exclude_from_pos": True})

    def test_modern_no_attr_is_unspecified(self):
        self.assertEqual(one_fp(modern_fp("H1", pads=THT_PAD))["type"], "unspecified")
        # no (version) reads as 20201115, after the legacy cut-off
        self.assertEqual(one_fp(modern_fp("H1", pads=THT_PAD), "")["type"], "unspecified")

    def test_technology_token_wins(self):
        self.assertEqual(one_fp(modern_fp("J1", "(attr through_hole)", THT_PAD))["type"],
                         "through_hole")
        self.assertEqual(one_fp(legacy_module("R1", "(attr smd)"), "(version 20171130)")["type"],
                         "smd")


def fid_fp(ref, prop, x):
    return modern_fp(ref, "(attr smd)", SMD_PAD.format(extra=f" (property {prop})"), x=x)


class PadMarkers(unittest.TestCase):
    def test_global_fiducial_pads_satisfy_fd001(self):
        fps = extract_footprints(board([fid_fp("REF**", "pad_prop_fiducial_glob", x)
                                        for x in (5, 15, 25)]))
        self.assertEqual(analyze_fiducials(fps)["findings"], [])

    def test_local_fiducial_pads_do_not_satisfy_fd001(self):
        fps = extract_footprints(board([fid_fp("REF**", "pad_prop_fiducial_loc", x)
                                        for x in (5, 15, 25)]))
        findings = analyze_fiducials(fps)["findings"]
        self.assertEqual([(f["rule_id"], f["side"], f["fiducial_count"]) for f in findings],
                         [("FD-001", "F.Cu", 0)])

    def test_testpoint_pad_counts_for_te001(self):
        pad = SMD_PAD.format(extra=' (net 1 "SIG") (property pad_prop_testpoint)')
        fps = extract_footprints(board([modern_fp("J9", "(attr smd)", pad)]))
        cov = analyze_test_point_coverage(fps, {0: "", 1: "SIG"})
        self.assertEqual((cov["nets_with_test_points"], cov["total_signal_nets"],
                          cov["test_point_count"]), (1, 1, 1))

    def test_only_the_testpoint_pad_of_a_part_counts(self):
        # a module with one test-point pad does not put a probe on its other pins
        pads = (SMD_PAD.format(extra=' (net 1 "SIG") (property pad_prop_testpoint)')
                + SMD_PAD.replace('"1"', '"2"').format(extra=' (net 2 "OTHER")'))
        fps = extract_footprints(board([modern_fp("U3", "(attr smd)", pads)]))
        cov = analyze_test_point_coverage(fps, {0: "", 1: "SIG", 2: "OTHER"})
        self.assertEqual((cov["nets_with_test_points"], cov["total_signal_nets"]), (1, 2))


if __name__ == "__main__":
    unittest.main()
