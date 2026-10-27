"""Bus names, sheet-pin member mapping, junctions on buses and several labels on one bus wire,
as KiCad 10 resolves them (net_settings.cpp ParseBusVector/ParseBusGroup, sch_connection.cpp
Clone, connection_graph.cpp ResolveDrivers/matchBusMember).  Every expected grouping is the
kicad-cli 10.0.6 netlist of the same generated schematic."""
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from schematic.connectivity import (  # noqa: E402
    BusGraph, bus_kind, expand_bus_name, pair_bus_members)
from schematic.pipeline import analyze_schematic  # noqa: E402

ROOT_UUID = "00000000-0000-0000-0000-0000000000a1"
CHILD_SHEET_UUID = "00000000-0000-0000-0000-0000000000b1"
CHILD_FILE_UUID = "00000000-0000-0000-0000-0000000000c1"
FONT = "(effects (font (size 1.27 1.27)))"
R_LIB = ('(lib_symbols (symbol "Device:R" (in_bom yes) (on_board yes)'
         f' (property "Reference" "R" (at 0 0 0) {FONT}) (property "Value" "R" (at 0 0 0) {FONT})'
         ' (symbol "R_1_1"'
         f' (pin passive line (at 0 3.81 270) (length 1.27) (name "~" {FONT}) (number "1" {FONT}))'
         f' (pin passive line (at 0 -3.81 90) (length 1.27) (name "~" {FONT}) (number "2" {FONT})))))')
CHILD_PATH = f"/{ROOT_UUID}/{CHILD_SHEET_UUID}"

_n = [0]


def _uuid():
    _n[0] += 1
    return f"30000000-0000-0000-0000-{_n[0]:012d}"


def bus(x1, y1, x2, y2):
    return f'(bus (pts (xy {x1} {y1}) (xy {x2} {y2})) (stroke (width 0) (type default)) (uuid "{_uuid()}"))'


def wire(x1, y1, x2, y2):
    return f'(wire (pts (xy {x1} {y1}) (xy {x2} {y2})) (stroke (width 0) (type default)) (uuid "{_uuid()}"))'


def label(kind, name, x, y):
    shape = " (shape input)" if kind in ("global_label", "hierarchical_label") else ""
    return f'({kind} "{name}"{shape} (at {x} {y} 0) {FONT} (uuid "{_uuid()}"))'


def junction(x, y):
    return f'(junction (at {x} {y}) (diameter 0) (color 0 0 0 0) (uuid "{_uuid()}"))'


def resistor(ref, x, y, path):
    return (f'(symbol (lib_id "Device:R") (at {x} {y} 0) (unit 1) (in_bom yes) (on_board yes)'
            f' (uuid "{_uuid()}") (property "Reference" "{ref}" (at {x} {y} 0) {FONT})'
            f' (property "Value" "1k" (at {x} {y} 0) {FONT})'
            f' (pin "1" (uuid "{_uuid()}")) (pin "2" (uuid "{_uuid()}"))'
            f' (instances (project "t" (path "{path}" (reference "{ref}") (unit 1)))))')


def tap(x, y, name, ref, path=f"/{ROOT_UUID}"):
    """A bus entry at (x, y) on a horizontal bus, a wire labelled ``name`` down to ``ref`` pin 1."""
    x2, y2 = x + 2.54, y + 2.54
    return [f'(bus_entry (at {x} {y}) (size 2.54 2.54) (stroke (width 0) (type default))'
            f' (uuid "{_uuid()}"))',
            wire(x2, y2, x2, y2 + 10), label("label", name, x2, y2 + 5),
            resistor(ref, x2, y2 + 13.81, path)]


def sheet_block(pin, x, y, w, h, py):
    return (f'(sheet (at {x} {y}) (size {w} {h}) (uuid "{CHILD_SHEET_UUID}")'
            f' (property "Sheetname" "child" (at {x} {y} 0) {FONT})'
            f' (property "Sheetfile" "child.kicad_sch" (at {x} {y} 0) {FONT})'
            f' (pin "{pin}" bidirectional (at {x} {py} 180) {FONT} (uuid "{_uuid()}"))'
            f' (instances (project "t" (path "/{ROOT_UUID}" (page "2")))))')


def doc(items, uuid=ROOT_UUID, root=True):
    tail = '(sheet_instances (path "/" (page "1")))' if root else ""
    return (f'(kicad_sch (version 20250114) (generator "eeschema") (uuid "{uuid}") (paper "A4")\n'
            + R_LIB + "\n" + "\n".join(items) + f"\n{tail})\n")


def analyze(files):
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in files.items():
            Path(tmp, name).write_text(text, encoding="utf-8")
        Path(tmp, "t.kicad_pro").write_text('{"meta":{"filename":"t.kicad_pro","version":1}}',
                                            encoding="utf-8")
        with redirect_stderr(StringIO()):
            return analyze_schematic(os.path.join(tmp, "t.kicad_sch"))


def pin1_groups(result):
    groups = set()
    for net in result["nets"].values():
        refs = frozenset(p["component"] for p in net.get("pins", []) if p.get("pin_number") == "1")
        if refs:
            groups.add(refs)
    return groups


def one_sheet(labels, members, global_label=None):
    """A bus carrying local labels ``labels`` (and an optional global label), tapped by wires
    labelled ``members`` to R1, R2, ..."""
    _n[0] = 0
    items = [bus(100, 50, 250, 50)]
    items += [label("label", name, 105 + i * 25, 50) for i, name in enumerate(labels)]
    if global_label:
        items.append(label("global_label", global_label, 130, 50))
    for k, m in enumerate(members):
        items += tap(160 + 10 * k, 50, m, f"R{k + 1}")
    return {"t.kicad_sch": doc(items)}


def across_pin(parent_labels, pin, child_label, parent_members, child_members, child_first=11):
    """Root bus with local labels ``parent_labels`` tapped to R1.. and ending on sheet pin
    ``pin``; the child's bus carries hierarchical label ``child_label`` tapped to R<child_first>.."""
    _n[0] = 0
    p = [bus(100, 50, 150, 50)]
    p += [label("label", name, 105 + i * 20, 50) for i, name in enumerate(parent_labels)]
    for k, m in enumerate(parent_members):
        p += tap(110 + 10 * k, 50, m, f"R{k + 1}")
    p.append(sheet_block(pin, 150, 40, 30, 30, 50))
    c = [bus(50, 50, 100, 50), label("hierarchical_label", child_label, 50, 50)]
    for k, m in enumerate(child_members):
        c += tap(55 + 10 * k, 50, m, f"R{k + child_first}", CHILD_PATH)
    return {"t.kicad_sch": doc(p), "child.kicad_sch": doc(c, CHILD_FILE_UUID, root=False)}


def verifier_pin(parent_label, pin, child_label, parent_members, child_members):
    """The verifier's layout: R1/R2 on the root bus, R3/R4 on the child's."""
    _n[0] = 0
    p = [bus(100, 50, 150, 50), label("label", parent_label, 105, 50)]
    p += tap(120, 50, parent_members[0], "R1") + tap(130, 50, parent_members[1], "R2")
    p.append(sheet_block(pin, 150, 40, 30, 30, 50))
    c = [bus(50, 50, 100, 50), label("hierarchical_label", child_label, 50, 50)]
    c += tap(60, 50, child_members[0], "R3", CHILD_PATH) + tap(70, 50, child_members[1], "R4", CHILD_PATH)
    return {"t.kicad_sch": doc(p), "child.kicad_sch": doc(c, CHILD_FILE_UUID, root=False)}


def junction_case(with_junction):
    """Root bus A[0..1] crossed by a vertical bus that runs to sheet pin D[0..1]."""
    _n[0] = 0
    p = [bus(100, 50, 160, 50), label("label", "A[0..1]", 105, 50)]
    p += tap(110, 50, "A0", "R1") + tap(120, 50, "A1", "R2")
    p += [bus(140, 30, 140, 90), bus(140, 90, 150, 90)]
    if with_junction:
        p.append(junction(140, 50))
    p.append(sheet_block("D[0..1]", 150, 80, 30, 30, 90))
    c = [bus(50, 50, 100, 50), label("hierarchical_label", "D[0..1]", 50, 50)]
    c += tap(60, 50, "D0", "R3", CHILD_PATH) + tap(70, 50, "D1", "R4", CHILD_PATH)
    return {"t.kicad_sch": doc(p), "child.kicad_sch": doc(c, CHILD_FILE_UUID, root=False)}


def groups(*sets):
    return {frozenset(s) for s in sets}


class BusNameTest(unittest.TestCase):
    def test_vectors_expand_ascending(self):
        self.assertEqual(expand_bus_name("A[15..13]"), ["A13", "A14", "A15"])
        self.assertEqual(expand_bus_name("DP[0..1]+"), ["DP0+", "DP1+"])
        self.assertEqual(expand_bus_name("[0..1]"), ["0", "1"])
        self.assertEqual(expand_bus_name("R_{C}[0..1]"), ["R_{C}0", "R_{C}1"])
        self.assertEqual(expand_bus_name("D_{[1..2]}"), ["D1", "D2"])

    def test_one_wide_vector_is_not_a_bus(self):
        self.assertIsNone(expand_bus_name("D[3..3]"))
        self.assertIsNone(bus_kind("D[3..3]"))

    def test_group_members_split_on_space_or_comma_and_keep_markup(self):
        self.assertEqual(expand_bus_name("I2C{SDA,SCL}"), ["I2C.SDA", "I2C.SCL"])
        self.assertEqual(expand_bus_name("SWD{SWCLK, SWD}"), ["SWD.SWCLK", "SWD.SWD"])
        self.assertEqual(expand_bus_name("CTL{~{OE} WE}"), ["CTL.~{OE}", "CTL.WE"])
        self.assertEqual(expand_bus_name("X{A B} "), ["X.A", "X.B"])

    def test_names_are_parsed_after_unescaping(self):
        self.assertIsNone(expand_bus_name("A{comma}B"))

    def test_bus_kind(self):
        self.assertEqual(bus_kind("D[0..3]"), "vector")
        self.assertEqual(bus_kind("P{X Y}"), "group")
        self.assertIsNone(bus_kind("~{OE}"))


class PairMembersTest(unittest.TestCase):
    def test_vectors_pair_by_position_up_to_the_smaller_width(self):
        pairs, reason = pair_bus_members("P[0..3]", ["P0", "P1", "P2", "P3"], "D[0..1]", ["D0", "D1"])
        self.assertEqual(pairs, [("P0", "D0"), ("P1", "D1")])
        self.assertIsNone(reason)

    def test_groups_pair_by_member_name(self):
        pairs, _ = pair_bus_members("P{SCL SDA}", ["P.SCL", "P.SDA"], "C{SDA SCL}", ["C.SDA", "C.SCL"])
        self.assertEqual(sorted(pairs), [("P.SCL", "C.SCL"), ("P.SDA", "C.SDA")])


def _graph(*labels):
    g = BusGraph(0, [{"x1": 0, "y1": 0, "x2": 100, "y2": 0}], [], {})
    for i, (name, role) in enumerate(labels):
        g.add_bus_label(name, 5 + 10 * i, 0, role=role)
    g.finalize()
    return g, g.cluster_at(0, 0)


class ClusterDriverTest(unittest.TestCase):
    def test_wider_label_drives_when_neither_is_a_superset_alphabetical(self):
        g, cid = _graph(("X[0..1]", "local"), ("D[0..3]", "local"))
        self.assertEqual(g.cluster_driver(cid)["name"], "D[0..3]")
        self.assertEqual(sorted(g.member_aliases(cid)), [("X0", "D0"), ("X1", "D1")])

    def test_superset_drives(self):
        g, cid = _graph(("D[4..7]", "local"), ("D[0..7]", "local"))
        self.assertEqual(g.cluster_driver(cid)["name"], "D[0..7]")
        self.assertEqual(sorted(g.member_aliases(cid)),
                         [("D4", "D0"), ("D5", "D1"), ("D6", "D2"), ("D7", "D3")])

    def test_global_drives_over_local(self):
        g, cid = _graph(("A[0..1]", "local"), ("ZZ[0..1]", "global"))
        self.assertEqual(g.cluster_driver(cid)["name"], "ZZ[0..1]")

    def test_group_label_on_a_vector_driver_does_not_alias(self):
        g, cid = _graph(("P{X Y}", "local"), ("A[0..1]", "local"))
        self.assertEqual(g.cluster_driver(cid)["name"], "A[0..1]")
        self.assertEqual(g.member_aliases(cid), [])

    def test_sheet_pin_never_drives(self):
        g, cid = _graph(("X[0..3]", "pin"))
        self.assertIsNone(g.cluster_driver(cid))


class SheetPinMappingTest(unittest.TestCase):
    def check(self, files, expected):
        self.assertEqual(pin1_groups(analyze(files)), expected)

    def test_opposite_direction_maps_by_position(self):
        self.check(verifier_pin("P[0..1]", "D[1..0]", "D[1..0]", ["P0", "P1"], ["D0", "D1"]),
                   groups({"R1", "R3"}, {"R2", "R4"}))

    def test_descending_parent_label(self):
        self.check(across_pin(["P[3..0]"], "D[0..3]", "D[0..3]", ["P0", "P3"], ["D0", "D3"]),
                   groups({"R1", "R11"}, {"R2", "R12"}))
        self.check(across_pin(["P[1..0]"], "P[1..0]", "P[1..0]", ["P0", "P1"], ["P0", "P1"]),
                   groups({"R1", "R11"}, {"R2", "R12"}))

    def test_group_members_map_by_name(self):
        self.check(verifier_pin("P{SCL SDA}", "C{SDA SCL}", "C{SDA SCL}",
                                ["P.SCL", "P.SDA"], ["C.SCL", "C.SDA"]),
                   groups({"R1", "R3"}, {"R2", "R4"}))
        self.check(across_pin(["P{A B C}"], "C{A B}", "C{A B}", ["P.A", "P.B", "P.C"], ["C.A", "C.B"]),
                   groups({"R1", "R11"}, {"R2", "R12"}, {"R3"}))

    def test_different_widths_join_up_to_the_smaller(self):
        self.check(verifier_pin("P[0..3]", "D[0..1]", "D[0..1]", ["P0", "P1"], ["D0", "D1"]),
                   groups({"R1", "R3"}, {"R2", "R4"}))
        self.check(verifier_pin("P[2..5]", "D[0..1]", "D[0..1]", ["P2", "P3"], ["D0", "D1"]),
                   groups({"R1", "R3"}, {"R2", "R4"}))
        self.check(across_pin(["P[0..1]"], "D[0..3]", "D[0..3]", ["P0", "P1"], ["D0", "D1", "D2", "D3"]),
                   groups({"R1", "R11"}, {"R2", "R12"}, {"R13"}, {"R14"}))

    def test_comma_and_markup_groups(self):
        self.check(verifier_pin("I2C{SDA,SCL}", "I2C{SDA,SCL}", "I2C{SDA,SCL}",
                                ["I2C.SDA", "I2C.SCL"], ["I2C.SDA", "I2C.SCL"]),
                   groups({"R1", "R3"}, {"R2", "R4"}))
        self.check(verifier_pin("CTL{~{OE} WE}", "CTL{~{OE} WE}", "CTL{~{OE} WE}",
                                ["CTL.~{OE}", "CTL.WE"], ["CTL.~{OE}", "CTL.WE"]),
                   groups({"R1", "R3"}, {"R2", "R4"}))
        self.check(across_pin(["X{A B} "], "X{A B} ", "X{A B} ", ["X.A", "X.B"], ["X.A", "X.B"]),
                   groups({"R1", "R11"}, {"R2", "R12"}))

    def test_prefix_forms(self):
        self.check(across_pin(["[0..1]"], "[0..1]", "[0..1]", ["0", "1"], ["0", "1"]),
                   groups({"R1", "R11"}, {"R2", "R12"}))
        self.check(across_pin(["R_{C}[0..1]"], "R_{C}[0..1]", "R_{C}[0..1]",
                              ["R_{C}0", "R_{C}1"], ["R_{C}0", "R_{C}1"]),
                   groups({"R1", "R11"}, {"R2", "R12"}))

    def test_one_wide_vector_is_not_a_bus(self):
        self.check(across_pin(["D[3..3]"], "D[3..3]", "D[3..3]", ["D3"], ["D3"]),
                   groups({"R1"}, {"R11"}))


class BusJunctionTest(unittest.TestCase):
    def test_junction_joins_crossing_bus_interiors(self):
        self.assertEqual(pin1_groups(analyze(junction_case(True))),
                         groups({"R1", "R3"}, {"R2", "R4"}))

    def test_crossing_without_junction_stays_apart(self):
        self.assertEqual(pin1_groups(analyze(junction_case(False))),
                         groups({"R1"}, {"R2"}, {"R3"}, {"R4"}))


class LabelsOnOneBusTest(unittest.TestCase):
    def check(self, files, expected):
        self.assertEqual(pin1_groups(analyze(files)), expected)

    def test_two_names_alias_by_position(self):
        self.check(one_sheet(["A[0..1]", "B[0..1]"], ["A0", "B0", "A1", "B1"]),
                   groups({"R1", "R2"}, {"R3", "R4"}))

    def test_sub_range_relabel_aliases_by_position(self):
        # KiCad's own netlist joins D0 with D4: D[4..7]'s index 0 is D4.
        self.check(one_sheet(["D[0..7]", "D[4..7]"], [f"D{i}" for i in range(8)]),
                   groups({"R1", "R5"}, {"R2", "R6"}, {"R3", "R7"}, {"R4", "R8"}))

    def test_overlapping_ranges_close_transitively(self):
        self.check(one_sheet(["D[0..3]", "D[2..5]"], [f"D{i}" for i in range(6)]),
                   groups({"R1", "R3", "R5"}, {"R2", "R4", "R6"}))

    def test_groups_alias_by_member_name(self):
        self.check(one_sheet(["P{X Y}", "Q{Y X}"], ["P.X", "Q.X", "P.Y", "Q.Y"]),
                   groups({"R1", "R2"}, {"R3", "R4"}))

    def test_group_label_on_a_vector_driver_does_not_alias(self):
        self.check(one_sheet(["P{X Y}", "A[0..1]"], ["P.X", "A0", "P.Y", "A1"]),
                   groups({"R1"}, {"R2"}, {"R3"}, {"R4"}))

    def test_global_label_drives(self):
        self.check(one_sheet(["A[0..1]"], ["A0", "ZZ0", "A1", "ZZ1"], global_label="ZZ[0..1]"),
                   groups({"R1", "R2"}, {"R3", "R4"}))

    def test_two_widths_and_a_sheet_pin(self):
        self.check(across_pin(["D[0..3]", "X[0..1]"], "Y[0..1]", "Y[0..1]",
                              ["X0", "X1", "D0", "D1"], ["Y0", "Y1"]),
                   groups({"R1", "R3", "R11"}, {"R2", "R4", "R12"}))

    def test_two_same_width_names_and_a_sheet_pin(self):
        self.check(across_pin(["D[0..1]", "X[0..1]"], "Y[0..1]", "Y[0..1]",
                              ["X0", "X1", "D0", "D1"], ["Y0", "Y1"]),
                   groups({"R1", "R3", "R11"}, {"R2", "R4", "R12"}))

    def test_hierarchical_and_local_label_on_the_child_bus(self):
        _n[0] = 0
        p = [bus(100, 50, 150, 50), label("label", "P[0..1]", 105, 50)]
        p += tap(110, 50, "P0", "R1") + tap(120, 50, "P1", "R2")
        p.append(sheet_block("D[0..1]", 150, 40, 30, 30, 50))
        c = [bus(40, 50, 100, 50), label("hierarchical_label", "D[0..1]", 40, 50),
             label("label", "Q[0..1]", 80, 50)]
        c += tap(55, 50, "Q0", "R11", CHILD_PATH) + tap(65, 50, "Q1", "R12", CHILD_PATH)
        files = {"t.kicad_sch": doc(p), "child.kicad_sch": doc(c, CHILD_FILE_UUID, root=False)}
        self.check(files, groups({"R1", "R11"}, {"R2", "R12"}))


if __name__ == "__main__":
    unittest.main()
