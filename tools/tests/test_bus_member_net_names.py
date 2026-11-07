"""A net that reaches a sheet only through a bus is named after the bus member there, the way
KiCad names it, unless a label or power symbol on that net sits on the same sheet: then that
label names it. A bus member with no pin on its net makes no net. Each fixture's kicad-cli
10.0.8 netlist is quoted in the test that uses it."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT))

from tools.tests.test_body_style_and_hidden_pins import net_of  # noqa: E402
from tools.tests.test_same_sheet_power_names import (  # noqa: E402
    CHILD_FILE_UUID, CHILD_SHEET_UUID, R_LIB, ROOT_UUID, Sheet, _uuid, run, sheet_block)


def tap(sheet, x, name, ref):
    """A bus entry off a horizontal bus at y = 50, its wire labelled `name`, ending on `ref`."""
    x2, y2 = round(x + 2.54, 2), 52.54
    sheet.items.append(f'(bus_entry (at {x} 50) (size 2.54 2.54) (uuid "{_uuid()}"))')
    sheet.wire(x2, y2, x2, y2 + 10)
    sheet.label("label", name, x2, y2 + 5)
    sheet.r(ref, x2, y2 + 10)


def child_bus_files(root_label, child_labels, taps):
    """Root: a bus carrying `root_label` (if any) into the child's sheet pin, named like the
    child's hierarchical label (the first of `child_labels`). Child: a bus carrying
    `child_labels` (kind, name), tapped per `taps` (name, ref)."""
    root = Sheet(20250114)
    root.wire(100, 50, 150, 50, "bus")
    if root_label:
        root.label("label", root_label, 105, 50)
    child = Sheet(20250114, path=f"/{ROOT_UUID}/{CHILD_SHEET_UUID}")
    child.wire(50, 50, 120, 50, "bus")
    for i, (kind, name) in enumerate(child_labels):
        child.label(kind, name, 50 + 60 * i, 50)
    for i, (name, ref) in enumerate(taps):
        tap(child, 60 + 10 * i, name, ref)
    pin = child_labels[0][1]
    return {"t.kicad_sch": root.text([R_LIB], extra=sheet_block(
                "object", "object.kicad_sch", 150, 40, [(pin, 150, 50)])),
            "object.kicad_sch": child.text([R_LIB], uuid=CHILD_FILE_UUID, root=False)}


def pinless_alias_files():
    """One sheet: a bus labelled with the alias {PWR} (members VDD) and nothing tapped off
    it; R1 on a local label SIG."""
    s = Sheet(20250114)
    s.wire(100, 50, 150, 50, "bus"); s.label("label", "{PWR}", 105, 50)
    s.r("R1", 50, 50); s.wire(50, 50, 50, 40); s.label("label", "SIG", 50, 45)
    s.items.append('(bus_alias "PWR" (members "VDD"))')
    return {"t.kicad_sch": s.text([R_LIB])}


class BusMemberNetNameTest(unittest.TestCase):
    def test_root_bus_member_names_the_child_net(self):
        # kicad-cli: /CPU_DB0 = R11.1; /CPU_DB1 = R12.1
        r = run(child_bus_files("CPU_DB[0..15]", [("hierarchical_label", "CPU_DB[1..15]")],
                                [("CPU_DB1", "R11"), ("CPU_DB2", "R12")]))
        self.assertEqual(net_of(r, "R11", "1"), "CPU_DB0")
        self.assertEqual(net_of(r, "R12", "1"), "CPU_DB1")

    def test_label_on_the_members_sheet_names_the_net(self):
        # kicad-cli: /object/cnt0 = R11.1
        r = run(child_bus_files(None, [("hierarchical_label", "CNT[0..3]"),
                                       ("label", "cnt[0..3]")], [("cnt0", "R11")]))
        self.assertEqual(net_of(r, "R11", "1"), "cnt0")

    def test_pinless_alias_member_makes_no_net(self):
        # kicad-cli: /SIG = R1.1, no VDD net
        r = run(pinless_alias_files())
        self.assertEqual(net_of(r, "R1", "1"), "SIG")
        self.assertNotIn("VDD", r["nets"])


if __name__ == "__main__":
    unittest.main()
