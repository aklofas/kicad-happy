"""find_executable never returns a program from the current directory on Windows."""
import os, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))
from kicad_core import executables  # noqa: E402
from kicad_core.executables import find_executable  # noqa: E402


class FindExecutableTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.cwd = self.tmp / "cwd"
        self.bin = self.tmp / "bin"
        for d in (self.cwd, self.bin):
            d.mkdir()
            (d / "ngspice.exe").write_bytes(b"")
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.cwd)

    def test_windows_skips_cwd_and_relative_entries(self):
        path = os.pathsep.join([".", "", "rel", f'"{self.bin}"'])
        with mock.patch.dict(os.environ, {"PATH": path}), \
                mock.patch.object(executables, "_on_windows", return_value=True):
            self.assertEqual(find_executable("ngspice"), str(self.bin / "ngspice.exe"))
        with mock.patch.dict(os.environ, {"PATH": "."}), \
                mock.patch.object(executables, "_on_windows", return_value=True):
            self.assertIsNone(find_executable("ngspice"))

    def test_posix_is_which_made_absolute(self):
        with mock.patch.object(executables, "_on_windows", return_value=False):
            with mock.patch("shutil.which", return_value="./x"):
                self.assertEqual(find_executable("x"), os.path.abspath("./x"))
            with mock.patch("shutil.which", return_value=None):
                self.assertIsNone(find_executable("x"))


if __name__ == "__main__":
    unittest.main()
