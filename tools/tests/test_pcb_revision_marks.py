"""The silkscreen revision check accepts a revision word followed by a digit (`rev2`, `Rev1.0`,
`Ver1.0`) and a dotted V-number (`board_v1.1`), but not rail or word text that only ends in a
digit (`3V3`, `5V0`, `VCC_3V3`, `SERVER2`, `LEVEL2`, `DRIVER1`)."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.sexp import parse  # noqa: E402
from pcb.reader import extract_footprints, extract_silkscreen  # noqa: E402


def missing_revision(text):
    root = parse('(kicad_pcb (version 20221018) (generator pcbnew)\n'
                 ' (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (37 "F.SilkS" user))\n'
                 f' (gr_text "{text}" (at 10 10) (layer "F.SilkS")\n'
                 '  (effects (font (size 1 1) (thickness 0.15)))))\n')
    silk = extract_silkscreen(root, extract_footprints(root))
    return any(w["type"] == "missing_revision" for w in silk.get("documentation_warnings", []))


class RevisionMarks(unittest.TestCase):
    def test_revision_forms_are_read(self):
        for text in ("rev2", "Rev1.0", "board_v1.1", "Ver1.0", "Rev A", "V1.0"):
            with self.subTest(text=text):
                self.assertFalse(missing_revision(text))

    def test_rail_and_word_text_is_not_a_revision(self):
        for text in ("3V3", "5V0", "VCC_3V3", "SERVER2", "LEVEL2", "DRIVER1"):
            with self.subTest(text=text):
                self.assertTrue(missing_revision(text))


if __name__ == "__main__":
    unittest.main()
