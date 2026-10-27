"""Library symbols and their unit/body pins are selected as KiCad does: every direct child of
lib_symbols is a symbol (only nested sub-symbols are units), a placed unit carries its own pins
plus the common unit-0 pins, and a placed body style carries its own pins plus body-0 pins."""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from schematic.pipeline import analyze_schematic  # noqa: E402
from schematic.reader import parse_single_sheet  # noqa: E402


def _pin(num, x, y, kind="passive"):
    return (f'(pin {kind} line (at {x} {y} 0) (length 2.54) '
            f'(name "P{num}" (effects (font (size 1.27 1.27)))) '
            f'(number "{num}" (effects (font (size 1.27 1.27)))))')


def _lib(name, subs, extra=""):
    short = name.split(":")[-1]
    body = " ".join(f'(symbol "{short}_{suffix}" {items})' for suffix, items in subs)
    return (f'(symbol "{name}" {extra} (in_bom yes) (on_board yes)'
            f' (property "Reference" "U" (at 0 0 0)) (property "Value" "{short}" (at 0 0 0)) {body})')


def _placed(lib_id, ref, n, extra="", x=100, y=100):
    return (f'(symbol (lib_id "{lib_id}") (at {x} {y} 0) {extra} (in_bom yes) (on_board yes)'
            f' (uuid "00000000-0000-0000-0000-0000000001{n:02d}")'
            f' (property "Reference" "{ref}" (at 0 0 0)) (property "Value" "V" (at 0 0 0)))')


def _wire(x1, y1, x2, y2, n):
    return f'(wire (pts (xy {x1} {y1}) (xy {x2} {y2})) (uuid "00000000-0000-0000-0000-0000000002{n:02d}"))'


def _label(name, x, y, n):
    return f'(label "{name}" (at {x} {y} 0) (uuid "00000000-0000-0000-0000-0000000003{n:02d}"))'


def _sch(tmp, libs, body, version=20250114):
    path = os.path.join(tmp, "t.kicad_sch")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'(kicad_sch (version {version}) (generator "eeschema")'
                f' (uuid "00000000-0000-0000-0000-0000000000aa") (paper "A4")'
                f' (lib_symbols {" ".join(libs)}) {body})')
    return path


def _pins(comp):
    return sorted((p["number"], p["x"], p["y"]) for p in comp["pins"])


def _analyze(path):
    with redirect_stderr(StringIO()):
        return analyze_schematic(path)


def _net_members(result, net):
    return sorted((p["component"], p["pin_number"]) for p in result["nets"].get(net, {}).get("pins", []))


class TopLevelNumericSuffixTest(unittest.TestCase):
    """KiCad parses every direct child of lib_symbols as a symbol; a name's own _<n>_<n> is not
    a unit suffix (only nested sub-symbols are units)."""

    def test_raspberry_pi_2_3_keeps_its_pins(self):
        lib = _lib("Connector:Raspberry_Pi_2_3", [("0_1", ""), ("1_1", _pin(1, -5, 0) + _pin(2, 5, 0))])
        body = (_placed("Connector:Raspberry_Pi_2_3", "J1", 1)
                + _wire(95, 100, 80, 100, 1) + _label("A", 80, 100, 1)
                + _wire(105, 100, 120, 100, 2) + _label("B", 120, 100, 2))
        with tempfile.TemporaryDirectory() as tmp:
            path = _sch(tmp, [lib], body)
            (comp,) = parse_single_sheet(path).components
            r = _analyze(path)
        self.assertEqual(_pins(comp), [("1", 95, 100), ("2", 105, 100)])
        self.assertEqual(_net_members(r, "A"), [("J1", "1")])
        self.assertEqual(_net_members(r, "B"), [("J1", "2")])

    def test_nested_unit_of_a_numeric_named_symbol(self):
        lib = _lib("x:R_1_1", [("1_1", _pin(1, 0, 5) + _pin(2, 0, -5))])
        with tempfile.TemporaryDirectory() as tmp:
            sheet = parse_single_sheet(_sch(tmp, [lib], _placed("x:R_1_1", "R1", 1, "(unit 1)")))
        self.assertIn("x:R_1_1", sheet.lib_symbols)
        self.assertEqual(sorted(sheet.lib_symbols["x:R_1_1"]["unit_pins"]), [1])
        (comp,) = sheet.components
        self.assertEqual(_pins(comp), [("1", 100, 95), ("2", 100, 105)])


# G: unit 1 has pin 1 at (-5,0), unit 2 pin 2 at (5,0), unit 3 is graphics only.
G_LIB = _lib("t:G", [("1_1", _pin(1, -5, 0)), ("2_1", _pin(2, 5, 0)),
                     ("3_1", "(rectangle (start -2 -2) (end 2 2) (stroke (width 0)) (fill (type none)))")])


class PinlessUnitTest(unittest.TestCase):
    """KiCad SCH_SYMBOL::GetPins keeps a pin when its unit is 0 or the placed unit."""

    def test_graphics_only_unit_has_no_pins(self):
        with tempfile.TemporaryDirectory() as tmp:
            (comp,) = parse_single_sheet(_sch(tmp, [G_LIB], _placed("t:G", "U1", 1, "(unit 3)"))).components
        self.assertEqual(comp["pins"], [])

    def test_graphics_only_unit_gets_common_pins_only(self):
        lib = G_LIB.replace('(symbol "G_1_1"', f'(symbol "G_0_1" {_pin(9, 0, 5)}) (symbol "G_1_1"', 1)
        with tempfile.TemporaryDirectory() as tmp:
            (comp,) = parse_single_sheet(_sch(tmp, [lib], _placed("t:G", "U1", 1, "(unit 3)"))).components
        self.assertEqual(_pins(comp), [("9", 100, 95)])

    def test_pinless_unit_does_not_join_a_wire_at_another_units_pin(self):
        # U1 unit 1 at (0,100): pin 1 on net A. U1 unit 3 at (100,100): a wire end sits where
        # unit 2's pin 2 would be (105,100); KiCad leaves net B without any U1 pin.
        body = (_placed("t:G", "U1", 1, "(unit 1)", x=0)
                + _wire(-5, 100, -20, 100, 1) + _label("A", -20, 100, 1)
                + _placed("t:G", "U1", 2, "(unit 3)")
                + _wire(105, 100, 120, 100, 2) + _label("B", 120, 100, 2))
        with tempfile.TemporaryDirectory() as tmp:
            r = _analyze(_sch(tmp, [G_LIB], body))
        self.assertEqual(_net_members(r, "A"), [("U1", "1")])
        self.assertEqual(_net_members(r, "B"), [])
        by_unit = {c.get("unit"): c for c in r["components"] if c["reference"] == "U1"}
        self.assertEqual(by_unit[1]["pin_nets"], {"1": "A"})
        self.assertEqual(by_unit[3]["pin_nets"], {})


# S: KiCad 10 custom body styles. Pin 1 is at (-5,0) in body 1, (-7,0) in body 2 and (5,0) in
# body 3; pin 2 at (0,5) is shared by every body (body 0).
S_LIB = _lib("t:S", [("0_0", _pin(2, 0, 5)), ("1_1", _pin(1, -5, 0)), ("1_2", _pin(1, -7, 0)),
                     ("1_3", _pin(1, 5, 0))], extra='(body_styles "A" "B" "C")')


class CustomBodyStyleTest(unittest.TestCase):
    """KiCad SCH_SYMBOL::UpdatePins keeps a library pin when its body style is 0 or the placed one."""

    def _pins(self, extra):
        with tempfile.TemporaryDirectory() as tmp:
            path = _sch(tmp, [S_LIB], _placed("t:S", "U1", 1, "(unit 1) " + extra), version=20251028)
            (comp,) = parse_single_sheet(path).components
        return _pins(comp)

    def test_body_style_three_takes_its_own_pins(self):
        self.assertEqual(self._pins("(body_style 3)"), [("1", 105, 100), ("2", 100, 95)])

    def test_body_style_one_and_two_unchanged(self):
        self.assertEqual(self._pins("(body_style 1)"), [("1", 95, 100), ("2", 100, 95)])
        self.assertEqual(self._pins("(body_style 2)"), [("1", 93, 100), ("2", 100, 95)])


if __name__ == "__main__":
    unittest.main()
