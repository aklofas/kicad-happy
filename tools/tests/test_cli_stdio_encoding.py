"""Every command-line script writes UTF-8 to a pipe under a legacy code page (Windows cp1252)."""
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MAIN = re.compile(r'^if __name__ == ["\']__main__["\']:', re.M)
# A library module whose __main__ block is a debug aid that takes a file, not --help.
NOT_A_CLI = {"skills/kicad/scripts/kicad_core/sexp.py"}


def entry_points():
    for path in sorted((REPO / "skills").rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if path.name.startswith("test_") or rel in NOT_A_CLI:
            continue
        if MAIN.search(path.read_text(encoding="utf-8")):
            yield rel


class Cp1252Pipe(unittest.TestCase):
    def test_help_is_utf8_under_cp1252(self):
        env = dict(os.environ, PYTHONIOENCODING="cp1252:strict")
        for rel in entry_points():
            with self.subTest(script=rel):
                r = subprocess.run([sys.executable, str(REPO / rel), "--help"],
                                   capture_output=True, env=env, timeout=60, cwd=REPO)
                err = r.stderr.decode("utf-8", "replace")
                self.assertEqual(r.returncode, 0, err[-400:])
                r.stdout.decode("utf-8")
                r.stderr.decode("utf-8")

    def test_non_cp1252_text_reaches_the_pipe(self):
        code = ("import sys; sys.path.insert(0, %r); from kicad_core.cli import utf8_stdio; "
                "utf8_stdio(); print('\\u2192 \\u03a9 \\u2264'); "
                "print('\\u2014', file=sys.stderr)" % str(REPO / "skills" / "kicad" / "scripts"))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=60,
                           env=dict(os.environ, PYTHONIOENCODING="cp1252:strict"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.decode("utf-8").strip(), "→ Ω ≤")
        self.assertEqual(r.stderr.decode("utf-8").strip(), "—")

    def test_every_entry_point_sets_utf8_stdio(self):
        # A new script must not reintroduce the cp1252 crash: its __main__ block
        # calls utf8_stdio() or reconfigures both streams itself.
        for rel in entry_points():
            with self.subTest(script=rel):
                text = (REPO / rel).read_text(encoding="utf-8")
                block = text[MAIN.search(text).end():]
                self.assertTrue("utf8_stdio()" in block or
                                ("sys.stdout, sys.stderr" in block and "reconfigure(" in block),
                                rel)


if __name__ == "__main__":
    unittest.main()
