"""lifecycle_audit.py exits with the return code of main()."""
import os
import runpy
import subprocess
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, "skills", "kicad", "scripts", "lifecycle_audit.py")


class LifecycleCliExit(unittest.TestCase):
    def test_missing_input_exits_2_without_traceback(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT, os.path.join(ROOT, "no-such-analysis.json")],
            capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    def test_main_return_code_is_the_exit_code(self):
        sys.path.insert(0, os.path.dirname(SCRIPT))
        try:
            import lifecycle_audit
            with mock.patch.object(lifecycle_audit, "main", return_value=3):
                with mock.patch.object(sys, "argv", [SCRIPT]):
                    with self.assertRaises(SystemExit) as cm:
                        # runpy re-executes the file, so patch via a fresh module namespace
                        src = open(SCRIPT, encoding="utf-8").read()
                        guard = src[src.index('if __name__ == "__main__":'):]
                        exec(compile(guard, SCRIPT, "exec"),
                             {"__name__": "__main__", "sys": sys,
                              "main": lambda: 3})
            self.assertEqual(cm.exception.code, 3)
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
