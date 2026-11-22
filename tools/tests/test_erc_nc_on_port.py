"""A no-connect marker on a hierarchical label or a sheet pin marks the port unused."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT))

from tools.tests.test_erc_pins import _one_pin_lib  # noqa: E402
from tools.tests.test_same_sheet_power_names import Sheet, run, sheet_block  # noqa: E402

LIBS = [_one_pin_lib("I", "input")]
NC = '(no_connect (at {x} 50) (uuid "00000000-0000-0000-0000-00000000fffe"))'


def _two_pins():
    s = Sheet(20250114)
    s.symbol("t:I", "U1", "I", 50, 50, ("1",))
    s.symbol("t:I", "U3", "I", 70, 50, ("1",))
    s.wire(50, 50, 60, 50); s.wire(60, 50, 70, 50)
    return s


def _recs(r):
    return [w for w in r["design_analysis"]["erc_warnings"] if w["type"] == "no_connect_connected"]


class NcOnPortTest(unittest.TestCase):
    def test_marker_on_hierarchical_label_raises_nothing(self):
        s = _two_pins()
        s.label("hierarchical_label", "SIG", 60, 50)
        s.items.append(NC.format(x=60))
        r = run({"t.kicad_sch": s.text(LIBS)})
        self.assertEqual(_recs(r), [])
        self.assertTrue(all("_nc_on_port" not in n for n in r["nets"].values()))
        self.assertEqual([w for w in r["design_analysis"]["erc_warnings"]
                          if w["type"] == "pin_not_driven"], [])

    def test_marker_on_a_part_pin_of_the_same_net_still_raises(self):
        s = _two_pins()
        s.label("hierarchical_label", "SIG", 60, 50)
        s.items.append(NC.format(x=70))
        self.assertEqual(len(_recs(run({"t.kicad_sch": s.text(LIBS)}))), 1)

    def test_marker_on_a_plain_wire_point_still_raises(self):
        s = _two_pins()
        s.items.append(NC.format(x=60))
        self.assertEqual(len(_recs(run({"t.kicad_sch": s.text(LIBS)}))), 1)

    def test_marker_on_a_sheet_pin_raises_nothing(self):
        s = _two_pins()
        s.items.append(sheet_block("Sub", "sub.kicad_sch", 70, 40, [("SIG", 60, 50)]))
        s.items.append(NC.format(x=60))
        self.assertEqual(_recs(run({"t.kicad_sch": s.text(LIBS)})), [])


if __name__ == "__main__":
    unittest.main()
