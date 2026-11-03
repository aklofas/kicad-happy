"""atomic_write_text with follow_symlinks=False, the --output writers and the manifest mode."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.fileio import atomic_write_text  # noqa: E402


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.d = Path(self._td.name)
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)


class ByteIdentity(_Tmp):
    def test_bytes_match_plain_write(self):
        text = "caf\u00e9\nline2\n"
        a = self.d / "a"
        b = self.d / "b"
        atomic_write_text(a, text, follow_symlinks=False)
        b.write_text(text, encoding="utf-8")
        self.assertEqual(a.read_bytes(), b.read_bytes())


@unittest.skipIf(os.name == "nt", "symlinks and POSIX modes")
class AtomicWriteNoFollow(_Tmp):
    def test_link_to_file_replaced_victim_kept(self):
        victim = self.d / "victim"
        victim.write_text("keep", encoding="utf-8")
        os.chmod(victim, 0o600)
        link = self.d / "out.json"
        os.symlink(victim, link)
        atomic_write_text(link, "new", follow_symlinks=False)
        self.assertFalse(link.is_symlink())
        self.assertEqual(link.read_text(encoding="utf-8"), "new")
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep")
        self.assertEqual(victim.stat().st_mode & 0o777, 0o600)
        self.assertEqual(link.stat().st_mode & 0o777, 0o644)

    def test_dangling_link_replaced_target_not_created(self):
        link = self.d / "out"
        os.symlink(self.d / "missing", link)
        atomic_write_text(link, "x", follow_symlinks=False)
        self.assertFalse(link.is_symlink())
        self.assertEqual(link.read_text(encoding="utf-8"), "x")
        self.assertFalse((self.d / "missing").exists())

    def test_regular_file_keeps_mode(self):
        f = self.d / "reg"
        f.write_text("a", encoding="utf-8")
        os.chmod(f, 0o640)
        atomic_write_text(f, "b", follow_symlinks=False)
        self.assertEqual(f.read_text(encoding="utf-8"), "b")
        self.assertEqual(f.stat().st_mode & 0o777, 0o640)

    def test_new_file_gets_umask_mode(self):
        f = self.d / "new"
        atomic_write_text(f, "c", follow_symlinks=False)
        self.assertEqual(f.stat().st_mode & 0o777, 0o644)
        self.assertEqual(sorted(os.listdir(self.d)), ["new"])

    def test_dev_null_is_written_not_replaced(self):
        atomic_write_text("/dev/null", "zz", follow_symlinks=False)
        self.assertFalse(os.path.isfile("/dev/null"))
        self.assertTrue(os.path.exists("/dev/null"))

    def test_default_still_follows(self):
        victim = self.d / "victim"
        victim.write_text("old", encoding="utf-8")
        link = self.d / "link"
        os.symlink(victim, link)
        atomic_write_text(link, "new")
        self.assertTrue(link.is_symlink())
        self.assertEqual(victim.read_text(encoding="utf-8"), "new")

    def test_dotdot_resolved_by_the_kernel(self):
        (self.d / "a" / "b").mkdir(parents=True)
        os.symlink(self.d / "a" / "b", self.d / "lb")
        atomic_write_text(str(self.d / "lb") + "/../y", "k", follow_symlinks=False)
        self.assertEqual((self.d / "a" / "y").read_text(encoding="utf-8"), "k")
        self.assertFalse((self.d / "y").exists())

    def test_dev_stdout_redirected_to_file(self):
        out = self.d / "o.txt"
        code = ("import sys; sys.path.insert(0, %r)\n"
                "from kicad_core.fileio import atomic_write_text\n"
                "atomic_write_text('/dev/stdout', 'HELLO\\n', follow_symlinks=False)\n") % str(SCRIPTS)
        with open(out, "w", encoding="utf-8") as fh:
            r = subprocess.run([sys.executable, "-c", code], stdout=fh, stderr=subprocess.PIPE,
                               text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(out.read_text(encoding="utf-8"), "HELLO\n")
        self.assertTrue(os.path.islink("/dev/stdout"))


@unittest.skipIf(os.name == "nt", "symlinks and POSIX modes")
class ManifestMode(_Tmp):
    def test_new_manifest_is_umask_mode(self):
        from analysis_cache import save_manifest
        adir = self.d / "analysis"
        save_manifest(str(adir), {"a": 1})
        mp = adir / "manifest.json"
        self.assertEqual(mp.stat().st_mode & 0o777, 0o644)
        self.assertEqual(mp.read_text(encoding="utf-8"), json.dumps({"a": 1}, indent=2) + "\n")
        self.assertEqual(sorted(os.listdir(adir)), ["manifest.json"])

    def test_existing_mode_kept(self):
        from analysis_cache import save_manifest
        adir = self.d / "analysis"
        save_manifest(str(adir), {"a": 1})
        os.chmod(adir / "manifest.json", 0o664)
        save_manifest(str(adir), {"a": 2})
        self.assertEqual((adir / "manifest.json").stat().st_mode & 0o777, 0o664)

    def test_existing_owner_only_manifest_gets_umask_mode(self):
        from analysis_cache import save_manifest
        adir = self.d / "analysis"
        save_manifest(str(adir), {"a": 1})
        os.chmod(adir / "manifest.json", 0o600)
        save_manifest(str(adir), {"a": 2})
        self.assertEqual((adir / "manifest.json").stat().st_mode & 0o777, 0o644)

    def test_existing_0640_manifest_kept(self):
        from analysis_cache import save_manifest
        adir = self.d / "analysis"
        save_manifest(str(adir), {"a": 1})
        os.chmod(adir / "manifest.json", 0o640)
        save_manifest(str(adir), {"a": 2})
        self.assertEqual((adir / "manifest.json").stat().st_mode & 0o777, 0o640)


@unittest.skipIf(os.name == "nt", "symlinks and POSIX modes")
class CliOutputLink(_Tmp):
    def _run(self, *argv):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, *argv], capture_output=True, text=True, env=env)

    def test_diff_analysis_output_replaces_link(self):
        a = self.d / "a.json"
        a.write_text(json.dumps({"analyzer_type": "schematic", "findings": []}), encoding="utf-8")
        victim = self.d / "victim"
        victim.write_text("keep", encoding="utf-8")
        out = self.d / "out.json"
        os.symlink(victim, out)
        r = self._run(str(SCRIPTS / "diff_analysis.py"), str(a), str(a), "--output", str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(out.is_symlink())
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep")
        json.loads(out.read_text(encoding="utf-8"))

    def test_analyze_pcb_output_replaces_link(self):
        pcb = self.d / "t.kicad_pcb"
        pcb.write_text('(kicad_pcb (version 20240108) (generator "pcbnew") (general (thickness 1.6)) '
                       '(layers (0 "F.Cu" signal) (31 "B.Cu" signal)) (net 0 ""))', encoding="utf-8")
        victim = self.d / "victim"
        victim.write_text("keep", encoding="utf-8")
        out = self.d / "out.json"
        os.symlink(victim, out)
        r = self._run(str(SCRIPTS / "analyze_pcb.py"), str(pcb), "--output", str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(out.is_symlink())
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep")
        json.loads(out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
