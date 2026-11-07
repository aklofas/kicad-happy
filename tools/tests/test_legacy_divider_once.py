"""A legacy (KiCad 5) schematic lists a feedback divider once in findings: the divider record
sits in both voltage_dividers and feedback_networks, and the flattened output keeps one copy,
as the modern path does."""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from schematic.pipeline import analyze_legacy_schematic  # noqa: E402

HEAD = "EESchema Schematic File Version 4\nEELAYER 30 0\nEELAYER END\n$Descr A4 11693 8268\n$EndDescr\n"
LIB = ("EESchema-LIBRARY Version 2.4\n#encoding utf-8\n"
       # Pin 1 lands 200 mil above the anchor, pin 2 200 mil below (matrix 1 0 0 -1).
       "DEF R R 0 40 Y Y 1 F N\nF0 \"R\" 0 0 50 H V C CNN\nDRAW\n"
       "X ~ 1 0 200 100 D 50 50 1 1 P\nX ~ 2 0 -200 100 U 50 50 1 1 P\nENDDRAW\nENDDEF\n"
       # VOUT above the anchor, FB 200 mil right of it, GND below.
       "DEF REG U 0 40 Y Y 1 F N\nF0 \"U\" 0 0 50 H V C CNN\nDRAW\n"
       "X VOUT 1 0 200 100 D 50 50 1 1 w\nX FB 2 200 0 100 L 50 50 1 1 I\n"
       "X GND 3 0 -200 100 U 50 50 1 1 W\nENDDRAW\nENDDEF\n#\n#End Library\n")


def comp(lib, ref, value, x, y, ts):
    return (f"$Comp\nL t:{lib} {ref}\nU 1 1 {ts}\nP {x} {y}\n"
            f'F 0 "{ref}" H {x} {y} 50  0000 C CNN\nF 1 "{value}" H {x} {y} 50  0000 C CNN\n'
            f"\t1    {x} {y}\n\t1    0    0    -1\n$EndComp\n")


def label(x, y, name):
    return f"Text Label {x} {y} 0    50   ~ 0\n{name}\n"


# R1 from VOUT to FB, R2 from FB to GND, U1's FB pin on the mid-point.
BODY = (comp("REG", "U1", "REG", 1000, 1000, "5A000001")
        + label(1000, 800, "VOUT") + label(1200, 1000, "FB") + label(1000, 1200, "GND")
        + comp("R", "R1", "10k", 2000, 1000, "5A000002")
        + label(2000, 800, "VOUT") + label(2000, 1200, "FB")
        + comp("R", "R2", "3.3k", 3000, 1000, "5A000003")
        + label(3000, 800, "FB") + label(3000, 1200, "GND"))


class LegacyFeedbackDividerTest(unittest.TestCase):
    def test_feedback_divider_is_listed_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            sch = os.path.join(tmp, "board.sch")
            with open(sch, "w", encoding="utf-8", newline="\n") as f:
                f.write(HEAD + BODY + "$EndSCHEMATC\n")
            with open(os.path.join(tmp, "board-cache.lib"), "w", encoding="utf-8", newline="\n") as f:
                f.write(LIB)
            with redirect_stderr(StringIO()):
                result = analyze_legacy_schematic(sch)
        vd = [f for f in result["findings"] if f.get("rule_id") == "VD-DET"]
        self.assertEqual(len(vd), 1, vd)
        self.assertEqual(sorted(vd[0]["components"]), ["R1", "R2"])
        self.assertTrue(vd[0].get("is_feedback"))
        self.assertEqual(result["summary"]["total_findings"], len(result["findings"]))


if __name__ == "__main__":
    unittest.main()
