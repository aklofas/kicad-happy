# tools/tests/test_bom_manager_legacy.py
"""bom_manager reads KiCad 5 .sch projects through the schematic analyzer's legacy reader.

Expected values follow KiCad's legacy loader: F0-F3 are Reference/Value/Footprint/Datasheet, F4+
are user fields named by their last quoted token, a sheet used twice takes each instance's
reference from the symbol's `AR Path=` record, and KiCad 5 has no in_bom or dnp flag.
"""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOM = ROOT / "skills" / "bom" / "scripts"
sys.path.insert(0, str(BOM))

import bom_manager

HEAD = "EESchema Schematic File Version 4\nEELAYER 30 0\nEELAYER END\n$Descr A4 11693 8268\n$EndDescr\n"


def comp(ref, ts, value="10k", footprint="R_0603", unit=1, extra="", ar=(), lib="Device:R"):
    ar_lines = "".join(f'AR Path="{p}" Ref="{r}"  Part="{unit}" \n' for p, r in ar)
    return (f"$Comp\nL {lib} {ref}\nU {unit} 1 {ts}\nP 1000 1000\n{ar_lines}"
            f'F 0 "{ref}" H 1000 1000 50  0000 C CNN\n'
            f'F 1 "{value}" H 1000 1000 50  0000 C CNN\n'
            f'F 2 "{footprint}" H 1000 1000 50  0001 C CNN\n'
            f'F 3 "~" H 1000 1000 50  0001 C CNN\n{extra}'
            "\t1    1000 1000\n\t1    0    0    -1\n$EndComp\n")


def sheet(ts, filename):
    return (f"$Sheet\nS 3000 1500 1000 1000\nU {ts}\n"
            f'F0 "S" 50\nF1 "{filename}" 50\n$EndSheet\n')


class LegacyBom(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, body):
        path = self.dir / name
        path.write_text(HEAD + body + "$EndSCHEMATC\n", encoding="utf-8")
        return path

    def refs(self, report):
        return sorted(r for e in report["bom"] for r in e["references"])

    def test_user_field_is_the_mpn_and_tilde_footprint_is_empty(self):
        root = self.write("a.sch",
                          comp("R1", "5F000001",
                               extra='F 4 "RC0805FR-0710KL" H 1000 1000 50  0001 C CNN "MPN"\n')
                          + comp("C1", "5F000002", value="100n", footprint="~", lib="Device:C"))
        report = bom_manager.analyze(root)
        by_ref = {r: e for e in report["bom"] for r in e["references"]}
        self.assertEqual(by_ref["R1"]["mpn"], "RC0805FR-0710KL")
        self.assertEqual(by_ref["C1"]["footprint"], "")
        self.assertEqual(by_ref["R1"]["footprint"], "R_0603")

    def test_power_symbols_are_not_parts(self):
        root = self.write("a.sch", comp("R1", "5F000001")
                          + comp("#PWR01", "5F000002", value="GND", footprint="", lib="power:GND")
                          + comp("#FLG01", "5F000003", value="PWR_FLAG", footprint="", lib="power:PWR_FLAG"))
        self.assertEqual(self.refs(bom_manager.analyze(root)), ["R1"])

    def test_repeated_sheet_takes_each_instances_reference(self):
        self.write("child.sch", comp("R1", "5F000010", ar=[("/5F0000A1/5F000010", "R10"),
                                                           ("/5F0000A2/5F000010", "R20")]))
        root = self.write("root.sch", sheet("5F0000A1", "child.sch") + sheet("5F0000A2", "child.sch"))
        report = bom_manager.analyze(root, recursive=True)
        self.assertEqual(self.refs(report), ["R10", "R20"])
        self.assertEqual(self.refs(bom_manager.analyze(root)), [])

    def test_units_of_one_part_are_one_line(self):
        root = self.write("a.sch",
                          comp("U1", "5F000001", value="", footprint="", unit=1, lib="Device:Q")
                          + comp("U1", "5F000002", value="LM358", footprint="SOIC-8", unit=2, lib="Device:Q"))
        report = bom_manager.analyze(root)
        self.assertEqual(len(report["bom"]), 1)
        self.assertEqual(report["bom"][0]["value"], "LM358")
        self.assertEqual(report["bom"][0]["footprint"], "SOIC-8")

    def test_cli_accepts_sch_and_writers_reject_it(self):
        root = self.write("a.sch", comp("R1", "5F000001"))
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        run = lambda *a: subprocess.run([sys.executable, *a], capture_output=True, text=True, env=env)
        ok = run(str(BOM / "bom_manager.py"), str(root), "--json")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn('"R1"', ok.stdout)
        for script in ("edit_properties.py", "sync_datasheet_urls.py"):
            bad = run(str(BOM / script), str(root))
            self.assertEqual(bad.returncode, 1, script)
            self.assertIn("read only", bad.stderr)


if __name__ == "__main__":
    unittest.main()
