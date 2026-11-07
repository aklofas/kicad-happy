# tools/tests/test_pcb_gp001_debug_path.py
"""--gp001-debug writes its file into --analysis-dir when given, else beside --output,
else beside the board."""
import contextlib, io, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts" / "analyze_pcb.py"

BOARD = '''(kicad_pcb (version 20221018) (generator pcbnew)
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
  (net 0 "")
  (gr_rect (start 100 100) (end 120 120) (layer "Edge.Cuts") (stroke (width 0.1) (type default)))
)
'''


def _run(cwd, *args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True,
                          text=True, timeout=120)


class TestGp001DebugPath(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.d = self._t.name
        os.makedirs(os.path.join(self.d, "proj"))
        os.makedirs(os.path.join(self.d, "out"))
        with open(os.path.join(self.d, "proj", "b.kicad_pcb"), "w", encoding="utf-8") as f:
            f.write(BOARD)

    def tearDown(self):
        self._t.cleanup()

    def test_beside_output(self):
        r = _run(self.d, "proj/b.kicad_pcb", "--full", "--gp001-debug", "--output", "out/pcb.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.d, "out", "gp001_debug.json")))
        self.assertEqual(os.listdir(os.path.join(self.d, "proj")), ["b.kicad_pcb"])

    def test_without_output_stays_beside_board(self):
        r = _run(self.d, "proj/b.kicad_pcb", "--full", "--gp001-debug")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.d, "proj", "gp001_debug.json")))

    def test_output_wins_over_analysis_dir(self):
        os.makedirs(os.path.join(self.d, "O"))
        r = _run(self.d, "proj/b.kicad_pcb", "--full", "--gp001-debug",
                 "--analysis-dir", "A", "--output", "O/pcb.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.d, "O", "pcb.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.d, "A", "gp001_debug.json")))
        self.assertFalse(os.path.exists(os.path.join(self.d, "A", "manifest.json")))
        self.assertEqual(os.listdir(os.path.join(self.d, "proj")), ["b.kicad_pcb"])

    def test_analysis_dir_only(self):
        r = _run(self.d, "proj/b.kicad_pcb", "--full", "--gp001-debug", "--analysis-dir", "A")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.d, "A", "gp001_debug.json")))
        self.assertEqual(os.listdir(os.path.join(self.d, "proj")), ["b.kicad_pcb"])

    @unittest.skipIf(os.name == "nt", "symlinks")
    @unittest.skipUnless(hasattr(os, "symlink"), "no symlinks")
    def test_symlinked_target_is_not_followed(self):
        victim = os.path.join(self.d, "victim.txt")
        with open(victim, "w", encoding="utf-8") as f:
            f.write("keep")
        try:
            os.symlink(victim, os.path.join(self.d, "out", "gp001_debug.json"))
        except OSError:
            self.skipTest("cannot symlink")
        r = _run(self.d, "proj/b.kicad_pcb", "--full", "--gp001-debug", "--output", "out/pcb.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(victim, encoding="utf-8") as f:
            self.assertEqual(f.read(), "keep")
        self.assertIn("GP-001 debug write failed", r.stderr)


class TestGp001DebugWindowsHeldOpen(unittest.TestCase):
    def test_held_open_file_on_windows_warns_and_continues(self):
        sys.path.insert(0, str(SCRIPT.parent))
        from kicad_core import fileio
        from pcb.pipeline import finalize_for_cli
        with tempfile.TemporaryDirectory() as d:
            result = {"_gp001_debug_samples": [{"hit": True}]}
            err = io.StringIO()
            with mock.patch.object(fileio, "_is_windows", return_value=True), \
                    mock.patch.object(fileio.os, "replace",
                                      side_effect=PermissionError(13, "denied")), \
                    contextlib.redirect_stderr(err):
                finalize_for_cli(result, {}, pcb_path=os.path.join(d, "b.kicad_pcb"),
                                 analysis_dir_arg=d, return_path_radius_mm=1.0, stage=None)
            self.assertIn("GP-001 debug write failed", err.getvalue())
            self.assertNotIn("_gp001_debug_samples", result)
            self.assertEqual(os.listdir(d), [])


if __name__ == "__main__":
    unittest.main()
