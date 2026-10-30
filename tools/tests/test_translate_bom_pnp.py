"""translate_bom_pnp: DNP and population columns, designator ranges, whole-token DNP markers."""
import csv
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "bom" / "scripts" / "translate_bom_pnp.py"

_spec = importlib.util.spec_from_file_location("translate_bom_pnp", SCRIPT)
tb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tb)

# kicad-cli `sch export bom` default: labels Refs,Value,Footprint,Qty,DNP; a run of
# three or more references is written R1-R4, the DNP cell holds "DNP" or nothing.
KICAD_BOM = (
    '"Refs","Value","Footprint","Qty","DNP"\n'
    '"R1-R4,R7","10k","R_0603","5",""\n'
    '"C5","100n","C_0402","1","DNP"\n'
)
CPL = (
    "Designator,Mid X (mm),Mid Y (mm),Layer,Rotation\n"
    + "".join(f"{r},1.0,2.0,T,0\n" for r in ("R1", "R2", "R3", "R4", "R7", "C5", "TP1"))
)


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = Path(self._tmp.name)

    def write(self, name, text):
        p = self.d / name
        p.write_text(text, encoding="utf-8")
        return p


class BomTranslation(Case):
    def test_dnp_column_and_range(self):
        src = self.write("bom.csv", KICAD_BOM)
        out = self.d / "jlc.csv"
        stats = tb.translate_bom(str(src), str(out))
        rows = read_rows(out)
        self.assertEqual([r["Designator"] for r in rows], ["R1,R2,R3,R4,R7"])
        self.assertEqual(stats["skipped_dnp"], 1)

    def test_population_column(self):
        for header, cell, fitted in (("Populate", "0", False), ("Populate", "1", True),
                                     ("Fitted", "Not Fitted", False), ("Fitted", "Fitted", True)):
            with self.subTest(header=header, cell=cell):
                src = self.write("bom.csv", f"Designator,Value,Footprint,{header}\nR1,10k,R_0603,{cell}\n")
                out = self.d / "jlc.csv"
                tb.translate_bom(str(src), str(out))
                self.assertEqual([r["Designator"] for r in read_rows(out)], ["R1"] if fitted else [])

    def test_population_header_is_exact(self):
        # "Do Not Populate" is a DNP-polarity column, not a population column
        src = self.write("bom.csv", "Designator,Value,Footprint,Do Not Populate\nR1,10k,R_0603,\n")
        out = self.d / "jlc.csv"
        tb.translate_bom(str(src), str(out))
        self.assertEqual([r["Designator"] for r in read_rows(out)], ["R1"])

    def test_part_number_containing_dnp_stays_fitted(self):
        src = self.write("bom.csv", "Designator,Value,Footprint\nU1,OPT4003DNPRQ1,X\nU2,IXDNI604PI,X\n")
        out = self.d / "jlc.csv"
        stats = tb.translate_bom(str(src), str(out))
        self.assertEqual([r["Designator"] for r in read_rows(out)], ["U1", "U2"])
        self.assertEqual(stats["skipped_dnp"], 0)

    def test_range_free_cell_is_verbatim(self):
        src = self.write("bom.csv", 'Designator,Value,Footprint\n"C1, C2","1u",X\n')
        out = self.d / "jlc.csv"
        tb.translate_bom(str(src), str(out))
        self.assertEqual([r["Designator"] for r in read_rows(out)], ["C1, C2"])


class PnpFilter(Case):
    def _filtered(self, bom_path):
        cpl = self.write("cpl.csv", CPL)
        out = self.d / "cpl_out.csv"
        stats = tb.translate_pnp(str(cpl), str(out), bom_filter_path=str(bom_path), units="mm")
        return [r["Designator"] for r in read_rows(out)], set(stats["filtered_orphan_samples"])

    def test_translated_bom(self):
        src = self.write("bom.csv", KICAD_BOM)
        jlc = self.d / "jlc.csv"
        tb.translate_bom(str(src), str(jlc))
        kept, orphans = self._filtered(jlc)
        self.assertEqual(kept, ["R1", "R2", "R3", "R4", "R7"])
        self.assertEqual(orphans, {"C5", "TP1"})

    def test_raw_kicad_bom(self):
        kept, orphans = self._filtered(self.write("bom.csv", KICAD_BOM))
        self.assertEqual(kept, ["R1", "R2", "R3", "R4", "R7"])
        self.assertEqual(orphans, {"C5", "TP1"})


class Helpers(unittest.TestCase):
    def test_expand_ranges(self):
        self.assertEqual(tb._expand_designators("R1-R4"), ["R1", "R2", "R3", "R4"])
        self.assertEqual(tb._expand_designators("R1-R4,R7"), ["R1", "R2", "R3", "R4", "R7"])
        self.assertEqual(tb._expand_designators("USB-HOST2-USB-HOST4"),
                         ["USB-HOST2", "USB-HOST3", "USB-HOST4"])

    def test_not_ranges(self):
        for tok in ("R4-R1", "J1-A", "MKB-1", "R1-C4", "R3-R3"):
            with self.subTest(tok=tok):
                self.assertEqual(tb._expand_designators(tok), [tok])

    def test_is_dnp_whole_token(self):
        for v in ("OPT4003DNPRQ1", "IXDNI604PI", "SIP32408DNP-T1-GE4", "100nF"):
            with self.subTest(v=v):
                self.assertFalse(tb._is_dnp(v))
        for v in ("R_DNP_0402", "0R (DNI)", "DNP", "No Stuff", "DNP(2.2k)", "*DNP", "0/DNI", "do not populate"):
            with self.subTest(v=v):
                self.assertTrue(tb._is_dnp(v))


if __name__ == "__main__":
    unittest.main()
