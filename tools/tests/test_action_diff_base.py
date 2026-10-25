"""The Action's diff-base copy of the project comes wholly from the base commit: hierarchical
sub-sheets, the PCB and the project config; a schematic-only project extracts cleanly; the
working tree is not touched."""
import os, shutil, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "action" / "diff_base.sh"


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))


def _write(repo, rel, text):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _bash(repo, script):
    return subprocess.run(["bash", "-c", f'set -euo pipefail; . "{HELPER}"; {script}'],
                          cwd=repo, capture_output=True, text=True, encoding="utf-8")


@unittest.skipUnless(shutil.which("git") and shutil.which("bash") and shutil.which("tar"), "needs git, bash, tar")
class DiffBaseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self._tmp.name, "repo")
        os.makedirs(self.repo)
        _git(self.repo, "init", "-q")
        for rel, text in {"hw/top.kicad_sch": "top base", "hw/sub/child.kicad_sch": "child base",
                          "hw/top.kicad_pro": "pro base", "hw/top.kicad_pcb": "pcb base",
                          ".kicad-happy.json": "cfg base", "hw/notes.txt": "not kicad"}.items():
            _write(self.repo, rel, text)
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "base")
        _git(self.repo, "tag", "base")
        for rel in ("hw/top.kicad_sch", "hw/sub/child.kicad_sch", "hw/top.kicad_pcb", ".kicad-happy.json"):
            _write(self.repo, rel, rel + " head")
        _write(self.repo, "hw/sub/new.kicad_sch", "new in head")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "head")
        self.dest = os.path.join(self._tmp.name, "base tree")

    def tearDown(self):
        self._tmp.cleanup()

    def _read(self, rel):
        return (Path(self.dest) / rel).read_text(encoding="utf-8")

    def test_sub_sheets_pcb_and_config_come_from_base(self):
        r = _bash(self.repo, f'kh_extract_base base "{self.dest}" hw/top.kicad_sch hw/top.kicad_pcb ./.kicad-happy.json')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self._read("hw/top.kicad_sch"), "top base")
        self.assertEqual(self._read("hw/sub/child.kicad_sch"), "child base")
        self.assertEqual(self._read("hw/top.kicad_pro"), "pro base")
        self.assertEqual(self._read("hw/top.kicad_pcb"), "pcb base")
        self.assertEqual(self._read(".kicad-happy.json"), "cfg base")
        self.assertFalse((Path(self.dest) / "hw/sub/new.kicad_sch").exists())
        self.assertFalse((Path(self.dest) / "hw/notes.txt").exists())
        self.assertEqual((Path(self.repo) / "hw/sub/child.kicad_sch").read_text(encoding="utf-8"),
                         "hw/sub/child.kicad_sch head")

    def test_no_pcb_no_config(self):
        r = _bash(self.repo, f'kh_extract_base base "{self.dest}" hw/top.kicad_sch "" ""; '
                             f'p=$(kh_base_path "{self.dest}" ""); [ -z "$p" ] && echo EMPTY')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("EMPTY", r.stdout)
        self.assertEqual(self._read("hw/sub/child.kicad_sch"), "child base")
        self.assertFalse((Path(self.dest) / "hw/top.kicad_pcb").exists())

    def test_base_path_maps_into_the_tree(self):
        r = _bash(self.repo, f'kh_base_path "{self.dest}" ./hw/top.kicad_sch')
        self.assertEqual(r.stdout.strip(), f"{self.dest}/hw/top.kicad_sch")

    def test_symlinked_checkout_path(self):
        link = os.path.join(self._tmp.name, "link")
        os.symlink(self.repo, link)
        r = _bash(link, f'kh_base_path "{self.dest}" "{link}/hw/top.kicad_sch"')
        self.assertEqual(r.stdout.strip(), f"{self.dest}/hw/top.kicad_sch", r.stderr)

    def test_non_ascii_sub_sheet_name(self):
        _write(self.repo, "hw/Netzteil_Übersicht.kicad_sch", "psu base")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "psu")
        r = _bash(self.repo, f'kh_extract_base HEAD "{self.dest}" hw/top.kicad_sch hw/top.kicad_pcb ""')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self._read("hw/Netzteil_Übersicht.kicad_sch"), "psu base")

    def test_legacy_sch_root(self):
        _write(self.repo, "old/main.sch", "legacy root")
        _write(self.repo, "old/power.sch", "legacy sub")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "legacy")
        r = _bash(self.repo, f'kh_extract_base HEAD "{self.dest}" old/main.sch "" ""')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self._read("old/main.sch"), "legacy root")
        self.assertEqual(self._read("old/power.sch"), "legacy sub")

    def test_nothing_at_base_returns_1(self):
        r = _bash(self.repo, f'kh_extract_base base "{self.dest}" "" missing.kicad_pcb "" || echo NONE')
        self.assertIn("NONE", r.stdout)


if __name__ == "__main__":
    unittest.main()
