"""KiCad 10 projects with several top-level sheets (.kicad_pro schematic.top_level_sheets).

KiCad 10.0.7 loads every declared top-level sheet whichever one is named (files-io.cpp and
eeschema_helpers.cpp LoadSchematic), keys each sheet's instance paths off its declared uuid
unless that is nil, skips a missing file, and repairs a missing declared file to
<project>.kicad_sch when that exists (project_file.cpp PROJECT_FILE::LoadFromFile).  The
installed kicad-cli 10.0.6 loads only the named root, so expected values follow the 10.0.7
source: for the two-sheet project below, R1 and R2 with SIG = {R1.1, R2.1}.
"""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from kicad_core.project import discover_root_schematic, resolve_project_input  # noqa: E402
from schematic.pipeline import analyze_schematic  # noqa: E402

NIL = "00000000-0000-0000-0000-000000000000"

R_LIB = ('(symbol "Device:R" (pin_numbers (hide yes)) (pin_names (offset 0)) (in_bom yes)'
         ' (on_board yes) (property "Reference" "R" (at 0 0 0)) (property "Value" "R" (at 0 0 0))'
         ' (property "Footprint" "" (at 0 0 0)) (property "Datasheet" "" (at 0 0 0))'
         ' (symbol "R_1_1"'
         ' (pin passive line (at 0 3.81 270) (length 1.27) (name "~") (number "1"))'
         ' (pin passive line (at 0 -3.81 90) (length 1.27) (name "~") (number "2"))))')


def u(n):
    return f"00000000-0000-4000-8000-{n:012d}"


def resistor(uuid, ref, x, instances):
    """A resistor at (x, 50), pin 1 at (x, 46.19), with inline instances [(path, ref)]."""
    inst = " ".join(f'(path "{p}" (reference "{r}") (unit 1))' for p, r in instances)
    return (f'(symbol (lib_id "Device:R") (at {x} 50 0) (unit 1) (in_bom yes) (on_board yes)'
            f' (dnp no) (uuid "{uuid}") (property "Reference" "{ref}" (at {x} 50 0))'
            f' (property "Value" "1k" (at {x} 52 0)) (property "Footprint" "" (at {x} 50 0))'
            f' (property "Datasheet" "" (at {x} 50 0))'
            f' (pin "1" (uuid "{uuid[:-3]}101")) (pin "2" (uuid "{uuid[:-3]}102"))'
            f' (instances (project "f5_multi" {inst})))')


def labelled(kind, name, x, wire_uuid, label_uuid):
    """A wire from pin 1 of the resistor at x to a label of *kind* named *name*."""
    return (f'(wire (pts (xy {x} 46.19) (xy {x + 10} 46.19)) (uuid "{wire_uuid}"))'
            f' ({kind} "{name}" (at {x + 10} 46.19 0) (uuid "{label_uuid}"))')


def sheet(uuid, fname, x):
    return (f'(sheet (at {x} 80) (size 20 10) (uuid "{uuid}")'
            f' (property "Sheetname" "s{x}" (at {x} 79 0))'
            f' (property "Sheetfile" "{fname}" (at {x} 91 0)))')


def sch(uuid, body):
    return (f'(kicad_sch (version 20250114) (generator "eeschema") (generator_version "9.0")'
            f' (uuid "{uuid}") (paper "A4") (lib_symbols {R_LIB}) {body}'
            f' (sheet_instances (path "/" (page "1"))))\n')


def pro(name, sheets):
    """A .kicad_pro declaring [(filename, sheet name, uuid)] as top-level sheets."""
    entries = ", ".join(f'{{"filename": "{f}", "name": "{n}", "uuid": "{i}"}}'
                        for f, n, i in sheets)
    return (f'{{"meta": {{"filename": "{name}.kicad_pro", "version": 3}},'
            f' "schematic": {{"top_level_sheets": [{entries}]}}}}\n')


ROOT_FILE_UUID = u(101)
SECOND_FILE_UUID = u(102)
SECOND_DECLARED = u(103)


def f5_multi(label="global_label", root_extra="", second_extra=""):
    """The survey's f5_multi project: two declared sheets, each one R wired to SIG; the
    second sheet's symbol is keyed by the sheet's declared uuid (R? in the file, R2 there)."""
    root = (resistor(u(10), "R1", 50, [(f"/{ROOT_FILE_UUID}", "R1")])
            + labelled(label, "SIG", 50, u(11), u(12)) + root_extra)
    second = (resistor(u(20), "R?", 50, [(f"/{SECOND_DECLARED}", "R2")])
              + labelled(label, "SIG", 50, u(21), u(22)) + second_extra)
    return {"f5_multi.kicad_pro": pro("f5_multi", [("f5_multi.kicad_sch", "f5_multi", NIL),
                                                   ("second.kicad_sch", "second",
                                                    SECOND_DECLARED)]),
            "f5_multi.kicad_sch": sch(ROOT_FILE_UUID, root),
            "second.kicad_sch": sch(SECOND_FILE_UUID, second)}


def write(tmp, files):
    for name, text in files.items():
        with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
            f.write(text)


def analyze(files, name):
    with tempfile.TemporaryDirectory() as tmp:
        write(tmp, files)
        err = StringIO()
        with redirect_stderr(err):
            result = analyze_schematic(os.path.join(tmp, name))
    return result, err.getvalue()


def nets_of(result):
    """Each net as a sorted tuple of ref.pin."""
    return sorted(tuple(sorted(f'{p["component"]}.{p["pin_number"]}' for p in net["pins"]))
                  for net in result["nets"].values() if net["pins"])


class DeclaredTopLevelSheetsTest(unittest.TestCase):
    def test_every_declared_sheet_with_its_instance_references(self):
        for name in ("f5_multi.kicad_sch", "second.kicad_sch"):
            with self.subTest(named=name):
                result, err = analyze(f5_multi(), name)
                self.assertEqual(sorted(c["reference"] for c in result["components"]),
                                 ["R1", "R2"])
                self.assertEqual(nets_of(result), [("R1.1", "R2.1"), ("R1.2",), ("R2.2",)])
                self.assertEqual(sorted(os.path.basename(s) for s in result["sheets"]),
                                 ["f5_multi.kicad_sch", "second.kicad_sch"])
                self.assertIn("discovered 1 additional top-level sheets from .kicad_pro", err)
                self.assertNotIn("hierarchy_warning", result)

    def test_a_sheet_with_children_does_not_suppress_its_peers(self):
        child = sch(u(30), resistor(u(31), "R?", 50, [(f"/{ROOT_FILE_UUID}/{u(32)}", "R5")]))
        files = dict(f5_multi(root_extra=sheet(u(32), "child.kicad_sch", 100)),
                     **{"child.kicad_sch": child})
        result, _ = analyze(files, "f5_multi.kicad_sch")
        self.assertEqual(sorted(c["reference"] for c in result["components"]),
                         ["R1", "R2", "R5"])
        self.assertIn(("R1.1", "R2.1"), nets_of(result))

    def test_repeated_sub_sheet_under_a_peer_keeps_both_instances(self):
        child = sch(u(40), resistor(u(41), "R?", 50, [(f"/{SECOND_DECLARED}/{u(42)}", "R10"),
                                                      (f"/{SECOND_DECLARED}/{u(43)}", "R11")]))
        files = dict(f5_multi(second_extra=sheet(u(42), "child.kicad_sch", 100)
                              + sheet(u(43), "child.kicad_sch", 130)),
                     **{"child.kicad_sch": child})
        result, _ = analyze(files, "f5_multi.kicad_sch")
        self.assertEqual(sorted(c["reference"] for c in result["components"]),
                         ["R1", "R10", "R11", "R2"])

    def test_local_labels_on_different_top_level_sheets_stay_apart(self):
        result, _ = analyze(f5_multi(label="label"), "f5_multi.kicad_sch")
        self.assertEqual(nets_of(result), [("R1.1",), ("R1.2",), ("R2.1",), ("R2.2",)])

    def test_a_missing_declared_sheet_is_skipped(self):
        files = f5_multi()
        del files["second.kicad_sch"]
        result, _ = analyze(files, "f5_multi.kicad_sch")
        self.assertEqual([c["reference"] for c in result["components"]], ["R1"])


class ProjectInputTest(unittest.TestCase):
    def project(self, tmp, declared, files):
        write(tmp, dict({"proj.kicad_pro": pro("proj", [(f, "x", NIL) for f in declared])},
                        **{f: sch(u(50), "") for f in files}))

    def test_directory_and_project_inputs_open_the_declared_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.project(tmp, ["logic.kicad_sch"], ["logic.kicad_sch"])
            for given in (tmp, os.path.join(tmp, "proj.kicad_pro")):
                path, _ = resolve_project_input(given, ".kicad_sch")
                self.assertEqual(os.path.basename(path), "logic.kicad_sch")

    def test_a_missing_declared_root_falls_back_to_the_project_schematic(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.project(tmp, ["gone.kicad_sch", "logic.kicad_sch"],
                         ["proj.kicad_sch", "logic.kicad_sch"])
            path, _ = resolve_project_input(tmp, ".kicad_sch")
            self.assertEqual(os.path.basename(path), "proj.kicad_sch")

    def test_a_board_input_is_unaffected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.project(tmp, ["logic.kicad_sch"], ["logic.kicad_sch"])
            write(tmp, {"proj.kicad_pcb": "(kicad_pcb)\n"})
            path, _ = resolve_project_input(tmp, ".kicad_pcb")
            self.assertEqual(os.path.basename(path), "proj.kicad_pcb")

    def test_a_sub_sheet_finds_its_declared_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.project(tmp, ["logic.kicad_sch"], [])
            os.mkdir(os.path.join(tmp, "sheets"))
            write(tmp, {"logic.kicad_sch": sch(u(50), sheet(u(51), "sheets/child.kicad_sch", 100)),
                        "sheets/child.kicad_sch": sch(u(52), "")})
            root = discover_root_schematic(os.path.join(tmp, "sheets", "child.kicad_sch"))
            self.assertEqual(os.path.basename(root or ""), "logic.kicad_sch")


if __name__ == "__main__":
    unittest.main()
