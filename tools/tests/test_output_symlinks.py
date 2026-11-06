"""atomic_write_text with follow_symlinks=False, the --output writers and the manifest mode."""
import json, os, secrets, subprocess, sys, tempfile, unittest
from unittest import mock
from pathlib import Path

from tools.tests._fixtures import fixture_path, have

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
SIMPLE = fixture_path("simple-project")
SHEET = ('(kicad_sch (version 20231120) (generator "eeschema")\n'
         '\t(symbol (lib_id "Device:R") (at 10 10 0)\n'
         '\t\t(property "Reference" "R1" (at 0 0 0))\n'
         '\t)\n)\n')
sys.path.insert(0, str(SCRIPTS))

from kicad_core import fileio  # noqa: E402
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
        b.write_text(text, encoding="utf-8", newline="\n")
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

    def test_link_to_fifo_replaced_fifo_gets_nothing(self):
        fifo = self.d / "victim_fifo"
        os.mkfifo(fifo)
        link = self.d / "out1.json"
        os.symlink(fifo, link)
        rfd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
        self.addCleanup(os.close, rfd)
        atomic_write_text(link, "payload", follow_symlinks=False)
        try:
            got = os.read(rfd, 4096)
        except BlockingIOError:
            got = b""
        self.assertEqual(got, b"")
        self.assertFalse(link.is_symlink())
        self.assertEqual(link.read_text(encoding="utf-8"), "payload")

    def test_fifo_named_directly_is_written(self):
        fifo = self.d / "pipe"
        os.mkfifo(fifo)
        rfd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
        self.addCleanup(os.close, rfd)
        atomic_write_text(fifo, "pp", follow_symlinks=False)
        self.assertEqual(os.read(rfd, 4096), b"pp")

    @unittest.skipUnless(os.path.isdir("/dev/shm"), "no /dev/shm")
    def test_regular_file_in_dev_shm_written_atomically(self):
        fd, name = tempfile.mkstemp(dir="/dev/shm")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(name) and os.unlink(name))
        before = os.stat(name).st_ino
        atomic_write_text(name, "shm", follow_symlinks=False)
        self.assertNotEqual(os.stat(name).st_ino, before)
        with open(name, encoding="utf-8") as f:
            self.assertEqual(f.read(), "shm")

    @unittest.skipUnless(os.path.isdir("/dev/shm"), "no /dev/shm")
    def test_link_under_dev_shm_replaced_victim_kept(self):
        victim = self.d / "victim"
        victim.write_text("keep", encoding="utf-8")
        link = "/dev/shm/kh_%s.json" % secrets.token_hex(6)
        os.symlink(victim, link)
        self.addCleanup(lambda: os.path.lexists(link) and os.unlink(link))
        atomic_write_text(link, "new", follow_symlinks=False)
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep")
        self.assertFalse(os.path.islink(link))
        with open(link, encoding="utf-8") as f:
            self.assertEqual(f.read(), "new")

    def test_dev_fd_pipe_is_streamed(self):
        r, w = os.pipe()
        self.addCleanup(os.close, r)
        self.addCleanup(os.close, w)
        atomic_write_text(f"/dev/fd/{w}", "piped", follow_symlinks=False)
        self.assertEqual(os.read(r, 4096), b"piped")

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


class WindowsOpenTarget(_Tmp):
    def test_windows_open_target_clear_error(self):
        out = self.d / "out.json"
        out.write_text("old", encoding="utf-8")
        with mock.patch.object(fileio, "_is_windows", return_value=True), \
                mock.patch.object(fileio.os, "replace", side_effect=PermissionError(13, "denied")):
            with self.assertRaises(SystemExit) as cm:
                atomic_write_text(out, "new", follow_symlinks=False)
        self.assertIn("open in another program", str(cm.exception.code))
        self.assertIn(str(out), str(cm.exception.code))
        self.assertEqual(sorted(os.listdir(self.d)), ["out.json"])
        self.assertEqual(out.read_text(encoding="utf-8"), "old")

    def test_permission_error_elsewhere_propagates(self):
        out = self.d / "out.json"
        with mock.patch.object(fileio, "_is_windows", return_value=False), \
                mock.patch.object(fileio.os, "replace", side_effect=PermissionError(13, "denied")):
            with self.assertRaises(PermissionError):
                atomic_write_text(out, "new", follow_symlinks=False)
        self.assertEqual(os.listdir(self.d), [])


@unittest.skipIf(os.name == "nt", "symlinks and POSIX modes")
class AtomicWriteFollowSpecialNodes(_Tmp):
    _CODE = ("import sys; sys.path.insert(0, %r)\n"
             "from kicad_core.fileio import atomic_write_text\n"
             "atomic_write_text('/dev/stdout', 'HELLO\\n')\n") % str(SCRIPTS)

    def test_fifo_named_directly_is_written(self):
        fifo = self.d / "pipe"
        os.mkfifo(fifo)
        rfd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
        self.addCleanup(os.close, rfd)
        atomic_write_text(fifo, "pp")
        self.assertEqual(os.read(rfd, 4096), b"pp")
        self.assertFalse(fifo.is_file())

    def test_link_to_fifo_writes_the_fifo_and_keeps_the_link(self):
        fifo = self.d / "pipe"
        os.mkfifo(fifo)
        link = self.d / "out.json"
        os.symlink(fifo, link)
        rfd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
        self.addCleanup(os.close, rfd)
        atomic_write_text(link, "lk")
        self.assertEqual(os.read(rfd, 4096), b"lk")
        self.assertTrue(link.is_symlink())

    def test_dev_stdout_into_a_pipe(self):
        r = subprocess.run([sys.executable, "-c", self._CODE], capture_output=True, text=True,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual((r.returncode, r.stdout), (0, "HELLO\n"), r.stderr)

    def test_dev_stdout_redirected_to_a_file_keeps_the_inode(self):
        out = self.d / "o.txt"
        with open(out, "w", encoding="utf-8") as fh:
            ino = os.fstat(fh.fileno()).st_ino
            r = subprocess.run([sys.executable, "-c", self._CODE], stdout=fh,
                               stderr=subprocess.PIPE, text=True,
                               env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.stat(out).st_ino, ino)
        self.assertEqual(out.read_text(encoding="utf-8"), "HELLO\n")


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

    def _run_in(self, *argv, text=True):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, *argv], capture_output=True, text=text, env=env,
                              cwd=self.d)

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

    def _victim_link(self, name="out.json"):
        victim = self.d / "victim"
        victim.write_text("keep", encoding="utf-8")
        out = self.d / name
        os.symlink(victim, out)
        return victim, out

    def _assert_replaced(self, r, victim, out):
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(out.is_symlink())
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep")

    def test_analyze_schematic_output_replaces_link(self):
        sch = self.d / "t.kicad_sch"
        sch.write_text(SHEET, encoding="utf-8")
        victim, out = self._victim_link()
        r = self._run_in(str(SCRIPTS / "analyze_schematic.py"), str(sch), "--output", str(out))
        self._assert_replaced(r, victim, out)
        json.loads(out.read_text(encoding="utf-8"))

    def test_analyze_schematic_output_bytes_match_stdout(self):
        import re
        sch = self.d / "t.kicad_sch"
        sch.write_text(SHEET, encoding="utf-8")
        out = self.d / "o.json"
        argv = [str(SCRIPTS / "analyze_schematic.py"), str(sch)]
        a = self._run_in(*argv, "--output", str(out), text=False)
        b = self._run_in(*argv, text=False)
        self.assertEqual((a.returncode, b.returncode), (0, 0), a.stderr + b.stderr)
        run_id = re.compile(rb'"run_id": "[^"]*"')
        self.assertEqual(run_id.sub(b"R", out.read_bytes()) + b"\n", run_id.sub(b"R", b.stdout))

    def test_analyze_schematic_output_relative_dash_and_other_filesystem(self):
        sch = self.d / "t.kicad_sch"
        sch.write_text(SHEET, encoding="utf-8")
        targets = ["rel.json", "-"]
        if os.path.isdir("/dev/shm"):
            shm = "/dev/shm/kh_%s.json" % secrets.token_hex(6)
            self.addCleanup(lambda: os.path.lexists(shm) and os.unlink(shm))
            targets.append(shm)
        for t in targets:
            r = self._run_in(str(SCRIPTS / "analyze_schematic.py"), str(sch), "--output", t)
            self.assertEqual(r.returncode, 0, r.stderr)
            path = Path(t) if os.path.isabs(t) else self.d / t
            self.assertTrue(path.is_file(), t)
            json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual([n for n in os.listdir(self.d) if n.endswith(".tmp")], [])

    def test_fab_release_gate_output_replaces_link(self):
        sch = self.d / "s.json"
        sch.write_text(json.dumps({"statistics": {"total_components": 1, "total_nets": 2,
                                                  "dnp_parts": 0}}), encoding="utf-8")
        pcb = self.d / "p.json"
        pcb.write_text(json.dumps({"connectivity": {"total_nets_with_pads": 2, "unrouted_count": 0,
                                                    "routing_complete": True},
                                   "dfm_summary": {"dfm_tier": "standard"},
                                   "statistics": {"footprint_count": 1, "net_count": 2},
                                   "silkscreen": {"documentation_warnings": []}}),
                       encoding="utf-8")
        victim, out = self._victim_link()
        r = self._run_in(str(SCRIPTS / "fab_release_gate.py"), "--schematic", str(sch),
                      "--pcb", str(pcb), "--output", str(out))
        self.assertFalse(out.is_symlink(), r.stderr)
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep")
        json.loads(out.read_text(encoding="utf-8"))

    def test_translate_bom_output_replaces_link(self):
        bom = self.d / "bom.csv"
        bom.write_text("Reference,Value,Footprint,Manufacturer,Manufacturer Part Number\n"
                       "R1,10k,Resistor_SMD:R_0402_1005Metric,Yageo,RC0402FR-0710KL\n",
                       encoding="utf-8")
        victim, out = self._victim_link("out.csv")
        r = self._run_in(str(ROOT / "skills" / "bom" / "scripts" / "translate_bom_pnp.py"), "bom",
                      str(bom), "-o", str(out))
        self._assert_replaced(r, victim, out)
        raw = out.read_bytes()
        self.assertTrue(raw.startswith(b"Comment,Designator,Footprint,"), raw)
        self.assertIn(b"\r\n", raw)
        import csv
        rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        self.assertEqual(rows[1][1], "R1")

    def _simple_jsons(self):
        sch, pcb = self.d / "sch.json", self.d / "pcb.json"
        for script, src, dst in (("analyze_schematic.py", "simple.kicad_sch", sch),
                                 ("analyze_pcb.py", "simple.kicad_pcb", pcb)):
            r = self._run_in(str(SCRIPTS / script), str(SIMPLE / src), "--output", str(dst))
            self.assertEqual(r.returncode, 0, r.stderr)
        return sch, pcb

    @unittest.skipUnless(have(SIMPLE / "simple.kicad_sch"), "frozen fixtures not present")
    def test_cross_verify_output_replaces_link(self):
        sch, pcb = self._simple_jsons()
        victim, out = self._victim_link()
        r = self._run_in(str(SCRIPTS / "cross_verify.py"), "--schematic", str(sch), "--pcb", str(pcb),
                      "--output", str(out))
        self._assert_replaced(r, victim, out)
        self.assertTrue(out.read_text(encoding="utf-8").endswith("}\n"))
        json.loads(out.read_text(encoding="utf-8"))

    @unittest.skipUnless(have(SIMPLE / "simple.kicad_sch"), "frozen fixtures not present")
    def test_analyze_emc_output_replaces_link(self):
        sch, pcb = self._simple_jsons()
        victim, out = self._victim_link()
        r = self._run_in(str(ROOT / "skills" / "emc" / "scripts" / "analyze_emc.py"),
                      "--schematic", str(sch), "--pcb", str(pcb), "--output", str(out))
        self._assert_replaced(r, victim, out)
        json.loads(out.read_text(encoding="utf-8"))


_OUTPUT_WRITERS = [
    "skills/kicad/scripts/analyze_schematic.py", "skills/kicad/scripts/analyze_gerbers.py",
    "skills/kicad/scripts/analyze_thermal.py", "skills/kicad/scripts/cross_analysis.py",
    "skills/emc/scripts/analyze_emc.py", "skills/kicad/scripts/lifecycle_audit.py",
    "skills/kicad/scripts/fab_release_gate.py", "skills/kicad/scripts/cross_verify.py",
    "skills/spice/scripts/simulate_subcircuits.py", "skills/spice/scripts/extract_parasitics.py",
    "skills/bom/scripts/translate_bom_pnp.py", "action/format-report.py",
    "skills/kicad/scripts/what_if.py", "skills/kicad/scripts/analyze_pcb.py",
    "skills/kicad/scripts/diff_analysis.py", "skills/bom/scripts/bom_manager.py",
]


def _calls(src, name):
    """The argument text of every call to *name* in *src* (parentheses balanced)."""
    out, i = [], src.find(name + "(")
    while i != -1:
        j = start = i + len(name) + 1
        depth = 1
        while depth:
            depth += {"(": 1, ")": -1}.get(src[j], 0)
            j += 1
        out.append(src[start:j - 1])
        i = src.find(name + "(", j)
    return out


class OutputWritersSource(unittest.TestCase):
    def test_no_plain_output_writes(self):
        import re
        plain = re.compile(r"open\((?:args\.output\w*|output_path), ['\"]w['\"]"
                           r"|Path\([^)]*output[^)]*\)\.write_text\(")
        target = re.compile(r"\s*(?:args\.output\w*|output_path)\s*,")
        for rel in _OUTPUT_WRITERS:
            src = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIsNone(plain.search(src), f"{rel}: {plain.search(src)}")
            calls = [c for c in _calls(src, "atomic_write_text") if target.match(c)]
            self.assertTrue(calls, rel)
            for c in calls:
                self.assertIn("follow_symlinks=False", c, f"{rel}: {c}")

if __name__ == "__main__":
    unittest.main()
