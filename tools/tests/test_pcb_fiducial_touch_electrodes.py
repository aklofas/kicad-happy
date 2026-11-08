"""FD-001 counts the SMD parts a pick-and-place machine places. A capacitive touch electrode
footprint is copper, not a placed part; a connector valued "Resistive_Touch" is still placed."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.sexp import parse  # noqa: E402
from pcb.assembly import analyze_fiducials  # noqa: E402
from pcb.reader import extract_footprints  # noqa: E402


def part(ref, lib, value, x):
    return (f'(footprint "{lib}" (layer "F.Cu") (at {x} 10)\n'
            f' (property "Reference" "{ref}" (at 0 3 0) (layer "F.SilkS"))\n'
            f' (property "Value" "{value}" (at 0 -3 0) (layer "F.Fab"))\n'
            ' (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask")))\n')


def fd001(items):
    root = parse('(kicad_pcb (version 20221018) (generator pcbnew)\n'
                 ' (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n' + items + ')\n')
    return analyze_fiducials(extract_footprints(root))["findings"]


class TouchElectrodes(unittest.TestCase):
    def test_touch_electrode_alone_raises_no_fiducial_finding(self):
        self.assertEqual(fd001(part("E1", "Touch:Capacitive_Touch_Pad_10mm", "PAD", 10)), [])

    def test_touch_electrodes_are_not_counted_beside_parts(self):
        items = (part("E1", "Touch:TouchButton_8mm", "BTN", 10)
                 + part("E2", "Touch:TouchButton_8mm", "BTN", 20)
                 + part("R1", "Resistor_SMD:R_0603_1608Metric", "10k", 30))
        (f,) = fd001(items)
        self.assertEqual(f["smd_component_count"], 1)

    def test_connector_valued_touch_is_still_a_placed_part(self):
        (f,) = fd001(part("J1", "Connector_FFC-FPC:Hirose_FH12-4S-0.5SH", "Resistive_Touch", 10))
        self.assertEqual(f["smd_component_count"], 1)


if __name__ == "__main__":
    unittest.main()
