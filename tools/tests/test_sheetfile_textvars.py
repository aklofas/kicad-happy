"""A (sheet) block's file name may use project text variables; KiCad expands them from the
project's text_variables and ${PROJECTNAME} when it opens the sheet, and does not expand
OS environment variables (kicad-cli netlist: `${BLOCK_DIR}/${NAME}_sub.kicad_sch` loads
R1, `${ENVDIR}/...` with ENVDIR only in the environment loads nothing)."""
import json, os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from kicad_core.project import (discover_root_schematic, expand_sheet_file,  # noqa: E402
                                is_referenced_as_child)
from schematic.pipeline import analyze_schematic  # noqa: E402

ROOT_UUID = "11111111-1111-1111-1111-111111111111"
SHEET_UUID = "22222222-2222-2222-2222-222222222222"

R_LIB = ('(lib_symbols (symbol "Device:R" (pin_numbers hide) (pin_names (offset 0))'
         ' (in_bom yes) (on_board yes) (property "Reference" "R" (at 0 0 0))'
         ' (property "Value" "R" (at 0 0 0))'
         ' (symbol "R_1_1" (pin passive line (at 0 3.81 270) (length 1.27) (name "~") (number "1"))'
         ' (pin passive line (at 0 -3.81 90) (length 1.27) (name "~") (number "2")))))')


def root_sch(project, sheetfile):
    return (f'(kicad_sch (version 20231120) (generator "eeschema") (uuid "{ROOT_UUID}")'
            f' (paper "A4") {R_LIB}'
            f' (sheet (at 50 50) (size 20 10) (uuid "{SHEET_UUID}")'
            f' (property "Sheetname" "blk" (at 50 49 0))'
            f' (property "Sheetfile" "{sheetfile}" (at 50 61 0))'
            f' (instances (project "{project}" (path "/{ROOT_UUID}" (page "2")))))'
            f' (sheet_instances (path "/" (page "1"))))\n')


def sub_sch(project):
    return (f'(kicad_sch (version 20231120) (generator "eeschema")'
            f' (uuid "33333333-3333-3333-3333-333333333333") (paper "A4") {R_LIB}'
            f' (symbol (lib_id "Device:R") (at 100 100 0) (unit 1) (in_bom yes) (on_board yes)'
            f' (uuid "44444444-4444-4444-4444-444444444444")'
            f' (property "Reference" "R1" (at 0 0 0)) (property "Value" "10k" (at 0 0 0))'
            f' (property "Footprint" "" (at 0 0 0))'
            f' (instances (project "{project}" (path "/{ROOT_UUID}/{SHEET_UUID}"'
            f' (reference "R1") (unit 1)))))'
            f' (sheet_instances (path "/" (page "1"))))\n')


def build(tmp, project, sheetfile, sub_rel, variables):
    """Write <project>.kicad_pro/.kicad_sch and the sub-sheet at *sub_rel*."""
    pro = {"meta": {"version": 1}}
    if variables is not None:
        pro["text_variables"] = variables
    files = {f"{project}.kicad_pro": json.dumps(pro),
             f"{project}.kicad_sch": root_sch(project, sheetfile),
             sub_rel: sub_sch(project)}
    for rel, text in files.items():
        path = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return os.path.join(tmp, f"{project}.kicad_sch")


def refs_of(root):
    with redirect_stderr(StringIO()):
        result = analyze_schematic(root)
    return sorted(c["reference"] for c in result["components"])


class SheetFileTextVarsTest(unittest.TestCase):
    def test_project_variables_in_directory_and_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build(tmp, "amp", "${BLOCK_DIR}/${NAME}_sub.kicad_sch",
                         "blocks/amp_sub.kicad_sch", {"BLOCK_DIR": "blocks", "NAME": "amp"})
            self.assertEqual(refs_of(root), ["R1"])

    def test_projectname(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build(tmp, "amp", "${PROJECTNAME}_sub.kicad_sch", "amp_sub.kicad_sch", {})
            self.assertEqual(refs_of(root), ["R1"])

    def test_unknown_token_stays_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build(tmp, "amp", "${NOPE}/amp_sub.kicad_sch",
                         "blocks/amp_sub.kicad_sch", {"BLOCK_DIR": "blocks"})
            self.assertEqual(refs_of(root), [])
            self.assertEqual(expand_sheet_file("${NOPE}/a.kicad_sch", root),
                             "${NOPE}/a.kicad_sch")

    def test_environment_variable_is_not_expanded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build(tmp, "amp", "${ENVDIR}/amp_sub.kicad_sch",
                         "blocks/amp_sub.kicad_sch", {})
            old = os.environ.get("ENVDIR")
            os.environ["ENVDIR"] = "blocks"
            try:
                self.assertEqual(refs_of(root), [])
            finally:
                if old is None:
                    del os.environ["ENVDIR"]
                else:
                    os.environ["ENVDIR"] = old

    def test_projectname_without_project_file_stays_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            sch = os.path.join(tmp, "amp.kicad_sch")
            self.assertEqual(expand_sheet_file("${PROJECTNAME}/sub.kicad_sch", sch),
                             "${PROJECTNAME}/sub.kicad_sch")

    def test_plain_name_is_unchanged(self):
        self.assertEqual(expand_sheet_file("a/b.kicad_sch", "/nonexistent/x.kicad_sch"),
                         "a/b.kicad_sch")


class SheetFileTextVarsDiscoveryTest(unittest.TestCase):
    def test_sibling_named_by_variable_is_a_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            build(tmp, "amp", "${NAME}_sub.kicad_sch", "amp_sub.kicad_sch", {"NAME": "amp"})
            self.assertTrue(is_referenced_as_child(os.path.join(tmp, "amp_sub.kicad_sch")))
            self.assertFalse(is_referenced_as_child(os.path.join(tmp, "amp.kicad_sch")))

    def test_root_discovered_from_sub_sheet_in_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build(tmp, "amp", "${BLOCK_DIR}/${NAME}_sub.kicad_sch",
                         "blocks/amp_sub.kicad_sch", {"BLOCK_DIR": "blocks", "NAME": "amp"})
            self.assertEqual(
                discover_root_schematic(os.path.join(tmp, "blocks", "amp_sub.kicad_sch")),
                os.path.abspath(root))


if __name__ == "__main__":
    unittest.main()
