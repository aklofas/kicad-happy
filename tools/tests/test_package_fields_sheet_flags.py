"""Package fields of multi-unit parts, sheet BOM/DNP/board flags, and DNP-pure BOM lines.

Expected values follow KiCad 10: the netlist takes each field of a multi-unit part from the
lowest unit that sets it (single-unit symbols keep their own fields); a sheet's
in_bom/dnp/on_board flag applies to every symbol below it, through nested sheets (KiCad 9+);
the kicad-cli 10.0.6 BOM and netlist of the same files agree (R1, R3 in the BOM; R2 DNP;
R3 off the board; U201 footprint DIP-14; fitted and DNP parts on separate lines)."""
import os, shutil, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from kicad_core.fields import merge_unit_fields  # noqa: E402
from schematic.pipeline import analyze_schematic  # noqa: E402

LIB = '''(lib_symbols
 (symbol "Device:R" (pin_numbers (hide yes)) (pin_names (offset 0)) (exclude_from_sim no) (in_bom yes) (on_board yes)
  (property "Reference" "R" (at 0 0 0)) (property "Value" "R" (at 0 0 0))
  (property "Footprint" "" (at 0 0 0)) (property "Datasheet" "" (at 0 0 0))
  (symbol "R_1_1"
   (pin passive line (at 0 3.81 270) (length 1.27) (name "~") (number "1"))
   (pin passive line (at 0 -3.81 90) (length 1.27) (name "~") (number "2"))))
 (symbol "T:Quad" (pin_names (offset 0)) (exclude_from_sim no) (in_bom yes) (on_board yes)
  (property "Reference" "U" (at 0 0 0)) (property "Value" "Quad" (at 0 0 0))
  (property "Footprint" "" (at 0 0 0)) (property "Datasheet" "" (at 0 0 0))
  (symbol "Quad_1_1" (pin passive line (at 0 3.81 270) (length 1.27) (name "A") (number "1")))
  (symbol "Quad_2_1" (pin passive line (at 0 3.81 270) (length 1.27) (name "B") (number "2")))
  (symbol "Quad_3_1" (pin passive line (at 0 3.81 270) (length 1.27) (name "C") (number "3")))
  (symbol "Quad_4_1" (pin passive line (at 0 3.81 270) (length 1.27) (name "D") (number "4")))))'''

ROOT_UUID = "00000000-0000-4000-8000-0071000000e0"
DIP = "Package_DIP:DIP-14_W7.62mm_Socket"


class _Ids:
    def __init__(self):
        self.n = 700

    def __call__(self):
        self.n += 1
        return f"00000000-0000-4000-8000-{self.n:012d}"


def _prop(name, val):
    return f'(property "{name}" "{val}" (at 0 0 0))'


def _sym(uid, ref, value, path, *, lib_id="Device:R", unit=1, fp="", extra=(), dnp="no",
         pins=("1", "2"), at=(0, 0)):
    props = [_prop("Reference", ref), _prop("Value", value), _prop("Footprint", fp), _prop("Datasheet", "")]
    props += [_prop(k, v) for k, v in extra]
    pl = " ".join(f'(pin "{p}" (uuid "{uid()}"))' for p in pins)
    return (f'(symbol (lib_id "{lib_id}") (at {at[0]} {at[1]} 0) (unit {unit}) (exclude_from_sim no)'
            f' (in_bom yes) (on_board yes) (dnp {dnp}) (uuid "{uid()}") ' + " ".join(props)
            + f' {pl} (instances (project "pf" (path "{path}" (reference "{ref}") (unit {unit})))))')


def _sheet(uid, name, file, flags, at):
    return (f'(sheet (at {at} 80) (size 20 10) (exclude_from_sim no) {flags} (uuid "{uid}")'
            f' {_prop("Sheetname", name)} {_prop("Sheetfile", file)}'
            f' (instances (project "pf" (path "/{ROOT_UUID}" (page "2")))))')


def _doc(uuid, items, root=True):
    tail = '\n(sheet_instances (path "/" (page "1")))' if root else ""
    return (f'(kicad_sch (version 20250114) (generator "eeschema") (generator_version "9.0")'
            f' (uuid "{uuid}") (paper "A4")\n{LIB}\n' + "\n".join(items) + f"{tail})\n")


SHEET_A = "00000000-0000-4000-8000-00720000005e"   # default flags
SHEET_B = "00000000-0000-4000-8000-00730000005e"   # (in_bom no) (dnp yes)
SHEET_C = "00000000-0000-4000-8000-00740000005e"   # (on_board no)
SHEET_M = "00000000-0000-4000-8000-00750000005e"   # (in_bom no), holds a nested sheet
SHEET_N = "00000000-0000-4000-8000-00760000005e"   # default flags, below M


def write_project(tmp):
    uid = _Ids()
    rp = "/" + ROOT_UUID
    root_items = [
        # Units in file order 3, 1, 2, 4; only unit 2 has the footprint, only unit 3 the MPN.
        _sym(uid, "U201", "LM324", rp, lib_id="T:Quad", unit=3, pins=("3",), extra=[("MPN", "LM324N")],
             at=(10, 10)),
        _sym(uid, "U201", "LM324", rp, lib_id="T:Quad", unit=1, pins=("1",), at=(20, 10)),
        _sym(uid, "U201", "LM324", rp, lib_id="T:Quad", unit=2, pins=("2",), fp=DIP, at=(30, 10)),
        _sym(uid, "U201", "LM324", rp, lib_id="T:Quad", unit=4, pins=("4",), at=(40, 10)),
        # Fitted and DNP parts that share value, footprint and MPN.
        _sym(uid, "R10", "10k", rp, fp="Resistor_SMD:R_0603_1608Metric", at=(10, 30)),
        _sym(uid, "R11", "10k", rp, fp="Resistor_SMD:R_0603_1608Metric", dnp="yes", at=(20, 30)),
        _sheet(SHEET_A, "a", "child.kicad_sch", "(in_bom yes) (on_board yes) (dnp no)", 50),
        _sheet(SHEET_B, "b", "child.kicad_sch", "(in_bom no) (dnp yes)", 80),
        _sheet(SHEET_C, "c", "child.kicad_sch", "(in_bom yes) (on_board no) (dnp no)", 110),
        _sheet(SHEET_M, "m", "mid.kicad_sch", "(in_bom no)", 140),
    ]
    child = _sym(uid, "R1", "1k", f"{rp}/{SHEET_A}")
    child = child.replace(
        f'(path "{rp}/{SHEET_A}" (reference "R1") (unit 1))',
        f'(path "{rp}/{SHEET_A}" (reference "R1") (unit 1))'
        f' (path "{rp}/{SHEET_B}" (reference "R2") (unit 1))'
        f' (path "{rp}/{SHEET_C}" (reference "R3") (unit 1))')
    mid_items = [
        _sym(uid, "R9", "1k", f"{rp}/{SHEET_M}"),
        _sheet(SHEET_N, "n", "leaf.kicad_sch", "(in_bom yes) (on_board yes) (dnp no)", 50).replace(
            f'(path "/{ROOT_UUID}" (page "2"))', f'(path "/{ROOT_UUID}/{SHEET_M}" (page "6"))'),
    ]
    files = {
        "pf.kicad_sch": _doc(ROOT_UUID, root_items),
        "child.kicad_sch": _doc("00000000-0000-4000-8000-0077000000e0", [child], root=False),
        "mid.kicad_sch": _doc("00000000-0000-4000-8000-0078000000e0", mid_items, root=False),
        "leaf.kicad_sch": _doc("00000000-0000-4000-8000-0079000000e0",
                               [_sym(uid, "R12", "2k", f"{rp}/{SHEET_M}/{SHEET_N}")], root=False),
        "pf.kicad_pro": '{"meta": {"filename": "pf.kicad_pro", "version": 3}, "schematic": {}}',
    }
    for name, text in files.items():
        with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
            f.write(text)
    return os.path.join(tmp, "pf.kicad_sch")


class MergeUnitFieldsTest(unittest.TestCase):
    def test_lowest_unit_with_text_wins_for_mandatory_fields(self):
        merged = merge_unit_fields([(3, {"Footprint": "X:SO-14"}), (1, {"Footprint": ""}),
                                    (2, {"Footprint": DIP}), (4, {"Footprint": ""})])
        self.assertEqual(merged["Footprint"], DIP)

    def test_conflicting_values_lowest_unit_wins(self):
        merged = merge_unit_fields([(2, {"Value": "SO-8"}), (1, {"Value": "SOP-8"})])
        self.assertEqual(merged["Value"], "SOP-8")

    def test_other_fields_come_from_the_lowest_unit_carrying_them(self):
        merged = merge_unit_fields([(2, {"MPN": "B"}), (1, {"MPN": ""}), (3, {"Vendor": "v"})])
        self.assertEqual(merged, {"MPN": "", "Vendor": "v"})

    def test_ties_keep_file_order_and_blank_mandatory_stays_blank(self):
        merged = merge_unit_fields([(1, {"Value": "a", "Datasheet": ""}), (1, {"Value": "b"})])
        self.assertEqual(merged, {"Value": "a", "Datasheet": ""})


class AnalyzerProjectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        with redirect_stderr(StringIO()):
            cls.out = analyze_schematic(write_project(cls.tmp))
        cls.comps = {}
        for c in cls.out["components"]:
            cls.comps.setdefault(c["reference"], c)
        cls.bom = {r: line for line in cls.out["bom"] for r in line["references"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_multi_unit_footprint_and_mpn_from_any_unit(self):
        line = self.bom["U201"]
        self.assertEqual(line["footprint"], DIP)
        self.assertEqual(line["mpn"], "LM324N")
        self.assertNotIn("U201", self.out["statistics"]["missing_footprint"])
        self.assertNotIn("U201", self.out["statistics"]["missing_mpn"])

    def test_sheet_flags_reach_their_symbols(self):
        self.assertEqual((self.comps["R1"]["in_bom"], self.comps["R1"]["dnp"]), (True, False))
        self.assertEqual((self.comps["R2"]["in_bom"], self.comps["R2"]["dnp"]), (False, True))
        self.assertEqual((self.comps["R3"]["in_bom"], self.comps["R3"]["on_board"]), (True, False))
        self.assertFalse(self.comps["R9"]["in_bom"])

    def test_nested_sheet_inherits_and_cannot_re_include(self):
        self.assertFalse(self.comps["R12"]["in_bom"])

    def test_bom_holds_only_kicad_bom_parts(self):
        self.assertEqual(set(self.bom) - {"R10", "R11", "U201"}, {"R1", "R3"})

    def test_bom_line_never_mixes_dnp_and_fitted(self):
        self.assertIsNot(self.bom["R10"], self.bom["R11"])
        self.assertFalse(self.bom["R10"]["dnp"])
        self.assertTrue(self.bom["R11"]["dnp"])
        self.assertEqual(self.out["statistics"]["dnp_parts"], 1)


if __name__ == "__main__":
    unittest.main()
