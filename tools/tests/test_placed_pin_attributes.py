"""Placed-pin attributes as KiCad 10 resolves them: a placed pin's selected alternate sets its
name and electrical type, stacked pin numbers ([1-5]) expand to one pin per number, and jumper
symbols (jumper_pin_groups, duplicate_pin_numbers_are_jumpers) join their pins.

Expected values are kicad-cli 10.0.6 `sch export netlist` output for these same files
(pinfunction = <name>_<number>, pintype) and the KiCad ExpandStackedPinNotation rule."""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from schematic.pipeline import analyze_schematic  # noqa: E402
from schematic.reader import _expand_stacked, parse_single_sheet  # noqa: E402

F = '(effects (font (size 1.27 1.27)))'
U = "00000000-0000-0000-0000-0000000000aa"


def _write(tmp, text):
    path = os.path.join(tmp, "t.kicad_sch")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _analyze(text):
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(tmp, text)
        with redirect_stderr(StringIO()):
            return analyze_schematic(path)


# --- alternates ------------------------------------------------------------------------------

def _apin(kind, num, name, x, y, alts):
    return (f'(pin {kind} line (at {x} {y} 0) (length 2.54) (name "{name}" {F}) '
            f'(number "{num}" {F}) {alts})')


def _alt_sch(version):
    lib = ('(lib_symbols (symbol "t:MCU" (in_bom yes) (on_board yes)'
           f' (property "Reference" "U" (at 0 0 0) {F}) (property "Value" "MCU" (at 0 0 0) {F})'
           ' (symbol "MCU_1_1" '
           + _apin("bidirectional", "32", "PA11", -10, 0,
                   '(alternate "USBDM" bidirectional line) (alternate "TIM1_CH4" output line)')
           + _apin("bidirectional", "31", "PA10", -10, 5, '(alternate "USART1_RX" input line)')
           + _apin("bidirectional", "30", "PA9", -10, 10, '(alternate "USART1_TX" output line)')
           + _apin("bidirectional", "29", "~", -10, 15, '(alternate "~" input line)')
           + ')))')
    pins = ' '.join(f'(pin "{n}" (alternate "{a}") (uuid "00000000-0000-0000-0000-0000000000c{i}"))'
                    for i, (n, a) in enumerate([("32", "TIM1_CH4"), ("31", "PA10"),
                                                ("30", "NOPE"), ("29", "~")]))
    sym = ('(symbol (lib_id "t:MCU") (at 100 100 0) (unit 1) (in_bom yes) (on_board yes) (dnp no)'
           ' (uuid "00000000-0000-0000-0000-000000000001")'
           f' (property "Reference" "U1" (at 0 0 0) {F}) (property "Value" "MCU" (at 0 0 0) {F}) {pins}'
           f' (instances (project "t" (path "/{U}" (reference "U1") (unit 1)))))')
    return (f'(kicad_sch (version {version}) (generator "eeschema") (uuid "{U}") (paper "A4")'
            f' {lib} {sym} (sheet_instances (path "/" (page "1"))))')


def _alt_pins(version):
    with tempfile.TemporaryDirectory() as tmp:
        (comp,) = parse_single_sheet(_write(tmp, _alt_sch(version))).components
    return {p["number"]: (p["name"], p["type"]) for p in comp["pins"]}


class PinAlternateTest(unittest.TestCase):
    def test_selected_alternate_sets_name_and_type(self):
        # kicad-cli: pin 32 pinfunction TIM1_CH4_32, pintype output
        self.assertEqual(_alt_pins(20251028)["32"], ("TIM1_CH4", "output"))

    def test_alternate_equal_to_base_name_keeps_base(self):
        self.assertEqual(_alt_pins(20251028)["31"], ("PA10", "bidirectional"))

    def test_unknown_alternate_keeps_base(self):
        self.assertEqual(_alt_pins(20251028)["30"], ("PA9", "bidirectional"))

    def test_tilde_base_name_is_empty_in_files_before_20250318(self):
        # kicad-cli: a 20250114 file reads the base name "~" as empty, so the "~" alternate
        # applies (pintype input); in a 20251028 file it equals the base name and is ignored.
        self.assertEqual(_alt_pins(20250114)["29"], ("~", "input"))
        self.assertEqual(_alt_pins(20251028)["29"], ("~", "bidirectional"))

    def test_net_pins_carry_the_alternate(self):
        r = _analyze(_alt_sch(20251028))
        got = {(p["pin_number"], p["pin_name"], p["pin_type"])
               for net in r["nets"].values() for p in net["pins"] if p["component"] == "U1"}
        self.assertIn(("32", "TIM1_CH4", "output"), got)
        self.assertNotIn("_pin_alternates", r["components"][0])


# --- stacked pin numbers ---------------------------------------------------------------------

class ExpandStackedTest(unittest.TestCase):
    def test_kicad_expansion_rule(self):
        self.assertEqual(_expand_stacked("[1-5]"), ["1", "2", "3", "4", "5"])
        self.assertEqual(_expand_stacked("[6,7,9-11]"), ["6", "7", "9", "10", "11"])
        self.assertEqual(_expand_stacked("[A1-A3]"), ["A1", "A2", "A3"])
        self.assertEqual(_expand_stacked("[A01-A03]"), ["A1", "A2", "A3"])
        self.assertEqual(_expand_stacked("[ 1 , B2 ]"), ["1", "B2"])
        self.assertEqual(_expand_stacked("12"), ["12"])

    def test_invalid_notation_is_the_literal(self):
        for text in ("[A1-B3]", "[5-1]", "1]", "[1-5", "[A-B]", "[]", "[,]"):
            self.assertEqual(_expand_stacked(text), [text], text)


# --- jumpers and stacked pins in one sheet ---------------------------------------------------

def _ppin(num, x, y, a):
    return f'(pin passive line (at {x} {y} {a}) (length 1.27) (name "~" {F}) (number "{num}" {F}))'


def _lsym(name, extra, pins):
    short = name.split(":")[1]
    return (f'(symbol "{name}" {extra} (in_bom yes) (on_board yes)'
            f' (property "Reference" "X" (at 0 0 0) {F}) (property "Value" "X" (at 0 0 0) {F})'
            f' (symbol "{short}_1_1" {" ".join(pins)}))')


def _jumper_sch(dup="yes"):
    lib = ('(lib_symbols '
           + _lsym("t:R", "", [_ppin("1", 0, 3.81, 270), _ppin("2", 0, -3.81, 90)])
           + _lsym("t:JP", '(jumper_pin_groups ("1" "2"))',
                   [_ppin("1", 0, 3.81, 270), _ppin("2", 0, -3.81, 90)])
           + _lsym("t:JD", f'(duplicate_pin_numbers_are_jumpers {dup})',
                   [_ppin("1", 0, 3.81, 270), _ppin("1", 0, -3.81, 90)])
           + _lsym("t:S", "", [_ppin("[1-5]", 0, 3.81, 270), _ppin("[6,7,9-11]", 0, -3.81, 90)])
           + ')')
    n = [0]

    def uid():
        n[0] += 1
        return f"00000000-0000-0000-0000-{n[0]:012d}"

    def place(lib_id, ref, x, y):
        return (f'(symbol (lib_id "{lib_id}") (at {x} {y} 0) (unit 1) (in_bom yes) (on_board yes)'
                f' (dnp no) (uuid "{uid()}") (property "Reference" "{ref}" (at {x} {y} 0) {F})'
                f' (property "Value" "X" (at {x} {y} 0) {F})'
                f' (instances (project "t" (path "/{U}" (reference "{ref}") (unit 1)))))')

    def wire(x1, y1, x2, y2):
        return f'(wire (pts (xy {x1} {y1}) (xy {x2} {y2})) (uuid "{uid()}"))'

    def label(x, y, name):
        return f'(label "{name}" (at {x} {y} 0) {F} (uuid "{uid()}"))'

    body = [place("t:JP", "JP1", 50, 50), wire(50, 46.19, 50, 40), place("t:R", "R1", 50, 36.19),
            wire(50, 53.81, 50, 60), place("t:R", "R2", 50, 63.81),
            place("t:JD", "JD1", 90, 50), wire(90, 46.19, 90, 40), place("t:R", "R3", 90, 36.19),
            wire(90, 53.81, 90, 60), place("t:R", "R4", 90, 63.81),
            place("t:S", "S1", 130, 50), wire(130, 46.19, 130, 40), label(130, 40, "TOP"),
            wire(130, 53.81, 130, 60), label(130, 60, "BOT")]
    return (f'(kicad_sch (version 20251028) (generator "eeschema") (uuid "{U}") (paper "A4")'
            f' {lib} {" ".join(body)} (sheet_instances (path "/" (page "1"))))')


def _net_members(r):
    return sorted(sorted((p["component"], p["pin_number"]) for p in net["pins"])
                  for net in r["nets"].values() if net["pins"])


class JumperAndStackedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = _analyze(_jumper_sch())
        cls.members = _net_members(cls.r)

    def test_jumper_pin_group_joins_its_pins(self):
        # kicad-cli: Net-(JP1-~-Pad1) = JP1.1, JP1.2, R1.2, R2.1
        self.assertIn([("JP1", "1"), ("JP1", "2"), ("R1", "2"), ("R2", "1")], self.members)

    def test_duplicate_pin_numbers_join_as_jumpers(self):
        # kicad-cli: Net-(JD1-~) = JD1.1, R3.2, R4.1 (both JD1 pins numbered 1)
        net = next(m for m in self.members if ("R3", "2") in m)
        self.assertIn(("R4", "1"), net)
        self.assertNotIn(("R1", "1"), net)

    def test_duplicate_pin_numbers_without_the_flag_stay_apart(self):
        net = next(m for m in _net_members(_analyze(_jumper_sch(dup="no"))) if ("R3", "2") in m)
        self.assertNotIn(("R4", "1"), net)

    def test_stacked_numbers_are_one_pin_each(self):
        # kicad-cli: /TOP = S1.1..5, /BOT = S1.6,7,9,10,11
        s1 = next(c for c in self.r["components"] if c["reference"] == "S1")
        self.assertEqual(s1["pin_nets"], {**{n: "TOP" for n in "12345"},
                                          **{n: "BOT" for n in ("6", "7", "9", "10", "11")}})
        self.assertNotIn("_jumper_groups", s1)

    def test_stacked_library_pins_count_as_placed(self):
        # every contact of S1's two stacked pins is placed, so no pin-coverage warning
        self.assertNotIn("S1", [w["component"] for w in self.r.get("pin_coverage_warnings", [])])


if __name__ == "__main__":
    unittest.main()
