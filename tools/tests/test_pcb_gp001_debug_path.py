# tools/tests/test_pcb_gp001_debug_path.py
"""--gp001-debug writes its file beside --output, never into the board's directory."""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
