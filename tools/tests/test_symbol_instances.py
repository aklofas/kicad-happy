"""Which reference, unit, value and footprint a placed symbol shows, as KiCad 10 loads it: the
instance whose path equals the sheet's full path (root sheet included), KiCad 6 per-instance
values and footprints, KiCad's fallback when a path has no instance, and "~" as an empty field.
Expected values are kicad-cli 10.0.6 netlist / BOM exports of the same files."""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from kicad_core.instances import resolve_instance  # noqa: E402
from schematic.hierarchy import parse_all_sheets  # noqa: E402
from schematic.pipeline import analyze_schematic  # noqa: E402

ROOT_UUID = "00000000-0000-4000-8000-0001000000e0"
CHILD_UUID = "00000000-0000-4000-8000-0026000000e0"

R_LIB = ('(symbol "Device:R" (pin_numbers hide) (pin_names (offset 0)) (in_bom yes) (on_board yes)'
         ' (property "Reference" "R" (at 0 0 0)) (property "Value" "R" (at 0 0 0))'
         ' (property "Footprint" "" (at 0 0 0)) (property "Datasheet" "" (at 0 0 0))'
         ' (symbol "R_1_1"'
         ' (pin passive line (at 0 3.81 270) (length 1.27) (name "~") (number "1"))'
         ' (pin passive line (at 0 -3.81 90) (length 1.27) (name "~") (number "2"))))')

# a global power symbol whose one pin is a hidden power input named +3V3
PWR_LIB = ('(symbol "power:+3.3V" (power) (pin_names (offset 0)) (in_bom yes) (on_board yes)'
           ' (property "Reference" "#PWR" (at 0 0 0)) (property "Value" "+3.3V" (at 0 0 0))'
           ' (symbol "+3.3V_1_1" (pin power_in line (at 0 0 90) (length 0) hide'
           ' (name "+3V3") (number "1"))))')


def sym(uuid, ref, value, x, *, fp="", ds="", inst="", lib_id="Device:R", pins=("1", "2")):
    pl = " ".join(f'(pin "{p}" (uuid "{uuid[:-3]}{i:03d}"))' for i, p in enumerate(pins, 100))
    return (f'(symbol (lib_id "{lib_id}") (at {x} 50 0) (unit 1) (in_bom yes) (on_board yes)'
            f' (uuid "{uuid}") (property "Reference" "{ref}" (at {x} 50 0))'
            f' (property "Value" "{value}" (at {x} 52 0)) (property "Footprint" "{fp}" (at {x} 50 0))'
            f' (property "Datasheet" "{ds}" (at {x} 50 0)) {pl}{inst})')


def sheet(uuid, fname, x):
    return (f'(sheet (at {x} 80) (size 20 10) (uuid "{uuid}")'
            f' (property "Sheet name" "s{x}" (at {x} 79 0))'
            f' (property "Sheet file" "{fname}" (at {x} 91 0)))')


def sch(version, uuid, body, libs=(R_LIB,), tail=""):
    return (f'(kicad_sch (version {version}) (generator "eeschema") (uuid "{uuid}") (paper "A4")'
            f' (lib_symbols {" ".join(libs)}) {body} {tail})\n')


def u(n):
    return f"00000000-0000-4000-8000-{n:012d}"


def f1_root():
    """Format 20250114 root: R? with a root-path instance R5; R7 whose only instance is from
    project "other" (R9); R2 with instances zzz:R11 then f1_root:R12; R3 with no instances.
    kicad-cli: R3 R5 R9 R12."""
    def inst(*ps):
        return (" (instances " + " ".join(f'(project "{p}" (path "{path}" (reference "{r}")'
                                          f' (unit 1)))' for p, path, r in ps) + ")")
    body = " ".join([
        sym(u(10), "R?", "1k", 50, inst=inst(("f1_root", "/" + ROOT_UUID, "R5"))),
        sym(u(20), "R7", "1k", 70, inst=inst(("other", "/" + u(255), "R9"))),
        sym(u(30), "R2", "1k", 90, inst=inst(("zzz", "/" + u(254), "R11"),
                                             ("f1_root", "/" + u(253), "R12"))),
        sym(u(40), "R3", "1k", 110)])
    return {"f1_root.kicad_sch": sch(20250114, ROOT_UUID, body,
                                     tail='(sheet_instances (path "/" (page "1")))')}


def f1_k6(version=20211123):
    """KiCad 6 root: R1 (Value "") whose symbol_instances give R3 / 4k7 / R_0603; R1 (10k) whose
    instance value and footprint are "~"; a child sheet R1 (1k) whose instance gives R20 / 22k.
    kicad-cli: R3 4k7 Resistor_SMD:R_0603_1608Metric; R4 10k; R20 22k."""
    si = (f'(symbol_instances'
          f' (path "/{u(17)}" (reference "R3") (unit 1) (value "4k7")'
          f' (footprint "Resistor_SMD:R_0603_1608Metric"))'
          f' (path "/{u(20)}" (reference "R4") (unit 1) (value "~") (footprint "~"))'
          f' (path "/{u(160)}/{u(23)}" (reference "R20") (unit 1) (value "22k") (footprint "")))')
    tail = (f'(sheet_instances (path "/" (page "1")) (path "/{u(160)}" (page "2"))) {si}')
    root = " ".join([sym(u(17), "R1", "", 50), sym(u(20), "R1", "10k", 70),
                     sheet(u(160), "child.kicad_sch", 100)])
    return {"f1_k6.kicad_sch": sch(version, ROOT_UUID, root, tail=tail),
            "child.kicad_sch": sch(version, CHILD_UUID, sym(u(23), "R1", "1k", 50))}


def repeated_k6(ax=100, bx=140):
    """KiCad 6 root with one child sheet placed twice: sheet A (first in the file, page 3) at
    x = ax and sheet B (page 2) at x = bx.  The child's R1 gets R10 / 1k on A and R11 / 2k on B.
    KiCad applies the values to the one symbol sheet by sheet in hierarchy order, child sheets
    sorted by position (page numbers are not applied yet), so the last sheet's value shows on
    both.  kicad-cli: ax=100, bx=140 -> R10 2k, R11 2k; ax=140, bx=100 -> R10 1k, R11 1k."""
    a, b = u(170), u(180)
    si = (f'(symbol_instances (path "/{a}/{u(23)}" (reference "R10") (unit 1) (value "1k")'
          f' (footprint "")) (path "/{b}/{u(23)}" (reference "R11") (unit 1) (value "2k")'
          f' (footprint "")))')
    tail = (f'(sheet_instances (path "/" (page "1")) (path "/{a}" (page "3"))'
            f' (path "/{b}" (page "2"))) {si}')
    root = sheet(a, "child.kicad_sch", ax) + " " + sheet(b, "child.kicad_sch", bx)
    return {"rep.kicad_sch": sch(20211123, ROOT_UUID, root, tail=tail),
            "child.kicad_sch": sch(20211123, CHILD_UUID, sym(u(23), "R1", "", 50))}


def shared_uuid_k6():
    """KiCad 6 root with two different child files whose resistor carries the same uuid (a
    copied sheet file): instances give R2 / 100R on sheet A (a.kicad_sch) and R5 / 10k on
    sheet B (b.kicad_sch).  They are two symbols, each keeping its own instance value.
    kicad-cli: R2 100R; R5 10k."""
    a, b = u(170), u(180)
    si = (f'(symbol_instances (path "/{a}/{u(23)}" (reference "R2") (unit 1) (value "100R")'
          f' (footprint "")) (path "/{b}/{u(23)}" (reference "R5") (unit 1) (value "10k")'
          f' (footprint "")))')
    tail = (f'(sheet_instances (path "/" (page "1")) (path "/{a}" (page "2"))'
            f' (path "/{b}" (page "3"))) {si}')
    root = sheet(a, "a.kicad_sch", 100) + " " + sheet(b, "b.kicad_sch", 140)
    return {"sh.kicad_sch": sch(20211123, ROOT_UUID, root, tail=tail),
            "a.kicad_sch": sch(20211123, CHILD_UUID, sym(u(23), "R1", "", 50)),
            "b.kicad_sch": sch(20211123, u(27), sym(u(23), "R1", "", 50))}


def tilde(version):
    """R1 with Value "~" and Datasheet "~"; R2 whose Footprint is "~".
    kicad-cli at 20250114: R1 value "" datasheet ""; R2 footprint ""."""
    body = (sym(u(50), "R1", "~", 50, ds="~", inst=(
                f' (instances (project "t" (path "/{ROOT_UUID}" (reference "R1") (unit 1))))'))
            + " " + sym(u(60), "R2", "1k", 70, fp="~", inst=(
                f' (instances (project "t" (path "/{ROOT_UUID}" (reference "R2") (unit 1))))')))
    return {"t.kicad_sch": sch(version, ROOT_UUID, body,
                               tail='(sheet_instances (path "/" (page "1")))')}


def power_k6():
    """KiCad 6 root: R1 pin 1 on a power:+3.3V placement whose Value is "" and whose
    symbol_instances value is "+3.3V"; its hidden power pin is +3V3.  KiCad applies the instance
    value, then renames the legacy power symbol after its pin.  kicad-cli: net +3V3 = R1.1."""
    si = (f'(symbol_instances (path "/{u(70)}" (reference "R1") (unit 1) (value "1k")'
          f' (footprint "")) (path "/{u(80)}" (reference "#PWR01") (unit 1) (value "+3.3V")'
          f' (footprint "")))')
    body = (sym(u(70), "R1", "1k", 50) + f' (wire (pts (xy 50 46.19) (xy 50 40)) (uuid "{u(90)}"))'
            + " " + sym(u(80), "#PWR01", "", 50, lib_id="power:+3.3V", pins=("1",))
            .replace("(at 50 50 0)", "(at 50 40 0)", 1))
    return {"p.kicad_sch": sch(20211123, ROOT_UUID, body, libs=(R_LIB, PWR_LIB),
                               tail=f'(sheet_instances (path "/" (page "1"))) {si}')}


def write(tmp, files):
    for name, text in files.items():
        with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
            f.write(text)


def components(files, root):
    """(reference, value, footprint) per placed symbol, from parse_all_sheets."""
    with tempfile.TemporaryDirectory() as tmp:
        write(tmp, files)
        with redirect_stderr(StringIO()):
            parsed = parse_all_sheets(os.path.join(tmp, root))
    return sorted((c["reference"], c["value"], c["footprint"]) for c in parsed["components"])


def analyze(files, root):
    with tempfile.TemporaryDirectory() as tmp:
        write(tmp, files)
        with redirect_stderr(StringIO()):
            return analyze_schematic(os.path.join(tmp, root))


class ResolveInstanceRuleTest(unittest.TestCase):
    """KiCad's rule (sch_symbol.cpp GetRef / AddHierarchicalReference,
    sch_sheet_path.cpp CheckForMissingSymbolInstances)."""

    def cand(self, path, project, ref):
        return {"path": path, "project": project, "reference": ref, "unit": 1}

    def test_exact_path_wins_last_duplicate(self):
        cands = [self.cand("/a/b", "p", "R1"), self.cand("/a/c", "p", "R2"),
                 self.cand("/A/B", "q", "R3")]
        self.assertEqual(resolve_instance(cands, "/a/b", "p")["reference"], "R3")

    def test_missing_path_takes_first_of_project_then_first(self):
        cands = [self.cand("/x", "zzz", "R11"), self.cand("/y", "proj", "R12"),
                 self.cand("/z", "proj", "R13")]
        self.assertEqual(resolve_instance(cands, "/a", "proj")["reference"], "R12")
        self.assertEqual(resolve_instance(cands, "/a", "other")["reference"], "R11")

    def test_no_candidates(self):
        self.assertIsNone(resolve_instance([], "/a", "proj"))


class SymbolInstanceTest(unittest.TestCase):
    def test_root_sheet_symbols_take_their_instance(self):
        refs = [c[0] for c in components(f1_root(), "f1_root.kicad_sch")]
        self.assertEqual(refs, ["R12", "R3", "R5", "R9"])

    def test_kicad6_instance_value_and_footprint(self):
        self.assertEqual(components(f1_k6(), "f1_k6.kicad_sch"), [
            ("R20", "22k", ""),
            ("R3", "4k7", "Resistor_SMD:R_0603_1608Metric"),
            ("R4", "10k", "")])

    def test_stale_symbol_instances_in_newer_file_ignored(self):
        # a 20221004 root never applies (symbol_instances); its symbols have no inline
        # instances, so KiCad keeps the placed fields. kicad-cli: R1 "" ; R1 10k ; R1 1k
        self.assertEqual(components(f1_k6(20221004), "f1_k6.kicad_sch"), [
            ("R1", "", ""), ("R1", "10k", ""), ("R1", "1k", "")])

    def test_repeated_kicad6_sheet_takes_the_last_sheets_value(self):
        self.assertEqual(components(repeated_k6(), "rep.kicad_sch"),
                         [("R10", "2k", ""), ("R11", "2k", "")])
        self.assertEqual(components(repeated_k6(140, 100), "rep.kicad_sch"),
                         [("R10", "1k", ""), ("R11", "1k", "")])

    def test_copied_sheet_files_keep_their_own_values(self):
        self.assertEqual(components(shared_uuid_k6(), "sh.kicad_sch"),
                         [("R2", "100R", ""), ("R5", "10k", "")])

    def test_tilde_is_an_empty_field_before_20250318(self):
        r = analyze(tilde(20250114), "t.kicad_sch")
        by_ref = {c["reference"]: c for c in r["components"]}
        self.assertEqual(by_ref["R1"]["value"], "")
        self.assertEqual(by_ref["R1"]["datasheet"], "")
        self.assertEqual(by_ref["R2"]["footprint"], "")

    def test_tilde_is_literal_from_20250318(self):
        # sch_io_kicad_sexpr_parser.cpp maps "~" only when the file version is < 20250318
        r = analyze(tilde(20250318), "t.kicad_sch")
        by_ref = {c["reference"]: c for c in r["components"]}
        self.assertEqual(by_ref["R1"]["value"], "~")
        self.assertEqual(by_ref["R2"]["footprint"], "~")

    def test_kicad6_power_value_applied_before_legacy_rename(self):
        r = analyze(power_k6(), "p.kicad_sch")
        net = next(n for n, d in r["nets"].items()
                   if any(p["component"] == "R1" and p["pin_number"] == "1" for p in d["pins"]))
        self.assertEqual(net, "+3V3")


if __name__ == "__main__":
    unittest.main()
