"""gen_output_schema_md.py --help prints usage and writes nothing."""
import shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SENTINEL = "sentinel: must survive --help\n"


class HelpHasNoSideEffect(unittest.TestCase):
    def test_help_leaves_output_schema_md_alone(self):
        tracked = ROOT / "skills" / "kicad" / "references" / "output-schema.md"
        before = tracked.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp)
            ignore = shutil.ignore_patterns("__pycache__")
            shutil.copytree(ROOT / "skills" / "kicad" / "scripts", copy / "skills" / "kicad" / "scripts", ignore=ignore)
            shutil.copytree(ROOT / "skills" / "emc" / "scripts", copy / "skills" / "emc" / "scripts", ignore=ignore)
            target = copy / "skills" / "kicad" / "references" / "output-schema.md"
            target.parent.mkdir(parents=True)
            target.write_text(SENTINEL, encoding="utf-8")
            r = subprocess.run([sys.executable, str(copy / "skills" / "kicad" / "scripts" / "gen_output_schema_md.py"), "--help"],
                               capture_output=True, text=True, cwd=tmp, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("usage:", r.stdout)
            self.assertEqual(target.read_text(encoding="utf-8"), SENTINEL)
        self.assertEqual(tracked.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
