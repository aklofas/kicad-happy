"""A legacy project's sym-lib-table is read even when a <stem>-cache.lib exists: a component
`nick:Name` takes its pins from the project library, not from the built-in table."""
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
RES = """DEF {name} R 0 0 N Y 1 F N
F0 "R" 0 0 50 H V C CNN
DRAW
X ~ 1 0 300 0 U 50 50 1 1 P
X ~ 2 0 -300 0 D 50 50 1 1 P
ENDDRAW
ENDDEF
"""
COMP = ("$Comp\nL proj:R R1\nU 1 1 5F000001\nP 4000 3000\n"
        'F 0 "R1" H 4000 3000 50  0000 C CNN\nF 1 "1k" H 4000 3000 50  0000 C CNN\n'
        "\t1    4000 3000\n\t1    0    0    -1\n$EndComp\n")
TABLE = '(sym_lib_table\n  (lib (name proj)(type Legacy)(uri {uri})(options "")(descr ""))\n)\n'


def analyze(uri, with_cache=True, cache_lib=None, proj_lib=None, table=None, comp=COMP,
            cwd=None):
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "t.sch"), "w", encoding="utf-8") as f:
            f.write(HEAD + comp + "$EndSCHEMATC\n")
        if with_cache:
            with open(os.path.join(tmp, "t-cache.lib"), "w", encoding="utf-8") as f:
                f.write(LIB_HEAD + (cache_lib or RES.format(name="OLIMEX_RCL_R")) + "#End Library\n")
        with open(os.path.join(tmp, "proj.lib"), "w", encoding="utf-8") as f:
            f.write(LIB_HEAD + (proj_lib or RES.format(name="R")) + "#End Library\n")
        with open(os.path.join(tmp, "sym-lib-table"), "w", encoding="utf-8") as f:
            f.write(table or TABLE.format(uri=uri))
        old = os.getcwd()
        if cwd:
            os.chdir(cwd)
        try:
            with redirect_stderr(StringIO()):
                return analyze_legacy_schematic(os.path.join(tmp, "t.sch"))
        finally:
            os.chdir(old)


def pins(result):
    comp = next(c for c in result["components"] if c["reference"] == "R1")
    return comp, {p["number"]: (round(p["x"], 4), round(p["y"], 4)) for p in comp["pins"]}


class SymLibTableWithCache(unittest.TestCase):
    # Pin 1 sits 300 mil from the part origin (the built-in R would put it at 150 mil).
    EXPECTED = {"1": (round(4000 * MIL, 4), round((3000 - 300) * MIL, 4)),
                "2": (round(4000 * MIL, 4), round((3000 + 300) * MIL, 4))}

    def test_project_lib_pins_with_cache_present(self):
        comp, got = pins(analyze("${KIPRJMOD}/proj.lib"))
        self.assertEqual(got, self.EXPECTED)
        self.assertNotEqual(comp.get("_pin_source"), "builtin")

    def test_unresolved_variable_entry_is_skipped(self):
        comp, got = pins(analyze("${UNSET_VAR}/proj.lib"))
        self.assertEqual(comp.get("_pin_source"), "builtin")

    def test_missing_library_file_is_skipped(self):
        comp, got = pins(analyze("${KIPRJMOD}/nope.lib"))
        self.assertEqual(comp.get("_pin_source"), "builtin")

    def test_without_cache_unchanged(self):
        comp, got = pins(analyze("${KIPRJMOD}/proj.lib", with_cache=False))
        self.assertEqual(got, self.EXPECTED)

    def test_library_wins_over_cache_copy_of_the_same_symbol(self):
        # cache keeps the symbol as proj_R with 200 mil pins; the library has 300 mil pins
        cache = RES.format(name="proj_R").replace("300", "200")
        comp, got = pins(analyze("${KIPRJMOD}/proj.lib", cache_lib=cache))
        self.assertEqual(got, self.EXPECTED)

    def test_relative_uri_is_relative_to_the_project(self):
        comp, got = pins(analyze("proj.lib", cwd=tempfile.gettempdir()))
        self.assertEqual(got, self.EXPECTED)

    def test_bad_entry_does_not_hide_later_entries(self):
        table = ("(sym_lib_table\n  (lib (name bad)(type Legacy)(uri))\n"
                 "  (lib (name dir)(type Legacy)(uri ${KIPRJMOD}))\n"
                 "  (lib (name proj)(type Legacy)(uri ${KIPRJMOD}/proj.lib)(options \"\")(descr \"\"))\n)\n")
        comp, got = pins(analyze(None, table=table))
        self.assertEqual(got, self.EXPECTED)

    def test_table_symbols_do_not_break_a_unique_cache_suffix(self):
        # bare `Q` maps to the cache symbol OLIMEX_Q; the library's X_Q must not make it ambiguous
        q = RES.format(name="OLIMEX_Q").replace("300", "100")
        lib = RES.format(name="X_Q")
        q_comp = COMP.replace("proj:R", "Q")
        comp, got = pins(analyze("${KIPRJMOD}/proj.lib", cache_lib=q, proj_lib=lib, comp=q_comp))
        self.assertEqual(comp.get("_pin_source"), "suffix_match")
        self.assertEqual(got["1"][1], round((3000 - 100) * MIL, 4))


if __name__ == "__main__":
    unittest.main()
