"""BOM CSVs saved by Excel (UTF-8 with a byte-order mark, CRLF) keep their hand edits and
designators; translate_bom_pnp reads a cp1252 BOM and refuses xlsx with a usage error; an
updated property keeps its backslashes."""
import csv, os, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOM = ROOT / "skills" / "bom" / "scripts"
FX = Path(os.environ.get("KH_FIXTURES", "/tmp/harness-pin/tests/fixtures")) / "simple-project"


def _run(script, *args, **kw):
    return subprocess.run([sys.executable, str(BOM / script), *args],
                          capture_output=True, text=True, encoding="utf-8", **kw)


def _excel_save(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerows(rows)


def _read(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


@unittest.skipUnless((FX / "simple.kicad_sch").is_file(), "fixtures absent")
class BomManagerExcelCsvTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.csv = self.tmp / "bom.csv"
        r = _run("bom_manager.py", "export", str(FX / "simple.kicad_sch"), "-o", str(self.csv))
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.csv, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        head = rows[0]
        for row in rows[1:]:
            row[head.index("Chosen_Distributor")] = "LCSC"
            row[head.index("Notes")] = f"note {row[0]}"
        _excel_save(self.csv, rows)
        self.refs = [row[0] for row in rows[1:]]

    def tearDown(self):
        self._tmp.cleanup()

    def test_export_merge_keeps_hand_edits(self):
        r = _run("bom_manager.py", "export", str(FX / "simple.kicad_sch"), "-o", str(self.csv))
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = _read(self.csv)
        self.assertEqual([x["Reference"] for x in rows], self.refs)
        self.assertEqual([x["Chosen_Distributor"] for x in rows], ["LCSC"] * len(self.refs))
        self.assertEqual([x["Notes"] for x in rows], [f"note {ref}" for ref in self.refs])

    def test_order_reads_the_designators(self):
        r = _run("bom_manager.py", "order", str(self.csv), "-o", str(self.tmp / "ord"), "--json")
        self.assertNotIn("Traceback", r.stderr)
        self.assertNotIn(", , ", r.stdout + r.stderr)
        self.assertRegex(r.stdout + r.stderr, r"\bR1\b")


class TranslateBomPnpTest(unittest.TestCase):
    def test_cp1252_bom_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "Poly BOM.csv")
            with open(src, "w", newline="", encoding="cp1252") as f:
                f.write("Comment,Designator,Footprint,LCSC\r\n100nF \u00b110%,C1,0603,C14663\r\n")
            out = os.path.join(tmp, "jlc.csv")
            r = _run("translate_bom_pnp.py", "bom", src, "-o", out)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out, encoding="utf-8") as f:
                self.assertIn("100nF \u00b110%", f.read())

    def test_undefined_cp1252_byte_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "odd.csv")
            with open(src, "wb") as f:   # 0x81 is undefined in cp1252, 0xb1 is the cp1252 plus-minus
                f.write(b"Comment,Designator,Footprint,LCSC\r\n100nF \xb110% \x81,C1,0603,C14663\r\n")
            out = os.path.join(tmp, "jlc.csv")
            r = _run("translate_bom_pnp.py", "bom", src, "-o", out)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out, encoding="utf-8") as f:
                self.assertIn("100nF \u00b110% \ufffd", f.read())

    def test_xlsx_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "x.xlsx")
            with open(src, "w", encoding="utf-8") as f:
                f.write("a,b\n")
            r = _run("translate_bom_pnp.py", "bom", src, "-o", os.path.join(tmp, "j.csv"))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("xlsx input is not supported", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_help_does_not_advertise_xlsx(self):
        r = _run("translate_bom_pnp.py", "bom", "--help")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("xlsx", r.stdout)


@unittest.skipUnless((FX / "simple.kicad_sch").is_file(), "fixtures absent")
class EditPropertiesBackslashTest(unittest.TestCase):
    def test_updated_value_keeps_backslashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            sch = os.path.join(tmp, "edit.kicad_sch")
            shutil.copy(FX / "simple.kicad_sch", sch)
            upd = os.path.join(tmp, "upd.json")
            with open(upd, "w", encoding="utf-8") as f:
                f.write('{"R1": {"Datasheet": "C:\\\\ds\\\\tps.pdf"}}')
            r = _run("edit_properties.py", sch, "--updates", upd)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(sch, encoding="utf-8") as f:
                text = f.read()
        lines = [l for l in text.splitlines() if '"C:' in l]
        self.assertTrue(lines, "Datasheet property not written")
        self.assertIn('"C:\\\\ds\\\\tps.pdf"', lines[0])


if __name__ == "__main__":
    unittest.main()
