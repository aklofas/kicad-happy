"""Which label names a net, as kicad-cli 10.0.6 exports it: a local label outranks a
hierarchical label and a sheet pin, equal-rank names resolve to the alphabetically first
escaped name (connection_graph.cpp ResolveDrivers), and a hierarchical label carried by a net
named after another driver is not reported unconnected."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT))

from tools.tests.test_body_style_and_hidden_pins import net_of  # noqa: E402
from tools.tests.test_same_sheet_power_names import (  # noqa: E402
    CHILD_FILE_UUID, CHILD_SHEET_UUID, R_LIB, ROOT_UUID, Sheet, power_lib, run, sheet_block)

CHILD_PATH = f"/{ROOT_UUID}/{CHILD_SHEET_UUID}"


def net_name(result, ref, number):
    """The net's shown name: display_name when the key carries a sheet prefix."""
    key = net_of(result, ref, number)
    net = result["nets"][key]
    return net.get("display_name") or key


# --- fixtures (each one's kicad-cli 10.0.6 netlist is quoted in the test that uses it) -------

def f7_files():
    """Root: R1-R2 wire with local VCCX and a dangling hierarchical label PORT; R3 wired to sheet
    pin PIN. Child: R4 on a wire with hierarchical label PIN and local label LOC."""
    root = Sheet(20250114)
    root.r("R1", 50, 50); root.r("R2", 60, 50); root.wire(50, 50, 60, 50)
    root.label("label", "VCCX", 52, 50); root.label("hierarchical_label", "PORT", 58, 50)
    root.r("R3", 100, 50); root.wire(100, 50, 150, 50)
    child = Sheet(20250114, path=CHILD_PATH)
    child.r("R4", 60, 50); child.wire(50, 50, 60, 50)
    child.label("hierarchical_label", "PIN", 50, 50); child.label("label", "LOC", 55, 50)
    return {"t.kicad_sch": root.text([R_LIB], extra=sheet_block(
                "child", "child.kicad_sch", 150, 40, [("PIN", 150, 50)])),
            "child.kicad_sch": child.text([R_LIB], uuid=CHILD_FILE_UUID, root=False)}


def f7b_files():
    """Root: R3 wired to sheet pin PIN with local label PNET. Child: R4 on hier label PIN."""
    root = Sheet(20250114)
    root.r("R3", 100, 50); root.wire(100, 50, 150, 50); root.label("label", "PNET", 110, 50)
    child = Sheet(20250114, path=CHILD_PATH)
    child.r("R4", 60, 50); child.wire(50, 50, 60, 50)
    child.label("hierarchical_label", "PIN", 50, 50)
    return {"t.kicad_sch": root.text([R_LIB], extra=sheet_block(
                "child", "child.kicad_sch", 150, 40, [("PIN", 150, 50)])),
            "child.kicad_sch": child.text([R_LIB], uuid=CHILD_FILE_UUID, root=False)}


def depth_files():
    """Root: R3 wired to sheet pin PIN with local ZZZ. Child: R4 on hier PIN with local AAA."""
    root = Sheet(20250114)
    root.r("R3", 100, 50); root.wire(100, 50, 150, 50); root.label("label", "ZZZ", 110, 50)
    child = Sheet(20250114, path=CHILD_PATH)
    child.r("R4", 60, 50); child.wire(50, 50, 60, 50)
    child.label("hierarchical_label", "PIN", 50, 50); child.label("label", "AAA", 55, 50)
    return {"t.kicad_sch": root.text([R_LIB], extra=sheet_block(
                "child", "child.kicad_sch", 150, 40, [("PIN", 150, 50)])),
            "child.kicad_sch": child.text([R_LIB], uuid=CHILD_FILE_UUID, root=False)}


def tie_files():
    """One sheet. R1: local SCL1 placed before local SCL. R2: global GA before global GB.
    R3: local A{slash}B (shown A/B) before local AB; R5: local CD before C{slash}D.
    R4: power VCC before power +5V."""
    s = Sheet(20250114)
    s.r("R1", 50, 50); s.wire(50, 50, 50, 30)
    s.label("label", "SCL1", 50, 45); s.label("label", "SCL", 50, 40)
    s.r("R2", 80, 50); s.wire(80, 50, 80, 30)
    s.label("global_label", "GA", 80, 45); s.label("global_label", "GB", 80, 40)
    s.r("R3", 110, 50); s.wire(110, 50, 110, 30)
    s.label("label", "A{slash}B", 110, 45); s.label("label", "AB", 110, 40)
    s.r("R4", 140, 50); s.wire(140, 50, 140, 30); s.wire(140, 30, 150, 30)
    s.symbol("power:VCC", "#PWR1", "VCC", 140, 30, ("1",))
    s.symbol("power:+5V", "#PWR2", "+5V", 150, 30, ("1",))
    s.r("R5", 170, 50); s.wire(170, 50, 170, 30)
    s.label("label", "CD", 170, 45); s.label("label", "C{slash}D", 170, 40)
    return {"t.kicad_sch": s.text([R_LIB, power_lib("power:VCC", "VCC"),
                                   power_lib("power:+5V", "+5V")])}


def hier_global_files():
    """One sheet: R1 on a wire with a hierarchical label PORT and a global label GNET."""
    s = Sheet(20250114)
    s.r("R1", 50, 50); s.wire(50, 50, 50, 30)
    s.label("hierarchical_label", "PORT", 50, 45); s.label("global_label", "GNET", 50, 40)
    return {"t.kicad_sch": s.text([R_LIB])}


class DriverPriorityTest(unittest.TestCase):
    def test_local_label_beats_hierarchical_label(self):
        # kicad-cli: /VCCX = R1.1 R2.1; /child/LOC = R3.1 R4.1
        r = run(f7_files())
        self.assertEqual(net_name(r, "R1", "1"), "VCCX")
        self.assertEqual(net_name(r, "R4", "1"), "LOC")
        self.assertEqual(net_of(r, "R3", "1"), net_of(r, "R4", "1"))

    def test_parent_local_label_beats_sheet_pin_and_child_hier_label(self):
        # kicad-cli: /PNET = R3.1 R4.1
        r = run(f7b_files())
        self.assertEqual(net_name(r, "R4", "1"), "PNET")
        self.assertEqual(net_of(r, "R3", "1"), net_of(r, "R4", "1"))

    def test_shallower_sheet_wins_an_equal_rank_tie(self):
        # kicad-cli: /ZZZ = R3.1 R4.1
        r = run(depth_files())
        self.assertEqual(net_name(r, "R4", "1"), "ZZZ")


class TieBreakTest(unittest.TestCase):
    def test_alphabetical_tie_break(self):
        # kicad-cli: /SCL = R1.1; GA = R2.1; /AB = R3.1; +5V = R4.1
        r = run(tie_files())
        self.assertEqual(net_name(r, "R1", "1"), "SCL")
        self.assertEqual(net_name(r, "R2", "1"), "GA")
        self.assertEqual(net_name(r, "R4", "1"), "+5V")

    def test_tie_break_compares_the_escaped_name(self):
        # kicad-cli: /AB = R3.1; /CD = R5.1 ("A{slash}B" sorts after "AB", "A/B" before it)
        r = run(tie_files())
        self.assertEqual(net_name(r, "R3", "1"), "AB")
        self.assertEqual(net_name(r, "R5", "1"), "CD")


class HierarchicalLabelAuditTest(unittest.TestCase):
    def test_label_on_a_net_named_by_a_global_label_is_connected(self):
        # kicad-cli: GNET = R1.1 (PORT is on it)
        r = run(hier_global_files())
        self.assertEqual(net_name(r, "R1", "1"), "GNET")
        self.assertEqual(r["hierarchical_labels"].get("unconnected_hierarchical", []), [])

    def test_label_on_a_net_named_by_a_local_label_is_connected(self):
        # PORT sits on /VCCX (kicad-cli), so it is carried by a net
        r = run(f7_files())
        self.assertNotIn("PORT", r["hierarchical_labels"].get("unconnected_hierarchical", []))
        self.assertEqual(r["hierarchical_labels"].get("unconnected_hierarchical", []), [])


if __name__ == "__main__":
    unittest.main()
