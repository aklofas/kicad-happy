"""The PWR_FLAG audit follows KiCad's ERC "power pin not driven" check: every net with a
power input pin and no power output or PWR_FLAG is reported, not only power-symbol rails.
A power input with a no-connect flag on it is not checked. A sub-sheet read on its own does
not report a net that leaves the sheet through a hierarchical or global label, since another
sheet can drive it, nor a net that a global power symbol or a hidden power input joins to other
sheets; a root file read with --no-hierarchy still reads all its sheets and stays strict."""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT))

from schematic.audits import audit_pwr_flags  # noqa: E402
from schematic.pipeline import analyze_schematic  # noqa: E402
from tools.tests.test_body_style_and_hidden_pins import net_of  # noqa: E402
from tools.tests.test_same_sheet_power_names import R_LIB, Sheet, power_lib  # noqa: E402


def pin(ref, number, pin_type, name="~"):
    return {"component": ref, "pin_number": number, "pin_name": name, "pin_type": pin_type}


def net(*pins, labels=(), no_connect=False, has_pwr_flag=False):
    return {"pins": list(pins), "labels": list(labels), "no_connect": no_connect,
            "has_pwr_flag": has_pwr_flag}


def part(ref, kind, *pins):
    """A component with (number, type, x, y[, name]) pins on sheet 0."""
    return {"reference": ref, "type": kind,
            "pins": [{"number": q[0], "type": q[1], "x": q[2], "y": q[3],
                      "name": q[4] if len(q) > 4 else "~"} for q in pins]}


def nc(x, y):
    return {"x": x, "y": y, "_sheet": 0}


def power_symbol(ref, scope="global"):
    return {"reference": ref, "type": "power_symbol", "_power_scope": scope}


def hier(name):
    return {"name": name, "type": "hierarchical_label"}


def warned(warnings):
    return [w["net"] for w in warnings]


class EveryNetTest(unittest.TestCase):
    def test_connector_fed_unnamed_net_warns_with_net_wording(self):
        nets = {"__unnamed_8": net(pin("J1", "1", "passive"), pin("BT1", "1", "power_in", "+"))}
        w = audit_pwr_flags([], nets, set())
        self.assertEqual(warned(w), ["__unnamed_8"])
        self.assertEqual(w[0]["message"], "Net '__unnamed_8' has power_in pins but no power_out"
                                          " or PWR_FLAG — ERC will flag this")
        self.assertEqual(w[0]["pin_types"], ["passive", "power_in"])

    def test_lone_pin_on_a_no_connect_net_does_not_warn(self):
        nets = {"__unnamed_8": net(pin("BT1", "1", "power_in"), no_connect=True)}
        self.assertEqual(audit_pwr_flags([], nets, set()), [])

    def test_other_net_flagged_no_connect_is_not_reported(self):
        nets = {"VAUX": net(pin("U1", "4", "power_in", "VAUX"), pin("C1", "1", "passive"),
                            no_connect=True)}
        self.assertEqual(audit_pwr_flags([], nets, set()), [])

    def test_power_input_with_a_no_connect_flag_on_it_is_not_checked(self):
        parts = [part("#PWR01", "power_symbol", ("1", "power_in", 10, 10)),
                 part("U1", "ic", ("4", "power_in", 20, 10)), part("C1", "capacitor")]
        nets = {"+3V3": net(pin("#PWR01", "1", "power_in"), pin("C1", "1", "passive"),
                            no_connect=True)}
        self.assertEqual(audit_pwr_flags(parts, nets, {"+3V3"}, no_connects=[nc(10, 10)]), [])

    def test_other_power_inputs_on_the_net_are_still_checked(self):
        # kicad-cli 10.0.8 reports a rail whose only flagged pin is one power symbol's.
        parts = [part("#PWR01", "power_symbol", ("1", "power_in", 10, 10)),
                 part("U1", "ic", ("4", "power_in", 20, 10))]
        nets = {"+3V3": net(pin("#PWR01", "1", "power_in"), pin("U1", "4", "power_in", "VDD"),
                            no_connect=True)}
        w = audit_pwr_flags(parts, nets, {"+3V3"}, no_connects=[nc(10, 10)])
        self.assertEqual(warned(w), ["+3V3"])

    def test_pins_without_numbers_are_told_apart_by_name(self):
        # Two power inputs with an empty pin number: the flag on one does not hide the other.
        parts = [part("U14", "ic", ("", "power_in", 10, 10, "RD+"), ("", "power_in", 20, 10, "GLV+"))]
        nets = {"GLV+": net(pin("U14", "", "power_in", "GLV+")),
                "RD+": net(pin("U14", "", "power_in", "RD+"))}
        w = audit_pwr_flags(parts, nets, set(), no_connects=[nc(10, 10)])
        self.assertEqual(warned(w), ["GLV+"])

    def test_power_symbol_rail_keeps_its_wording(self):
        nets = {"+3V3": net(pin("#PWR01", "1", "power_in"), pin("U1", "4", "power_in", "VDD"))}
        w = audit_pwr_flags([], nets, {"+3V3"})
        self.assertEqual(w, [{"net": "+3V3",
                              "message": "Power rail '+3V3' has power_in pins but no power_out"
                                         " or PWR_FLAG — ERC will flag this",
                              "pin_types": ["power_in"]}])

    def test_power_symbol_with_another_reference_prefix_is_a_rail(self):
        nets = {"GND": net(pin("#GND01", "1", "power_in"), pin("U1", "5", "power_in", "VSS"))}
        w = audit_pwr_flags([power_symbol("#GND01")], nets, set())
        self.assertTrue(w[0]["message"].startswith("Power rail 'GND'"), w)

    def test_driven_and_flagged_nets_do_not_warn(self):
        nets = {"VOUT": net(pin("U2", "2", "power_out"), pin("U1", "4", "power_in")),
                "VIN": net(pin("U2", "1", "power_in"), has_pwr_flag=True),
                "SIG": net(pin("U1", "5", "input"), pin("U2", "3", "output"))}
        self.assertEqual(audit_pwr_flags([], nets, set()), [])

    def test_output_is_sorted_by_net_name(self):
        nets = {"VBAT": net(pin("U1", "1", "power_in")),
                "+5V": net(pin("#PWR02", "1", "power_in"), pin("U1", "2", "power_in")),
                "AVDD": net(pin("U1", "3", "power_in"))}
        self.assertEqual(warned(audit_pwr_flags([], nets, {"+5V"})), ["+5V", "AVDD", "VBAT"])


# A KiCad 5 root: U1's power input VCC on a label, with no driver and no PWR_FLAG.
LEGACY_HEAD = ("EESchema Schematic File Version 4\nEELAYER 30 0\nEELAYER END\n"
               "$Descr A4 11693 8268\n$EndDescr\n")
LEGACY_LIB = ("EESchema-LIBRARY Version 2.4\n#encoding utf-8\n"
              "DEF LOAD U 0 40 Y Y 1 F N\nF0 \"U\" 0 0 50 H V C CNN\nDRAW\n"
              "X VCC 1 0 200 100 D 50 50 1 1 W\nX A 2 0 -200 100 U 50 50 1 1 P\n"
              "ENDDRAW\nENDDEF\n#\n#End Library\n")
LEGACY_BODY = ("$Comp\nL t:LOAD U1\nU 1 1 5A000001\nP 1000 1000\n"
               'F 0 "U1" H 1000 1000 50  0000 C CNN\nF 1 "LOAD" H 1000 1000 50  0000 C CNN\n'
               "\t1    1000 1000\n\t1    0    0    -1\n$EndComp\n"
               "Text Label 1000 800 0    50   ~ 0\nVCC\n")
VOLATILE = ("inputs", "run_id", "elapsed_s", "timings", "total_elapsed_s")


class LegacyRootTest(unittest.TestCase):
    def test_no_hierarchy_leaves_a_legacy_root_unchanged(self):
        # The KiCad 5 reader has no PWR_FLAG audit: the read with --no-hierarchy is the same
        # as without it, and neither carries pwr_flag_warnings.
        with tempfile.TemporaryDirectory() as tmp:
            sch = os.path.join(tmp, "board.sch")
            with open(sch, "w", encoding="utf-8", newline="\n") as f:
                f.write(LEGACY_HEAD + LEGACY_BODY + "$EndSCHEMATC\n")
            with open(os.path.join(tmp, "board-cache.lib"), "w", encoding="utf-8", newline="\n") as f:
                f.write(LEGACY_LIB)
            with redirect_stderr(StringIO()):
                plain = analyze_schematic(sch)
                flat = analyze_schematic(sch, no_hierarchy=True)
        self.assertEqual(net_of(flat, "U1", "1"), "VCC")
        self.assertNotIn("pwr_flag_warnings", flat)
        self.assertEqual({k: v for k, v in flat.items() if k not in VOLATILE},
                         {k: v for k, v in plain.items() if k not in VOLATILE})


class StandaloneSheetTest(unittest.TestCase):
    NETS = {"VBUS": net(pin("U1", "1", "power_in", "VCC"), labels=[hier("VBUS")]),
            "VIO": net(pin("U1", "2", "power_in", "VIO"),
                       labels=[{"name": "VIO", "type": "global_label"}]),
            "__unnamed_0": net(pin("U1", "3", "power_in", "VDDA"))}

    def test_sub_sheet_read_alone_skips_nets_that_leave_the_sheet(self):
        w = audit_pwr_flags([], self.NETS, set(), standalone_sheet=True)
        self.assertEqual(warned(w), ["__unnamed_0"])

    def test_root_file_reports_labelled_nets(self):
        w = audit_pwr_flags([], self.NETS, set())
        self.assertEqual(warned(w), ["VBUS", "VIO", "__unnamed_0"])

    def test_local_label_does_not_leave_the_sheet(self):
        nets = {"VBUS": net(pin("U1", "1", "power_in"), labels=[{"name": "VBUS", "type": "label"}])}
        self.assertEqual(warned(audit_pwr_flags([], nets, set(), standalone_sheet=True)), ["VBUS"])


class StandaloneSheetRailTest(unittest.TestCase):
    def test_sub_sheet_read_alone_skips_global_power_rails(self):
        nets = {"+3V3": net(pin("#PWR01", "1", "power_in"), pin("U1", "4", "power_in", "VDD")),
                "GND": net(pin("#GND01", "1", "power_in"), pin("U1", "5", "power_in", "VSS"))}
        parts = [power_symbol("#PWR01"), power_symbol("#GND01")]
        self.assertEqual(audit_pwr_flags(parts, nets, {"+3V3"}, standalone_sheet=True), [])
        self.assertEqual(warned(audit_pwr_flags(parts, nets, {"+3V3"})), ["+3V3", "GND"])

    def test_hidden_power_input_joins_other_sheets(self):
        # KiCad joins a hidden power-input pin to every same-name net (a global power pin).
        nets = {"GND": net(pin("D11", "10", "power_in", "GND"),
                           labels=[{"name": "GND", "type": "label"}])}
        parts = [{"reference": "D11", "type": "ic",
                  "pins": [{"number": "10", "name": "GND", "type": "power_in", "hidden": True,
                            "x": 0, "y": 0}]}]
        self.assertEqual(audit_pwr_flags(parts, nets, set(), standalone_sheet=True), [])
        self.assertEqual(warned(audit_pwr_flags(parts, nets, set())), ["GND"])
        parts[0]["pins"][0].pop("hidden")
        self.assertEqual(warned(audit_pwr_flags(parts, nets, set(), standalone_sheet=True)), ["GND"])

    def test_local_power_symbol_rail_still_warns(self):
        nets = {"VLOC": net(pin("#PWR03", "1", "power_in"), pin("U1", "4", "power_in", "VDD"))}
        w = audit_pwr_flags([power_symbol("#PWR03", "local")], nets, {"VLOC"}, standalone_sheet=True)
        self.assertEqual(warned(w), ["VLOC"])
        self.assertTrue(w[0]["message"].startswith("Power rail 'VLOC'"))


# U: pin 1 a visible power input VCC at (0, -5.08) from the anchor, pin 2 passive A at (-5.08, 0).
U_LIB = ('(symbol "t:U" (in_bom yes) (on_board yes)'
         ' (property "Reference" "U" (at 0 0 0)) (property "Value" "U" (at 0 0 0))'
         ' (symbol "U_1_1"'
         ' (pin power_in line (at 0 5.08 270) (length 0) (name "VCC") (number "1"))'
         ' (pin passive line (at -5.08 0 0) (length 0) (name "A") (number "2"))))')


def sheet_text():
    """U1.VCC on a hierarchical label VBUS, U2.VCC on a +3V3 power symbol, U3.VCC on a wire
    with no label, U4.VCC wired to R1 with a no-connect flag on U4.VCC."""
    s = Sheet(20250114)
    s.symbol("t:U", "U1", "U", 50, 50, ("1", "2"))
    s.wire(50, 44.92, 50, 40); s.label("hierarchical_label", "VBUS", 50, 40)
    s.symbol("t:U", "U2", "U", 80, 50, ("1", "2"))
    s.wire(80, 44.92, 80, 40); s.symbol("power:+3V3", "#PWR01", "+3V3", 80, 40, ("1",))
    s.symbol("t:U", "U3", "U", 110, 50, ("1", "2"))
    s.wire(110, 44.92, 110, 40)
    s.symbol("t:U", "U4", "U", 140, 50, ("1", "2"))
    s.r("R1", 160, 40); s.wire(140, 44.92, 140, 40); s.wire(140, 40, 160, 40)
    s.items.append('(no_connect (at 140 44.92) (uuid "00000000-0000-0000-0000-0000000000dd"))')
    return s.text([U_LIB, R_LIB, power_lib("power:+3V3", "+3V3")], root=False)


def analyze(as_root):
    """Analyze the sheet with --no-hierarchy; a .kicad_pro of the same name makes it a root."""
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "t.kicad_sch"), "w", encoding="utf-8") as f:
            f.write(sheet_text())
        if as_root:
            with open(os.path.join(tmp, "t.kicad_pro"), "w", encoding="utf-8") as f:
                f.write('{"meta":{"filename":"t.kicad_pro","version":1}}')
        with redirect_stderr(StringIO()):
            return analyze_schematic(os.path.join(tmp, "t.kicad_sch"), no_hierarchy=True)


class NoHierarchyReadTest(unittest.TestCase):
    def test_root_file_read_with_no_hierarchy_keeps_every_warning(self):
        r = analyze(as_root=True)
        self.assertIsNone(r.get("hierarchy_warning"))
        unnamed = net_of(r, "U3", "1")
        self.assertEqual(net_of(r, "U4", "1"), net_of(r, "R1", "1"))
        self.assertEqual(warned(r["pwr_flag_warnings"]), sorted(["+3V3", "VBUS", unnamed]))
        msgs = {w["net"]: w["message"] for w in r["pwr_flag_warnings"]}
        self.assertTrue(msgs["+3V3"].startswith("Power rail '+3V3'"))
        self.assertTrue(msgs["VBUS"].startswith("Net 'VBUS'"))

    def test_sub_sheet_read_alone_skips_its_labelled_net(self):
        r = analyze(as_root=False)
        self.assertIsNotNone(r.get("hierarchy_warning"))
        self.assertEqual(net_of(r, "U1", "1"), "VBUS")
        self.assertNotIn("VBUS", warned(r["pwr_flag_warnings"]))
        self.assertIn(net_of(r, "U3", "1"), warned(r["pwr_flag_warnings"]))

    def test_sub_sheet_read_alone_skips_its_power_symbol_rail(self):
        r = analyze(as_root=False)
        self.assertEqual(net_of(r, "U2", "1"), "+3V3")
        self.assertEqual(warned(r["pwr_flag_warnings"]), [net_of(r, "U3", "1")])


if __name__ == "__main__":
    unittest.main()
