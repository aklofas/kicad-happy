"""Datasheet coverage (DS-001/DS-002/DS-003) counts the PDF files in the
project's datasheets folder: JSON beside them (extractions, a sync index)
and a second link to the same PDF are not more datasheets."""
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from schematic.audits import audit_datasheet_coverage  # noqa: E402


def _part(ref, value, mpn=""):
    return {"reference": ref, "value": value, "footprint": "R_0603",
            "type": "resistor", "in_bom": True, "dnp": False, "mpn": mpn}


def _write(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


class DatasheetCoverageCountsPdfs(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # Nested so the parent/grandparent search stays inside the temp tree.
        self.proj = Path(tmp.name) / "repo" / "board"
        self.ds = self.proj / "datasheets"
        self.ds.mkdir(parents=True)

    def _rules(self, parts):
        return [(f["rule_id"], f["datasheet_file_count"])
                for f in audit_datasheet_coverage(parts, str(self.proj))]

    def _json_only(self):
        _write(self.ds / "index.json", '{"parts": {}}')
        _write(self.ds / "extracted" / "a.json", "{}")

    def test_json_only_folder_without_mpns_is_no_coverage(self):
        self._json_only()
        self.assertEqual(self._rules([_part("R1", "10k"), _part("R2", "1k")]),
                         [("DS-001", 0)])

    def test_json_only_folder_with_mpns_asks_for_sync(self):
        self._json_only()
        parts = [_part("R1", "10k", "RC0603-10K"), _part("R2", "1k")]
        self.assertEqual(self._rules(parts), [("DS-002", 0)])

    def test_pdf_and_a_link_to_it_count_once(self):
        _write(self.ds / "a.pdf")
        _write(self.ds / "a.json", "{}")
        _write(self.ds / "extracted" / "b.pdf")
        try:
            os.symlink(self.ds / "a.pdf", self.ds / "a-copy.pdf")
            os.symlink(self.ds / "missing.pdf", self.ds / "dangling.pdf")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        parts = [_part("R1", "10k", "RC0603-10K"), _part("R2", "1k")]
        self.assertEqual(self._rules(parts), [("DS-003", 1)])

    def _findings(self, parts):
        return audit_datasheet_coverage(parts, str(self.proj))

    def test_folder_without_pdf_is_named(self):
        self._json_only()
        f = self._findings([_part("R1", "10k"), _part("R2", "1k")])[0]
        self.assertEqual(f["rule_id"], "DS-001")
        self.assertTrue(f["summary"].startswith(
            "Datasheets directory ./datasheets holds no PDF"), f["summary"])
        self.assertEqual(f["datasheets_dir"], str(self.ds))
        self.assertEqual(f["datasheet_file_count"], 0)

    def test_folder_without_pdf_is_named_when_parts_have_mpns(self):
        self._json_only()
        parts = [_part("R1", "10k", "RC0603-10K"), _part("R2", "1k")]
        f = self._findings(parts)[0]
        self.assertEqual(f["rule_id"], "DS-002")
        self.assertTrue(f["summary"].startswith(
            "Datasheets directory ./datasheets holds no PDF (1/2"),
            f["summary"])
        self.assertEqual(f["datasheets_dir"], str(self.ds))

    def test_no_folder_keeps_the_absent_wording(self):
        self.ds.rmdir()
        f = self._findings([_part("R1", "10k")])[0]
        self.assertEqual(f["rule_id"], "DS-001")
        self.assertTrue(f["summary"].startswith(
            "No datasheets directory found and no BOM parts"))
        self.assertIsNone(f["datasheets_dir"])
        f = self._findings([_part("R1", "10k", "X1")])[0]
        self.assertEqual(f["rule_id"], "DS-002")
        self.assertTrue(f["summary"].startswith(
            "No datasheets directory found (1/1"))
        self.assertIsNone(f["datasheets_dir"])

    def test_empty_folder_does_not_hide_a_populated_one(self):
        _write(self.proj / "docs" / "datasheets" / "a.pdf")
        for parts in ([_part("R1", "10k", "RC0603-10K")],
                      [_part("R1", "10k"), _part("R2", "1k")]):
            rules = [f["rule_id"] for f in self._findings(parts)]
            self.assertNotIn("DS-001", rules)
            self.assertNotIn("DS-002", rules)
        f = self._findings([_part("R1", "10k")])[0]
        self.assertEqual(f["rule_id"], "DS-003")
        self.assertEqual(f["datasheets_dir"],
                         str(self.proj / "docs" / "datasheets"))

    def test_populated_folder_is_the_one_counted(self):
        _write(self.proj.parent / "datasheets" / "b.pdf")
        _write(self.proj.parent / "datasheets" / "c.pdf")
        parts = [_part("R%d" % i, "v%d" % i) for i in range(5)]
        f = self._findings(parts)[0]
        self.assertEqual(f["rule_id"], "DS-003")
        self.assertEqual(f["datasheet_file_count"], 2)
        self.assertEqual(f["datasheets_dir"],
                         str(self.proj.parent / "datasheets"))

    def test_nearest_populated_folder_wins(self):
        _write(self.ds / "a.pdf")
        _write(self.proj.parent / "datasheets" / "b.pdf")
        _write(self.proj.parent / "datasheets" / "c.pdf")
        parts = [_part("R%d" % i, "v%d" % i) for i in range(5)]
        f = self._findings(parts)[0]
        self.assertEqual(f["datasheet_file_count"], 1)
        self.assertEqual(f["datasheets_dir"], str(self.ds))

    def test_parent_folder_without_pdf_is_named_relative(self):
        self.ds.rmdir()
        (self.proj.parent / "datasheets").mkdir()
        f = self._findings([_part("R1", "10k")])[0]
        self.assertIn("directory ../datasheets holds no PDF", f["summary"])
        self.assertEqual(f["datasheets_dir"],
                         str(self.proj.parent / "datasheets"))

    def test_first_of_several_empty_folders_is_named(self):
        (self.proj.parent / "datasheets").mkdir()
        f = self._findings([_part("R1", "10k")])[0]
        self.assertIn("directory ./datasheets holds no PDF", f["summary"])

    def test_folder_text_uses_forward_slashes(self):
        real = os.path.relpath

        def win_relpath(path, start=os.curdir):
            return real(path, start).replace("/", "\\")

        with mock.patch("os.path.relpath", win_relpath):
            f = self._findings([_part("R1", "10k")])[0]
            self.assertIn("directory ./datasheets holds no PDF", f["summary"])
            self.ds.rmdir()
            (self.proj.parent / "datasheets").mkdir()
            f = self._findings([_part("R1", "10k")])[0]
            self.assertIn("directory ../datasheets holds no PDF", f["summary"])


if __name__ == "__main__":
    unittest.main()
