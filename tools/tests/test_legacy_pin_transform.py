"""Legacy (KiCad 5) pins land where KiCad puts them: absolute pin = P + (a*px + b*py, c*px + d*py)
with the raw `.lib` pin offset and the raw `$Comp` matrix, and only built-in fallback pins snap
to a nearby wire end that nothing else holds."""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from schematic.pipeline import analyze_legacy_schematic  # noqa: E402

MIL = 0.0254

HEAD = "EESchema Schematic File Version 4\nEELAYER 30 0\nEELAYER END\n$Descr A4 11693 8268\n$EndDescr\n"
LIB_HEAD = "EESchema-LIBRARY Version 2.4\n#encoding utf-8\n"


def comp(lib_id, ref, x, y, matrix, unit=1, ts="5F000001"):
    return (f"$Comp\nL {lib_id} {ref}\nU {unit} 1 {ts}\nP {x} {y}\n"
            f'F 0 "{ref}" H {x} {y} 50  0000 C CNN\nF 1 "V" H {x} {y} 50  0000 C CNN\n'
            f"\t{unit}    {x} {y}\n\t{matrix}\n$EndComp\n")


def wire(x1, y1, x2, y2):
    return f"Wire Wire Line\n\t{x1} {y1} {x2} {y2}\n"


def label(x, y, name):
    return f"Text Label {x} {y} 0    50   ~ 0\n{name}\n"


def analyze(body, cache_lib=None):
    with tempfile.TemporaryDirectory() as tmp:
        sch = os.path.join(tmp, "t.sch")
        with open(sch, "w", encoding="utf-8") as f:
            f.write(HEAD + body + "$EndSCHEMATC\n")
        if cache_lib is not None:
            with open(os.path.join(tmp, "t-cache.lib"), "w", encoding="utf-8") as f:
                f.write(LIB_HEAD + cache_lib + "#\n#End Library\n")
        with redirect_stderr(StringIO()):
            return analyze_legacy_schematic(sch)


def pin_xy(result, ref, number):
    for c in result["components"]:
        if c["reference"] == ref:
            for p in c["pins"]:
                if p["number"] == number:
                    return (round(p["x"], 4), round(p["y"], 4))
    raise AssertionError(f"{ref}.{number} not found")


def net_of(result, ref, number):
    for name, net in result["nets"].items():
        for p in net.get("pins") or []:
            if p["component"] == ref and p["pin_number"] == number:
                return name
    return None


def mm(x_mil, y_mil):
    return (round(x_mil * MIL, 4), round(y_mil * MIL, 4))


TWO_PIN_LIB = ("DEF T U 0 40 Y Y 1 F N\nF0 \"U\" 0 0 50 H V C CNN\nDRAW\n"
               "X TOP 1 0 200 100 D 50 50 1 1 P\nX BOT 2 0 -200 100 U 50 50 1 1 P\n"
               "X VCC 3 100 0 100 L 50 50 1 1 W N\nENDDRAW\nENDDEF\n")


class MatrixTest(unittest.TestCase):
    def test_two_pin_symbol_nets(self):
        body = (comp("t:T", "U1", 1000, 1000, "1    0    0    -1", ts="5F000001")
                + comp("t:T", "U2", 3000, 1000, "-1   0    0    1", ts="5F000002")
                + wire(1000, 800, 1000, 500) + wire(1000, 1200, 1000, 1500)
                + label(1000, 500, "NTOP1") + label(1000, 1500, "NBOT1")
                + wire(3000, 800, 3000, 500) + wire(3000, 1200, 3000, 1500)
                + label(3000, 500, "N2UP") + label(3000, 1500, "N2DOWN"))
        r = analyze(body, TWO_PIN_LIB)
        self.assertEqual(net_of(r, "U1", "1"), "NTOP1")
        self.assertEqual(net_of(r, "U1", "2"), "NBOT1")
        self.assertEqual(net_of(r, "U2", "1"), "N2DOWN")
        self.assertEqual(net_of(r, "U2", "2"), "N2UP")

    def test_off_axis_pin_for_each_matrix(self):
        lib = ("DEF P U 0 40 Y Y 1 F N\nF0 \"U\" 0 0 50 H V C CNN\nDRAW\n"
               "X A 1 100 200 100 D 50 50 1 1 P\nENDDRAW\nENDDEF\n")
        expected = {
            "1 0 0 -1": (1100, 800),
            "-1 0 0 -1": (900, 800),
            "-1 0 0 1": (900, 1200),
            "0 1 1 0": (1200, 1100),
        }
        for matrix, (ex, ey) in expected.items():
            with self.subTest(matrix=matrix):
                r = analyze(comp("p:P", "U1", 1000, 1000, matrix), lib)
                self.assertEqual(pin_xy(r, "U1", "1"), mm(ex, ey))

    def test_angle_and_mirror_fields(self):
        expected = {
            "1 0 0 -1": (0, False, False),
            "-1 0 0 1": (180, False, False),
            "-1 0 0 -1": (0, False, True),
            "1 0 0 1": (0, True, False),
        }
        for matrix, want in expected.items():
            with self.subTest(matrix=matrix):
                r = analyze(comp("t:T", "U1", 1000, 1000, matrix), TWO_PIN_LIB)
                c = r["components"][0]
                self.assertEqual((c["angle"], c["mirror_x"], c["mirror_y"]), want)

    def test_unit_two_with_negative_matrix(self):
        lib = ("DEF M U 0 40 Y Y 2 L N\nF0 \"U\" 0 0 50 H V C CNN\nDRAW\n"
               "X A 1 -200 100 100 R 50 50 1 1 I\nX B 2 -200 -100 100 R 50 50 1 1 O\n"
               "X C 3 300 150 100 L 50 50 2 1 I\nX D 4 300 -50 100 L 50 50 2 1 O\n"
               "ENDDRAW\nENDDEF\n")
        r = analyze(comp("m:M", "U3", 4000, 2000, "-1   0    0    1", unit=2), lib)
        c = r["components"][0]
        self.assertEqual(sorted(p["number"] for p in c["pins"]), ["3", "4"])
        self.assertEqual(pin_xy(r, "U3", "3"), mm(3700, 2150))
        self.assertEqual(pin_xy(r, "U3", "4"), mm(3700, 1950))


R_LIB = ("DEF Device_R R 0 0 N Y 1 F N\nF0 \"R\" 80 0 50 V V C CNN\nDRAW\n"
         "X ~ 1 0 150 50 D 50 50 1 1 P\nX ~ 2 0 -150 50 U 50 50 1 1 P\nENDDRAW\nENDDEF\n")
J_LIB = ("DEF J J 0 40 Y Y 1 F N\nF0 \"J\" 0 0 50 H V C CNN\nDRAW\n"
         "X P 1 0 0 0 R 50 50 1 1 P\nENDDRAW\nENDDEF\n")


class SnapTest(unittest.TestCase):
    def test_parsed_lib_pin_stays_on_its_no_connect(self):
        # R1 pin 1 at (2000,1850), pin 2 at (2000,2150) on a NoConn; a wire end 200 mil further out
        body = (comp("Device:R", "R1", 2000, 2000, "1    0    0    -1")
                + wire(2000, 1850, 2000, 1500) + label(2000, 1500, "TOP")
                + "NoConn ~ 2000 2150\n"
                + wire(2000, 2350, 2000, 2600) + label(2000, 2600, "FAR"))
        r = analyze(body, R_LIB)
        self.assertEqual(pin_xy(r, "R1", "2"), mm(2000, 2150))
        self.assertNotEqual(net_of(r, "R1", "2"), "FAR")
        self.assertEqual(net_of(r, "R1", "1"), "TOP")

    def test_builtin_pin_snaps_to_a_free_wire_end(self):
        # built-in R: pin 1 at (2000,1850), 20 mil (0.508 mm) short of the wire end at (2000,1830)
        body = (comp("Device:R", "R1", 2000, 2000, "1    0    0    -1")
                + wire(2000, 1830, 2000, 1500) + label(2000, 1500, "TOP")
                + wire(2000, 2150, 2000, 2400) + label(2000, 2400, "BOT"))
        r = analyze(body, J_LIB)
        self.assertEqual(pin_xy(r, "R1", "1"), mm(2000, 1830))
        self.assertEqual(net_of(r, "R1", "1"), "TOP")
        self.assertEqual(net_of(r, "R1", "2"), "BOT")

    def test_builtin_pin_does_not_take_a_parsed_lib_pins_wire_end(self):
        body = (comp("Device:R", "R1", 2000, 2000, "1    0    0    -1", ts="5F000001")
                + comp("j:J", "J1", 2000, 1830, "1    0    0    -1", ts="5F000002")
                + wire(2000, 1830, 2000, 1500) + label(2000, 1500, "TOP")
                + wire(2000, 2150, 2000, 2400) + label(2000, 2400, "BOT"))
        r = analyze(body, J_LIB)
        self.assertEqual(pin_xy(r, "R1", "1"), mm(2000, 1850))
        self.assertNotEqual(net_of(r, "R1", "1"), "TOP")
        self.assertEqual(net_of(r, "J1", "1"), "TOP")
        self.assertEqual(net_of(r, "R1", "2"), "BOT")

    def test_builtin_pin_does_not_take_another_builtin_pins_wire_end(self):
        # R1 pin 1 sits on the wire end (2000,1850); R2 (matrix 0 1 1 0) has pin 2 at
        # (2020,1850), 20 mil away, and must not snap onto R1's end
        body = (comp("Device:R", "R1", 2000, 2000, "1    0    0    -1", ts="5F000001")
                + comp("Device:R", "R2", 2170, 1850, "0    1    1    0", ts="5F000002")
                + wire(2000, 1850, 2000, 1500) + label(2000, 1500, "TOP")
                + wire(2000, 2150, 2000, 2400) + label(2000, 2400, "BOT"))
        r = analyze(body, J_LIB)
        self.assertEqual(pin_xy(r, "R1", "1"), mm(2000, 1850))
        self.assertEqual(net_of(r, "R1", "1"), "TOP")
        self.assertEqual(pin_xy(r, "R2", "2"), mm(2020, 1850))
        self.assertNotEqual(net_of(r, "R2", "2"), "TOP")

    def test_two_builtin_pins_want_one_free_end_the_nearer_takes_it(self):
        # end E (2000,1830): R1 pin 1 is 20 mil from it, R2 pin 2 (R2 listed first) 40 mil;
        # R2 pin 2 does not fall back to the held end at (1700,1830)
        body = (comp("Device:R", "R2", 2000, 1640, "1    0    0    -1", ts="5F000002")
                + comp("Device:R", "R1", 2000, 2000, "1    0    0    -1", ts="5F000001")
                + wire(2000, 1830, 1700, 1830) + label(1700, 1830, "TOP"))
        r = analyze(body, J_LIB)
        self.assertEqual(pin_xy(r, "R1", "1"), mm(2000, 1830))
        self.assertEqual(net_of(r, "R1", "1"), "TOP")
        self.assertEqual(pin_xy(r, "R2", "2"), mm(2000, 1790))
        self.assertNotEqual(net_of(r, "R2", "2"), "TOP")

    def test_the_losing_pin_does_not_fall_back_to_a_farther_free_end(self):
        # as above, but the wire's far end (1700,1830) is free: R2 pin 2 still stays put
        body = (comp("Device:R", "R2", 2000, 1640, "1    0    0    -1", ts="5F000002")
                + comp("Device:R", "R1", 2000, 2000, "1    0    0    -1", ts="5F000001")
                + wire(2000, 1830, 1700, 1830))
        r = analyze(body, J_LIB)
        self.assertEqual(pin_xy(r, "R1", "1"), mm(2000, 1830))
        self.assertEqual(pin_xy(r, "R2", "2"), mm(2000, 1790))
        self.assertNotEqual(net_of(r, "R2", "2"), net_of(r, "R1", "1"))

    def _held_end(self, holder):
        # built-in R1 pin 1 at (2000,1850), 20 mil short of the end (2000,1830) held by `holder`;
        # the wire's far end (2000,1500) is beyond the 12 mm snap radius
        body = (comp("Device:R", "R1", 2000, 2000, "1    0    0    -1", ts="5F000001")
                + wire(2000, 1830, 2000, 1500) + holder)
        r = analyze(body, J_LIB)
        self.assertEqual(pin_xy(r, "R1", "1"), mm(2000, 1850))

    def test_a_label_holds_an_end(self):
        self._held_end(label(2000, 1830, "TOP"))

    def test_a_power_symbol_holds_an_end(self):
        self._held_end(comp("power:+5V", "#PWR01", 2000, 1830, "1    0    0    -1", ts="5F000003"))

    def test_a_no_connect_holds_an_end(self):
        self._held_end("NoConn ~ 2000 1830\n")

    def test_builtin_components_are_counted(self):
        body = (comp("Device:R", "R1", 2000, 2000, "1    0    0    -1", ts="5F000001")
                + comp("j:J", "J1", 4000, 1830, "1    0    0    -1", ts="5F000002"))
        r = analyze(body, J_LIB)
        cov = r["legacy_analysis_quality"]["pin_source_coverage"]
        self.assertEqual(cov["builtin_fallback"], 1)
        self.assertEqual(cov["parsed_lib"], 1)


if __name__ == "__main__":
    unittest.main()
