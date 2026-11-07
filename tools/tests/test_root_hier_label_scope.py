"""A hierarchical label on the root sheet has no parent sheet pin: KiCad scopes it to the root
sheet. It joins same-name local and global labels on the root sheet, but not a global label or
power symbol of that name on another sheet. Each fixture's kicad-cli 10.0.8 netlist is quoted in
the test that uses it."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT))

from tools.tests.test_body_style_and_hidden_pins import net_of  # noqa: E402
from tools.tests.test_same_sheet_power_names import (  # noqa: E402
    CHILD_FILE_UUID, CHILD_SHEET_UUID, R_LIB, ROOT_UUID, Sheet, power_lib, run, sheet_block)
from tools.tests.test_top_level_sheets_kicad10 import analyze, f5_multi  # noqa: E402


def files(root_items, child_items):
    """Root sheet with R1 on a hierarchical label D0, plus whatever `root_items` adds; one child
    sheet (no sheet pins) with whatever `child_items` adds."""
    root = Sheet(20250114)
    root.r("R1", 50, 50); root.wire(50, 50, 50, 40)
    root.label("hierarchical_label", "D0", 50, 45)
    root_items(root)
    child = Sheet(20250114, path=f"/{ROOT_UUID}/{CHILD_SHEET_UUID}")
    child_items(child)
    libs = [R_LIB, power_lib("power:D0", "D0")]
    return {"t.kicad_sch": root.text(libs, extra=sheet_block("child", "child.kicad_sch",
                                                                150, 40, [])),
            "child.kicad_sch": child.text(libs, uuid=CHILD_FILE_UUID, root=False)}


def child_global(s):
    s.r("R11", 50, 50); s.wire(50, 50, 50, 40); s.label("global_label", "D0", 50, 45)


def child_power(s):
    s.r("R11", 50, 50); s.wire(50, 50, 50, 40)
    s.symbol("power:D0", "#PWR1", "D0", 50, 40, ("1",))


def root_local(s):
    s.r("R2", 80, 50); s.wire(80, 50, 80, 40); s.label("label", "D0", 80, 45)


def root_global(s):
    s.r("R2", 80, 50); s.wire(80, 50, 80, 40); s.label("global_label", "D0", 80, 45)


def nothing(s):
    pass


def sheet_pin_files():
    """Root: R1 on a hierarchical label D0 wired to the child's sheet pin D0. Child: R11 on
    its hierarchical label D0."""
    root = Sheet(20250114)
    root.r("R1", 50, 50); root.wire(50, 50, 50, 45); root.wire(50, 45, 150, 45)
    root.label("hierarchical_label", "D0", 50, 45)
    child = Sheet(20250114, path=f"/{ROOT_UUID}/{CHILD_SHEET_UUID}")
    child.r("R11", 50, 50); child.wire(50, 50, 50, 40)
    child.label("hierarchical_label", "D0", 50, 45)
    return {"t.kicad_sch": root.text([R_LIB], extra=sheet_block(
                "child", "child.kicad_sch", 150, 40, [("D0", 150, 45)])),
            "child.kicad_sch": child.text([R_LIB], uuid=CHILD_FILE_UUID, root=False)}


def two_top_level_files():
    """Two declared top-level sheets: R1 on a global label SIG, R2 on a hierarchical SIG."""
    files = f5_multi()
    files["second.kicad_sch"] = files["second.kicad_sch"].replace(
        '(global_label "SIG"', '(hierarchical_label "SIG"')
    return files


class RootHierarchicalLabelScopeTest(unittest.TestCase):
    def test_global_label_on_another_sheet_stays_apart(self):
        # kicad-cli: /D0 = R1.1; D0 = R11.1
        r = run(files(nothing, child_global))
        self.assertIsNotNone(net_of(r, "R1", "1"))
        self.assertIsNotNone(net_of(r, "R11", "1"))
        self.assertNotEqual(net_of(r, "R1", "1"), net_of(r, "R11", "1"))

    def test_power_symbol_on_another_sheet_stays_apart(self):
        # kicad-cli: /D0 = R1.1; D0 = R11.1
        r = run(files(nothing, child_power))
        self.assertIsNotNone(net_of(r, "R11", "1"))
        self.assertNotEqual(net_of(r, "R1", "1"), net_of(r, "R11", "1"))

    def test_power_net_keeps_its_name(self):
        # kicad-cli: /D0 = R1.1; D0 = R11.1
        r = run(files(nothing, child_power))
        self.assertEqual(net_of(r, "R11", "1"), "D0")
        self.assertNotEqual(net_of(r, "R1", "1"), "D0")

    def test_on_another_top_level_sheet_stays_apart(self):
        # kicad-cli on f5_multi.kicad_sch: SIG = R1.1; /second/SIG = R2.1
        for name in ("f5_multi.kicad_sch", "second.kicad_sch"):
            with self.subTest(named=name):
                r, _ = analyze(two_top_level_files(), name)
                self.assertIsNotNone(net_of(r, "R2", "1"))
                self.assertNotEqual(net_of(r, "R1", "1"), net_of(r, "R2", "1"))
                self.assertEqual(net_of(r, "R1", "1"), "SIG")

    def test_sheet_pin_still_joins_the_child(self):
        # kicad-cli: /D0 = R1.1 R11.1
        r = run(sheet_pin_files())
        self.assertIsNotNone(net_of(r, "R1", "1"))
        self.assertEqual(net_of(r, "R1", "1"), net_of(r, "R11", "1"))

    def test_local_label_on_the_root_sheet_joins(self):
        # kicad-cli: /D0 = R1.1 R2.1
        r = run(files(root_local, nothing))
        self.assertIsNotNone(net_of(r, "R1", "1"))
        self.assertEqual(net_of(r, "R1", "1"), net_of(r, "R2", "1"))

    def test_global_label_on_the_root_sheet_joins(self):
        # kicad-cli: D0 = R1.1 R2.1
        r = run(files(root_global, nothing))
        self.assertIsNotNone(net_of(r, "R1", "1"))
        self.assertEqual(net_of(r, "R1", "1"), net_of(r, "R2", "1"))


if __name__ == "__main__":
    unittest.main()
