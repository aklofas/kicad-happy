"""Each PWR_FLAG is a power output pin of its own in the ERC pin-conflict records."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT))

from tools.tests.test_erc_pins import _flag_lib, _one_pin_lib, by_type, erc, two_pin_net  # noqa: E402
from tools.tests.test_same_sheet_power_names import Sheet, run  # noqa: E402


def _pairs(result):
    return [sorted(p["pins"]) for w in result["design_analysis"]["erc_warnings"]
            if w["type"] == "pin_to_pin" for p in w["pairs"]]


class PwrFlagPinsTest(unittest.TestCase):
    def test_two_flags_on_one_net_conflict(self):
        s = Sheet(20250114)
        s.symbol("t:I", "U1", "I", 60, 50, ("1",))
        s.wire(40, 50, 45, 50); s.wire(45, 50, 50, 50); s.wire(50, 50, 60, 50)
        s.symbol("power:PWR_FLAG", "#FLG0101", "PWR_FLAG", 45, 50, ("1",))
        s.symbol("power:PWR_FLAG", "#FLG0102", "PWR_FLAG", 50, 50, ("1",))
        r = run({"t.kicad_sch": s.text([_one_pin_lib("I", "input"), _flag_lib()])})
        recs = [w for w in r["design_analysis"]["erc_warnings"] if w["type"] == "pin_to_pin"]
        self.assertEqual([w["severity"] for w in recs], ["error"])
        self.assertIn(["#FLG0101.1", "#FLG0102.1"], _pairs(r))

    def test_pin_marker_names_the_nearer_flag_not_the_earlier_reference(self):
        s = Sheet(20250114)
        s.symbol("t:O", "U1", "O", 50, 50, ("1",))
        s.wire(50, 50, 52, 50); s.wire(52, 50, 70, 50)
        s.symbol("power:PWR_FLAG", "#FLG0102", "PWR_FLAG", 52, 50, ("1",))
        s.symbol("power:PWR_FLAG", "#FLG0101", "PWR_FLAG", 70, 50, ("1",))
        r = run({"t.kicad_sch": s.text([_one_pin_lib("O", "output"), _flag_lib()])})
        rec = next(w for w in r["design_analysis"]["erc_warnings"] if w["type"] == "pin_to_pin")
        marked = [p["pins"] for p in rec["pairs"] if p["pins"][0] == "U1.1"]
        self.assertEqual(marked, [["U1.1", "#FLG0102.1"]])

    def test_flag_without_collected_points_keeps_the_synthetic_pin(self):
        nets, comps = two_pin_net("output", "passive", has_pwr_flag=True)
        recs = by_type(erc(nets, comps), "pin_to_pin")
        self.assertEqual([sorted(p["pins"]) for p in recs[0]["pairs"]], [["#FLG.1", "U1.1"]])

    def test_flag_still_drives_the_net(self):
        flag = [("#FLG0101", "1", 0, 5, 5)]
        nets, comps = two_pin_net("power_in", "passive", has_pwr_flag=True, _pwr_flags=flag)
        self.assertEqual(erc(nets, comps), [])
        nets, comps = two_pin_net("power_in", "passive")
        self.assertEqual([w["type"] for w in erc(nets, comps)], ["power_pin_not_driven"])

    def test_flagged_net_keeps_has_pwr_flag(self):
        s = Sheet(20250114)
        s.symbol("t:I", "U1", "I", 60, 50, ("1",))
        s.wire(45, 50, 60, 50)
        s.symbol("power:PWR_FLAG", "#FLG0101", "PWR_FLAG", 45, 50, ("1",))
        r = run({"t.kicad_sch": s.text([_one_pin_lib("I", "input"), _flag_lib()])})
        self.assertTrue(any(i.get("has_pwr_flag") for i in r["nets"].values()))

    def test_single_flag_without_a_conflict_has_no_record(self):
        s = Sheet(20250114)
        s.symbol("t:I", "U1", "I", 60, 50, ("1",))
        s.wire(45, 50, 60, 50)
        s.symbol("power:PWR_FLAG", "#FLG0101", "PWR_FLAG", 45, 50, ("1",))
        r = run({"t.kicad_sch": s.text([_one_pin_lib("I", "input"), _flag_lib()])})
        self.assertEqual(_pairs(r), [])

    def test_flag_list_is_not_in_the_output(self):
        s = Sheet(20250114)
        s.symbol("t:I", "U1", "I", 60, 50, ("1",))
        s.wire(45, 50, 60, 50)
        s.symbol("power:PWR_FLAG", "#FLG0101", "PWR_FLAG", 45, 50, ("1",))
        r = run({"t.kicad_sch": s.text([_one_pin_lib("I", "input"), _flag_lib()])})
        for info in r["nets"].values():
            self.assertNotIn("_pwr_flags", info)


if __name__ == "__main__":
    unittest.main()
