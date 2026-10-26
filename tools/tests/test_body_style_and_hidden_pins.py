"""A placed symbol carries the pins of its own body style (De Morgan) plus the shared body-0 pins,
in both readers, and a KiCad 5 hidden power-in pin joins the net named after it."""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from schematic.pipeline import analyze_legacy_schematic, analyze_schematic  # noqa: E402
from schematic.reader import parse_single_sheet  # noqa: E402

MIL = 0.0254


def _pin(num, x, y, kind="input"):
    return (f'(pin {kind} line (at {x} {y} 0) (length 2.54) '
            f'(name "P{num}" (effects (font (size 1.27 1.27)))) '
            f'(number "{num}" (effects (font (size 1.27 1.27)))))')


# G: body 1 pins 1/2/3 at (-5,0)/(5,0)/(0,5), body 2 at (-7,0)/(7,0)/(0,7); pin 4 in G_0_1 is
# all units, body 1 only; pin 5 in G_0_0 is all units, both bodies (kicad-cli 10.0.6 netlist
# lists pin 4 only for body 1 and pin 5 for both)
G_LIB = ('(lib_symbols (symbol "t:G" (in_bom yes) (on_board yes)'
         ' (property "Reference" "U" (at 0 0 0)) (property "Value" "G" (at 0 0 0))'
         f' (symbol "G_0_0" {_pin(5, 0, -8)})'
         f' (symbol "G_0_1" {_pin(4, 0, -5)})'
         f' (symbol "G_1_1" {_pin(1, -5, 0)} {_pin(2, 5, 0, "output")} {_pin(3, 0, 5)})'
         f' (symbol "G_1_2" {_pin(1, -7, 0)} {_pin(2, 7, 0, "output")} {_pin(3, 0, 7)})))')


def _placed(extra, ref="U1", x=100, y=100, uuid="00000000-0000-0000-0000-000000000001"):
    return (f'(symbol (lib_id "t:G") (at {x} {y} 0) (unit 1) {extra} (in_bom yes) (on_board yes)'
            f' (uuid "{uuid}") (property "Reference" "{ref}" (at 0 0 0))'
            f' (property "Value" "G" (at 0 0 0)))')


def _write_sch(tmp, version, body):
    lib = G_LIB
    if version >= 20251028:  # KiCad 10 declares the De Morgan body on the lib symbol
        lib = lib.replace('(symbol "t:G" ', '(symbol "t:G" (body_styles demorgan) ', 1)
    path = os.path.join(tmp, "t.kicad_sch")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'(kicad_sch (version {version}) (generator "eeschema")'
                f' (uuid "00000000-0000-0000-0000-0000000000aa") (paper "A4") {lib} {body})')
    return path


def modern_pins(extra, version=20250114):
    with tempfile.TemporaryDirectory() as tmp:
        sheet = parse_single_sheet(_write_sch(tmp, version, _placed(extra)))
    (comp,) = sheet.components
    return sorted((p["number"], p["x"], p["y"]) for p in comp["pins"])


BODY1 = [("1", 95, 100), ("2", 105, 100), ("3", 100, 95), ("4", 100, 105), ("5", 100, 108)]
BODY2 = [("1", 93, 100), ("2", 107, 100), ("3", 100, 93), ("5", 100, 108)]


class ModernBodyStyleTest(unittest.TestCase):
    def test_no_convert_gives_body_one_pins_once(self):
        self.assertEqual(modern_pins(""), BODY1)

    def test_convert_two_gives_body_two_pins(self):
        self.assertEqual(modern_pins("(convert 2)"), BODY2)

    def test_kicad10_body_style_one(self):
        self.assertEqual(modern_pins("(body_style 1)", version=20251028), BODY1)

    def test_kicad10_body_style_two(self):
        self.assertEqual(modern_pins("(body_style 2)", version=20251028), BODY2)

    def test_lib_pins_hold_body_one_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = parse_single_sheet(_write_sch(tmp, 20250114, _placed("")))
        sym = sheet.lib_symbols["t:G"]
        self.assertEqual(sorted(p["number"] for p in sym["pins"]), ["1", "2", "3", "4", "5"])

    def test_body_one_pin_is_not_on_a_wire_at_the_body_two_position(self):
        body = (_placed("")
                + ' (wire (pts (xy 93 100) (xy 80 100)) (uuid "00000000-0000-0000-0000-0000000000b1"))'
                + ' (label "ALT" (at 80 100 0) (uuid "00000000-0000-0000-0000-0000000000b2"))'
                + ' (wire (pts (xy 95 100) (xy 95 120)) (uuid "00000000-0000-0000-0000-0000000000b3"))'
                + ' (label "MAIN" (at 95 120 0) (uuid "00000000-0000-0000-0000-0000000000b4"))')
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_sch(tmp, 20250114, body)
            with redirect_stderr(StringIO()):
                r = analyze_schematic(path)
        self.assertEqual(net_of(r, "U1", "1"), "MAIN")
        self.assertNotIn("U1", [p["component"] for p in r["nets"].get("ALT", {}).get("pins", [])])
        self.assertEqual(sum(1 for c in r["components"] if c["reference"] == "U1"), 1)
        self.assertNotIn("_body_style", r["components"][0])


# H: unit 1 has pin 1 in both bodies, unit 2 has pin 2 in body 1 only. kicad-cli 10.0.6 lists
# no pin at all for unit 2 placed with (convert 2), and pin 2 for unit 2 with body 1.
H_LIB = ('(lib_symbols (symbol "t:H" (in_bom yes) (on_board yes)'
         ' (property "Reference" "U" (at 0 0 0)) (property "Value" "H" (at 0 0 0))'
         f' (symbol "H_1_1" {_pin(1, -5, 0)}) (symbol "H_1_2" {_pin(1, -7, 0)})'
         f' (symbol "H_2_1" {_pin(2, 5, 0)})))')


class ModernUnitWithoutAlternateBodyTest(unittest.TestCase):
    def _pins(self, extra):
        sym = ('(symbol (lib_id "t:H") (at 100 100 0) ' + extra + ' (in_bom yes) (on_board yes)'
               ' (uuid "00000000-0000-0000-0000-000000000001")'
               ' (property "Reference" "U1" (at 0 0 0)) (property "Value" "H" (at 0 0 0)))')
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.kicad_sch")
            with open(path, "w", encoding="utf-8") as f:
                f.write('(kicad_sch (version 20250114) (generator "eeschema")'
                        f' (uuid "00000000-0000-0000-0000-0000000000aa") (paper "A4") {H_LIB} {sym})')
            (comp,) = parse_single_sheet(path).components
        return sorted((p["number"], p["x"], p["y"]) for p in comp["pins"])

    def test_unit_two_body_two_takes_no_other_units_pins(self):
        self.assertEqual(self._pins("(unit 2) (convert 2)"), [])

    def test_unit_two_body_one(self):
        self.assertEqual(self._pins("(unit 2)"), [("2", 105, 100)])


HEAD = "EESchema Schematic File Version 4\nEELAYER 30 0\nEELAYER END\n$Descr A4 11693 8268\n$EndDescr\n"
LIB_HEAD = "EESchema-LIBRARY Version 2.4\n#encoding utf-8\n"


def comp(lib_id, ref, x, y, unit=1, convert=1, ts="5F000001", value="V"):
    return (f"$Comp\nL {lib_id} {ref}\nU {unit} {convert} {ts}\nP {x} {y}\n"
            f'F 0 "{ref}" H {x} {y} 50  0000 C CNN\nF 1 "{value}" H {x} {y} 50  0000 C CNN\n'
            f"\t{unit}    {x} {y}\n\t1    0    0    -1\n$EndComp\n")


def wire(x1, y1, x2, y2):
    return f"Wire Wire Line\n\t{x1} {y1} {x2} {y2}\n"


def label(x, y, name):
    return f"Text Label {x} {y} 0    50   ~ 0\n{name}\n"


def glabel(x, y, name):
    return f"Text GLabel {x} {y} 0    50   Input ~ 0\n{name}\n"


def analyze(body, cache_lib):
    with tempfile.TemporaryDirectory() as tmp:
        sch = os.path.join(tmp, "t.sch")
        with open(sch, "w", encoding="utf-8") as f:
            f.write(HEAD + body + "$EndSCHEMATC\n")
        with open(os.path.join(tmp, "t-cache.lib"), "w", encoding="utf-8") as f:
            f.write(LIB_HEAD + cache_lib + "#\n#End Library\n")
        with redirect_stderr(StringIO()):
            return analyze_legacy_schematic(sch)


def net_of(result, ref, number):
    for name, net in result["nets"].items():
        for p in net.get("pins") or []:
            if p["component"] == ref and p["pin_number"] == number:
                return name
    return None


def pins_of(result, ref):
    for c in result["components"]:
        if c["reference"] == ref:
            return sorted((p["number"], round(p["x"], 4), round(p["y"], 4)) for p in c["pins"])
    raise AssertionError(ref)


def mm(n, x_mil, y_mil):
    return (n, round(x_mil * MIL, 4), round(y_mil * MIL, 4))


# pin 1 at x=-200 (convert 1) and x=-300 (convert 2); pin 2 common to both bodies
D_LIB = ("DEF D_G U 0 40 Y Y 1 F N\nF0 \"U\" 0 0 50 H V C CNN\nDRAW\n"
         "X A 1 -200 0 100 R 50 50 1 1 I\nX A 1 -300 0 200 R 50 50 1 2 I\n"
         "X Y 2 200 0 100 L 50 50 1 0 O\nENDDRAW\nENDDEF\n")


class LegacyBodyStyleTest(unittest.TestCase):
    def test_convert_one_pin_once_and_off_the_body_two_wire(self):
        body = (comp("d:G", "U1", 1000, 1000)
                + wire(700, 1000, 500, 1000) + label(500, 1000, "IN_ALT"))
        r = analyze(body, D_LIB)
        self.assertEqual(pins_of(r, "U1"), [mm("1", 800, 1000), mm("2", 1200, 1000)])
        self.assertNotEqual(net_of(r, "U1", "1"), "IN_ALT")

    def test_single_unit_convert_two_gets_body_two_pins(self):
        body = (comp("d:G", "U2", 2000, 1000, convert=2, ts="5F000002")
                + wire(1700, 1000, 1500, 1000) + label(1500, 1000, "IN_B2")
                + wire(1800, 1000, 1800, 1300) + label(1800, 1300, "IN_B1"))
        r = analyze(body, D_LIB)
        self.assertEqual(pins_of(r, "U2"), [mm("1", 1700, 1000), mm("2", 2200, 1000)])
        self.assertEqual(net_of(r, "U2", "1"), "IN_B2")

    def test_multi_unit_convert_two_gets_body_two_pins(self):
        lib = ("DEF M_G U 0 40 Y Y 2 L N\nF0 \"U\" 0 0 50 H V C CNN\nDRAW\n"
               "X A 1 -200 0 100 R 50 50 1 1 I\nX A 1 -300 0 200 R 50 50 1 2 I\n"
               "X B 2 -200 100 100 R 50 50 2 1 I\nX B 2 -300 100 200 R 50 50 2 2 I\n"
               "X V 3 0 300 100 D 50 50 0 0 W\nENDDRAW\nENDDEF\n")
        r = analyze(comp("m:G", "U3", 2000, 2000, unit=2, convert=2), lib)
        self.assertEqual(pins_of(r, "U3"), [mm("2", 1700, 1900), mm("3", 2000, 1700)])


    def test_multi_unit_unit_without_body_two_pins(self):
        # unit 2 has pin 2 in body 1 only; placed with convert 2 it shows only the
        # all-units pin 3, never unit 1's body-2 pin 1
        lib = ("DEF N_G U 0 40 Y Y 2 L N\nF0 \"U\" 0 0 50 H V C CNN\nDRAW\n"
               "X A 1 -200 0 100 R 50 50 1 1 I\nX A 1 -300 0 200 R 50 50 1 2 I\n"
               "X B 2 200 0 100 L 50 50 2 1 O\nX V 3 0 300 100 D 50 50 0 0 W\nENDDRAW\nENDDEF\n")
        r = analyze(comp("n:G", "U4", 2000, 2000, unit=2, convert=2), lib)
        self.assertEqual(pins_of(r, "U4"), [mm("3", 2000, 1700)])

    def test_no_internal_keys_in_output(self):
        body = (comp("d:G", "U1", 1000, 1000) + comp("d:G", "U2", 2000, 1000, convert=2, ts="5F000002")
                + wire(700, 1000, 500, 1000) + label(500, 1000, "IN_ALT"))
        r = analyze(body, D_LIB + "#\n" + T_LIB)
        found = []

        def walk(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if k in ("_body_style", "alt_pins", "alt_unit_pins") or (k == "hidden" and v is False):
                        found.append(k)
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(r)
        self.assertEqual(found, [])
        self.assertTrue(r["components"])

T_LIB = ("DEF T_T U 0 40 Y Y 1 F N\nF0 \"U\" 0 0 50 H V C CNN\nDRAW\n"
         "X TOP 1 0 200 100 D 50 50 1 1 P\nX BOT 2 0 -200 100 U 50 50 1 1 P\n"
         "X VCC 3 100 0 100 L 50 50 1 1 W N\nENDDRAW\nENDDEF\n"
         "#\nDEF power_VCC #PWR 0 0 Y Y 1 F P\nF0 \"#PWR\" 0 -150 50 H I C CNN\nDRAW\n"
         "X VCC 1 0 0 0 U 50 50 1 1 W N\nENDDRAW\nENDDEF\n"
         "#\nDEF power_PWR_FLAG #FLG 0 0 N N 1 F P\nF0 \"#FLG\" 0 75 50 H I C CNN\nDRAW\n"
         "X pwr 1 0 0 0 U 50 50 0 0 w N\nENDDRAW\nENDDEF\n")


class LegacyHiddenPowerPinTest(unittest.TestCase):
    def test_hidden_power_in_pins_join_the_global_label(self):
        body = (comp("t:T", "U1", 1000, 1000, ts="5F000001")
                + comp("t:T", "U2", 3000, 1000, ts="5F000002")
                + glabel(5000, 1000, "VCC") + wire(5000, 1000, 5500, 1000))
        r = analyze(body, T_LIB)
        self.assertEqual(net_of(r, "U1", "3"), "VCC")
        self.assertEqual(net_of(r, "U2", "3"), "VCC")
        u1 = next(c for c in r["components"] if c["reference"] == "U1")
        self.assertTrue(next(p for p in u1["pins"] if p["number"] == "3").get("hidden"))
        self.assertNotIn("hidden", next(p for p in u1["pins"] if p["number"] == "1"))

    def test_power_symbol_named_from_its_hidden_pin(self):
        # power:VCC placed with value +3V3: KiCad renames it after its hidden VCC pin on load,
        # so the wire it drives is the VCC net
        body = (comp("t:T", "U1", 1000, 1000, ts="5F000001")
                + comp("power:VCC", "#PWR01", 6000, 3000, ts="5F000003", value="+3V3")
                + comp("t:T", "U2", 6000, 2800, ts="5F000002")
                + wire(6000, 3000, 6000, 2800) + glabel(5000, 1000, "VCC"))
        r = analyze(body, T_LIB)
        self.assertEqual(net_of(r, "U1", "3"), "VCC")
        self.assertEqual(net_of(r, "U2", "2"), "VCC")
        self.assertEqual(net_of(r, "U2", "3"), "VCC")
        self.assertNotIn("+3V3", r["nets"])

    def test_hidden_power_out_pin_makes_no_net(self):
        lib = ("DEF O_O U 0 40 Y Y 1 F N\nF0 \"U\" 0 0 50 H V C CNN\nDRAW\n"
               "X VOUTX 1 0 0 0 U 50 50 1 1 w N\nENDDRAW\nENDDEF\n")
        body = (comp("o:O", "U5", 1000, 1000, ts="5F000005")
                + comp("o:O", "U6", 3000, 1000, ts="5F000006"))
        r = analyze(body, lib)
        self.assertNotIn("VOUTX", r["nets"])
        n5, n6 = net_of(r, "U5", "1"), net_of(r, "U6", "1")
        self.assertTrue(n5 is None or n5 != n6)

if __name__ == "__main__":
    unittest.main()
