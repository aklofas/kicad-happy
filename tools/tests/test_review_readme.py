"""The review README lists only scripts that exist."""
import re, unittest
from pathlib import Path

REVIEW = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "review"


class ReviewReadme(unittest.TestCase):
    def test_review_readme_lists_only_existing_scripts(self):
        text = (REVIEW / "README.md").read_text(encoding="utf-8")
        listed = re.findall(r"`(scripts/[\w./-]+\.py)`", text)
        self.assertTrue(listed)
        for rel in listed:
            self.assertTrue((REVIEW / rel).is_file(), rel)


if __name__ == "__main__":
    unittest.main()
