"""LB-001 counts one alias per drawn label name: a net reaching the same child label through
several sheet instances (`/A/SIG`, `/B/SIG`) carries one alias, not one per instance."""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT))

from tools.tests.test_legacy_hierarchy import analyze, hlabel, sheet, wire  # noqa: E402
from schematic.pipeline import analyze_schematic  # noqa: E402


def lb001(result):
    return [f for f in result["findings"] if f.get("rule_id") == "LB-001"]


def child(name):
    return hlabel(1000, 500, name)


def legacy(extra_sheet=None):
    pins = [("SIG", 3000, 2000), ("SIG", 5000, 2000)]
    root = (wire(3000, 2000, 6000, 2000)
            + sheet("5A000001", "a", "child.sch", [pins[0]])
            + sheet("5A000002", "b", "child.sch", [pins[1]]))
    files = {"root.sch": root, "child.sch": child("SIG")}
    if extra_sheet:
        files["root.sch"] += sheet("5A000003", "c", "other.sch", [("DATA", 6000, 2000)])
        files["other.sch"] = child("DATA")
    return analyze(files)


class LegacyTest(unittest.TestCase):
    def test_same_label_through_two_instances_is_not_an_alias(self):
        self.assertEqual(lb001(legacy()), [])

    def test_two_drawn_names_are_an_alias_listed_once_each(self):
        found = lb001(legacy(extra_sheet=True))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["aliases"], ["DATA", "SIG"])

    def test_net_labels_do_not_leak_internal_keys(self):
        for net in legacy(extra_sheet=True)["nets"].values():
            for lbl in net["labels"]:
                self.assertFalse([k for k in lbl if k.startswith("_bare")])


def sheet_block(uuid, name, fname, pin, x, y):
    return (f'(sheet (at {x} 50) (size 20 20) (uuid "{uuid}")\n'
            f'  (property "Sheetname" "{name}" (at {x} 48 0))\n'
            f'  (property "Sheetfile" "{fname}" (at {x} 72 0))\n'
            f'  (pin "{pin}" input (at {x} {y} 180) (uuid "{uuid[:-1]}9")))\n')


MODERN_HEAD = '(kicad_sch (version 20231120) (generator "eeschema") (uuid "00000000-0000-0000-0000-000000000000") (paper "A4")\n'


def modern(extra_sheet=False):
    root = (MODERN_HEAD + '(wire (pts (xy 100 60) (xy 160 60)) (uuid "00000000-0000-0000-0000-0000000000a1"))\n'
            + sheet_block("11111111-1111-1111-1111-111111111111", "a", "child.kicad_sch", "SIG", 100, 60)
            + sheet_block("22222222-2222-2222-2222-222222222222", "b", "child.kicad_sch", "SIG", 130, 60))
    files = {"root.kicad_sch": root + ")\n",
             "child.kicad_sch": MODERN_HEAD + '(hierarchical_label "SIG" (shape input) (at 10 10 0) (uuid "33333333-3333-3333-3333-333333333331"))\n)\n'}
    if extra_sheet:
        files["root.kicad_sch"] = root + sheet_block("44444444-4444-4444-4444-444444444444", "c", "other.kicad_sch", "DATA", 160, 60) + ")\n"
        files["other.kicad_sch"] = MODERN_HEAD + '(hierarchical_label "DATA" (shape input) (at 10 10 0) (uuid "33333333-3333-3333-3333-333333333332"))\n)\n'
    with tempfile.TemporaryDirectory() as tmp:
        for name, body in files.items():
            Path(tmp, name).write_text(body, encoding="utf-8")
        with redirect_stderr(StringIO()):
            return analyze_schematic(os.path.join(tmp, "root.kicad_sch"))


class ModernTest(unittest.TestCase):
    def test_same_label_through_two_instances_is_not_an_alias(self):
        self.assertEqual(lb001(modern()), [])

    def test_two_drawn_names_are_an_alias_listed_once_each(self):
        found = lb001(modern(extra_sheet=True))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["aliases"], ["DATA", "SIG"])


if __name__ == "__main__":
    unittest.main()
