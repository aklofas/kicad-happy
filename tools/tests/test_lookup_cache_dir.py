"""Typed datasheet lookups read only the schematic folder's own datasheets/extracted."""
import sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from schematic.pipeline import _resolve_lookup_paths  # noqa: E402


class LookupCacheDirTest(unittest.TestCase):
    def test_parent_folder_cache_is_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "parent"
            (parent / "datasheets" / "extracted").mkdir(parents=True)
            (parent / "board").mkdir()
            sch = parent / "board" / "x.kicad_sch"
            sch.write_text("", encoding="utf-8")
            self.assertIsNone(_resolve_lookup_paths(sch))

    def test_own_folder_cache_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp) / "board"
            (board / "datasheets" / "extracted").mkdir(parents=True)
            sch = board / "x.kicad_sch"
            sch.write_text("", encoding="utf-8")
            self.assertEqual(_resolve_lookup_paths(sch),
                             board.resolve() / "datasheets" / "extracted")


if __name__ == "__main__":
    unittest.main()
