# tools/tests/test_sync_datasheet_urls.py
"""Datasheet URL backfill matches each symbol's own part, never a bare reference."""
import contextlib, io, json, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "bom" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import sync_datasheet_urls
from kicad_core import sexp


def symbol(ref, **props):
    body = "".join(f'\t\t(property "{k}" "{v}" (at 0 0 0))\n' for k, v in props.items())
    return ('\t(symbol (lib_id "Device:R") (at 10 10 0)\n'
            f'\t\t(property "Reference" "{ref}" (at 0 0 0))\n'
            '\t\t(property "Datasheet" "" (at 0 0 0))\n' + body + '\t)\n')


def ok(url, refs=(), **extra):
    return {"status": "ok", "datasheet_url": url, "references": list(refs), "source": "digikey", **extra}


class UrlBackfillTest(unittest.TestCase):
    def sync(self, symbols, parts):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / "datasheets").mkdir()
            (proj / "datasheets" / "manifest.json").write_text(json.dumps({"parts": parts}), encoding="utf-8")
            root = proj / "root.kicad_sch"
            root.write_text('(kicad_sch (version 20231120) (generator "eeschema")\n' + "".join(symbols) + ')\n',
                            encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                sync_datasheet_urls.sync_datasheet_urls(str(root))
            tree = sexp.parse(root.read_text(encoding="utf-8"))
            out = {}
            for sym in sexp.find_all(tree, "symbol"):
                p = {q[1]: q[2] for q in sexp.find_all(sym, "property")}
                out[p["Reference"]] = p["Datasheet"]
            return out

    def test_replaced_part_does_not_inherit_stale_reference(self):
        got = self.sync([symbol("R1", MPN="A-NEW")], {"A-OLD": ok("https://e.com/a_old.pdf", ["R1"])})
        self.assertEqual(got["R1"], "")

    def test_mpn_matches_even_without_listed_reference(self):
        got = self.sync([symbol("R2", MPN="B")], {"B": ok("https://e.com/b.pdf")})
        self.assertEqual(got["R2"], "https://e.com/b.pdf")

    def test_distributor_pn_matches_mpnless_part(self):
        got = self.sync([symbol("R3", DigiKey="C3-ND")], {"C3-ND": ok("https://e.com/c.pdf", ["R3"])})
        self.assertEqual(got["R3"], "https://e.com/c.pdf")

    def test_slot_pn_matches(self):
        got = self.sync([symbol("R3", **{"Supplier 1": "LCSC", "Supplier 1 Part Number": "C99"})],
                        {"C99": ok("https://e.com/c99.pdf")})
        self.assertEqual(got["R3"], "https://e.com/c99.pdf")

    def test_value_only_when_no_other_identity(self):
        got = self.sync([symbol("R4", Value="LM1117-3.3"), symbol("R6", Value="LM1117-3.3", MPN="OTHER")],
                        {"LM1117-3.3": ok("https://e.com/d.pdf")})
        self.assertEqual(got["R4"], "https://e.com/d.pdf")
        self.assertEqual(got["R6"], "")

    def test_entry_not_ok_or_wrong_gives_no_url(self):
        got = self.sync([symbol("R5", MPN="E"), symbol("R7", MPN="F")],
                        {"E": ok("https://e.com/e.pdf", verification="wrong"),
                         "F": {**ok("https://e.com/f.pdf"), "status": "not_found"}})
        self.assertEqual(got["R5"], "")
        self.assertEqual(got["R7"], "")

    def test_urlfx_fixture_shape(self):
        parts = {"A-OLD": ok("https://e.com/a_old.pdf", ["R1"]), "B": ok("https://e.com/b.pdf"),
                 "C3-ND": ok("https://e.com/c.pdf", ["R3"]), "LM1117-3.3": ok("https://e.com/d.pdf", ["R4"]),
                 "E": ok("https://e.com/e.pdf", ["R5"], verification="wrong")}
        got = self.sync([symbol("R1", Value="x", MPN="A-NEW"), symbol("R2", Value="x", MPN="B"),
                         symbol("R3", Value="x", DigiKey="C3-ND"), symbol("R4", Value="LM1117-3.3"),
                         symbol("R5", Value="E", MPN="E")], parts)
        self.assertEqual(got, {"R1": "", "R2": "https://e.com/b.pdf", "R3": "https://e.com/c.pdf",
                               "R4": "https://e.com/d.pdf", "R5": ""})


if __name__ == "__main__":
    unittest.main()
