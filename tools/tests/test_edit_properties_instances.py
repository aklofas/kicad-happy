"""BOM write-back tools find a part by the reference KiCad shows, and write a repeated sheet once."""
import contextlib, io, json, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "bom" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import edit_properties, sync_datasheet_urls
from kicad_core import sexp

SHARED = ('(project "p" (path "/root-uuid/s1" (reference "C4") (unit 1)) '
          '(path "/root-uuid/s2" (reference "C7") (unit 1)))')


def sym(ref, uuid="u1", instances="", unit=1, props=""):
    return (f'\t(symbol (lib_id "Device:C") (at 10 10 0) (unit {unit})\n'
            f'\t\t(uuid "{uuid}")\n'
            f'\t\t(property "Reference" "{ref}" (at 0 0 0))\n' + props
            + (f'\t\t(instances {instances})\n' if instances else "") + '\t)\n')


def sch(*symbols):
    return ('(kicad_sch (version 20231120) (generator "eeschema")\n\t(uuid "root-uuid")\n'
            + "".join(symbols) + ')\n')


def actions(log, action):
    return [e for e in log if e["action"] == action]


class SharedSymbolTest(unittest.TestCase):
    def test_instance_ref_edits_shared_symbol_once(self):
        out, log = edit_properties.apply_updates(sch(sym("C4", instances=SHARED)), {"C7": {"MPN": "X"}})
        self.assertEqual(out.count('"MPN" "X"'), 1)
        self.assertEqual(actions(log, "error"), [])
        (w,) = actions(log, "warning")
        self.assertIn("C4", w["message"])
        self.assertIn("C7", w["message"])

    def test_file_reference_on_repeated_sheet_warns(self):
        out, log = edit_properties.apply_updates(sch(sym("C4", instances=SHARED)), {"C4": {"MPN": "X"}})
        self.assertEqual(out.count('"MPN" "X"'), 1)
        self.assertEqual(len(actions(log, "warning")), 1)

    def test_dry_run_one_would_insert(self):
        _, log = edit_properties.apply_updates(sch(sym("C4", instances=SHARED)), {"C7": {"MPN": "X"}},
                                               dry_run=True)
        self.assertEqual(len(actions(log, "would_insert")), 1)
        self.assertEqual(len(actions(log, "warning")), 1)

    def test_conflicting_values_refused(self):
        t = sch(sym("C4", instances=SHARED))
        out, log = edit_properties.apply_updates(t, {"C4": {"MPN": "A"}, "C7": {"MPN": "B"}})
        (e,) = actions(log, "error")
        self.assertIn("C4", e["message"])
        self.assertIn("C7", e["message"])
        self.assertNotIn("MPN", out)

    def test_same_value_through_two_instances_is_one_edit(self):
        out, log = edit_properties.apply_updates(sch(sym("C4", instances=SHARED)),
                                                 {"C4": {"MPN": "A"}, "C7": {"MPN": "A"}})
        self.assertEqual(out.count('"MPN" "A"'), 1)
        self.assertEqual(actions(log, "error"), [])


class OverReachTest(unittest.TestCase):
    def test_single_instance_has_no_warning(self):
        inst = '(project "p" (path "/root-uuid" (reference "R1") (unit 1)))'
        t = sch(sym("R1", instances=inst, props='\t\t(property "MPN" "OLD" (at 0 0 0))\n'))
        out, log = edit_properties.apply_updates(t, {"R1": {"MPN": "NEW"}})
        self.assertEqual(out, t.replace('"OLD"', '"NEW"'))
        self.assertEqual(actions(log, "warning"), [])

    def test_question_mark_file_reference_still_reachable(self):
        inst = '(project "p" (path "/root-uuid" (reference "R5") (unit 1)))'
        t = sch(sym("R?", instances=inst))
        for key in ("R5", "R?"):
            out, log = edit_properties.apply_updates(t, {key: {"MPN": "X"}})
            self.assertEqual(out.count('"MPN" "X"'), 1, key)
            self.assertEqual(actions(log, "error"), [], key)

    def test_multi_unit_symbol_edits_both_units_without_warning(self):
        inst = '(project "p" (path "/root-uuid" (reference "U1") (unit {u})))'
        t = sch(sym("U1", "a", inst.format(u=1), unit=1), sym("U1", "b", inst.format(u=2), unit=2))
        out, log = edit_properties.apply_updates(t, {"U1": {"MPN": "X"}})
        self.assertEqual(out.count('"MPN" "X"'), 2)
        self.assertEqual(actions(log, "warning"), [])

    def test_unknown_reference_still_an_error(self):
        _, log = edit_properties.apply_updates(sch(sym("C4")), {"C9": {"MPN": "X"}})
        self.assertEqual(len(actions(log, "error")), 1)


class SyncTest(unittest.TestCase):
    def test_two_blocks_same_stale_reference_keep_their_own_url(self):
        def part(inst_ref, mpn, uuid):
            inst = f'(project "p" (path "/root-uuid" (reference "{inst_ref}") (unit 1)))'
            return sym("C4", uuid, inst, props=f'\t\t(property "MPN" "{mpn}" (at 0 0 0))\n'
                                               '\t\t(property "Datasheet" "" (at 0 0 0))\n')
        parts = {m: {"status": "ok", "datasheet_url": f"https://e.com/{m}.pdf", "references": [],
                     "source": "digikey"} for m in ("A", "B")}
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / "datasheets").mkdir()
            (proj / "datasheets" / "manifest.json").write_text(json.dumps({"parts": parts}), encoding="utf-8")
            root = proj / "root.kicad_sch"
            root.write_text(sch(part("C4", "A", "u1"), part("C8", "B", "u2")), encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                sync_datasheet_urls.sync_datasheet_urls(str(root))
            tree = sexp.parse(root.read_text(encoding="utf-8"))
            got = [{q[1]: q[2] for q in sexp.find_all(s, "property")}["Datasheet"]
                   for s in sexp.find_all(tree, "symbol")]
        self.assertEqual(got, ["https://e.com/A.pdf", "https://e.com/B.pdf"])


if __name__ == "__main__":
    unittest.main()
