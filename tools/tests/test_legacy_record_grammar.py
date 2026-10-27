"""Legacy (KiCad 5) records read as KiCad's parseQuotedString and loadWire read them: a backslash is
dropped before a quote or a backslash and kept otherwise, and a wire header may carry style tokens."""
import os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from schematic import legacy_reader  # noqa: E402

_parse_legacy_single_sheet = legacy_reader._parse_legacy_single_sheet

HEAD = "EESchema Schematic File Version 4\nEELAYER 30 0\nEELAYER END\n$Descr A4 11693 8268\n$EndDescr\n"


def parse(body):
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "t.sch")
        with open(p, "w", encoding="utf-8") as f:
            f.write(HEAD + body + "$EndSCHEMATC\n")
        with open(os.path.join(tmp, "sub.sch"), "w", encoding="utf-8") as f:
            f.write(HEAD + "$EndSCHEMATC\n")
        return _parse_legacy_single_sheet(p)


class QuotedTest(unittest.TestCase):
    def test_escaped_quote(self):
        s = r'F 1 "1.3\"-128x64" H 3850 2400 50  0000 C CNN'
        self.assertEqual(legacy_reader._quoted(s, 3)[0], '1.3"-128x64')
        self.assertEqual(s[legacy_reader._quoted(s, 3)[1]:], " H 3850 2400 50  0000 C CNN")

    def test_backslash_rules(self):
        self.assertEqual(legacy_reader._quoted(r'F 3 "C:\\a\b" H', 3)[0], r'C:\a\b')

    def test_no_quote(self):
        self.assertIsNone(legacy_reader._quoted("F 3 x", 3))


class RecordTest(unittest.TestCase):
    def test_component_fields(self):
        body = ('$Comp\nL Device:R R1\nU 1 1 5F000001\nP 1000 1000\n'
                'F 0 "R1" H 0 0 50  0000 C CNN\n'
                'F 1 "1.3\\"-128x64" H 0 0 50  0000 C CNN\n'
                'F 3 "C:\\\\docs\\\\a.pdf" H 0 0 50  0001 C CNN\n'
                'F 4 "2\\" x 3\\"" H 0 0 50  0001 C CNN "Size"\n'
                'F 5 "ACME\\"1" H 0 0 50  0001 C CNN "MPN"\n$EndComp\n')
        c = parse(body)[0][0]
        self.assertEqual(c["value"], '1.3"-128x64')
        self.assertEqual(c["datasheet"], r'C:\docs\a.pdf')
        self.assertEqual(c["mpn"], 'ACME"1')

    def test_sheet_pin_with_escaped_quote(self):
        body = ('$Sheet\nS 4000 2000 1000 500\nU 5F0000AA\n'
                'F0 "sub" 50\nF1 "sub.sch" 50\nF2 "A\\"B" I R 4950 2500 50\n$EndSheet\n')
        labels = parse(body)[2]
        self.assertEqual([l["name"] for l in labels], ['A"B'])
        self.assertAlmostEqual(labels[0]["x"], 4950 * 0.0254, places=3)
        self.assertAlmostEqual(labels[0]["y"], 2500 * 0.0254, places=3)

    def test_styled_wire_kept(self):
        wires = parse("Wire Wire Line width 20 style dashed\n\t1000 1000 2000 1000\n")[1]
        self.assertEqual(len(wires), 1)
        self.assertAlmostEqual(wires[0]["x2"], 2000 * 0.0254, places=3)


if __name__ == "__main__":
    unittest.main()
