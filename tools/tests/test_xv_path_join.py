"""Schematic/PCB cross-checks pair parts as KiCad's Update PCB does.

Expected values follow KiCad 10.0.7 pcbnew/netlist_reader/board_netlist_updater.cpp: a
footprint belongs to the symbol whose sheet path (below the root) plus one of its unit uuids
equals the footprint's (path); the reference is used only when nothing matches by path.
fpidsEquivalent: a schematic footprint without a library nickname matches on the name alone,
otherwise the whole lib:name must be equal. The netlist (netlist_exporter_xml.cpp) gives a
multi-unit part the footprint of its lowest unit that has one, and one component per
reference; Update PCB copies the Value and fields exactly.
"""
import copy, os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import cross_analysis as ca  # noqa: E402
import cross_verify as cv  # noqa: E402
from kicad_core.pairing import pair_by_path  # noqa: E402
from schematic.pipeline import analyze_schematic  # noqa: E402
from tools.tests.test_legacy_hierarchy import analyze as analyze_legacy, comp, sheet  # noqa: E402

LIB = '''(lib_symbols
 (symbol "Device:R" (pin_numbers (hide yes)) (pin_names (offset 0)) (exclude_from_sim no) (in_bom yes) (on_board yes)
  (property "Reference" "R" (at 0 0 0)) (property "Value" "R" (at 0 0 0))
  (property "Footprint" "" (at 0 0 0)) (property "Datasheet" "" (at 0 0 0))
  (symbol "R_1_1"
   (pin passive line (at 0 3.81 270) (length 1.27) (name "~") (number "1"))
   (pin passive line (at 0 -3.81 90) (length 1.27) (name "~") (number "2")))))'''

ROOT_UUID = "00000000-0000-4000-8000-0081000000e0"
S1 = "00000000-0000-4000-8000-00820000005e"
S2 = "00000000-0000-4000-8000-00830000005e"
R5_UUID = "00000000-0000-4000-8000-000000000801"
C_UUID = "00000000-0000-4000-8000-000000000802"


def _prop(name, val):
    return f'(property "{name}" "{val}" (at 0 0 0))'


def _sym(uid, ref, value, paths, at):
    inst = " ".join(f'(path "{p}" (reference "{r}") (unit 1))' for p, r in paths)
    return (f'(symbol (lib_id "Device:R") (at {at} 20 0) (unit 1) (exclude_from_sim no) (in_bom yes)'
            f' (on_board yes) (dnp no) (uuid "{uid}") {_prop("Reference", ref)} {_prop("Value", value)}'
            f' {_prop("Footprint", "Resistor_SMD:R_0603_1608Metric")} {_prop("Datasheet", "")}'
            f' (instances (project "xv" {inst})))')


def _sheet(uid, name, at):
    return (f'(sheet (at {at} 80) (size 20 10) (exclude_from_sim no) (in_bom yes) (on_board yes)'
            f' (dnp no) (uuid "{uid}") {_prop("Sheetname", name)} {_prop("Sheetfile", "child.kicad_sch")}'
            f' (instances (project "xv" (path "/{ROOT_UUID}" (page "2")))))')


def _doc(uuid, items, root=True):
    tail = '\n(sheet_instances (path "/" (page "1")))' if root else ""
    return (f'(kicad_sch (version 20250114) (generator "eeschema") (generator_version "9.0")'
            f' (uuid "{uuid}") (paper "A4")\n{LIB}\n' + "\n".join(items) + f"{tail})\n")


def write_project(tmp):
    rp = "/" + ROOT_UUID
    files = {
        "xv.kicad_sch": _doc(ROOT_UUID, [_sym(R5_UUID, "R5", "10k", [(rp, "R5")], 10),
                                         _sheet(S1, "s1", 50), _sheet(S2, "s2", 80)]),
        "child.kicad_sch": _doc("00000000-0000-4000-8000-0084000000e0",
                                [_sym(C_UUID, "C4", "1u", [(f"{rp}/{S1}", "C4"), (f"{rp}/{S2}", "C7")], 10)],
                                root=False),
        "xv.kicad_pro": '{"meta": {"filename": "xv.kicad_pro", "version": 3}, "schematic": {}}',
    }
    for name, text in files.items():
        with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
            f.write(text)
    return os.path.join(tmp, "xv.kicad_sch")


class InstancePathTest(unittest.TestCase):
    """components[].instance_path is the footprint (path) KiCad writes for that unit: the
    sheet uuids below the root, then the symbol uuid (kicad-cli 10.0.6 netlist of these
    files: sheetpath tstamps "/", "/S1/", "/S2/" plus the component tstamps)."""

    def test_modern_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stderr(StringIO()):
                r = analyze_schematic(write_project(tmp))
        got = {c["reference"]: c.get("instance_path") for c in r["components"]}
        self.assertEqual(got, {"R5": f"/{R5_UUID}", "C4": f"/{S1}/{C_UUID}",
                               "C7": f"/{S2}/{C_UUID}"})

    def test_legacy_paths(self):
        root = comp("R1", 1000, 2200, "5B000001") + sheet("5A000001", "child", "child.sch")
        r = analyze_legacy({"t.sch": root, "child.sch": comp("R2", 1000, 1000, "5C000001")})
        got = {c["reference"]: c.get("instance_path") for c in r["components"]}
        self.assertEqual(got, {"R1": "/5B000001", "R2": "/5A000001/5C000001"})


def _c(ref, uuid_path, value="10k", fp="Resistor_SMD:R_0603_1608Metric", unit=1, mpn="",
       ctype="resistor", pin_nets=None, uuid=None):
    return {"reference": ref, "value": value, "footprint": fp, "unit": unit, "mpn": mpn,
            "type": ctype, "uuid": uuid or uuid_path.rsplit("/", 1)[-1], "instance_path": uuid_path,
            "pin_nets": pin_nets or {}}


def _fp(ref, path, value="10k", lib="Resistor_SMD:R_0603_1608Metric", mpn=""):
    fp = {"reference": ref, "value": value, "library": lib, "footprint": lib, "mpn": mpn}
    if path is not None:
        fp["sch_path"] = path
    return fp


def _xv(sch_comps, fps):
    out = ca.check_cross_validation({"components": sch_comps}, {"footprints": fps})
    out += ca.check_mpn_parity({"components": sch_comps}, {"footprints": fps})
    return out


def _rules(findings, rule):
    return [f for f in findings if f["rule_id"] == rule]


class PairByPathTest(unittest.TestCase):
    def test_reannotated_schematic_pairs_by_path(self):
        out = _xv([_c("R5", "/U")], [_fp("R7", "/U")])
        xv1 = _rules(out, "XV-001")
        self.assertEqual(len(xv1), 1)
        self.assertEqual(xv1[0]["reason"], "reference_mismatch")
        self.assertEqual(xv1[0]["components"], ["R5"])
        self.assertIn("R7", xv1[0]["description"])
        self.assertFalse(any("but not" in f["summary"] for f in xv1))

    def test_repeated_sheet_pairs_each_instance(self):
        sch = [_c("C7", "/S2/U", value="1u"), _c("C4", "/S1/U", value="10u")]
        fps = [_fp("C4", "/S2/U", value="1u"), _fp("C7", "/S1/U", value="10u")]
        out = _xv(sch, fps)
        self.assertEqual(_rules(out, "XV-002"), [])
        self.assertEqual([f.get("reason") for f in _rules(out, "XV-001")], ["reference_mismatch"])
        self.assertEqual(_rules(out, "XV-001")[0]["components"], ["C4", "C7"])

    def test_footprint_without_path_falls_back_to_reference(self):
        self.assertEqual(_xv([_c("R1", "/U1")], [_fp("R1", None)]), [])
        self.assertEqual(_xv([_c("R1", "/U1")], [_fp("R1", "/stale")]), [])

    def test_path_match_is_case_insensitive_and_any_unit(self):
        sch = [_c("U1", "/S/AA01", unit=1), _c("U1", "/S/AA02", unit=2)]
        self.assertEqual(_xv(sch, [_fp("U1", "/s/aa02")]), [])

    def test_missing_and_extra_still_reported(self):
        out = _xv([_c("R1", "/U1"), _c("R2", "/U2")], [_fp("R1", "/U1"), _fp("R3", "/U3")])
        summaries = sorted(f["summary"] for f in _rules(out, "XV-001"))
        self.assertEqual(summaries, ["1 component(s) in PCB but not schematic",
                                     "1 component(s) in schematic but not PCB"])

    def test_pair_helper_shape(self):
        pairs, sch_only, pcb_only = pair_by_path(
            {"components": [_c("R5", "/U"), _c("R2", "/U2"), _c("#PWR01", "/P")]},
            {"footprints": [_fp("R7", "/U"), _fp("H1", None)]})
        self.assertEqual([(r, fp["reference"]) for r, fp in pairs], [("R5", "R7")])
        self.assertEqual(sch_only, {"R2"})
        self.assertEqual(pcb_only, {"H1"})


class FootprintParityTest(unittest.TestCase):
    def test_name_change_is_a_warning(self):
        out = _rules(_xv([_c("R1", "/U1")], [_fp("R1", "/U1", lib="Resistor_SMD:R_0402_1005Metric")]),
                     "XV-003")
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["severity"], out[0]["components"]), ("warning", ["R1"]))

    def test_nickname_only_is_info(self):
        out = _rules(_xv([_c("R1", "/U1"), _c("R2", "/U2")],
                         [_fp("R1", "/U1", lib="MyLib:R_0603_1608Metric"),
                          _fp("R2", "/U2", lib="R_0603_1608Metric")]), "XV-003")
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["severity"], out[0]["components"]), ("info", ["R1", "R2"]))

    def test_schematic_without_nickname_matches_on_name(self):
        out = _xv([_c("R1", "/U1", fp="R_0603_1608Metric")], [_fp("R1", "/U1")])
        self.assertEqual(_rules(out, "XV-003"), [])

    def test_lowest_unit_with_a_footprint(self):
        dip = "Package_DIP:DIP-14_W7.62mm"
        sch = [_c("U1", "/S/A2", fp=dip, unit=2), _c("U1", "/S/A1", fp="", unit=1),
               _c("U1", "/S/A3", fp="Package_SO:SOIC-14", unit=3)]
        self.assertEqual(_rules(_xv(sch, [_fp("U1", "/S/A1", lib=dip)]), "XV-003"), [])

    def test_blank_footprint_not_compared(self):
        self.assertEqual(_rules(_xv([_c("R1", "/U1", fp="")], [_fp("R1", "/U1")]), "XV-003"), [])

    def test_one_difference_reported_once(self):
        # KiCad gives every instance of a repeated sheet without per-instance refs the same reference.
        sch = [_c("D1", "/S1/U", fp="LED_SMD:LED_0603"), _c("D1", "/S2/U", fp="LED_SMD:LED_0603")]
        fps = [_fp("D401", "/S1/U", lib="LED_SMD:LED_0805"), _fp("D501", "/S2/U", lib="LED_SMD:LED_0805")]
        self.assertEqual(len(_rules(_xv(sch, fps), "XV-003")), 1)

    def test_compares_the_path_partner(self):
        sch = [_c("U1", "/A", fp="Package_SO:SOIC-8"), _c("U2", "/B", fp="Package_QFP:LQFP-64")]
        fps = [_fp("U2", "/A", lib="Package_SO:SOIC-8"), _fp("U1", "/B", lib="Package_QFP:LQFP-64")]
        self.assertEqual(_rules(_xv(sch, fps), "XV-003"), [])


class DuplicateReferenceTest(unittest.TestCase):
    """KiCad merges the symbols of one reference only for multi-unit library symbols
    (netlist_exporter_base.cpp: GetUnitCount() > 1); Update PCB compares every other footprint
    with its own symbol."""

    def test_two_single_unit_symbols_sharing_a_reference(self):
        cases = (
            ([_c("R1", "/A", value="10k"), _c("R1", "/B", value="4k7")],
             [_fp("R1", "/A", value="10k"), _fp("R1", "/B", value="4k7")]),
            ([_c("U1", "/A", fp="Package_SO:SOIC-8"), _c("U1", "/B", fp="Package_DIP:DIP-8")],
             [_fp("U1", "/A", lib="Package_SO:SOIC-8"), _fp("U1", "/B", lib="Package_DIP:DIP-8")]),
            ([_c("Q1", "/A", mpn="BSS138"), _c("Q1", "/B", mpn="2N7002")],
             [_fp("Q1", "/A", mpn="BSS138"), _fp("Q1", "/B", mpn="2N7002")]),
        )
        for sch, fps in cases:
            out = _xv(sch, fps)
            self.assertEqual([f for f in out if f["rule_id"] in ("XV-002", "XV-003", "XV-004")], [],
                             sch[0]["reference"])

    def test_multi_unit_part_still_merges(self):
        dip = "Package_DIP:DIP-14_W7.62mm"
        sch = [_c("U1", "/S/A1", fp="", unit=1, mpn=""), _c("U1", "/S/A2", fp=dip, unit=2, mpn="LM324N")]
        out = _xv(sch, [_fp("U1", "/S/A1", lib=dip, mpn="LM324N")])
        self.assertEqual([f for f in out if f["rule_id"] in ("XV-003", "XV-004")], [])
        out = _xv(sch, [_fp("U1", "/S/A1", lib="Package_SO:SOIC-14", mpn="LM324DR")])
        self.assertEqual(sorted(f["rule_id"] for f in out), ["XV-003", "XV-004"])

    def test_stale_footprint_of_a_used_reference_is_unlinked(self):
        out = _xv([_c("R5", "/U")], [_fp("R7", "/U"), _fp("R5", "/stale")])
        xv1 = {f.get("reason"): f for f in _rules(out, "XV-001")}
        self.assertEqual(xv1["unlinked_footprint"]["components"], ["R5"])
        self.assertEqual(xv1["unlinked_footprint"]["severity"], "info")
        self.assertFalse(any("but not schematic" in f["summary"] for f in xv1.values()))


class ValueSyncTest(unittest.TestCase):
    def test_never_synchronised_value_reported(self):
        out = _rules(_xv([_c("C1", "/U1", value="10uF", fp="Capacitor_SMD:C_0603_1608Metric")],
                         [_fp("C1", "/U1", value="C_0603_1608Metric", lib="Capacitor_SMD:C_0603_1608Metric")]),
                     "XV-002")
        self.assertEqual(len(out), 1)
        self.assertIn("never synchronised", out[0]["summary"])
        self.assertEqual(out[0]["severity"], "warning")


class MpnParityTest(unittest.TestCase):
    def test_mpn_drift(self):
        out = _rules(_xv([_c("Q1", "/U1", mpn="BSS138")], [_fp("Q1", "/U1", mpn="BSS138LT1G")]), "XV-004")
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["severity"], out[0]["components"]), ("warning", ["Q1"]))

    def test_no_finding_when_equal_blank_or_padded(self):
        for sch_mpn, pcb_mpn in (("BSS138", "BSS138"), ("BSS138", ""), ("", "BSS138"), (" BSS138 ", "BSS138")):
            out = _xv([_c("Q1", "/U1", mpn=sch_mpn)], [_fp("Q1", "/U1", mpn=pcb_mpn)])
            self.assertEqual(_rules(out, "XV-004"), [], (sch_mpn, pcb_mpn))

    def test_checks_run_entry(self):
        _, runs = ca.run_all_checks({"components": [], "findings": []}, {"footprints": []})
        self.assertIn("XV-004", [r["check"] for r in runs])
        _, runs = ca.run_all_checks({"components": [], "findings": []}, None)
        self.assertEqual([r for r in runs if r["check"] == "XV-004"][0]["ran"], False)


class DecouplingPackagesTest(unittest.TestCase):
    def _sch(self, comps, caps):
        return {"components": comps,
                "findings": [{"detector": "detect_decoupling", "rail": "+3V3", "capacitors": caps}]}

    def test_units_count_once(self):
        nets = {"1": "+3V3"}
        comps = [_c("U1", f"/A{u}", unit=u, ctype="ic", pin_nets=nets) for u in (1, 2, 3, 4)]
        comps.append(_c("U2", "/B", ctype="ic", pin_nets=nets))
        self.assertEqual(ca.check_decoupling_adequacy(self._sch(comps, [{}, {}]), None), [])
        out = ca.check_decoupling_adequacy(self._sch(comps, [{}]), None)
        self.assertIn("1 caps for 2 ICs", out[0]["summary"])

    def test_single_unit_parts_sharing_a_reference_stay_distinct(self):
        nets = {"1": "+3V3"}
        comps = [_c("U5", "/A", ctype="ic", pin_nets=nets), _c("U5", "/B", ctype="ic", pin_nets=nets)]
        out = ca.check_decoupling_adequacy(self._sch(comps, [{}]), None)
        self.assertIn("1 caps for 2 ICs", out[0]["summary"])

    def test_unannotated_parts_stay_distinct(self):
        nets = {"1": "+3V3"}
        comps = [_c("U?", "/A", ctype="ic", pin_nets=nets), _c("U?", "/B", ctype="ic", pin_nets=nets)]
        out = ca.check_decoupling_adequacy(self._sch(comps, [{}]), None)
        self.assertIn("1 caps for 2 ICs", out[0]["summary"])


class CrossVerifyTest(unittest.TestCase):
    def test_path_join(self):
        sch = {"components": [_c("R5", "/U"), _c("R2", "/U2")]}
        pcb = {"footprints": [_fp("R7", "/U", value="4k7"), _fp("R2", None)]}
        res = cv.check_component_matching(sch, pcb)
        self.assertEqual((res["matched"], res["orphans"], res["missing"]), (2, [], []))
        self.assertEqual([m["ref"] for m in res["value_mismatches"]], ["R5"])
        self.assertEqual([(m["ref"], m["pcb_ref"]) for m in res["reference_mismatches"]], [("R5", "R7")])


if __name__ == "__main__":
    unittest.main()
