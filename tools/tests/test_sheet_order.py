"""Sibling sheets: the net name and the whole analysis do not depend on the order the
sheet blocks are stored in the root file.

KiCad names a net driven by equal-rank labels on several sheets from the shallower
sheet, then the lower full name: hierarchical labels EN on sheet "Amplifier" and
AMP_STB on sheet "Video" joined at the root give /Amplifier/EN (kicad-cli 10).
"""
import json, os, sys, tempfile, unittest
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


def project(reverse=False, amp=("Amplifier", "EN"), video=("Video", "AMP_STB")):
    """Root with two sibling sheets, (name, hierarchical label) each, joined at the root."""
    blocks = [sheet(AMPLIFIER, amp[0], "amp.kicad_sch", 100, amp[1]),
              sheet(VIDEO, video[0], "video.kicad_sch", 150, video[1])]
    if reverse:
        blocks.reverse()
    root = "".join(blocks) + '(wire (pts (xy 100 82) (xy 150 82)) (uuid "' + u(230) + '"))'
    return {"p.kicad_sch": sch(ROOT_UUID, root),
            "amp.kicad_sch": child(u(221), AMPLIFIER, "R1", amp[1]),
            "video.kicad_sch": child(u(211), VIDEO, "R2", video[1])}


INNER = u(240)


def nested_project():
    """Root sheets "Q" (port R) and "Z" (label Y); Q holds sheet "A" (label X) on the
    same net.  /Q/A/X is the lowest name but the deepest: KiCad names the net /Q/R."""
    files = project(amp=("Q", "R"), video=("Z", "Y"))
    files["amp.kicad_sch"] = sch(
        u(221), resistor(u(222), "R?", 50, [(f"/{ROOT_UUID}/{AMPLIFIER}", "R1")])
        + f'(wire (pts (xy 50 46.19) (xy 60 46.19)) (uuid "{u(223)}"))'
        f' (hierarchical_label "R" (shape input) (at 60 46.19 0) (uuid "{u(224)}"))'
        + sheet(INNER, "A", "inner.kicad_sch", 60, "X")
        .replace("(at 60 80)", "(at 60 40)").replace("(at 60 82 180)", "(at 60 46.19 180)"))
    files["inner.kicad_sch"] = sch(
        u(241), resistor(u(242), "R?", 50, [(f"/{ROOT_UUID}/{AMPLIFIER}/{INNER}", "R3")])
        + f'(wire (pts (xy 50 46.19) (xy 60 46.19)) (uuid "{u(243)}"))'
        f' (hierarchical_label "X" (shape input) (at 60 46.19 0) (uuid "{u(244)}"))')
    return files


def net_name(result, pins):
    [name] = [n for n, net in result["nets"].items()
              if sorted(f'{p["component"]}.{p["pin_number"]}' for p in net["pins"]) == pins]
    return name


def analyze(files, tmp=None):
    if tmp is None:
        with tempfile.TemporaryDirectory() as tmp:
            return analyze(files, tmp)
    for name, text in files.items():
        with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
            f.write(text)
    with redirect_stderr(StringIO()):
        return analyze_schematic(os.path.join(tmp, "p.kicad_sch"))


def stable(files):
    """The output as text, without the temporary directory or a run id."""
    with tempfile.TemporaryDirectory() as tmp:
        result = analyze(files, tmp)
        (result.get("inputs") or {}).pop("run_id", None)
        text = json.dumps(result, sort_keys=True, default=str)
        # Windows may name the temp dir by its short form (RUNNER~1) and record the long one
        for form in sorted({tmp, os.path.realpath(tmp)}, key=len, reverse=True):
            text = text.replace(json.dumps(form)[1:-1], "<tmp>")
        return text


class SiblingSheetOrderTest(unittest.TestCase):
    def test_the_net_is_named_on_the_amplifier_sheet_in_either_order(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                result = analyze(project(reverse))
                self.assertEqual(net_name(result, ["R1.1", "R2.1"]), f"/{AMPLIFIER}/EN")

    def test_kicad_tie_break_cases(self):
        """Expected names from kicad-cli 10.0.7 on these fixtures."""
        cases = [
            # the separators compare plain: /Audio/ sorts before /AudioFilters/
            ("plain separators", dict(amp=("Audio", "Z1"), video=("AudioFilters", "A1")),
             f"/{AMPLIFIER}/Z1"),
            # a sheet name's own '/' is escaped: /B{slash}C/ is one level, before /Z/
            ("escaped sheet name", dict(amp=("B/C", "EN"), video=("Z", "AMP_STB")),
             f"/{AMPLIFIER}/EN"),
        ]
        for label, kwargs, expected in cases:
            for reverse in (False, True):
                with self.subTest(label, reverse=reverse):
                    result = analyze(project(reverse, **kwargs))
                    self.assertEqual(net_name(result, ["R1.1", "R2.1"]), expected)
        with self.subTest("shallower sheet before the lower name"):
            result = analyze(nested_project())
            self.assertEqual(net_name(result, ["R1.1", "R2.1", "R3.1"]), f"/{AMPLIFIER}/R")

    def test_reversed_sheet_blocks_give_the_same_output(self):
        self.assertEqual(stable(project(False)), stable(project(True)))


if __name__ == "__main__":
    unittest.main()
