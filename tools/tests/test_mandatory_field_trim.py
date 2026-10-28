"""Mandatory fields (Reference, Value, Footprint, Datasheet, Description, sheet name and file)
lose leading and trailing spaces as KiCad's SCH_FIELD::SetText strips them, "~" is still tested
on the raw token, user fields keep their spaces, the sheet-file property is read in any case,
and a KiCad 6 instance value reaches every instance of a repeated sheet.  Expected values are
kicad-cli 10.0.7 netlist / BOM exports and KiCad's source."""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT))

from schematic.hierarchy import parse_all_sheets  # noqa: E402
from tools.tests.test_symbol_instances import (  # noqa: E402
    ROOT_UUID, CHILD_UUID, analyze, sch, sheet, sym, u, write)
from tools.tests.test_legacy_hierarchy import analyze as analyze_legacy  # noqa: E402

INST = (f' (instances (project "t" (path "/{ROOT_UUID}" (reference "R1") (unit 1))))')


def parse(files, root):
    with tempfile.TemporaryDirectory() as tmp:
        write(tmp, files)
        with redirect_stderr(StringIO()):
            return parse_all_sheets(os.path.join(tmp, root))


def one(version, value="1k", ref="R1", fp="", ds="", extra=""):
    body = sym(u(10), ref, value, 50, fp=fp, ds=ds, inst=INST + extra)
    files = {"t.kicad_sch": sch(version, ROOT_UUID, body,
                                tail='(sheet_instances (path "/" (page "1")))')}
    return parse(files, "t.kicad_sch")["components"][0]


class ModernTrimTest(unittest.TestCase):
    def test_datasheet_space_tilde_is_tilde(self):
        self.assertEqual(one(20231120, ds=" ~")["datasheet"], "~")

    def test_datasheet_bare_tilde_is_empty(self):
        self.assertEqual(one(20231120, ds="~")["datasheet"], "")

    def test_value_footprint_reference_trimmed(self):
        c = one(20231120, value="10k ", ref=" R1", fp=" Resistor_SMD:R_0603 ")
        self.assertEqual((c["reference"], c["value"], c["footprint"]),
                         ("R1", "10k", "Resistor_SMD:R_0603"))

    def test_description_trimmed_and_user_field_kept(self):
        c = one(20231120, extra=' (property "Description" " Chip " (at 0 0 0))'
                                ' (property "MPN" " ABC " (at 0 0 0))')
        self.assertEqual(c["description"], "Chip")
        self.assertEqual(c["mpn"], " ABC ")

    def test_vertical_tab_and_form_feed_trimmed(self):
        # wxString::Strip trims every wxSafeIsspace character: space, \t \n \v \f \r
        c = one(20231120, value="\v10k\f", fp="\fResistor_SMD:R_0603\v")
        self.assertEqual((c["value"], c["footprint"]), ("10k", "Resistor_SMD:R_0603"))

    def test_new_format_tilde_is_literal(self):
        self.assertEqual(one(20250318, ds="~")["datasheet"], "~")
        self.assertEqual(one(20250318, ds=" ~ ")["datasheet"], "~")

    def test_tilde_datasheet_adds_no_finding(self):
        def rules(ds):
            body = sym(u(10), "R1", "1k", 50, ds=ds, inst=INST)
            files = {"t.kicad_sch": sch(20231120, ROOT_UUID, body,
                                        tail='(sheet_instances (path "/" (page "1")))')}
            return sorted(f["rule_id"] for f in analyze(files, "t.kicad_sch")["findings"])
        self.assertEqual(rules(" ~"), rules("~"))


class Kicad6Test(unittest.TestCase):
    def test_instance_value_trimmed(self):
        si = (f'(symbol_instances (path "/{u(10)}" (reference "R1") (unit 1) (value "5.1k ")'
              f' (footprint "")))')
        body = sym(u(10), "R1", "", 50)
        files = {"k.kicad_sch": sch(20211123, ROOT_UUID, body,
                                    tail=f'(sheet_instances (path "/" (page "1"))) {si}')}
        self.assertEqual(parse(files, "k.kicad_sch")["components"][0]["value"], "5.1k")

    def test_inline_instance_value_vertical_tab_trimmed(self):
        inst = (f' (instances (project "t" (path "/{ROOT_UUID}" (reference "R1") (unit 1)'
                f' (value "\v4.7k\f"))))')
        body = sym(u(10), "R1", "", 50, inst=inst)
        files = {"k.kicad_sch": sch(20211123, ROOT_UUID, body,
                                    tail='(sheet_instances (path "/" (page "1")))')}
        self.assertEqual(parse(files, "k.kicad_sch")["components"][0]["value"], "4.7k")

    def test_value_on_repeated_sheet_reaches_every_instance(self):
        a, b = u(170), u(180)
        si = (f'(symbol_instances (path "/{a}/{u(23)}" (reference "R10") (unit 1) (value "10k")'
              f' (footprint "")) (path "/{b}/{u(23)}" (reference "R11") (unit 1) (value "")'
              f' (footprint "")))')
        tail = (f'(sheet_instances (path "/" (page "1")) (path "/{a}" (page "2"))'
                f' (path "/{b}" (page "3"))) {si}')
        root = sheet(a, "child.kicad_sch", 100) + " " + sheet(b, "child.kicad_sch", 140)
        files = {"rep.kicad_sch": sch(20211123, ROOT_UUID, root, tail=tail),
                 "child.kicad_sch": sch(20211123, CHILD_UUID, sym(u(23), "R1", "", 50))}
        got = sorted((c["reference"], c["value"])
                     for c in parse(files, "rep.kicad_sch")["components"])
        self.assertEqual(got, [("R10", "10k"), ("R11", "10k")])


def sheet_files(name_prop, file_prop):
    root = (f'(sheet (at 100 80) (size 20 10) (uuid "{u(160)}") {name_prop} {file_prop})')
    child = sym(u(23), "R1", "1k", 50, inst=(
        f' (instances (project "t" (path "/{ROOT_UUID}/{u(160)}" (reference "R1") (unit 1))))'))
    return {"t.kicad_sch": sch(20231120, ROOT_UUID, root,
                               tail='(sheet_instances (path "/" (page "1")))'),
            "sub.kicad_sch": sch(20231120, CHILD_UUID, child)}


class SheetTest(unittest.TestCase):
    def refs(self, files):
        return [c["reference"] for c in parse(files, "t.kicad_sch")["components"]]

    def test_sheet_file_property_any_case(self):
        for prop in ("SheetFile", "sheet file", "SHEETFILE"):
            files = sheet_files('(property "Sheetname" "m" (at 0 0 0))',
                                f'(property "{prop}" "sub.kicad_sch" (at 0 0 0))')
            self.assertEqual(self.refs(files), ["R1"], prop)

    def test_sheet_file_trimmed(self):
        files = sheet_files('(property "Sheetname" "m" (at 0 0 0))',
                            '(property "Sheetfile" "sub.kicad_sch " (at 0 0 0))')
        self.assertEqual(self.refs(files), ["R1"])

    def test_sheet_name_trimmed(self):
        files = sheet_files('(property "Sheetname" "Modem " (at 0 0 0))',
                            '(property "Sheetfile" "sub.kicad_sch" (at 0 0 0))')
        files["sub.kicad_sch"] = files["sub.kicad_sch"].replace('"1k"', '"${SHEETNAME}"')
        self.assertEqual([c["value"] for c in parse(files, "t.kicad_sch")["components"]],
                         ["Modem"])


class LegacyTest(unittest.TestCase):
    def comp(self, f1, f3):
        return (f'$Comp\nL t:T R1\nU 1 1 5A000001\nP 1000 1000\n'
                f'F 0 "R1" H 1000 1000 50  0000 C CNN\nF 1 "{f1}" H 1000 1000 50  0000 C CNN\n'
                f'F 3 "{f3}" H 1000 1000 50  0001 C CNN\n'
                f'\t1    1000 1000\n\t1    0    0    -1\n$EndComp\n')

    def test_f_fields_trimmed_tilde_literal(self):
        res = analyze_legacy({"root.sch": self.comp("10k ", " ~")})
        c = res["components"][0]
        self.assertEqual((c["value"], c["datasheet"]), ("10k", "~"))

    def test_f_fields_vertical_tab_form_feed_trimmed(self):
        res = analyze_legacy({"root.sch": self.comp("\f10k\v", "\v~")})
        c = res["components"][0]
        self.assertEqual((c["value"], c["datasheet"]), ("10k", "~"))


if __name__ == "__main__":
    unittest.main()
