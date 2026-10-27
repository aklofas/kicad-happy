"""A global bus label names global member nets: the same member under the same-name global bus
on two sheets is one net, a global net label of the member's name joins it, and a local label of
that name on another sheet does not.  Expected groupings are kicad-cli 10.0.6's netlist."""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from schematic.pipeline import analyze_schematic  # noqa: E402

ROOT_UUID = "00000000-0000-0000-0000-0000000000aa"
HEAD = '(kicad_sch (version 20231120) (generator "eeschema") (uuid "{}") (paper "A4")\n'
FONT = "(effects (font (size 1.27 1.27)))"
R_LIB = ('(lib_symbols (symbol "t:R" (in_bom yes) (on_board yes)'
         f' (property "Reference" "R" (at 0 0 0) {FONT}) (property "Value" "R" (at 0 0 0) {FONT})'
         ' (symbol "R_1_1"'
         f' (pin passive line (at -5 0 0) (length 2.54) (name "~" {FONT}) (number "1" {FONT}))'
         f' (pin passive line (at 5 0 180) (length 2.54) (name "~" {FONT}) (number "2" {FONT})))))\n')
SHEETS = {"a": "10000000-0000-0000-0000-000000000001", "b": "10000000-0000-0000-0000-000000000002",
          "c": "10000000-0000-0000-0000-000000000003", "d": "10000000-0000-0000-0000-000000000004",
          "e": "10000000-0000-0000-0000-000000000005"}

_n = [0]


def _uuid():
    _n[0] += 1
    return f"20000000-0000-0000-0000-{_n[0]:012d}"


def _resistor(sheet, ref, y):
    """R at (80, y): pin 1 at (75, y)."""
    return (f'(symbol (lib_id "t:R") (at 80 {y} 0) (unit 1) (in_bom yes) (on_board yes)'
            f' (uuid "{_uuid()}") (property "Reference" "{ref}" (at 80 {y - 3} 0) {FONT})'
            f' (property "Value" "R" (at 80 {y + 3} 0) {FONT})'
            f' (instances (project "t" (path "/{ROOT_UUID}/{SHEETS[sheet]}"'
            f' (reference "{ref}") (unit 1)))))\n')


def _wire(x1, y1, x2, y2):
    return f'(wire (pts (xy {x1} {y1}) (xy {x2} {y2})) (stroke (width 0) (type default)) (uuid "{_uuid()}"))\n'


def _label(kind, name, x, y, angle=0):
    shape = " (shape input)" if kind == "global_label" else ""
    return f'({kind} "{name}"{shape} (at {x} {y} {angle}) {FONT} (uuid "{_uuid()}"))\n'


def _bus(bus_name, kind="global_label"):
    """A vertical bus at x = 50 carrying a bus label."""
    return (f'(bus (pts (xy 50 40) (xy 50 100)) (stroke (width 0) (type default)) (uuid "{_uuid()}"))\n'
            + _label(kind, bus_name, 50, 45, 90))


def _member(sheet, ref, name, y):
    """A bus entry from the bus to a wire labelled ``name`` ending on ``ref`` pin 1."""
    return (f'(bus_entry (at 50 {y - 2.54}) (size 2.54 2.54) (stroke (width 0) (type default))'
            f' (uuid "{_uuid()}"))\n'
            + _wire(52.54, y, 75, y) + _label("label", name, 60, y) + _resistor(sheet, ref, y))


def _netlabelled(sheet, ref, kind, name, y):
    """A wire carrying a ``kind`` net label, ending on ``ref`` pin 1."""
    return _wire(55, y, 75, y) + _label(kind, name, 60, y) + _resistor(sheet, ref, y)


def _sheet_block(name, x, pin=""):
    return (f'(sheet (at {x} 20) (size 20 20) (fields_autoplaced yes) (uuid "{SHEETS[name]}")'
            f' (property "Sheetname" "{name}" (at {x} 19 0) {FONT})'
            f' (property "Sheetfile" "{name}.kicad_sch" (at {x} 41 0) {FONT}){pin}'
            f' (instances (project "t" (path "/{ROOT_UUID}" (page "{ord(name) - 95}")))))\n')


def write_project(tmp, root_local=None):
    """``root_local``: a local bus label added to the root bus beside its global D[0..3]."""
    _n[0] = 0
    children = {
        # two sheets each carry the global bus D[0..3]
        "a": _bus("D[0..3]") + _member("a", "R1", "D0", 60) + _member("a", "R3", "D1", 70),
        "b": _bus("D[0..3]") + _member("b", "R2", "D0", 60) + _member("b", "R4", "D1", 70),
        # a global net label D1 (joins), a local label D0 (does not)
        "c": (_netlabelled("c", "R5", "global_label", "D1", 60)
              + _netlabelled("c", "R6", "label", "D0", 70)),
        # a different global bus whose group members are B.D0 / B.D1
        "d": _bus("B{D0 D1}") + _member("d", "R7", "B.D0", 60),
        # reached from the root through sheet pin X[0..3], whose root bus carries only the
        # global label D[0..3]: the child's X0 is the root's D0
        "e": _bus("X[0..3]", "hierarchical_label") + _member("e", "R8", "X0", 60),
    }
    for name, body in children.items():
        Path(tmp, f"{name}.kicad_sch").write_text(
            HEAD.format(f"30000000-0000-0000-0000-00000000000{ord(name) - 96}") + R_LIB + body + ")\n",
            encoding="utf-8")
    root = (HEAD.format(ROOT_UUID) + "(lib_symbols)\n"
            + "".join(_sheet_block(n, 20 + 40 * i) for i, n in enumerate("abcd"))
            + _sheet_block("e", 180, f' (pin "X[0..3]" input (at 180 30 180) {FONT} (uuid "{_uuid()}"))')
            + f'(bus (pts (xy 150 30) (xy 180 30)) (stroke (width 0) (type default)) (uuid "{_uuid()}"))\n'
            + _label("global_label", "D[0..3]", 160, 30)
            + (_label("label", root_local, 170, 30) if root_local else "")
            + '(sheet_instances (path "/" (page "1")))\n)\n')
    Path(tmp, "t.kicad_sch").write_text(root, encoding="utf-8")
    return os.path.join(tmp, "t.kicad_sch")


def pin_groups(result):
    """Pin-1 sets per net, as frozensets of references."""
    groups = set()
    for net in result["nets"].values():
        refs = frozenset(p["component"] for p in net.get("pins", []) if p.get("pin_number") == "1")
        if refs:
            groups.add(refs)
    return groups


class GlobalBusMembersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stderr(StringIO()):
                cls.result = analyze_schematic(write_project(tmp))
        cls.groups = pin_groups(cls.result)

    def group_of(self, ref):
        (group,) = [g for g in self.groups if ref in g]
        return group

    def test_same_member_on_two_sheets_is_one_net(self):
        self.assertIn("R2", self.group_of("R1"))

    def test_sheet_pin_on_a_global_bus_maps_onto_its_members(self):
        self.assertIn("R8", self.group_of("R1"))

    def test_global_net_label_joins_the_member(self):
        self.assertEqual(self.group_of("R5"), {"R3", "R4", "R5"})

    def test_local_label_of_a_member_name_on_another_sheet_stays_apart(self):
        self.assertEqual(self.group_of("R6"), {"R6"})

    def test_other_global_bus_members_stay_apart(self):
        self.assertEqual(self.group_of("R7"), {"R7"})

    def test_groups_match_kicad(self):
        self.assertEqual(self.groups, {frozenset({"R1", "R2", "R8"}), frozenset({"R3", "R4", "R5"}),
                                       frozenset({"R6"}), frozenset({"R7"})})


class RootBusLabelsTest(unittest.TestCase):
    def analyze(self, root_local):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stderr(StringIO()):
                return analyze_schematic(write_project(tmp, root_local))

    def test_local_label_aliases_onto_the_global_driver(self):
        # KiCad drives the bus from the global label; the local ADDR[0..3] members
        # are renamed onto D0..D3 by position, so the sheet pin still maps from D.
        result = self.analyze("ADDR[0..3]")
        self.assertEqual(result["bus_topology"]["unresolved"], [])
        self.assertEqual(pin_groups(result), {frozenset({"R1", "R2", "R8"}), frozenset({"R3", "R4", "R5"}),
                                              frozenset({"R6"}), frozenset({"R7"})})

    def test_local_and_global_with_the_same_members_are_not_ambiguous(self):
        result = self.analyze("D[0..3]")
        self.assertEqual(result["bus_topology"]["unresolved"], [])
        self.assertIn(frozenset({"R1", "R2", "R8"}), pin_groups(result))


if __name__ == "__main__":
    unittest.main()
