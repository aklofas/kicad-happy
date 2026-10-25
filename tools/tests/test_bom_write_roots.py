# tools/tests/test_bom_write_roots.py
"""BOM schematic write-back stays inside the project, is atomic, and escapes names and line breaks."""
import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "bom" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import edit_properties, kicad_sexp, sync_datasheet_urls
from kicad_core import sexp


def sheet_text(ref, datasheet):
    return ('(kicad_sch (version 20231120) (generator "eeschema")\n'
            '\t(symbol (lib_id "Device:R") (at 10 10 0)\n'
            f'\t\t(property "Reference" "{ref}" (at 0 0 0))\n'
            f'\t\t(property "Datasheet" "{datasheet}" (at 0 0 0))\n'
            '\t)\n)\n')


class EscapeTest(unittest.TestCase):
    def test_line_breaks_escaped_and_round_trip(self):
        s = 'a\nb"c\\d'
        self.assertEqual(kicad_sexp.escape_kicad_string(s), 'a\\nb\\"c\\\\d')
        tree = sexp.parse('(p "%s")' % kicad_sexp.escape_kicad_string(s + "\r"))
        self.assertEqual(tree[1], s + "\r")

    def test_new_property_name_cannot_inject(self):
        name = 'X") (evil'
        text = "(symbol" + edit_properties.build_new_property(name, "v", "  ") + ")"
        props = sexp.find_all(sexp.parse(text), "property")
        self.assertEqual([p[1] for p in props], [name])


class SyncRootsTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        base = Path(self._td.name).resolve()
        self.proj = base / "proj"
        self.outside = base / "outside"
        self.proj.mkdir()
        self.outside.mkdir()
        (self.proj / "datasheets").mkdir()
        (self.proj / "datasheets" / "manifest.json").write_text(json.dumps({"parts": {
            "A": {"status": "ok", "datasheet_url": "https://e.com/a.pdf", "references": ["R1"]},
            "B": {"status": "ok", "datasheet_url": "https://e.com/b.pdf", "references": ["R2"]}}}),
            encoding="utf-8")
        self.other = self.outside / "other.kicad_sch"
        self.other.write_text(sheet_text("R2", ""), encoding="utf-8")
        self.other_bytes = self.other.read_bytes()

    def root_with_sheet(self, sheetfile):
        root = self.proj / "root.kicad_sch"
        root.write_text(sheet_text("R1", "") .rstrip().rstrip(")") +
                        f'\t(sheet (at 0 0) (property "Sheetfile" "{sheetfile}" (at 0 0 0)))\n)\n',
                        encoding="utf-8")
        return root

    def run_sync(self, root):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            sync_datasheet_urls.sync_datasheet_urls(str(root), recursive=True)
        return err.getvalue()

    def check(self, root):
        err = self.run_sync(root)
        self.assertEqual(self.other.read_bytes(), self.other_bytes)
        self.assertIn("other.kicad_sch", err)
        self.assertIn("not written", err)
        self.assertIn("https://e.com/a.pdf", root.read_text(encoding="utf-8"))

    def test_dotdot_sheet_not_written(self):
        self.check(self.root_with_sheet("../outside/other.kicad_sch"))

    def test_symlinked_sheet_not_written(self):
        try:
            os.symlink(self.other, self.proj / "link.kicad_sch")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self.check(self.root_with_sheet("link.kicad_sch"))

    def test_inside_sheet_still_written(self):
        sub = self.proj / "sub.kicad_sch"
        sub.write_text(sheet_text("R2", ""), encoding="utf-8")
        self.run_sync(self.root_with_sheet("sub.kicad_sch"))
        self.assertIn("https://e.com/b.pdf", sub.read_text(encoding="utf-8"))


class AtomicWriteTest(unittest.TestCase):
    def test_failed_replace_leaves_original_and_no_temp(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.kicad_sch"
            p.write_bytes(b"old")
            with mock.patch("os.replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    kicad_sexp.atomic_write_text(p, "new")
            self.assertEqual(p.read_bytes(), b"old")
            self.assertEqual(os.listdir(td), ["a.kicad_sch"])

    def test_write_replaces_and_keeps_mode(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.kicad_sch"
            p.write_bytes(b"old")
            os.chmod(p, 0o640)
            kicad_sexp.atomic_write_text(p, "newé")
            self.assertEqual(p.read_bytes(), "newé".encode("utf-8"))
            if os.name == "posix":
                self.assertEqual(p.stat().st_mode & 0o777, 0o640)


if __name__ == "__main__":
    unittest.main()
