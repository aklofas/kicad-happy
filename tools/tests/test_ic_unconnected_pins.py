"""Pinout rows count and list a pin that is wired to nothing, as KiCad's netlist does."""
import sys
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT))

from schematic.pipeline import analyze_schematic  # noqa: E402
from tools.tests._fixtures import fixture  # noqa: E402
from tools.tests.test_erc_pins import _one_pin_lib  # noqa: E402
from tools.tests.test_same_sheet_power_names import R_LIB, Sheet, run  # noqa: E402

NC = '(no_connect (at {x} {y}) (uuid "00000000-0000-0000-0000-00000000fffe"))'
FLAG_LIB = ('(symbol "power:PWR_FLAG" (power) (in_bom yes) (on_board yes)'
            ' (property "Reference" "#FLG" (at 0 0 0)) (property "Value" "PWR_FLAG" (at 0 0 0))'
            ' (symbol "PWR_FLAG_1_1" (pin power_out line (at 0 0 90) (length 0)'
            ' (name "pwr") (number "1"))))')


def _analyze(path):
    with redirect_stderr(StringIO()):
        return analyze_schematic(str(path))


def _listed(row):
    return [p["pin_number"] for p in row.get("unconnected_pin_list", [])]


class UnconnectedPinsTest(unittest.TestCase):
    def test_pin_alone_on_an_unnamed_net_is_listed(self):
        s = Sheet(20250114)
        s.symbol("t:P", "U1", "P", 50, 50, ("1",))
        row = run({"t.kicad_sch": s.text([_one_pin_lib("P", "passive")])})["ic_pin_analysis"][0]
        self.assertEqual(row["unconnected_pins"], 1)
        self.assertEqual(_listed(row), ["1"])
        self.assertTrue(row["pins"][0]["net"].startswith("__unnamed_"))

    def test_fixture_lone_connector_pin_is_listed(self):
        r = _analyze(fixture("simple-project", "simple.kicad_sch"))
        row = [x for x in r["ic_pin_analysis"] if x["reference"] == "J1"][0]
        self.assertEqual(row["unconnected_pins"], 1)
        self.assertEqual(_listed(row), ["2"])

    def test_transistor_pin_alone_is_listed(self):
        s = Sheet(20250114)
        s.symbol("t:P", "Q1", "P", 50, 50, ("1",))
        r = run({"t.kicad_sch": s.text([_one_pin_lib("P", "passive")])})
        self.assertEqual(r["transistor_pin_analysis"][0]["unconnected_pins"], 1)

    def test_wired_pin_is_not_listed(self):
        s = Sheet(20250114)
        s.symbol("t:P", "U1", "P", 50, 50, ("1",))
        s.r("R1", 50, 50)
        row = run({"t.kicad_sch": s.text([_one_pin_lib("P", "passive"), R_LIB])})["ic_pin_analysis"][0]
        self.assertEqual(row["unconnected_pins"], 0)
        self.assertNotIn("unconnected_pin_list", row)

    def test_no_connect_marker_is_not_unconnected(self):
        s = Sheet(20250114)
        s.symbol("t:P", "U1", "P", 50, 50, ("1",))
        s.items.append(NC.format(x=50, y=50))
        row = run({"t.kicad_sch": s.text([_one_pin_lib("P", "passive")])})["ic_pin_analysis"][0]
        self.assertEqual(row["unconnected_pins"], 0)

    def test_fixture_no_connect_marker_stays_out(self):
        r = _analyze(fixture("kh451", "pu001_no_connect.kicad_sch"))
        for row in r["ic_pin_analysis"]:
            self.assertEqual(row["unconnected_pins"], 0)
            self.assertNotIn("unconnected_pin_list", row)

    def test_shared_pin_wired_on_another_unit_is_connected(self):
        r = _analyze(fixture("multi-unit", "dual_opamp.kicad_sch"))
        for row in r["ic_pin_analysis"]:
            self.assertEqual(row["unconnected_pins"], 0)

    def test_pin_wired_on_a_second_copy_of_the_reference_is_connected(self):
        s = Sheet(20250114)
        s.symbol("t:P", "U1", "P", 50, 50, ("1",))
        s.symbol("t:P", "U1", "P", 90, 50, ("1",))
        s.r("R1", 90, 50)
        rows = run({"t.kicad_sch": s.text([_one_pin_lib("P", "passive"), R_LIB])})["ic_pin_analysis"]
        self.assertEqual([r["unconnected_pins"] for r in rows], [0, 0])

    def test_pin_wired_on_the_first_copy_of_the_reference_is_connected(self):
        s = Sheet(20250114)
        s.symbol("t:P", "U1", "P", 90, 50, ("1",))
        s.r("R1", 90, 50)
        s.symbol("t:P", "U1", "P", 50, 50, ("1",))
        rows = run({"t.kicad_sch": s.text([_one_pin_lib("P", "passive"), R_LIB])})["ic_pin_analysis"]
        self.assertEqual([r["unconnected_pins"] for r in rows], [0, 0])

    def test_lone_pin_with_a_power_flag_is_not_listed(self):
        s = Sheet(20250114)
        s.symbol("t:P", "U1", "P", 50, 50, ("1",))
        s.symbol("power:PWR_FLAG", "#FLG1", "PWR_FLAG", 50, 50, ("1",))
        row = run({"t.kicad_sch": s.text([_one_pin_lib("P", "passive"), FLAG_LIB])})["ic_pin_analysis"][0]
        self.assertEqual(row["unconnected_pins"], 0)

    def test_labelled_single_pin_net_is_not_listed(self):
        s = Sheet(20250114)
        s.symbol("t:P", "U1", "P", 50, 50, ("1",))
        s.label("label", "SIG", 50, 50)
        r = run({"t.kicad_sch": s.text([_one_pin_lib("P", "passive")])})
        row = r["ic_pin_analysis"][0]
        self.assertEqual(row["unconnected_pins"], 0)
        self.assertEqual(row["pins"][0]["net"], "SIG")


if __name__ == "__main__":
    unittest.main()
