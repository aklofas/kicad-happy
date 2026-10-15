import json, subprocess, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"


class SchemaVersionsFromAnyCwd(unittest.TestCase):
    def test_populated_when_cwd_is_elsewhere(self):
        code = ("import sys, json; sys.path.insert(0, %r); from capability_mode import _read_schema_versions; "
                "print(json.dumps(_read_schema_versions()))" % str(SCRIPTS))
        with tempfile.TemporaryDirectory() as cwd:
            out = subprocess.run([sys.executable, "-c", code], cwd=cwd, capture_output=True, text=True, check=True).stdout
        versions = json.loads(out)
        self.assertIn("regulator", versions)
        self.assertNotIn("base", versions)


if __name__ == "__main__":
    unittest.main()
