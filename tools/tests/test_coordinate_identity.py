"""Schematic points join only at KiCad's exact integer coordinates (1 IU = 100 nm): a wire end
0.001 mm off a pin and a label 0.03 mm off a wire do not join, a label within 1 IU of a wire and
a junction exactly on one do, and a power symbol joins a wire only at its ends.  A point left
unjoined within 0.01 mm of another point or 0.05 mm of a wire is a CoordinateNearMiss diagnostic.
Expected groupings are kicad-cli 10.0.6's netlist of the same schematics."""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from schematic.pipeline import analyze_schematic  # noqa: E402

FONT = "(effects (font (size 1.27 1.27)))"
ROOT_UUID = "00000000-0000-0000-0000-0000000000aa"
R_LIB = ('(symbol "Device:R" (pin_numbers (hide yes)) (pin_names (offset 0)) (in_bom yes) (on_board yes)'
         f' (property "Reference" "R" (at 2.032 0 90) {FONT}) (property "Value" "R" (at 0 0 90) {FONT})'
         ' (symbol "R_1_1"'
         f' (pin passive line (at 0 3.81 270) (length 1.27) (name "~" {FONT}) (number "1" {FONT}))'
         f' (pin passive line (at 0 -3.81 90) (length 1.27) (name "~" {FONT}) (number "2" {FONT}))))\n')
VCC_LIB = ('(symbol "power:VCC" (power) (pin_numbers (hide yes)) (pin_names (offset 0) (hide yes))'
           ' (in_bom yes) (on_board yes)'
           f' (property "Reference" "#PWR" (at 0 -3.81 0) {FONT}) (property "Value" "VCC" (at 0 3.81 0) {FONT})'
           ' (symbol "VCC_1_1" (pin power_in line (at 0 0 90) (length 0) (hide yes)'
           f' (name "VCC" {FONT}) (number "1" {FONT}))))\n')

_n = [0]


def _uuid():
    _n[0] += 1
    return f"20000000-0000-0000-0000-{_n[0]:012d}"


def R(ref, x, y):
    """Vertical resistor at (x, y): pin 1 at (x, y - 3.81), pin 2 at (x, y + 3.81)."""
    return (f'(symbol (lib_id "Device:R") (at {x} {y} 0) (unit 1) (in_bom yes) (on_board yes)'
            f' (uuid "{_uuid()}") (property "Reference" "{ref}" (at {x} {y} 90) {FONT})'
            f' (property "Value" "1k" (at {x} {y} 90) {FONT})'
            f' (instances (project "t" (path "/{ROOT_UUID}" (reference "{ref}") (unit 1)))))\n')


def P(ref, x, y):
    return (f'(symbol (lib_id "power:VCC") (at {x} {y} 0) (unit 1) (in_bom yes) (on_board yes)'
            f' (uuid "{_uuid()}") (property "Reference" "{ref}" (at {x} {y} 0) {FONT})'
            f' (property "Value" "VCC" (at {x} {y} 0) {FONT})'
            f' (instances (project "t" (path "/{ROOT_UUID}" (reference "{ref}") (unit 1)))))\n')


def W(x1, y1, x2, y2):
    return f'(wire (pts (xy {x1} {y1}) (xy {x2} {y2})) (stroke (width 0) (type default)) (uuid "{_uuid()}"))\n'


def L(name, x, y, kind="label"):
    shape = " (shape input)" if kind == "global_label" else ""
    return f'({kind} "{name}"{shape} (at {x} {y} 0) {FONT} (uuid "{_uuid()}"))\n'


def J(x, y):
    return f'(junction (at {x} {y}) (diameter 0) (color 0 0 0 0) (uuid "{_uuid()}"))\n'


def analyze(items):
    _n[0] = 0
    text = ('(kicad_sch (version 20250114) (generator "eeschema") (generator_version "9.0")'
            f' (uuid "{ROOT_UUID}") (paper "A4")\n(lib_symbols {R_LIB}{VCC_LIB})\n'
            + "".join(items) + '(sheet_instances (path "/" (page "1"))))\n')
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.kicad_sch")
        Path(path).write_text(text, encoding="utf-8")
        with redirect_stderr(StringIO()):
            return analyze_schematic(path)


def groups(result):
    """Nets with two or more pins, as frozensets of 'REF.PIN'."""
    out = set()
    for net in result["nets"].values():
        pins = frozenset(f'{p["component"]}.{p["pin_number"]}' for p in net.get("pins", [])
                         if not p["component"].startswith("#"))
        if len(pins) > 1:
            out.add(pins)
    return out


def near_misses(result):
    return [d for d in result["diagnostics"] if d["exception"] == "CoordinateNearMiss"]


class CoordinateSemanticsTest(unittest.TestCase):
    """Nine wire, pin, label and junction placements, each next to the same layout drawn
    on exact coordinates, with the groupings KiCad's netlist gives."""

    @classmethod
    def setUpClass(cls):
        cls.result = analyze(
            # 1 label mid single wire
            [R("R1", 50, 50), W(50, 53.81, 50, 70), L("A", 50, 60),
             R("R2", 80, 50), W(80, 53.81, 80, 60), L("A", 80, 60)]
            # 2 pin mid-wire
            + [W(100, 30, 130, 30), R("R3", 115, 33.81), R("R4", 100, 33.81)]
            # 3 wire end 0.001 mm off a pin
            + [R("R5", 150, 33.81), W(150.001, 30, 160, 30), R("R6", 160, 33.81)]
            # 4 label 0.03 mm off a wire
            + [R("R7", 50, 96.19), W(50, 100, 70, 100), L("B", 60, 100.03),
               R("R8", 80, 96.19), W(80, 100, 85, 100), L("B", 85, 100)]
            # 5 T with junction
            + [R("R9", 100, 96.19), W(100, 100, 130, 100), W(115, 100, 115, 120), J(115, 100),
               R("R10", 115, 123.81)]
            # 6 T without junction
            + [R("R11", 100, 146.19), W(100, 150, 130, 150), W(115, 150, 115, 170), R("R12", 115, 173.81)]
            # 7 wire end 0.00004 mm off (the same IU)
            + [R("R13", 200, 33.81), W(200.00004, 30, 210, 30), R("R14", 210, 33.81)]
            # 8 label 1 IU off a wire
            + [R("R15", 200, 96.19), W(200, 100, 220, 100), L("C", 210, 100.0001),
               R("R16", 230, 96.19), W(230, 100, 235, 100), L("C", 235, 100)]
            # 9 label on a crossing of two wires
            + [R("R17", 200, 146.19), W(200, 150, 220, 150), W(210, 140, 210, 160), L("D", 210, 150),
               R("R18", 210, 163.81)])
        cls.groups = groups(cls.result)

    def test_groupings_match_kicad(self):
        self.assertEqual(self.groups, {
            frozenset({"R1.2", "R2.2"}), frozenset({"R9.2", "R10.1"}), frozenset({"R13.1", "R14.1"}),
            frozenset({"R15.2", "R16.2"}), frozenset({"R17.2", "R18.1"})})

    def test_wire_end_off_a_pin_does_not_join(self):
        self.assertFalse(any({"R5.1", "R6.1"} <= g for g in self.groups))

    def test_label_off_a_wire_does_not_join(self):
        self.assertFalse(any({"R7.2", "R8.2"} <= g for g in self.groups))

    def test_two_near_misses_recorded(self):
        records = near_misses(self.result)
        self.assertEqual(len(records), 2, records)
        for d in records:
            self.assertEqual(d["source"], "schematic.connectivity.build_net_map")
            self.assertEqual(d["effect"], "not connected (KiCad joins exact coordinates)")
        text = " | ".join(d["message"] for d in records)
        self.assertIn("(150.001, 30) mm is 0.001 mm from", text)
        self.assertIn("label 'B' at (60, 100.03) mm is 0.03 mm from wire (50, 100)-(70, 100)", text)


class PowerSymbolTest(unittest.TestCase):
    """Power symbols at a wire end and inside a wire, and a global label on a wire."""

    @classmethod
    def setUpClass(cls):
        cls.result = analyze(
            [R("R1", 40, 46.19), W(40, 50, 60, 50), P("#PWR01", 50, 50), R("R2", 80, 46.19), P("#PWR02", 80, 50)]
            + [R("R3", 50, 96.19), W(50, 100, 70, 100), L("GG", 60, 100, "global_label"),
               R("R4", 80, 96.19), L("GG", 80, 100, "global_label")]
            + [R("R5", 120, 46.19), W(120, 50, 130, 50), P("#PWR03", 130, 50)])

    def test_groupings_match_kicad(self):
        self.assertEqual(groups(self.result),
                         {frozenset({"R3.2", "R4.2"}), frozenset({"R2.2", "R5.2"})})

    def test_power_symbol_inside_a_wire_does_not_join(self):
        vcc = self.result["nets"]["VCC"]
        self.assertNotIn("R1", {p["component"] for p in vcc["pins"]})


class HelperTest(unittest.TestCase):
    def test_to_iu_rounds_half_away_from_zero(self):
        from kicad_core.coords import to_iu
        self.assertEqual(to_iu(-0.00005), -1)
        self.assertEqual(to_iu(0.00005), 1)
        self.assertEqual(to_iu(200.00004), 2000000)
        self.assertEqual(to_iu(150.001), 1500010)

    def test_legacy_mils_are_mils_times_254(self):
        from kicad_core.coords import to_iu
        from kicad_core.values import snap_to_mil_grid
        for mils in range(-20000, 20001, 37):
            self.assertEqual(to_iu(snap_to_mil_grid(mils * 0.0254)), mils * 254, mils)

    def test_segment_hit(self):
        from kicad_core.coords import segment_hit_iu
        a, b = (0, 0), (1000, 0)
        self.assertTrue(segment_hit_iu((500, 1), a, b, 1))
        self.assertFalse(segment_hit_iu((500, 2), a, b, 1))
        self.assertTrue(segment_hit_iu((500, 0), a, b, 0))
        self.assertFalse(segment_hit_iu((500, 1), a, b, 0))
        self.assertTrue(segment_hit_iu((1000, 0), a, b, 0))
        self.assertFalse(segment_hit_iu((1001, 0), a, b, 0))
        # diagonal: (5, 6) is 0.71 IU from y = x
        self.assertTrue(segment_hit_iu((5, 5), (0, 0), (10, 10), 0))
        self.assertFalse(segment_hit_iu((5, 6), (0, 0), (10, 10), 0))
        self.assertTrue(segment_hit_iu((5, 6), (0, 0), (10, 10), 1))


class NearMissCapTest(unittest.TestCase):
    def test_twenty_records_and_one_summary(self):
        from schematic.connectivity import build_net_map
        comps, wires = [], []
        for i in range(25):
            x = 10.0 * i
            comps.append({"reference": f"R{i}", "value": "1k", "type": "resistor", "pins": [
                {"number": "1", "name": "~", "type": "passive", "x": x, "y": 0.0}]})
            wires.append({"x1": x + 0.001, "y1": 0.0, "x2": x, "y2": 5.0})
        sink = []
        with redirect_stderr(StringIO()) as err:
            build_net_map(comps, wires, [], [], [], diagnostics=sink)
        self.assertEqual(len(sink), 21)
        self.assertTrue(all(d["exception"] == "CoordinateNearMiss" for d in sink))
        self.assertIn("5 more", sink[-1]["message"])
        self.assertEqual(len(err.getvalue().splitlines()), 21)


class NearMissAcrossBucketsTest(unittest.TestCase):
    def _sink(self, wire_x):
        from schematic.connectivity import build_net_map
        comps = [{"reference": "R1", "value": "1k", "type": "resistor", "pins": [
            {"number": "1", "name": "~", "type": "passive", "x": 150.004, "y": 0.0}]}]
        sink = []
        with redirect_stderr(StringIO()):
            build_net_map(comps, [{"x1": wire_x, "y1": 0.0, "x2": wire_x, "y2": 5.0}], [], [], [],
                          diagnostics=sink)
        return [d["message"] for d in sink]

    def test_pair_across_a_bucket_edge_is_reported(self):
        # 150.004 and 150.006 mm are 0.002 mm apart on either side of 150.005
        self.assertEqual(self._sink(150.006), [
            "sheet 0: wire end at (150.006, 0) mm is 0.002 mm from pin 'R1.1' at (150.004, 0)"])

    def test_pair_more_than_0_01_mm_apart_is_not_reported(self):
        self.assertEqual(self._sink(150.016), [])


class BusGraphToleranceTest(unittest.TestCase):
    def test_bus_tap_keeps_its_tolerance(self):
        from schematic.connectivity import BusGraph
        g = BusGraph(0, [{"x1": 0.0, "y1": 0.0, "x2": 10.0, "y2": 0.0},
                         {"x1": 5.0, "y1": 0.03, "x2": 5.0, "y2": 10.0}], [], {})
        self.assertEqual(g.cluster_at(0.0, 0.0), g.cluster_at(5.0, 10.0))
        self.assertEqual(g.cluster_at(9.996, 0.04), g.cluster_at(0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
