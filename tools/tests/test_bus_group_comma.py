# tools/tests/test_bus_group_comma.py
"""A named bus group may separate its members with commas (CTRL{A,B}), as KiCad
does; kicad-cli joins CTRL.A across sheets. expand_bus_name split on whitespace
only, so CTRL{A,B} became one member "CTRL.A,B" and every tap labelled CTRL.A
was left on a per-sheet, single-pin net (entry_tap_name_not_in_bus)."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from schematic.connectivity import expand_bus_name  # noqa: E402

FX = Path(__file__).resolve().parent / "fixtures" / "bus_group_comma"


class GroupMemberSeparators(unittest.TestCase):
    def test_comma_separated(self):
        self.assertEqual(expand_bus_name("CTRL{A,B}"), ["CTRL.A", "CTRL.B"])

    def test_comma_and_space(self):
        self.assertEqual(expand_bus_name("CTRL{A, B}"), ["CTRL.A", "CTRL.B"])

    def test_space_separated_unchanged(self):
        self.assertEqual(expand_bus_name("CTRL{A B}"), ["CTRL.A", "CTRL.B"])

    def test_quoted_comma_stays_in_member(self):
        self.assertEqual(expand_bus_name('X{"A,B" C}'), ["X.A,B", "X.C"])

    def test_no_empty_members(self):
        self.assertEqual(expand_bus_name("CTRL{A,B,}"), ["CTRL.A", "CTRL.B"])
        self.assertIsNone(expand_bus_name("CTRL{ , }"))

    def test_unprefixed_and_nested_vector(self):
        self.assertEqual(expand_bus_name("{SDA,SCL}"), ["SDA", "SCL"])
        self.assertEqual(expand_bus_name("D{CLK,DAT[0..1]}"), ["D.CLK", "D.DAT0", "D.DAT1"])


class GroupBusAcrossSheets(unittest.TestCase):
    """Two sub-sheets share CTRL{A,B} through hierarchical sheet pins; each member
    is tapped by a bus entry whose wire carries the label CTRL.A / CTRL.B.
    kicad-cli 10.0.8: /CTRL.A = R1.1 + R3.1, /CTRL.B = R2.1 + R4.1."""

    def test_members_join_across_sheets(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "sch.json"
            subprocess.run([sys.executable, str(SCRIPTS / "analyze_schematic.py"),
                            str(FX / "repro.kicad_sch"), "--output", str(out)],
                           check=True, capture_output=True, cwd=t)
            d = json.loads(out.read_text())
        pins = {tuple(sorted(f"{p['component']}.{p['pin_number']}" for p in n["pins"]))
                for n in d["nets"].values()}
        self.assertIn(("R1.1", "R3.1"), pins)
        self.assertIn(("R2.1", "R4.1"), pins)
        self.assertEqual(d["bus_topology"]["unresolved"], [])


if __name__ == "__main__":
    unittest.main()
