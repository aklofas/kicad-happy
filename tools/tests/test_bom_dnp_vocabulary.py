"""One DNP vocabulary for the BOM manager and the pick-and-place translator."""
import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "bom" / "scripts"))

import bom_manager

_spec = importlib.util.spec_from_file_location(
    "translate_bom_pnp", ROOT / "skills" / "bom" / "scripts" / "translate_bom_pnp.py")
tb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tb)


class ValueMarkerTest(unittest.TestCase):
    def test_value_marker_is_dnp(self):
        for v in ("DNF", "NoPop", "nostuff", "Do Not Place", " dnf "):
            with self.subTest(v=v):
                self.assertTrue(bom_manager.is_dnp("", {"Value": v}))

    def test_ordinary_values_are_fitted(self):
        for v in ("10k", "DNF10", "x", "*", ""):
            with self.subTest(v=v):
                self.assertFalse(bom_manager.is_dnp("", {"Value": v}))


class DnpFieldTest(unittest.TestCase):
    def test_extra_cell_values_in_dnp_fields(self):
        for f, v in (("DNP", "Y"), ("DNP", "x"), ("DNP", "*"), ("DNM", "y")):
            with self.subTest(f=f, v=v):
                self.assertTrue(bom_manager.is_dnp("", {f: v}))

    def test_populate_polarity_unchanged(self):
        self.assertFalse(bom_manager.is_dnp("", {"POPULATE": "x"}))
        self.assertTrue(bom_manager.is_dnp("", {"POPULATE": "no"}))

    def test_negative_cells_are_fitted(self):
        for v in ("N", "no", ""):
            with self.subTest(v=v):
                self.assertFalse(bom_manager.is_dnp("", {"DNP": v}))


class AnalyzeTest(unittest.TestCase):
    def test_value_dnf_counts_as_dnp_line(self):
        def sym(ref, value, uuid):
            return ('(symbol (lib_id "Device:R") (at 10 10 0) (unit 1) (in_bom yes) (on_board yes)'
                    f' (dnp no) (uuid "{uuid}")\n  (property "Reference" "{ref}" (at 0 0 0))\n'
                    f'  (property "Value" "{value}" (at 0 0 0))\n  (property "Footprint" "R:R_0603" (at 0 0 0))\n)\n')
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.kicad_sch"
            p.write_text('(kicad_sch (version 20250114) (generator "eeschema") (uuid "r")\n'
                         + sym("R1", "10k", "a") + sym("R2", "DNF", "b") + ")\n", encoding="utf-8")
            report = bom_manager.analyze(p)
        lines = {r: e for e in report["bom"] for r in e["references"]}
        self.assertTrue(lines["R2"]["dnp"])
        self.assertFalse(lines["R1"]["dnp"])
        self.assertEqual(report["stats"]["dnp_lines"], 1)


class TranslatorTest(unittest.TestCase):
    def test_nopop_value_row_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "bom.csv"
            src.write_text("Designator,Value,Footprint\nR1,10k,R_0603\nR2,NoPop,R_0603\n", encoding="utf-8")
            out = Path(d) / "jlc.csv"
            stats = tb.translate_bom(str(src), str(out))
            with open(out, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(stats["skipped_dnp"], 1)
        self.assertEqual([r["Designator"] for r in rows], ["R1"])

    def test_translator_list_is_the_shared_vocabulary(self):
        self.assertEqual(set(tb.DNP_MARKERS), set(bom_manager.DNP_VALUE_MARKERS))


if __name__ == "__main__":
    unittest.main()
