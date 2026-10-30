"""A symbol's `Supplier N` field names the distributor of its own `Supplier N` part number, so
two symbols that use the same slot for different distributors file their numbers separately."""
import sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "bom" / "scripts"))

import bom_manager


def sym(ref, value, props, uuid):
    fields = "".join(f'  (property "{k}" "{v}" (at 0 0 0))\n' for k, v in props.items())
    return (f'(symbol (lib_id "Device:R") (at 10 10 0) (unit 1) (in_bom yes) (on_board yes)'
            f' (dnp no) (uuid "{uuid}")\n'
            f'  (property "Reference" "{ref}" (at 0 0 0))\n'
            f'  (property "Value" "{value}" (at 0 0 0))\n' + fields + ')\n')


def bom_of(*symbols):
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "t.kicad_sch"
        p.write_text('(kicad_sch (version 20250114) (generator "eeschema") (uuid "r")\n'
                     + "".join(symbols) + ")\n", encoding="utf-8")
        return {r: e for e in bom_manager.analyze(p)["bom"] for r in e["references"]}


class SupplierSlots(unittest.TestCase):
    def test_same_slot_two_distributors(self):
        b = bom_of(
            sym("R1", "1k", {"Supplier 1": "DigiKey", "Supplier 1 Part Number": "X-ND"}, "a"),
            sym("R2", "2k", {"Supplier 1": "Mouser", "Supplier 1 Part Number": "595-Y"}, "b"))
        self.assertEqual((b["R1"]["digikey"], b["R1"]["mouser"]), ("X-ND", ""))
        self.assertEqual((b["R2"]["mouser"], b["R2"]["digikey"]), ("595-Y", ""))

    def test_corpus_spellings(self):
        spellings = [("Supplier Part Number 2", "81-Z"), ("Supplier Part Num 2", "81-Z"),
                     ("SUPPLIER PART NUMBER 2", "81-Z"), ("Supplier_2 P/N", "81-Z"),
                     ("supplier 2 pn", "81-Z"), ("Supplier 2 Part #", "81-Z")]
        for i, (field, pn) in enumerate(spellings):
            with self.subTest(field=field):
                b = bom_of(
                    sym("R1", "1k", {"Supplier 1": "DigiKey", "Supplier 1 Part Number": "X-ND"}, "a"),
                    sym("R2", "2k", {"Supplier 2": "Mouser", field: pn}, f"b{i}"))
                self.assertEqual(b["R2"]["mouser"], pn)
                self.assertEqual(b["R2"]["digikey"], "")

    def test_direct_field_beats_slot(self):
        b = bom_of(sym("R1", "1k", {"Mouser Part Number": "DIRECT", "Supplier 1": "Mouser",
                                    "Supplier 1 Part Number": "SLOT"}, "a"))
        self.assertEqual(b["R1"]["mouser"], "DIRECT")

    def test_placeholder_slot_value_ignored(self):
        b = bom_of(sym("R1", "1k", {"Supplier 1": "DigiKey", "Supplier 1 Part Number": "~"}, "a"))
        self.assertEqual(b["R1"]["digikey"], "")

    def test_symbol_slots_helper(self):
        self.assertEqual(bom_manager._symbol_slots(
            {"Supplier 1": "JLCPCB", "Supplier 1 Part Number": "C1",
             "Supplier 2": "Farnell", "Supplier 2 P/N": "E2"}),
            {"lcsc": "C1", "element14": "E2"})


if __name__ == "__main__":
    unittest.main()
