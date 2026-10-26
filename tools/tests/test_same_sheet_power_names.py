"""Which nets carry which name, as kicad-cli 10.0.6 exports them: a local label joins the
same-name global label or power symbol on its own sheet, and in files older than 20230221 a
power symbol whose first pin is a hidden power input is named after that pin."""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT))

from schematic.pipeline import analyze_schematic  # noqa: E402
from tools.tests.test_body_style_and_hidden_pins import analyze, comp, net_of, wire  # noqa: E402

ROOT_UUID = "00000000-0000-0000-0000-0000000000aa"
CHILD_SHEET_UUID = "00000000-0000-0000-0000-0000000000bb"
CHILD_FILE_UUID = "00000000-0000-0000-0000-0000000000cc"
_n = [0]


def _uuid():
    _n[0] += 1
    return f"00000000-0000-0000-0000-{_n[0]:012d}"


R_LIB = ('(symbol "Device:R" (in_bom yes) (on_board yes)'
         ' (property "Reference" "R" (at 0 0 0)) (property "Value" "R" (at 0 0 0))'
         ' (symbol "R_1_1"'
         ' (pin passive line (at 0 3.81 270) (length 1.27) (name "~") (number "1"))'
         ' (pin passive line (at 0 -3.81 90) (length 1.27) (name "~") (number "2"))))')


def power_lib(name, pin_name, hidden=True):
    """A global power symbol; its one power-in pin sits on the placement point."""
    short = name.split(":")[-1]
    return (f'(symbol "{name}" (power) (in_bom yes) (on_board yes)'
            f' (property "Reference" "#PWR" (at 0 0 0)) (property "Value" "{short}" (at 0 0 0))'
            f' (symbol "{short}_1_1" (pin power_in line (at 0 0 90) (length 0)'
            f'{" hide" if hidden else ""} (name "{pin_name}") (number "1"))))')


# U: pin 1 passive at (-5.08, 0); pin 2 a hidden power input "VCC" at (0, 5.08)
U_LIB = ('(symbol "t:U" (in_bom yes) (on_board yes)'
         ' (property "Reference" "U" (at 0 0 0)) (property "Value" "U" (at 0 0 0))'
         ' (symbol "U_1_1"'
         ' (pin passive line (at -5.08 0 0) (length 0) (name "A") (number "1"))'
         ' (pin power_in line (at 0 5.08 270) (length 0) hide (name "VCC") (number "2"))))')


class Sheet:
    def __init__(self, version, path=f"/{ROOT_UUID}"):
        self.version, self.path, self.items, self.instances = version, path, [], []

    def symbol(self, lib_id, ref, value, x, y, pins, lib_name=None):
        u = _uuid()
        inst = ""
        if self.version < 20221002:
            self.instances.append(f'(path "{self.path}/{u}" (reference "{ref}") (unit 1)'
                                  f' (value "{value}") (footprint ""))')
        else:
            inst = (f' (instances (project "t" (path "{self.path}" (reference "{ref}")'
                    f' (unit 1))))')
        ln = f' (lib_name "{lib_name}")' if lib_name else ""
        pl = " ".join(f'(pin "{p}" (uuid "{_uuid()}"))' for p in pins)
        self.items.append(
            f'(symbol{ln} (lib_id "{lib_id}") (at {x} {y} 0) (unit 1) (in_bom yes) (on_board yes)'
            f' (uuid "{u}") (property "Reference" "{ref}" (at {x} {y} 0))'
            f' (property "Value" "{value}" (at {x} {y} 0)) {pl}{inst})')

    def r(self, ref, x, y_pin1):
        """Resistor whose pin 1 is at (x, y_pin1)."""
        self.symbol("Device:R", ref, "1k", x, round(y_pin1 + 3.81, 2), ("1", "2"))

    def wire(self, x1, y1, x2, y2, kind="wire"):
        self.items.append(f'({kind} (pts (xy {x1} {y1}) (xy {x2} {y2})) (uuid "{_uuid()}"))')

    def label(self, kind, name, x, y):
        shape = " (shape input)" if kind != "label" else ""
        self.items.append(f'({kind} "{name}"{shape} (at {x} {y} 0) (uuid "{_uuid()}"))')

    def text(self, libs, uuid=ROOT_UUID, root=True, extra=""):
        tail = ""
        if root:
            tail = '(sheet_instances (path "/" (page "1")))'
            if self.instances:
                tail += f' (symbol_instances {" ".join(self.instances)})'
        return (f'(kicad_sch (version {self.version}) (generator "eeschema") (uuid "{uuid}")'
                f' (paper "A4") (lib_symbols {" ".join(libs)}) {" ".join(self.items)} {extra}'
                f' {tail})\n')


def sheet_block(name, fname, x, y, pins):
    pl = " ".join(f'(pin "{p}" bidirectional (at {px} {py} 180) (uuid "{_uuid()}"))'
                  for p, px, py in pins)
    return (f'(sheet (at {x} {y}) (size 30 30) (uuid "{CHILD_SHEET_UUID}")'
            f' (property "Sheetname" "{name}" (at {x} {y} 0))'
            f' (property "Sheetfile" "{fname}" (at {x} {y} 0)) {pl}'
            f' (instances (project "t" (path "/{ROOT_UUID}" (page "2")))))')


def run(files):
    """Write the project, analyze t.kicad_sch, return the result."""
    with tempfile.TemporaryDirectory() as tmp:
        for name, txt in files.items():
            with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
                f.write(txt)
        with open(os.path.join(tmp, "t.kicad_pro"), "w", encoding="utf-8") as f:
            f.write('{"meta":{"filename":"t.kicad_pro","version":1}}')
        with redirect_stderr(StringIO()):
            return analyze_schematic(os.path.join(tmp, "t.kicad_sch"))


def members(result, name):
    return sorted(f'{p["component"]}.{p["pin_number"]}' for p in result["nets"][name]["pins"]
                  if not p["component"].startswith("#"))


# --- fixtures (each one's kicad-cli 10.0.6 netlist is quoted in the test that uses it) -------

def f1_files():
    """Local VCC + power VCC, local SIG + global SIG, global SIG2 on one sheet."""
    s = Sheet(20250114)
    s.r("R1", 50, 50); s.wire(50, 50, 50, 40); s.label("label", "VCC", 50, 45)
    s.r("R2", 80, 50); s.wire(80, 50, 80, 40); s.label("global_label", "SIG2", 80, 45)
    s.r("R3", 110, 50); s.wire(110, 50, 110, 40)
    s.symbol("power:VCC", "#PWR1", "VCC", 110, 40, ("1",))
    s.r("R4", 50, 100); s.wire(50, 100, 50, 90); s.label("label", "SIG", 50, 95)
    s.r("R5", 80, 100); s.wire(80, 100, 80, 90); s.label("global_label", "SIG", 80, 95)
    return {"t.kicad_sch": s.text([R_LIB, power_lib("power:VCC", "VCC")])}


def case_c_files():
    """Root: local bus B[0..1] into a sheet pin, global B0, local B1. Child: hier bus P[0..1]
    tapped into labels P0 (R11) and P1 (R12)."""
    root = Sheet(20250114)
    root.wire(100, 50, 150, 50, "bus"); root.label("label", "B[0..1]", 105, 50)
    root.r("R1", 50, 100); root.wire(50, 100, 50, 90); root.label("global_label", "B0", 50, 95)
    root.r("R2", 70, 100); root.wire(70, 100, 70, 90); root.label("label", "B1", 70, 95)
    child = Sheet(20250114, path=f"/{ROOT_UUID}/{CHILD_SHEET_UUID}")
    child.wire(50, 50, 100, 50, "bus")
    child.label("hierarchical_label", "P[0..1]", 50, 50)
    for x, lab, ref in ((55, "P0", "R11"), (65, "P1", "R12")):
        x2, y2 = round(x + 2.54, 2), 52.54
        child.items.append(f'(bus_entry (at {x} 50) (size 2.54 2.54) (uuid "{_uuid()}"))')
        child.wire(x2, y2, x2, y2 + 10)
        child.label("label", lab, x2, y2 + 5)
        child.r(ref, x2, y2 + 10)
    return {"t.kicad_sch": root.text([R_LIB], extra=sheet_block(
                "child", "child.kicad_sch", 150, 40, [("P[0..1]", 150, 50)])),
            "child.kicad_sch": child.text([R_LIB], uuid=CHILD_FILE_UUID, root=False)}


def isolation_files():
    """Local VCC on the child sheet, power VCC and global VCC on the root: no same-sheet pair."""
    root = Sheet(20250114)
    root.r("R1", 50, 50); root.wire(50, 50, 50, 40)
    root.symbol("power:VCC", "#PWR1", "VCC", 50, 40, ("1",))
    root.r("R2", 80, 50); root.wire(80, 50, 80, 40); root.label("global_label", "SIG", 80, 45)
    child = Sheet(20250114, path=f"/{ROOT_UUID}/{CHILD_SHEET_UUID}")
    child.r("R11", 50, 50); child.wire(50, 50, 50, 40); child.label("label", "VCC", 50, 45)
    child.r("R12", 80, 50); child.wire(80, 50, 80, 40); child.label("label", "SIG", 80, 45)
    return {"t.kicad_sch": root.text([R_LIB, power_lib("power:VCC", "VCC")],
                                     extra=sheet_block("child", "child.kicad_sch", 150, 40, [])),
            "child.kicad_sch": child.text([R_LIB, power_lib("power:VCC", "VCC")],
                                          uuid=CHILD_FILE_UUID, root=False)}


def power_files(version, value, pin_name, hidden=True):
    """R1 pin 1 on a power:+3.3V symbol showing `value` whose one pin is named `pin_name`."""
    s = Sheet(version)
    s.r("R1", 50, 50); s.wire(50, 50, 50, 40)
    s.symbol("power:+3.3V", "#PWR1", value, 50, 40, ("1",))
    return {"t.kicad_sch": s.text([R_LIB, power_lib("power:+3.3V", pin_name, hidden)])}


def legacy_power_files():
    """KiCad's qa legacy_power construct (20211123): a power:+3.3V placement whose cached lib
    symbol +3.3V_1 has a hidden power pin VCC drives U1.1; U1's hidden power pin 2 is VCC; a
    second, plain power:+3.3V drives R1.1."""
    s = Sheet(20211123)
    s.symbol("t:U", "U1", "U", 100, 100, ("1", "2"))
    s.wire(94.92, 100, 90, 100); s.wire(90, 100, 90, 90)
    s.symbol("power:+3.3V", "#PWR1", "+3.3V", 90, 90, ("1",), lib_name="+3.3V_1")
    s.r("R1", 50, 50); s.wire(50, 50, 50, 40)
    s.symbol("power:+3.3V", "#PWR2", "+3.3V", 50, 40, ("1",))
    return {"t.kicad_sch": s.text([R_LIB, U_LIB, power_lib("+3.3V_1", "VCC"),
                                   power_lib("power:+3.3V", "+3.3V")])}


class SameSheetJoinTest(unittest.TestCase):
    def test_local_label_joins_power_symbol_and_global_label_on_its_sheet(self):
        # kicad-cli: VCC = R1.1 R3.1; SIG = R4.1 R5.1; SIG2 = R2.1
        r = run(f1_files())
        self.assertEqual(members(r, "VCC"), ["R1.1", "R3.1"])
        self.assertEqual(members(r, "SIG"), ["R4.1", "R5.1"])
        self.assertEqual(members(r, "SIG2"), ["R2.1"])

    def test_bus_member_joins_same_sheet_global_label(self):
        # kicad-cli: B0 = R1.1 R11.1; /B1 = R2.1 R12.1
        r = run(case_c_files())
        self.assertEqual(net_of(r, "R1", "1"), net_of(r, "R11", "1"))
        self.assertEqual(net_of(r, "R1", "1"), "B0")
        self.assertEqual(members(r, "B0"), ["R1.1", "R11.1"])
        self.assertEqual(net_of(r, "R2", "1"), net_of(r, "R12", "1"))

    def test_local_label_on_another_sheet_stays_apart(self):
        # kicad-cli: VCC = R1.1; SIG = R2.1; /child/VCC = R11.1; /child/SIG = R12.1
        r = run(isolation_files())
        for ref_a, ref_b in (("R1", "R11"), ("R2", "R12")):
            self.assertIsNotNone(net_of(r, ref_b, "1"))
            self.assertNotEqual(net_of(r, ref_a, "1"), net_of(r, ref_b, "1"))
        self.assertEqual(members(r, "VCC"), ["R1.1"])
        self.assertEqual(members(r, "SIG"), ["R2.1"])


class LegacyPowerSymbolNameTest(unittest.TestCase):
    def test_qa_legacy_power(self):
        # kicad-cli: VCC = U1.1 U1.2; +3.3V = R1.1
        r = run(legacy_power_files())
        self.assertEqual(members(r, "VCC"), ["U1.1", "U1.2"])
        self.assertEqual(members(r, "+3.3V"), ["R1.1"])

    def test_pre_20230221_hidden_pin_names_the_net(self):
        # kicad-cli: +3V3 = R1.1
        r = run(power_files(20211123, "+3.3V", "+3V3"))
        self.assertEqual(net_of(r, "R1", "1"), "+3V3")
        self.assertNotIn("+3.3V", r["nets"])
        self.assertEqual([p["net_name"] for p in r["power_symbols"]], ["+3V3"])
        self.assertEqual([p["name"] for p in r["statistics"]["power_rails"]], ["+3V3"])

    def test_20230221_keeps_the_value(self):
        # kicad-cli: +3.3V = R1.1
        r = run(power_files(20230221, "+3.3V", "+3V3"))
        self.assertEqual(net_of(r, "R1", "1"), "+3.3V")

    def test_visible_power_pin_keeps_the_value(self):
        # kicad-cli: +3.3V = R1.1 (KiCad 10 renames only a hidden first pin)
        r = run(power_files(20211123, "+3.3V", "+3V3", hidden=False))
        self.assertEqual(net_of(r, "R1", "1"), "+3.3V")


# KiCad 5 cache library: T_T with a hidden VCC power input; power symbols with a hidden or a
# visible power-in pin named VCC
T_LIB = ("DEF T_T U 0 40 Y Y 1 F N\nF0 \"U\" 0 0 50 H V C CNN\nDRAW\n"
         "X TOP 1 0 200 100 D 50 50 1 1 P\nX BOT 2 0 -200 100 U 50 50 1 1 P\n"
         "X VCC 3 100 0 100 L 50 50 1 1 W N\nENDDRAW\nENDDEF\n"
         "#\nDEF power_VCC #PWR 0 0 Y Y 1 F P\nF0 \"#PWR\" 0 -150 50 H I C CNN\nDRAW\n"
         "X VCC 1 0 0 0 U 50 50 1 1 W N\nENDDRAW\nENDDEF\n"
         "#\nDEF power_VIS #PWR 0 0 Y Y 1 F P\nF0 \"#PWR\" 0 -150 50 H I C CNN\nDRAW\n"
         "X VCC 1 0 0 0 U 50 50 1 1 W\nENDDRAW\nENDDEF\n")


class KiCad5PowerSymbolNameTest(unittest.TestCase):
    def test_hidden_pin_names_the_net(self):
        body = (comp("power:VCC", "#PWR01", 6000, 3000, ts="5F000003", value="+3V3")
                + comp("t:T", "U2", 6000, 2800, ts="5F000002") + wire(6000, 3000, 6000, 2800))
        r = analyze(body, T_LIB)
        self.assertEqual(net_of(r, "U2", "2"), "VCC")
        self.assertEqual(net_of(r, "U2", "3"), "VCC")
        self.assertEqual([p["net_name"] for p in r["power_symbols"]], ["VCC"])

    def test_visible_pin_keeps_the_value(self):
        body = (comp("power:VIS", "#PWR01", 6000, 3000, ts="5F000003", value="+3V3")
                + comp("t:T", "U2", 6000, 2800, ts="5F000002") + wire(6000, 3000, 6000, 2800))
        r = analyze(body, T_LIB)
        self.assertEqual(net_of(r, "U2", "2"), "+3V3")
        self.assertNotEqual(net_of(r, "U2", "3"), "+3V3")
        self.assertEqual([p["net_name"] for p in r["power_symbols"]], ["+3V3"])


if __name__ == "__main__":
    unittest.main()
