"""Text variables in symbol fields expand as KiCad 10 expands them (the symbol's own fields,
generated tokens, the sheet chain, the schematic, the project's text_variables, cross
references).  Expected values are the kicad-cli 10.0.6 netlist export of the same files
("~" there means empty)."""
import json, os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from kicad_core.textvars import expand_text_vars  # noqa: E402
from schematic.hierarchy import parse_all_sheets  # noqa: E402
from schematic.pipeline import analyze_schematic  # noqa: E402

LIB = '''(lib_symbols
 (symbol "Device:R" (pin_numbers (hide yes)) (pin_names (offset 0)) (exclude_from_sim no) (in_bom yes) (on_board yes)
  (property "Reference" "R" (at 0 0 0)) (property "Value" "R" (at 0 0 0))
  (property "Footprint" "" (at 0 0 0)) (property "Datasheet" "" (at 0 0 0))
  (symbol "R_1_1"
   (pin passive line (at 0 3.81 270) (length 1.27) (name "~") (number "1"))
   (pin passive line (at 0 -3.81 90) (length 1.27) (name "~") (number "2"))))
 (symbol "T:Dual" (pin_names (offset 0)) (exclude_from_sim no) (in_bom yes) (on_board yes)
  (property "Reference" "U" (at 0 0 0)) (property "Value" "Dual" (at 0 0 0))
  (property "Footprint" "" (at 0 0 0)) (property "Datasheet" "" (at 0 0 0))
  (property "Description" "dual thing" (at 0 0 0))
  (symbol "Dual_1_1" (pin passive line (at 0 3.81 270) (length 1.27) (name "A") (number "1")))
  (symbol "Dual_2_1" (pin passive line (at 0 3.81 270) (length 1.27) (name "B") (number "2")))))'''

ROOT_UUID = "00000000-0000-4000-8000-0001000000e0"
SHEET_UUID = "00000000-0000-4000-8000-00030000005f"


class _Ids:
    def __init__(self):
        self.n = 100

    def __call__(self):
        self.n += 1
        return f"00000000-0000-4000-8000-{self.n:012d}"


def _esc(v):
    return v.replace("\\", "\\\\").replace('"', '\\"')


def _prop(name, val):
    return f'(property "{name}" "{_esc(val)}" (at 0 0 0))'


def _sym(uid, ref, value, path, *, lib_id="Device:R", unit=1, fp="", extra=(), attrs="", pins=("1", "2")):
    props = [_prop("Reference", ref), _prop("Value", value), _prop("Footprint", fp), _prop("Datasheet", "")]
    props += [_prop(k, v) for k, v in extra]
    pl = " ".join(f'(pin "{p}" (uuid "{uid()}"))' for p in pins)
    attrs = attrs or "(exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)"
    return (f'(symbol (lib_id "{lib_id}") (at 0 0 0) (unit {unit}) {attrs} (uuid "{uid()}") '
            + " ".join(props) + f' {pl} (instances (project "tv" (path "{path}"'
            f' (reference "{ref}") (unit {unit})))))')


def _doc(uuid, items, title_block, root=True):
    tail = '\n(sheet_instances (path "/" (page "1")))' if root else ""
    return (f'(kicad_sch (version 20250114) (generator "eeschema") (generator_version "9.0") (uuid "{uuid}") (paper "A4")\n'
            f'{LIB}\n' + "\n".join(items) + f"\n{title_block}{tail})\n")


# reference -> (value, footprint, extra fields) on the root sheet; expected = kicad-cli value
ROOT_CASES = [
    ("R1", "${MPN}", "", [("MPN", "RC0603FR-0710KL")], "RC0603FR-0710KL"),
    ("R2", "${VOUT}", "", [], "3V3"),
    ("R3", "rev ${REVISION}", "", [], "rev B"),
    ("R4", "${NOPE}", "", [], "${NOPE}"),
    ("R6", "${REFERENCE}", "", [], "R6"),
    ("R7", "${mpn}", "", [("MPN", "lowercase-ok")], "lowercase-ok"),
    ("R8", "\\${MPN}", "", [("MPN", "escaped")], "${MPN}"),
    ("R9", "${SHEETNAME}", "", [], "tv"),
    ("R10", "${R1:VALUE}", "", [], "RC0603FR-0710KL"),
    ("R11", "${U99:VALUE}", "", [], "<Unresolved: U99>"),
    ("R12", "${NESTED}", "", [], "3V3x"),
    ("R13", "${SHEETPATH}", "", [], "/"),
    ("R14", "${PROJECTNAME}", "", [], "tv"),
    ("R15", "${FILENAME}", "", [], "tv.kicad_sch"),
    ("R16", "${${KEY}}", "", [("KEY", "MPN"), ("MPN", "nested-ok")], "nested-ok"),
    ("R17", "${SIM.PARAMS}", "", [], ""),
    ("R18", "${FOO}", "", [("FOO", "${BAR}"), ("BAR", "bar-ok")], "bar-ok"),
    ("R19", "${VALUE}", "", [], "VALUE"),
    ("R20", "${FOOTPRINT_NAME}", "Resistor_SMD:R_0603", [], "R_0603"),
    ("R22", "${COMMENT1}", "", [], "c1"),
    ("R23", "${TITLE}", "", [], "RootT"),
    ("R24", "${X:Y}", "", [], "<Unresolved: X>"),
    ("R25", "${R1:NOFIELD}", "", [], "<Unresolved: R1:NOFIELD>"),
    ("R26", "a\\${MPN}b ${MPN}", "", [("MPN", "m")], "a${MPN}b m"),
    ("R27", "${SELF}", "", [("SELF", "${SELF}")], "SELF"),
    ("R28", "${A}", "", [("A", "${B}"), ("B", "${A}")], "${A}"),
    ("R29", "${Sheetname}", "", [], "${Sheetname}"),
]
SUB_CASES = [
    ("R30", "${SHEETNAME}", "Power"),
    ("R31", "${VARX}", "sheetvar"),
    ("R32", "${REVISION}", "C"),
    ("R33", "${TITLE}", ""),
    ("R34", "${VOUT}", "3V3"),
    ("R35", "${R1:VALUE}", "RC0603FR-0710KL"),
    ("R36", "${SHEETPATH}", "/Power/"),
    ("R37", "${varx}", "${varx}"),
    ("R39", "${COMMENT1}", ""),
    ("R40", "${FILENAME}", "tv.kicad_sch"),
]
DUAL_CASES = [
    ("U1", 2, "${REFERENCE}|${UNIT}|${SHORT_REFERENCE}|${FOOTPRINT_LIBRARY}|${FOOTPRINT_NAME}"
              "|${SYMBOL_LIBRARY}|${SYMBOL_NAME}|${EXCLUDE_FROM_BOM}|${EXCLUDE_FROM_BOARD}",
     "U1B|B|U1|Pkg|SO-8|T|Dual|Excluded from BOM|"),
    ("U2", 1, "a${ERC_ERROR x}b${}c${SYMBOL_DESCRIPTION}", "abcdual thing"),
    ("U3", 1, "${U1:REFERENCE}", "U1B"),
]


def _project(tmp):
    uid = _Ids()
    rp = "/" + ROOT_UUID
    items = [_sym(uid, ref, value, rp, fp=fp, extra=extra) for ref, value, fp, extra, _ in ROOT_CASES]
    items += [_sym(uid, ref, value, rp, lib_id="T:Dual", unit=unit, fp="Pkg:SO-8", pins=(str(unit),),
                   attrs="(exclude_from_sim no) (in_bom no) (on_board yes) (dnp no)")
              for ref, unit, value, _ in DUAL_CASES]
    items.append(f'(sheet (at 100 100) (size 20 10) (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)'
                 f' (uuid "{SHEET_UUID}") {_prop("Sheetname", "Power")} {_prop("Sheetfile", "sub.kicad_sch")}'
                 f' {_prop("VARX", "sheetvar")} (instances (project "tv" (path "{rp}" (page "2")))))')
    files = {
        "tv.kicad_sch": _doc(ROOT_UUID, items, '(title_block (title "RootT") (rev "B") (comment 1 "c1"))'),
        "sub.kicad_sch": _doc("00000000-0000-4000-8000-0002000000e0",
                              [_sym(uid, ref, value, rp + "/" + SHEET_UUID) for ref, value, _ in SUB_CASES],
                              '(title_block (rev "C"))', root=False),
        "tv.kicad_pro": json.dumps({"meta": {"filename": "tv.kicad_pro", "version": 3}, "schematic": {},
                                    "text_variables": {"VOUT": "3V3", "NESTED": "${VOUT}x"}}),
    }
    for name, text in files.items():
        with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
            f.write(text)
    return os.path.join(tmp, "tv.kicad_sch")


class ExpandTextVarsTest(unittest.TestCase):
    """The expansion rules of KiCad's ExpandTextVars / ResolveTextVars (common.cpp)."""

    def resolve(self, token):
        return {"A": "x", "B": "A", "C": "${A}"}.get(token)

    def test_rules(self):
        cases = [
            ("${A}", "x"),
            ("${NOPE}", "${NOPE}"),             # unresolved stays literal
            ("\\${A}", "${A}"),                 # escaped: a literal ${
            ("a\\${A}b${A}", "a${A}bx"),
            ("${${B}}", "x"),                   # innermost first
            ("${C}", "x"),                      # a value holding a variable expands again
            ("p${}q", "pq"),                    # an empty token is dropped
            ("p${ERC_WARNING check}q", "pq"),   # ERC/DRC messages only show during ERC/DRC
            ("@{${A}+1}", "@{x+1}"),            # math: variables expanded, not evaluated
            ("no vars", "no vars"),
        ]
        for text, want in cases:
            with self.subTest(text=text):
                self.assertEqual(expand_text_vars(text, self.resolve), want)


class FieldTextVariablesTest(unittest.TestCase):

    def test_values_match_kicad(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stderr(StringIO()):
                parsed = parse_all_sheets(_project(tmp))
        got = {c["reference"]: c["value"] for c in parsed["components"]}
        want = {ref: v for ref, _, _, _, v in ROOT_CASES}
        want.update({ref: v for ref, _, v in SUB_CASES})
        want.update({ref: v for ref, _, _, v in DUAL_CASES})
        self.assertEqual(got, want)

    def test_footprint_and_mpn_fields_expand(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _project(tmp)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            text = text.replace(
                _prop("Footprint", "Resistor_SMD:R_0603"),
                _prop("Footprint", "${FPLIB}:R_0603_1608Metric") + " " + _prop("FPLIB", "Resistor_SMD")
                + " " + _prop("MPN", "${VOUT}-part"))
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            with redirect_stderr(StringIO()):
                parsed = parse_all_sheets(path)
        r20 = next(c for c in parsed["components"] if c["reference"] == "R20")
        self.assertEqual(r20["footprint"], "Resistor_SMD:R_0603_1608Metric")
        self.assertEqual(r20["value"], "R_0603_1608Metric")
        self.assertEqual(r20["mpn"], "3V3-part")

    def test_bom_keeps_parts_with_the_same_raw_value_apart(self):
        """Two connectors whose Value is ${MPN} with different MPNs are two BOM lines."""
        uid = _Ids()
        rp = "/" + ROOT_UUID
        items = [_sym(uid, "J1", "${MPN}", rp, extra=[("MPN", "PartA")]),
                 _sym(uid, "J2", "${MPN}", rp, extra=[("MPN", "PartB")])]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tv.kicad_sch")
            with open(path, "w", encoding="utf-8") as f:
                f.write(_doc(ROOT_UUID, items, ""))
            with redirect_stderr(StringIO()):
                result = analyze_schematic(path)
        lines = sorted((tuple(b["references"]), b["value"]) for b in result["bom"])
        self.assertEqual(lines, [(("J1",), "PartA"), (("J2",), "PartB")])


if __name__ == "__main__":
    unittest.main()
