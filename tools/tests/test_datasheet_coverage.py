"""Datasheet coverage (DS-001/DS-002/DS-003) counts the PDF files in the
project's datasheets folder: JSON beside them (extractions, a sync index)
and a second link to the same PDF are not more datasheets."""
import os
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
