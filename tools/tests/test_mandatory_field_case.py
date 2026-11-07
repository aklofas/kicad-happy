"""Value, Footprint, Datasheet and Description are read as KiCad 10 reads them: the name matches
in any case and a later duplicate replaces the earlier one.  Reference keeps its exact name and
its first entry, so a lower-case "reference" stays a user field.  A KiCad 6 instance value or
footprint of only spaces sets the field empty.  Expected values are kicad-cli 10.0.8 netlist
exports and KiCad's source (sch_io_kicad_sexpr_parser.cpp, sch_sheet_path.cpp)."""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT))

from kicad_core.sexp import parse as parse_sexp  # noqa: E402
from schematic.hierarchy import parse_all_sheets  # noqa: E402
from schematic.reader import _symbol_fields  # noqa: E402
from tools.tests.test_symbol_instances import (  # noqa: E402
    ROOT_UUID, CHILD_UUID, sch, sheet, sym, u, write)

INST = f' (instances (project "t" (path "/{ROOT_UUID}" (reference "R1") (unit 1))))'


def parse(files, root):
    with tempfile.TemporaryDirectory() as tmp:
        write(tmp, files)
        with redirect_stderr(StringIO()):
            return parse_all_sheets(os.path.join(tmp, root))


def prop(name, text):
    return f' (property "{name}" "{text}" (at 0 0 0))'


def one(extra, value="1k", version=20231120, ds=""):
    body = sym(u(10), "R1", value, 50, ds=ds, inst=extra + INST)
    files = {"t.kicad_sch": sch(version, ROOT_UUID, body,
                                tail='(sheet_instances (path "/" (page "1")))')}
    return parse(files, "t.kicad_sch")["components"][0]


class PlacedFieldCaseTest(unittest.TestCase):
    def test_later_upper_case_value_replaces_value(self):
        # esp32-ble-gamepad S1: Value "Left" then VALUE "430173003816"; kicad-cli gives the part number
        self.assertEqual(one(prop("VALUE", "430173003816"), value="Left")["value"],
                         "430173003816")

    def test_later_empty_value_empties_value(self):
        # Arty100T C12: Value "100nF" then VALUE ""; kicad-cli writes "~" (empty)
        self.assertEqual(one(prop("VALUE", ""), value="100nF")["value"], "")

    def test_later_datasheet_duplicate_wins(self):
        c = one(prop("datasheet", "https://x/b.pdf"), ds="https://x/a.pdf")
        self.assertEqual(c["datasheet"], "https://x/b.pdf")

    def test_lower_case_footprint_and_description(self):
        c = one(prop("footprint", "Resistor_SMD:R_0603") + prop("DESCRIPTION", " Chip "))
        self.assertEqual((c["footprint"], c["description"]), ("Resistor_SMD:R_0603", "Chip"))

    def test_reference_keeps_exact_name_and_first_entry(self):
        c = one(prop("reference", "D601") + prop("Reference", "R9"))
        self.assertEqual(c["reference"], "R1")

    def test_tilde_case_variant_is_empty_in_old_files(self):
        self.assertEqual(one(prop("DATASHEET", "~"), ds="https://x/a.pdf")["datasheet"], "")

    def test_symbol_without_value_takes_lib_value_any_case(self):
        lib = ('(symbol "Device:R" (in_bom yes) (on_board yes)'
               ' (property "Reference" "R" (at 0 0 0)) (property "VALUE" "LibVal" (at 0 0 0))'
               ' (symbol "R_1_1" (pin passive line (at 0 3.81 270) (length 1.27) (name "~")'
               ' (number "1"))))')
        body = (f'(symbol (lib_id "Device:R") (at 50 50 0) (unit 1) (in_bom yes) (on_board yes)'
                f' (uuid "{u(10)}") (property "Reference" "R1" (at 0 0 0)) {INST})')
        files = {"t.kicad_sch": sch(20231120, ROOT_UUID, body, libs=(lib,),
                                    tail='(sheet_instances (path "/" (page "1")))')}
        self.assertEqual(parse(files, "t.kicad_sch")["components"][0]["value"], "LibVal")


class SymbolFieldListTest(unittest.TestCase):
    def test_case_variant_merges_onto_mandatory_name(self):
        node = parse_sexp('(symbol (property "Reference" "R1") (property "reference" "X")'
                          ' (property "Datasheet" "a") (property "DATASHEET" "b")'
                          ' (property "MPN" "P1"))')
        fields = _symbol_fields(node, "1k", "fp", False)
        self.assertEqual(fields, [("Reference", "R1"), ("Value", "1k"), ("Footprint", "fp"),
                                  ("Datasheet", "b"), ("Description", ""),
                                  ("reference", "X"), ("MPN", "P1")])


class Kicad6SpaceValueTest(unittest.TestCase):
    def test_instance_value_of_spaces_empties_value(self):
        si = (f'(symbol_instances (path "/{u(10)}" (reference "R1") (unit 1) (value " ")'
              f' (footprint " ")))')
        body = sym(u(10), "R1", "1k", 50, fp="Resistor_SMD:R_0603")
        files = {"k.kicad_sch": sch(20211123, ROOT_UUID, body,
                                    tail=f'(sheet_instances (path "/" (page "1"))) {si}')}
        c = parse(files, "k.kicad_sch")["components"][0]
        self.assertEqual((c["value"], c["footprint"]), ("", ""))

    def test_instance_empty_value_keeps_symbol_value(self):
        si = f'(symbol_instances (path "/{u(10)}" (reference "R1") (unit 1) (value "")))'
        body = sym(u(10), "R1", "1k", 50)
        files = {"k.kicad_sch": sch(20211123, ROOT_UUID, body,
                                    tail=f'(sheet_instances (path "/" (page "1"))) {si}')}
        self.assertEqual(parse(files, "k.kicad_sch")["components"][0]["value"], "1k")

    def test_spaces_on_last_repeated_sheet_empty_every_instance(self):
        a, b = u(170), u(180)
        si = (f'(symbol_instances (path "/{a}/{u(23)}" (reference "R10") (unit 1) (value "10k")'
              f' (footprint "")) (path "/{b}/{u(23)}" (reference "R11") (unit 1) (value " ")'
              f' (footprint "")))')
        tail = (f'(sheet_instances (path "/" (page "1")) (path "/{a}" (page "2"))'
                f' (path "/{b}" (page "3"))) {si}')
        root = sheet(a, "child.kicad_sch", 100) + " " + sheet(b, "child.kicad_sch", 140)
        files = {"rep.kicad_sch": sch(20211123, ROOT_UUID, root, tail=tail),
                 "child.kicad_sch": sch(20211123, CHILD_UUID, sym(u(23), "R1", "1k", 50))}
        got = sorted((c["reference"], c["value"])
                     for c in parse(files, "rep.kicad_sch")["components"])
        self.assertEqual(got, [("R10", ""), ("R11", "")])


if __name__ == "__main__":
    unittest.main()
