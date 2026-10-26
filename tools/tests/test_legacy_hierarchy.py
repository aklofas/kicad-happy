"""Legacy (KiCad 5) hierarchy: a sheet pin joins the parent wire to the child's hierarchical
label of the same name, each sheet instance namespaces its labels as /<sheet timestamp>/NAME,
and a sheet used more than once contributes every instance's components, each taking its
reference from the symbol's `AR Path="/<sheet ts>/<symbol ts>"` record (else its `L`/`F0`)."""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from schematic.pipeline import analyze_legacy_schematic  # noqa: E402

HEAD = "EESchema Schematic File Version 4\nEELAYER 30 0\nEELAYER END\n$Descr A4 11693 8268\n$EndDescr\n"
LIB_HEAD = "EESchema-LIBRARY Version 2.4\n#encoding utf-8\n"

# Pin 1 sits 200 mil above the anchor and pin 2 200 mil below it (identity matrix 1 0 0 -1).
TWO_PIN_LIB = ("DEF T U 0 40 Y Y 1 F N\nF0 \"U\" 0 0 50 H V C CNN\nDRAW\n"
               "X TOP 1 0 200 100 D 50 50 1 1 P\nX BOT 2 0 -200 100 U 50 50 1 1 P\n"
               "ENDDRAW\nENDDEF\n")


def comp(ref, x, y, ts, ar=()):
    ar_lines = "".join(f'AR Path="{p}" Ref="{r}"  Part="1" \n' for p, r in ar)
    return (f"$Comp\nL t:T {ref}\nU 1 1 {ts}\nP {x} {y}\n{ar_lines}"
            f'F 0 "{ref}" H {x} {y} 50  0000 C CNN\nF 1 "V" H {x} {y} 50  0000 C CNN\n'
            f"\t1    {x} {y}\n\t1    0    0    -1\n$EndComp\n")


def sheet(ts, name, filename, pins=()):
    pin_lines = "".join(f'F{n} "{pname}" I L {px} {py} 60 \n'
                        for n, (pname, px, py) in enumerate(pins, start=2))
    return (f"$Sheet\nS 3000 1500 1000 1000\nU {ts}\n"
            f'F0 "{name}" 50\nF1 "{filename}" 50\n{pin_lines}$EndSheet\n')


def wire(x1, y1, x2, y2):
    return f"Wire Wire Line\n\t{x1} {y1} {x2} {y2}\n"


def hlabel(x, y, name):
    return f"Text HLabel {x} {y} 0    50   Input ~ 0\n{name}\n"


def analyze(files):
    """files: {filename: body}; the first entry is the root."""
    with tempfile.TemporaryDirectory() as tmp:
        for name, body in files.items():
            with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
                f.write(HEAD + body + "$EndSCHEMATC\n")
        root = next(iter(files))
        with open(os.path.join(tmp, Path(root).stem + "-cache.lib"), "w", encoding="utf-8") as f:
            f.write(LIB_HEAD + TWO_PIN_LIB + "#\n#End Library\n")
        with redirect_stderr(StringIO()):
            return analyze_legacy_schematic(os.path.join(tmp, root))


def net_of(result, ref, number):
    for name, net in result["nets"].items():
        for p in net.get("pins") or []:
            if p["component"] == ref and p["pin_number"] == number:
                return name
    return None


# A child sheet with one part whose pin 1 reaches the hierarchical label IN.
CHILD_R2 = comp("R2", 1000, 1000, "5C000001") + wire(1000, 800, 1000, 500) + hlabel(1000, 500, "IN")
CHILD_R3 = comp("R3", 1000, 1000, "5C000002") + wire(1000, 800, 1000, 500) + hlabel(1000, 500, "IN")


class SheetPinTest(unittest.TestCase):
    def test_sheet_pin_joins_parent_wire_and_child_label(self):
        root = (comp("R1", 1000, 2200, "5B000001") + wire(1000, 2000, 3000, 2000)
                + sheet("5A000001", "child", "child.sch", [("IN", 3000, 2000)]))
        r = analyze({"t.sch": root, "child.sch": CHILD_R2})
        self.assertEqual(net_of(r, "R1", "1"), "/5A000001/IN")
        self.assertEqual(net_of(r, "R2", "1"), "/5A000001/IN")

    def test_two_children_with_the_same_label_stay_apart(self):
        root = (sheet("A0000001", "c1", "c1.sch", [("IN", 3000, 2000)])
                + sheet("B0000001", "c2", "c2.sch", [("IN", 5000, 2000)]))
        r = analyze({"t.sch": root, "c1.sch": CHILD_R2, "c2.sch": CHILD_R3})
        self.assertEqual(net_of(r, "R2", "1"), "/A0000001/IN")
        self.assertEqual(net_of(r, "R3", "1"), "/B0000001/IN")


class RepeatedSheetTest(unittest.TestCase):
    def test_each_instance_takes_its_ar_reference(self):
        child = comp("R10", 1000, 1000, "5C000001",
                     ar=[("/AAAA0001/5C000001", "R10"), ("/BBBB0001/5C000001", "R11")])
        root = (sheet("AAAA0001", "ch1", "c.sch") + sheet("BBBB0001", "ch2", "c.sch"))
        r = analyze({"t.sch": root, "c.sch": child})
        self.assertEqual(sorted(c["reference"] for c in r["components"]), ["R10", "R11"])
        self.assertEqual(len(r["bom"]), 1)
        self.assertEqual(r["bom"][0]["quantity"], 2)
        self.assertEqual(sorted(r["bom"][0]["references"]), ["R10", "R11"])
        self.assertEqual(r["sheets_parsed"], 3)

    def test_instances_without_ar_keep_the_l_reference(self):
        root = (sheet("AAAA0001", "ch1", "c.sch") + sheet("BBBB0001", "ch2", "c.sch"))
        r = analyze({"t.sch": root, "c.sch": comp("R5", 1000, 1000, "5C000001")})
        self.assertEqual([c["reference"] for c in r["components"]], ["R5", "R5"])

    def test_ar_match_ignores_timestamp_case(self):
        child = comp("R10", 1000, 1000, "5c000001",
                     ar=[("/aaaa0001/5C000001", "R10"), ("/BBBB0001/5c000001", "R11")])
        root = (sheet("AAAA0001", "ch1", "c.sch") + sheet("bbbb0001", "ch2", "c.sch"))
        r = analyze({"t.sch": root, "c.sch": child})
        self.assertEqual(sorted(c["reference"] for c in r["components"]), ["R10", "R11"])


class RecursionTest(unittest.TestCase):
    def _recursion_diagnostics(self, r):
        return [d for d in r["diagnostics"] if d["effect"] == "recursive sheet skipped"]

    def test_sheet_that_lists_itself(self):
        root = comp("R1", 1000, 1000, "5B000001") + sheet("5A000001", "self", "t.sch")
        r = analyze({"t.sch": root})
        self.assertEqual(r["sheets_parsed"], 1)
        self.assertEqual(len(self._recursion_diagnostics(r)), 1)
        self.assertEqual([c["reference"] for c in r["components"]], ["R1"])

    def test_cycle_of_two(self):
        files = {
            "t.sch": sheet("5A000001", "a", "a.sch"),
            "a.sch": comp("R1", 1000, 1000, "5B000001") + sheet("5A000002", "b", "b.sch"),
            "b.sch": comp("R2", 1000, 1000, "5B000002") + sheet("5A000003", "a", "a.sch"),
        }
        r = analyze(files)
        self.assertEqual(r["sheets_parsed"], 3)
        self.assertEqual(len(self._recursion_diagnostics(r)), 1)
        self.assertEqual(sorted(c["reference"] for c in r["components"]), ["R1", "R2"])


class NamespaceHelperTest(unittest.TestCase):
    def test_labels_and_sheet_pins(self):
        from schematic.hierarchy import namespace_hierarchical_labels
        labels = [
            {"name": "IN", "type": "hierarchical_label"},
            {"name": "OUT", "type": "hierarchical_label", "_sheet_uuid": "u2"},
            {"name": "LOCAL", "type": "label"},
        ]
        namespace_hierarchical_labels(labels, "/u1")
        self.assertEqual([l["name"] for l in labels], ["/u1/IN", "/u1/u2/OUT", "LOCAL"])
        self.assertEqual(labels[1]["_hier_ns"], "/u1/u2")
        self.assertTrue(labels[1]["_is_sheet_pin"])
        self.assertNotIn("_sheet_uuid", labels[1])
        root_labels = [{"name": "IN", "type": "hierarchical_label"},
                       {"name": "P", "type": "hierarchical_label", "_sheet_uuid": "u9"}]
        namespace_hierarchical_labels(root_labels, "")
        self.assertEqual([l["name"] for l in root_labels], ["IN", "/u9/P"])


if __name__ == "__main__":
    unittest.main()
