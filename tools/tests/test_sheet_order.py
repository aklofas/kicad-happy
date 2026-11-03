"""Sibling sheets: the net name and the whole analysis do not depend on the order the
sheet blocks are stored in the root file.

KiCad names a net driven by equal-rank labels on several sheets from the shallower
sheet, then the lower full name: hierarchical labels EN on sheet "Amplifier" and
AMP_STB on sheet "Video" joined at the root give /Amplifier/EN (kicad-cli 10).
"""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from schematic.pipeline import analyze_schematic  # noqa: E402
from tools.tests.test_top_level_sheets_kicad10 import resistor, sch, u  # noqa: E402

ROOT_UUID = u(201)
# Video's uuid sorts first, so neither the stored order nor the uuid order alone
# puts the Amplifier sheet ahead of it.
VIDEO = u(210)
AMPLIFIER = u(220)


def sheet(uuid, name, fname, x, pin):
    return (f'(sheet (at {x} 80) (size 20 10) (uuid "{uuid}")'
            f' (property "Sheetname" "{name}" (at {x} 79 0))'
            f' (property "Sheetfile" "{fname}" (at {x} 91 0))'
            f' (pin "{pin}" input (at {x} 82 180) (uuid "{uuid[:-3]}901")))')


def child(file_uuid, sheet_uuid, ref, label):
    """One resistor whose pin 1 is wired to a hierarchical label."""
    return sch(file_uuid,
               resistor(u(int(sheet_uuid[-3:]) + 1), "R?", 50,
                        [(f"/{ROOT_UUID}/{sheet_uuid}", ref)])
               + f'(wire (pts (xy 50 46.19) (xy 60 46.19)) (uuid "{sheet_uuid[:-3]}902"))'
               f' (hierarchical_label "{label}" (shape input) (at 60 46.19 0)'
               f' (uuid "{sheet_uuid[:-3]}903"))')


def project(reverse):
    blocks = [sheet(AMPLIFIER, "Amplifier", "amp.kicad_sch", 100, "EN"),
              sheet(VIDEO, "Video", "video.kicad_sch", 150, "AMP_STB")]
    if reverse:
        blocks.reverse()
    root = "".join(blocks) + '(wire (pts (xy 100 82) (xy 150 82)) (uuid "' + u(230) + '"))'
    return {"p.kicad_sch": sch(ROOT_UUID, root),
            "amp.kicad_sch": child(u(221), AMPLIFIER, "R1", "EN"),
            "video.kicad_sch": child(u(211), VIDEO, "R2", "AMP_STB")}


def analyze(files):
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in files.items():
            with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
                f.write(text)
        with redirect_stderr(StringIO()):
            result = analyze_schematic(os.path.join(tmp, "p.kicad_sch"))
    return result


class SiblingSheetOrderTest(unittest.TestCase):
    def test_the_net_is_named_on_the_amplifier_sheet_in_either_order(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                result = analyze(project(reverse))
                [name] = [n for n, net in result["nets"].items()
                          if sorted(f'{p["component"]}.{p["pin_number"]}' for p in net["pins"])
                          == ["R1.1", "R2.1"]]
                self.assertEqual(name, f"/{AMPLIFIER}/EN")


if __name__ == "__main__":
    unittest.main()
