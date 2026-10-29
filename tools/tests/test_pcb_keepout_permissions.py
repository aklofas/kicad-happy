# tools/tests/test_pcb_keepout_permissions.py
"""KO-001 reports only what a rule area prohibits; `allowed` is permission."""
import os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pcb.pipeline import read_board  # noqa: E402
from pcb.reader import _extract_keepout_zones  # noqa: E402
from pcb.assembly import analyze_keepout_violations  # noqa: E402


CRTYD = ' (fp_rect (start -1 -1) (end 1 1) (layer "F.CrtYd") (stroke (width 0.05) (type solid)))'


def _ko001(footprints, vias, crtyd=""):
    board = f'''(kicad_pcb (version 20221018) (generator pcbnew)
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
  (net 0 "")
  (via (at 110 110) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 0))
  (footprint "L:F" (layer "F.Cu") (at 105 105)
    (property "Reference" "R1") (property "Value" "v")
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask")){crtyd})
  (zone (net 0) (net_name "") (layers "F.Cu" "B.Cu") (name "ko") (hatch edge 0.5)
    (keepout (tracks allowed) (vias {vias}) (pads allowed) (copperpour allowed) (footprints {footprints}))
    (polygon (pts (xy 100 100) (xy 120 100) (xy 120 120) (xy 100 120))))
)
'''
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "b.kicad_pcb")
        with open(p, "w", encoding="utf-8") as f:
            f.write(board)
        st = read_board(p)
        return analyze_keepout_violations(st.footprints, st.vias, _extract_keepout_zones(st.zones, st.footprints))


class TestKeepoutPermissions(unittest.TestCase):
    def test_footprints_allowed_is_silent(self):
        self.assertEqual(_ko001("allowed", "allowed"), [])

    def test_footprints_not_allowed_reports_footprint(self):
        # KiCad tests a footprint against a keepout by its courtyard (pcbexpr_functions.cpp);
        # kicad-cli 10.0.7: items_not_allowed "Footprint R1"
        f = _ko001("not_allowed", "allowed", CRTYD)
        self.assertEqual([x.get("component") for x in f], ["R1"])

    def test_footprint_prohibited_via_allowed_reports_only_the_footprint(self):
        # kicad-cli 10.0.7: one items_not_allowed, "Footprint R1", no via item
        f = _ko001("not_allowed", "allowed", CRTYD)
        self.assertEqual([(x.get("component"), "via_x" in x) for x in f], [("R1", False)])

    def test_via_prohibited_footprint_allowed(self):
        f = _ko001("allowed", "not_allowed")
        self.assertEqual(len(f), 1)
        self.assertIn("via_x", f[0])
        self.assertNotIn("component", f[0])


if __name__ == "__main__":
    unittest.main()
