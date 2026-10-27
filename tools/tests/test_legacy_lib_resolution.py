"""Legacy (KiCad 5) symbol library resolution.

A project's sym-lib-table is read even when a <stem>-cache.lib exists: a component `nick:Name`
takes its pins from the project library, not from the built-in table.  Without a cache the table
is searched by nickname; `~` in an `L` record reads as a space; a `DEF … P` symbol's power-input
pins join by name; libraries the analyzer cannot load, and cache copies that differ from a `.pro`
library, are reported in `diagnostics`."""
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


def analyze_files(files):
    """Analyze t.sch in a temp dir holding *files* ({name: text})."""
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in files.items():
            with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
                f.write(text)
        with redirect_stderr(StringIO()):
            return analyze_legacy_schematic(os.path.join(tmp, "t.sch"))


def lib_diagnostics(result):
    return [d for d in result["diagnostics"] if "librar" in d["message"]]


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

    def test_project_lib_pins_with_cache_present_has_no_library_diagnostic(self):
        self.assertEqual(lib_diagnostics(analyze("${KIPRJMOD}/proj.lib")), [])

    def test_unresolved_variable_entry_is_skipped(self):
        result = analyze("${UNSET_VAR}/proj.lib")
        comp, got = pins(result)
        self.assertEqual(comp.get("_pin_source"), "builtin")
        diags = lib_diagnostics(result)
        self.assertEqual(len(diags), 1)
        self.assertIn("'proj'", diags[0]["message"])
        self.assertIn("R1", diags[0]["message"])

    def test_missing_library_file_is_skipped(self):
        result = analyze("${KIPRJMOD}/nope.lib")
        comp, got = pins(result)
        self.assertEqual(comp.get("_pin_source"), "builtin")
        diags = lib_diagnostics(result)
        self.assertEqual(len(diags), 1)
        self.assertIn("'proj'", diags[0]["message"])

    def test_parenthesised_kiprjmod_resolves(self):
        # KiCad expands $(VAR) like ${VAR}
        result = analyze('"$(KIPRJMOD)/proj.lib"')
        comp, got = pins(result)
        self.assertEqual(got, self.EXPECTED)
        self.assertEqual(lib_diagnostics(result), [])

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


PIN_NAMED = """DEF {name} U 0 40 Y Y 1 F N
F0 "U" 0 0 50 H V C CNN
DRAW
X {pin1} 1 -300 0 100 R 50 50 1 1 I
X B 2 300 0 100 L 50 50 1 1 O
ENDDRAW
ENDDEF
"""


def comp_rec(lib_id, ref, x=4000, y=3000):
    return (f"$Comp\nL {lib_id} {ref}\nU 1 1 5F00{x:04d}\nP {x} {y}\n"
            f'F 0 "{ref}" H {x} {y} 50  0000 C CNN\nF 1 "V" H {x} {y} 50  0000 C CNN\n'
            f"\t1    {x} {y}\n\t1    0    0    -1\n$EndComp\n")


def legacy_table(*entries):
    return ("(sym_lib_table\n" + "".join(
        f'  (lib (name "{n}")(type Legacy)(uri "${{KIPRJMOD}}/{f}")(options "")(descr ""))\n'
        for n, f in entries) + ")\n")


class TableWithoutCache(unittest.TestCase):
    """KiCad 5 resolves `nick:name` through the table row named nick (sch_component.cpp Resolve)."""

    def test_nickname_selects_its_library(self):
        result = analyze_files({
            "t.sch": HEAD + comp_rec("coco2:74LS244", "IC11") + "$EndSCHEMATC\n",
            "coco2.lib": LIB_HEAD + PIN_NAMED.format(name="74LS244", pin1="~1G") + "#End Library\n",
            "74ls244.lib": LIB_HEAD + PIN_NAMED.format(name="74LS244", pin1="OEa") + "#End Library\n",
            "sym-lib-table": legacy_table(("coco2", "coco2.lib"), ("74ls244", "74ls244.lib")),
        })
        comp = next(c for c in result["components"] if c["reference"] == "IC11")
        self.assertEqual({p["number"]: p["name"] for p in comp["pins"]}["1"], "~1G")

    def test_tilde_in_library_id_reads_as_space(self):
        result = analyze_files({
            "t.sch": HEAD + comp_rec("OCP~Project:DM02", "U1") + "$EndSCHEMATC\n",
            "ocp.lib": LIB_HEAD + PIN_NAMED.format(name="DM02", pin1="EN") + "#End Library\n",
            "sym-lib-table": legacy_table(("OCP Project", "ocp.lib")),
        })
        comp = next(c for c in result["components"] if c["reference"] == "U1")
        self.assertEqual(comp["lib_id"], "OCP Project:DM02")
        self.assertEqual({p["number"]: p["name"] for p in comp["pins"]}["1"], "EN")


POWER_PART = """DEF {name} U 0 40 Y Y 1 F {flag}
F0 "U" 0 0 50 H V C CNN
DRAW
X VCC 1 -300 0 100 R 50 50 1 1 W{shape}
X OUT 2 300 0 100 L 50 50 1 1 O
ENDDRAW
ENDDEF
"""


def net_of(result, ref, pin):
    for name, net in result["nets"].items():
        if any(p["component"] == ref and p["pin_number"] == pin for p in net["pins"]):
            return name
    return None


class PowerFlagInDef(unittest.TestCase):
    """A power-input pin is global when its symbol is a power symbol (`DEF … P`) or the pin is
    invisible (KiCad SCH_PIN::IsGlobalPower)."""

    def build(self, flag):
        cache = (LIB_HEAD + POWER_PART.format(name="REG", flag=flag, shape="")
                 + POWER_PART.format(name="IC", flag="N", shape=" N") + "#End Library\n")
        return analyze_files({
            "t.sch": HEAD + comp_rec("REG", "U1", 2000, 2000) + comp_rec("IC", "U2", 6000, 5000)
                     + "$EndSCHEMATC\n",
            "t-cache.lib": cache,
        })

    def test_power_flagged_part_joins_by_pin_name(self):
        result = self.build("P")
        self.assertIsNotNone(net_of(result, "U1", "1"))
        self.assertEqual(net_of(result, "U1", "1"), net_of(result, "U2", "1"))

    def test_normal_part_with_visible_pin_stays_apart(self):
        result = self.build("N")
        self.assertNotEqual(net_of(result, "U1", "1"), net_of(result, "U2", "1"))

    def test_internal_key_is_not_emitted(self):
        result = self.build("P")
        comp = next(c for c in result["components"] if c["reference"] == "U1")
        self.assertFalse([k for k in comp if k.startswith("_global")])


class CacheAgainstProjectLibrary(unittest.TestCase):
    """KiCad 10 opens a pre-table project through the rescue dialog, whose default keeps the
    cache copy of a symbol that conflicts with the project library."""

    PRO = "update=0\n[eeschema]\nversion=1\nLibDir=\n[eeschema/libraries]\nLibName1=proj\n"

    def build(self, proj_offset):
        return analyze_files({
            "t.sch": HEAD + COMP.replace("proj:R", "R") + "$EndSCHEMATC\n",
            "t-cache.lib": LIB_HEAD + RES.format(name="R").replace("300", "200") + "#End Library\n",
            "proj.lib": LIB_HEAD + RES.format(name="R").replace("300", proj_offset) + "#End Library\n",
            "t.pro": self.PRO,
        })

    def test_conflicting_copy_keeps_cache_pins_and_reports_once(self):
        result = self.build("300")
        comp, got = pins(result)
        self.assertEqual(got["1"][1], round((3000 - 200) * MIL, 4))
        diags = lib_diagnostics(result)
        self.assertEqual(len(diags), 1)
        self.assertIn("proj", diags[0]["message"])
        self.assertIn("cache", diags[0]["effect"])

    def test_identical_copy_has_no_diagnostic(self):
        self.assertEqual(lib_diagnostics(self.build("200")), [])


if __name__ == "__main__":
    unittest.main()
