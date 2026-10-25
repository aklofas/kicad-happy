"""--text output survives a stdout that is not UTF-8 (a Windows cp1252 redirect)."""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
FIXTURES = Path(os.environ.get("KH_FIXTURES", "/tmp/harness-pin/tests/fixtures"))
ESD = FIXTURES / "determinism" / "usb_dual_esd.kicad_sch"


def _run(args, cwd):
    env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, *args], capture_output=True, cwd=cwd, env=env, timeout=300)


class HelperTest(unittest.TestCase):
    def test_helper_reencodes_a_cp1252_stdout_as_utf8(self):
        code = ("import sys; sys.path.insert(0, %r); from kicad_core.cli import utf8_text_stdout; "
                "utf8_text_stdout(); print('\\u03a9 \\u2264 \\u2265')" % str(SCRIPTS))
        with tempfile.TemporaryDirectory() as tmp:
            r = _run(["-c", code], tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.decode("utf-8").strip(), "Ω ≤ ≥")


@unittest.skipUnless(ESD.is_file(), "harness fixtures not present")
class CliTest(unittest.TestCase):
    def test_schematic_text_with_non_cp1252_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _run([str(SCRIPTS / "analyze_schematic.py"), str(ESD), "--text"], tmp)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-1500:])
        text = r.stdout.decode("utf-8")
        self.assertTrue(any(c in text for c in "≤≥Ω"))

    def test_pcb_text_under_cp1252(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _run([str(SCRIPTS / "analyze_pcb.py"),
                      str(FIXTURES / "simple-project" / "simple.kicad_pcb"), "--text"], tmp)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-1500:])
        r.stdout.decode("utf-8")


if __name__ == "__main__":
    unittest.main()
