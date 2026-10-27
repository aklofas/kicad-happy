"""KiCad 10 design variants (--variant) in analyze_schematic and bom_manager.

Expected values follow KiCad 10 (sch_io_kicad_sexpr_parser.cpp, SCH_SYMBOL / SCH_SHEET_PATH
variant getters) and match kicad-cli 10.0.6 `sch export bom --variant A` on the same files:
a variant block of a symbol instance overrides only what it names (dnp, in_bom, on_board,
fields); a sheet's variant flags reach every symbol below it; before file version 20260306 a
variant's in_bom is stored with the inverted meaning; without --variant the default variant
(the symbol's own attributes and fields) is used.  Power nets keep the base Value: KiCad's
connectivity does not apply variants."""
import io, json, os, shutil, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "bom" / "scripts"))

import analyze_schematic as analyze_schematic_cli  # noqa: E402
import bom_manager  # noqa: E402
from schematic.pipeline import analyze_schematic  # noqa: E402

LIB = '''(lib_symbols
 (symbol "Device:R" (pin_numbers (hide yes)) (pin_names (offset 0)) (exclude_from_sim no) (in_bom yes) (on_board yes)
  (property "Reference" "R" (at 0 0 0)) (property "Value" "R" (at 0 0 0))
  (property "Footprint" "" (at 0 0 0)) (property "Datasheet" "" (at 0 0 0))
  (symbol "R_1_1"
   (pin passive line (at 0 3.81 270) (length 1.27) (name "~") (number "1"))
   (pin passive line (at 0 -3.81 90) (length 1.27) (name "~") (number "2"))))
 (symbol "power:+5V" (power) (pin_numbers (hide yes)) (pin_names (offset 0) (hide yes)) (exclude_from_sim no)
  (in_bom yes) (on_board yes)
  (property "Reference" "#PWR" (at 0 0 0)) (property "Value" "+5V" (at 0 0 0))
  (property "Footprint" "" (at 0 0 0)) (property "Datasheet" "" (at 0 0 0))
  (symbol "+5V_1_1" (pin power_in line (at 0 0 90) (length 0) (hide yes) (name "+5V") (number "1")))))'''

ROOT_UUID = "00000000-0000-4000-8000-0281000000e0"
CHILD_UUID = "00000000-0000-4000-8000-0282000000e0"
SHEET = "00000000-0000-4000-8000-02830000005e"
SHEET2 = "00000000-0000-4000-8000-02840000005e"
CHILD2_UUID = "00000000-0000-4000-8000-0285000000e0"
FP = "Resistor_SMD:R_0603_1608Metric"


class _Ids:
    def __init__(self):
        self.n = 2800

    def __call__(self):
        self.n += 1
        return f"00000000-0000-4000-8000-{self.n:012d}"


def _prop(name, val):
    return f'(property "{name}" "{val}" (at 0 0 0))'


def _sym(uid, ref, value, path, at, *, variant="", dnp="no", in_bom="yes", lib_id="Device:R",
         fp=FP, pins=("1", "2")):
    pl = " ".join(f'(pin "{p}" (uuid "{uid()}"))' for p in pins)
    var = f' (variant (name "A") {variant})' if variant else ""
    return (f'(symbol (lib_id "{lib_id}") (at {at[0]} {at[1]} 0) (unit 1) (exclude_from_sim no)'
            f' (in_bom {in_bom}) (on_board yes) (dnp {dnp}) (uuid "{uid()}")'
            f' {_prop("Reference", ref)} {_prop("Value", value)} {_prop("Footprint", fp)}'
            f' {_prop("Datasheet", "")} {pl}'
            f' (instances (project "vt" (path "{path}" (reference "{ref}") (unit 1){var}))))')


def _doc(uuid, version, items, root=True):
    tail = '\n(sheet_instances (path "/" (page "1")))' if root else ""
    return (f'(kicad_sch (version {version}) (generator "eeschema") (generator_version "10.0")'
            f' (uuid "{uuid}") (paper "A4")\n{LIB}\n' + "\n".join(items) + f"{tail})\n")


def write_project(tmp, version=20260306):
    """R33 DNP, fitted in A; R70 in_bom yes, (in_bom no) in A; R71 (in_bom no), (in_bom yes)
    in A; R80 10k, Value HV in A; #PWR1 +5V, Value +12V in A; R90 on a sheet that is DNP in A;
    R91 on a sheet that is (in_bom no) in A."""
    uid = _Ids()
    rp = "/" + ROOT_UUID
    wire = f'(wire (pts (xy 20 6.19) (xy 20 0)) (stroke (width 0) (type default)) (uuid "{uid()}"))'
    root_items = [
        _sym(uid, "R33", "1k", rp, (10, 10), dnp="yes", variant="(dnp no)"),
        _sym(uid, "R70", "2k", rp, (10, 30), variant="(in_bom no)"),
        _sym(uid, "R71", "3k", rp, (10, 50), in_bom="no", variant="(in_bom yes)"),
        _sym(uid, "R80", "10k", rp, (20, 10), variant='(field (name "Value") (value "HV"))'),
        _sym(uid, "#PWR1", "+5V", rp, (20, 0), lib_id="power:+5V", fp="", pins=("1",),
             variant='(field (name "Value") (value "+12V"))'),
        wire,
        f'(sheet (at 60 80) (size 20 10) (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)'
        f' (uuid "{SHEET}") {_prop("Sheetname", "s")} {_prop("Sheetfile", "child.kicad_sch")}'
        f' (instances (project "vt" (path "{rp}" (page "2") (variant (name "A") (dnp yes))))))',
        f'(sheet (at 90 80) (size 20 10) (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)'
        f' (uuid "{SHEET2}") {_prop("Sheetname", "s2")} {_prop("Sheetfile", "child2.kicad_sch")}'
        f' (instances (project "vt" (path "{rp}" (page "3") (variant (name "A") (in_bom no))))))',
    ]
    files = {
        "vt.kicad_sch": _doc(ROOT_UUID, version, root_items),
        "child.kicad_sch": _doc(CHILD_UUID, version,
                                [_sym(uid, "R90", "4k7", f"{rp}/{SHEET}", (10, 10))], root=False),
        "child2.kicad_sch": _doc(CHILD2_UUID, version,
                                 [_sym(uid, "R91", "5k6", f"{rp}/{SHEET2}", (10, 10))], root=False),
        "vt.kicad_pro": json.dumps({"meta": {"filename": "vt.kicad_pro", "version": 3},
                                    "schematic": {"variants": [{"name": "A", "description": "a"}]}}),
    }
    for name, text in files.items():
        with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
            f.write(text)
    return os.path.join(tmp, "vt.kicad_sch")


def _quiet(fn, *args, **kwargs):
    with redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


class _Project(unittest.TestCase):
    version = 20260306

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kh-variant-")
        self.path = write_project(self.tmp, self.version)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def comps(self, variant=None):
        result = _quiet(analyze_schematic, self.path, variant=variant)
        return {c["reference"]: c for c in result["components"]}, result

    def bom(self, variant=None):
        report = _quiet(bom_manager.analyze, Path(self.path), recursive=True, variant=variant)
        return {ref: e for e in report["bom"] for ref in e["references"]}


class AnalyzerVariantTest(_Project):
    def test_default_variant_is_the_symbols_own_attributes(self):
        comps, result = self.comps()
        self.assertTrue(comps["R33"]["dnp"])
        self.assertTrue(comps["R70"]["in_bom"])
        self.assertFalse(comps["R71"]["in_bom"])
        self.assertEqual(comps["R80"]["value"], "10k")
        self.assertFalse(comps["R90"]["dnp"])
        self.assertTrue(comps["R91"]["in_bom"])
        self.assertNotIn("variant", result.get("project_settings", {}))

    def test_variant_overrides_what_it_names(self):
        comps, result = self.comps("A")
        self.assertFalse(comps["R33"]["dnp"])
        self.assertFalse(comps["R70"]["in_bom"])
        self.assertTrue(comps["R71"]["in_bom"])
        self.assertEqual(comps["R80"]["value"], "HV")
        self.assertEqual(comps["R80"]["footprint"], FP)
        self.assertTrue(comps["R90"]["dnp"])
        self.assertFalse(comps["R91"]["in_bom"])
        self.assertEqual(result["project_settings"]["variant"], "A")

    def test_power_net_keeps_the_base_value(self):
        _comps, result = self.comps("A")
        self.assertIn("+5V", result["nets"])
        self.assertNotIn("+12V", result["nets"])

    def test_unknown_variant_is_a_usage_error(self):
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                analyze_schematic_cli.main([self.path, "--variant", "Nope"])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("unknown variant 'Nope' (the project defines: A)", err.getvalue())


class BomManagerVariantTest(_Project):
    def test_default_variant(self):
        bom = self.bom()
        self.assertTrue(bom["R33"]["dnp"])
        self.assertIn("R70", bom)
        self.assertNotIn("R71", bom)
        self.assertEqual(bom["R80"]["value"], "10k")
        self.assertFalse(bom["R90"]["dnp"])
        self.assertIn("R91", bom)

    def test_variant(self):
        bom = self.bom("A")
        self.assertFalse(bom["R33"]["dnp"])
        self.assertNotIn("R70", bom)
        self.assertIn("R71", bom)
        self.assertEqual(bom["R80"]["value"], "HV")
        self.assertTrue(bom["R90"]["dnp"])
        self.assertNotIn("R91", bom)

    def test_unknown_variant_is_a_usage_error(self):
        err = io.StringIO()
        argv = sys.argv
        sys.argv = ["bom_manager.py", "analyze", self.path, "--recursive", "--json", "--variant", "Nope"]
        try:
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    bom_manager.main()
        finally:
            sys.argv = argv
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("unknown variant 'Nope' (the project defines: A)", err.getvalue())


class InvertedInBomBefore20260306Test(_Project):
    """Files of 20250922..20260305 store a variant's in_bom inverted: (in_bom no) includes."""
    version = 20260101

    def test_analyzer(self):
        comps, _ = self.comps("A")
        self.assertTrue(comps["R70"]["in_bom"])
        self.assertFalse(comps["R71"]["in_bom"])
        self.assertTrue(comps["R91"]["in_bom"])

    def test_bom_manager(self):
        bom = self.bom("A")
        self.assertIn("R70", bom)
        self.assertNotIn("R71", bom)
        self.assertIn("R91", bom)


if __name__ == "__main__":
    unittest.main()
