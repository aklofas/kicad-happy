"""Manifest run ids are folder names inside the analysis dir: an absolute, dotted or nested id
is never deleted by pruning and never written into."""
import io, json, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock
from tools.tests._fixtures import fixture_path, have

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
FX = fixture_path("simple-project")
sys.path.insert(0, str(SCRIPTS))

import analysis_cache  # noqa: E402


def _write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _outputs(tmp):
    d = os.path.join(tmp, "outputs")
    os.makedirs(d)
    _write(os.path.join(d, "schematic.json"), {"analyzer_type": "schematic"})
    return d


class RunIdTest(unittest.TestCase):
    def test_only_a_plain_child_name_is_a_run_id(self):
        with tempfile.TemporaryDirectory() as ad:
            self.assertTrue(analysis_cache._is_run_id(ad, "2026-10-24_1709"))
            for bad in ("", ".", "..", "../x", "a/b", "/tmp", os.path.abspath(ad), None, 7):
                self.assertFalse(analysis_cache._is_run_id(ad, bad), bad)


class PruneTest(unittest.TestCase):
    def test_prune_never_deletes_outside_the_analysis_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = os.path.join(tmp, "analysis")
            victim = os.path.join(tmp, "victim")
            os.makedirs(ad)
            os.makedirs(victim)
            Path(victim, "keep.txt").write_text("precious", encoding="utf-8")
            os.makedirs(os.path.join(ad, "old"))
            os.makedirs(os.path.join(ad, "new"))
            _write(os.path.join(ad, "manifest.json"), {"current": "new", "runs": {
                victim: {"generated": "0000", "outputs": {}},
                "../victim": {"generated": "0001", "outputs": {}},
                "old": {"generated": "0002", "outputs": {}},
                "new": {"generated": "0003", "outputs": {}}}})
            err = io.StringIO()
            with redirect_stderr(err):
                pruned = analysis_cache.prune_runs(ad, retention=1)
            self.assertEqual(pruned, ["old"])
            self.assertTrue(os.path.isfile(os.path.join(victim, "keep.txt")))
            self.assertFalse(os.path.exists(os.path.join(ad, "old")))
            self.assertTrue(os.path.isdir(os.path.join(ad, "new")))
            self.assertIn("analysis_cache.prune_runs", err.getvalue())
            self.assertIn("run id ignored", err.getvalue())


class WriteTest(unittest.TestCase):
    def test_overwrite_current_never_writes_outside(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = os.path.join(tmp, "a", "b")
            os.makedirs(ad)
            _write(os.path.join(ad, "manifest.json"), {"current": "../../etc", "runs": {"../../etc": {}}})
            err = io.StringIO()
            with redirect_stderr(err):
                analysis_cache.overwrite_current(ad, _outputs(tmp))
            self.assertFalse(os.path.exists(os.path.join(tmp, "etc")))
            current = analysis_cache.get_current_run(ad)
            self.assertIsNotNone(current)
            self.assertEqual(os.path.dirname(current[0]), ad)
            self.assertTrue(os.path.isfile(os.path.join(current[0], "schematic.json")))
            self.assertIn("analysis_cache.overwrite_current", err.getvalue())

    def test_get_current_run_ignores_an_escaping_id(self):
        with tempfile.TemporaryDirectory() as ad:
            _write(os.path.join(ad, "manifest.json"), {"current": "/etc", "runs": {"/etc": {}}})
            self.assertIsNone(analysis_cache.get_current_run(ad))
            self.assertEqual(analysis_cache.list_runs(ad), [])


class SymlinkAndOutputNameTest(unittest.TestCase):
    """A run dir that is a symlink into a nested folder, or a manifest output name with path
    parts, must not steer the copy-forward outside the analysis dir."""

    def _layout(self, tmp):
        ad = os.path.join(tmp, "x", "y", "proj", "analysis")
        os.makedirs(os.path.join(ad, "a", "b"))
        Path(tmp, "x", "y", "proj", "loot.json").write_text("{}", encoding="utf-8")
        return ad

    @unittest.skipUnless(hasattr(os, "symlink") and os.name == "posix", "needs POSIX symlinks")
    def test_symlinked_run_dir_is_not_a_run_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = self._layout(tmp)
            os.symlink(os.path.join(ad, "a", "b"), os.path.join(ad, "nest"))
            self.assertFalse(analysis_cache._is_run_id(ad, "nest"))
            _write(os.path.join(ad, "manifest.json"), {"current": "nest", "runs": {
                "nest": {"outputs": {"schematic": "../../../loot.json"}, "source_hashes": {}}}})
            err = io.StringIO()
            with redirect_stderr(err):
                analysis_cache.create_run(ad, _outputs(tmp), {}, {}, run_id="r2")
            self.assertFalse(os.path.exists(os.path.join(tmp, "x", "loot.json")))
            self.assertIn("run id ignored", err.getvalue())

    @unittest.skipUnless(hasattr(os, "symlink") and os.name == "posix", "needs POSIX symlinks")
    def test_symlinked_out_run_dir_says_it_resolves_outside(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = self._layout(tmp)
            elsewhere = os.path.join(tmp, "elsewhere", "2001-02-03_0405")
            os.makedirs(elsewhere)
            os.symlink(elsewhere, os.path.join(ad, "2001-02-03_0405"))
            _write(os.path.join(ad, "manifest.json"), {"current": "2001-02-03_0405", "runs": {
                "2001-02-03_0405": {"outputs": {}, "source_hashes": {}}}})
            err = io.StringIO()
            with redirect_stderr(err):
                analysis_cache.create_run(ad, _outputs(tmp), {}, {}, run_id="r2")
            self.assertIn("'2001-02-03_0405' resolves outside the analysis directory", err.getvalue())
            self.assertNotIn("is not a folder name", err.getvalue())
            _write(os.path.join(ad, "manifest.json"), {"current": "../x", "runs": {"../x": {}}})
            err = io.StringIO()
            with redirect_stderr(err):
                analysis_cache.create_run(ad, _outputs(os.path.join(tmp, "x")), {}, {},
                                          run_id="r3")
            self.assertIn("'../x' is not a folder name", err.getvalue())

    def test_output_name_with_path_parts_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = self._layout(tmp)
            os.makedirs(os.path.join(ad, "r1"))
            _write(os.path.join(ad, "r1", "pcb.json"), {"analyzer_type": "pcb"})
            _write(os.path.join(ad, "manifest.json"), {"current": "r1", "runs": {
                "r1": {"outputs": {"schematic": "../../../loot.json", "pcb": "pcb.json"},
                       "source_hashes": {}}}})
            err = io.StringIO()
            with redirect_stderr(err):
                analysis_cache.create_run(ad, _outputs(tmp), {}, {}, run_id="r2")
            self.assertFalse(os.path.exists(os.path.join(tmp, "x", "loot.json")))
            self.assertTrue(os.path.isfile(os.path.join(ad, "r2", "pcb.json")))
            self.assertIn("analysis_cache.create_run", err.getvalue())
            self.assertIn("manifest output ignored", err.getvalue())
            with open(os.path.join(ad, "manifest.json"), encoding="utf-8") as f:
                outputs = json.load(f)["runs"]["r2"]["outputs"]
            self.assertEqual(outputs, {"schematic": "schematic.json", "pcb": "pcb.json"})

    def test_nul_byte_run_id_is_rejected_not_raised(self):
        with tempfile.TemporaryDirectory() as ad:
            self.assertFalse(analysis_cache._is_run_id(ad, "bad\x00id"))

    def test_overwrite_current_drops_invalid_ids_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = os.path.join(tmp, "a", "b")
            os.makedirs(ad)
            _write(os.path.join(ad, "manifest.json"), {"current": "../../etc", "runs": {"../../etc": {}}})
            with redirect_stderr(io.StringIO()):
                analysis_cache.overwrite_current(ad, _outputs(tmp))
            err = io.StringIO()
            with redirect_stderr(err):
                analysis_cache.overwrite_current(ad, _outputs(os.path.join(tmp, "a")))
            self.assertNotIn("run id ignored", err.getvalue())
            with open(os.path.join(ad, "manifest.json"), encoding="utf-8") as f:
                self.assertNotIn("../../etc", json.load(f)["runs"])


class CurrentRunReadersTest(unittest.TestCase):
    """The SPICE and summary CLIs resolve the current run through the validated helper."""

    def _hostile(self, tmp):
        ad = os.path.join(tmp, "proj", "analysis")
        outside = os.path.join(tmp, "outside")
        os.makedirs(ad)
        os.makedirs(outside)
        _write(os.path.join(outside, "schematic.json"), {"analyzer_type": "schematic", "findings": []})
        _write(os.path.join(ad, "manifest.json"),
               {"current": "../../outside", "runs": {"../../outside": {"outputs": {}}}})
        return ad, outside

    def test_deep_review_gate_refuses_an_escaping_current(self):
        sys.path.insert(0, str(ROOT / "skills" / "kicad" / "review" / "scripts"))
        import deep_review_gate
        with tempfile.TemporaryDirectory() as tmp:
            ad, outside = self._hostile(tmp)
            _write(os.path.join(outside, "schematic.json"),
                   {"components": [{"reference": "LOOT1"}], "nets": {}})
            self.assertEqual(deep_review_gate.load_anchor_sets(ad), (set(), set(), {}))
            os.makedirs(os.path.join(ad, "r1"))
            _write(os.path.join(ad, "r1", "schematic.json"),
                   {"components": [{"reference": "U1"}], "nets": {"VCC": {}}})
            _write(os.path.join(ad, "manifest.json"), {"current": "r1", "runs": {"r1": {}}})
            self.assertEqual(deep_review_gate.load_anchor_sets(ad), ({"U1"}, {"VCC"}, {}))

    def test_spice_refuses_an_escaping_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad, outside = self._hostile(tmp)
            r = subprocess.run([sys.executable, str(ROOT / "skills" / "spice" / "scripts" /
                                                    "simulate_subcircuits.py"), "--analysis-dir", ad],
                               capture_output=True, text=True, encoding="utf-8", cwd=tmp, timeout=120)
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn("no 'current' run", r.stderr)
            self.assertFalse(os.path.exists(os.path.join(outside, "spice_work")))

    def test_summarize_refuses_an_escaping_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad, _outside = self._hostile(tmp)
            for extra in ((), ("--run", "../../outside")):
                with self.subTest(extra=extra):
                    r = subprocess.run([sys.executable, str(SCRIPTS / "summarize_findings.py"),
                                        ad, *extra],
                                       capture_output=True, text=True, encoding="utf-8", cwd=tmp,
                                       timeout=120)
                    self.assertNotEqual(r.returncode, 0)
                    self.assertIn("manifest has no run", r.stderr)


@unittest.skipUnless(have(FX), "harness fixtures not present")
class CliTest(unittest.TestCase):
    def _run(self, *args, cwd):
        env = dict(os.environ, PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, str(SCRIPTS / "analyze_schematic.py"), *args],
                              capture_output=True, text=True, encoding="utf-8", cwd=cwd, env=env)

    def test_retention_with_a_hostile_manifest_keeps_the_victim(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = os.path.join(tmp, "proj")
            ad = os.path.join(proj, "analysis")
            victim = os.path.join(tmp, "victim")
            os.makedirs(ad)
            os.makedirs(victim)
            Path(victim, "keep.txt").write_text("precious", encoding="utf-8")
            Path(proj, "simple.kicad_sch").write_bytes((FX / "simple.kicad_sch").read_bytes())
            _write(os.path.join(ad, "manifest.json"),
                   {"current": None, "runs": {victim: {"generated": "0000", "outputs": {}}}})
            _write(os.path.join(proj, ".kicad-happy.json"), {"analysis": {"retention": 1}})
            r = self._run(os.path.join(proj, "simple.kicad_sch"), "--analysis-dir", ad, cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.isfile(os.path.join(victim, "keep.txt")))
            self.assertIn("run id ignored", r.stderr)

    def test_hostile_current_does_not_steer_the_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = os.path.join(tmp, "ad", "7")
            os.makedirs(ad)
            _write(os.path.join(ad, "manifest.json"), {"current": "../../etc", "runs": {"../../etc": {}}})
            r = self._run(str(FX / "simple.kicad_sch"), "--analysis-dir", ad, cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(os.path.exists(os.path.join(tmp, "etc")))
            self.assertIn("run id ignored", r.stderr)


class LeafSymlinkTest(unittest.TestCase):
    def _outside(self, tmp, text="outside-secret"):
        path = os.path.join(tmp, "outside.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    @unittest.skipIf(os.name == "nt", "symlinks")
    def test_symlinked_previous_output_is_not_copied_forward(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = os.path.join(tmp, "analysis")
            first = analysis_cache.create_run(ad, _outputs(tmp), source_hashes={}, scripts={},
                                              run_id="r1")
            leaf = os.path.join(ad, first, "schematic.json")
            os.remove(leaf)
            os.symlink(self._outside(tmp), leaf)
            out2 = os.path.join(tmp, "out2")
            os.makedirs(out2)
            _write(os.path.join(out2, "pcb.json"), {"analyzer_type": "pcb"})
            err = io.StringIO()
            with redirect_stderr(err):
                analysis_cache.create_run(ad, out2, source_hashes={}, scripts={}, run_id="r2")
            new_leaf = os.path.join(ad, "r2", "schematic.json")
            self.assertFalse(os.path.lexists(new_leaf))
            self.assertIn("symlink", err.getvalue())

    @unittest.skipIf(os.name == "nt", "symlinks")
    def test_symlink_planted_in_the_new_run_is_not_written_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = os.path.join(tmp, "analysis")
            os.makedirs(os.path.join(ad, "r1"))
            outside = self._outside(tmp)
            os.symlink(outside, os.path.join(ad, "r1", "schematic.json"))
            err = io.StringIO()
            with redirect_stderr(err):
                analysis_cache.create_run(ad, _outputs(tmp), source_hashes={}, scripts={},
                                          run_id="r1")
            with open(outside, encoding="utf-8") as f:
                self.assertEqual(f.read(), "outside-secret")
            self.assertIn("symlink", err.getvalue())
            self.assertNotIn("schematic",
                             analysis_cache.load_manifest(ad)["runs"]["r1"]["outputs"])

    @unittest.skipIf(os.name == "nt", "symlinks")
    def test_overwrite_current_does_not_write_through_a_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = os.path.join(tmp, "analysis")
            rid = analysis_cache.create_run(ad, _outputs(tmp), source_hashes={}, scripts={},
                                            run_id="r1")
            leaf = os.path.join(ad, rid, "schematic.json")
            os.remove(leaf)
            outside = self._outside(tmp)
            os.symlink(outside, leaf)
            out2 = os.path.join(tmp, "out2")
            os.makedirs(out2)
            _write(os.path.join(out2, "schematic.json"), {"analyzer_type": "schematic"})
            with redirect_stderr(io.StringIO()):
                self.assertIs(analysis_cache.overwrite_current(ad, out2), False)
            with open(outside, encoding="utf-8") as f:
                self.assertEqual(f.read(), "outside-secret")
            os.remove(leaf)
            self.assertIs(analysis_cache.overwrite_current(ad, out2), True)
            self.assertIs(analysis_cache.overwrite_current(os.path.join(tmp, "fresh"), out2),
                          True)

    def test_ordinary_files_copy_unchanged_and_replace_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = os.path.join(tmp, "analysis")
            analysis_cache.create_run(ad, _outputs(tmp), source_hashes={}, scripts={}, run_id="r1")
            out2 = os.path.join(tmp, "out2")
            os.makedirs(out2)
            _write(os.path.join(out2, "pcb.json"), {"analyzer_type": "pcb"})
            analysis_cache.create_run(ad, out2, source_hashes={}, scripts={}, run_id="r2")
            self.assertEqual(sorted(os.listdir(os.path.join(ad, "r2"))), ["pcb.json", "schematic.json"])
            with open(os.path.join(ad, "r2", "schematic.json"), encoding="utf-8") as f:
                self.assertEqual(f.read(), '{"analyzer_type": "schematic"}')
            out3 = os.path.join(tmp, "out3")
            os.makedirs(out3)
            _write(os.path.join(out3, "pcb.json"), {"analyzer_type": "pcb", "n": 2})
            analysis_cache.overwrite_current(ad, out3)
            with open(os.path.join(ad, "r2", "pcb.json"), encoding="utf-8") as f:
                self.assertEqual(f.read(), '{"analyzer_type": "pcb", "n": 2}')
            self.assertEqual(sorted(os.listdir(os.path.join(ad, "r2"))), ["pcb.json", "schematic.json"])


@unittest.skipIf(os.name == "nt", "symlinks")
class PlantedSymlinkWriterTest(unittest.TestCase):
    def _secret(self, tmp):
        path = os.path.join(tmp, "victim.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("keep")
        return path

    def _assert_kept(self, path):
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "keep")

    def test_corrupt_manifest_backup_is_not_written_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            victim = self._secret(tmp)
            ad = os.path.join(tmp, "analysis")
            os.makedirs(ad)
            with open(os.path.join(ad, "manifest.json"), "w", encoding="utf-8") as f:
                f.write("{not json")
            os.symlink(victim, os.path.join(ad, "manifest.json.bak"))
            with redirect_stderr(io.StringIO()):
                analysis_cache.load_manifest(ad)
            self._assert_kept(victim)

    def test_dangling_gitignore_symlink_is_not_created_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "not-yet.txt")
            ad = os.path.join(tmp, "analysis")
            os.makedirs(ad)
            os.symlink(target, os.path.join(ad, ".gitignore"))
            err = io.StringIO()
            with redirect_stderr(err):
                analysis_cache.ensure_gitignore(ad)
            self.assertFalse(os.path.exists(target))
            self.assertIn("symlink", err.getvalue())

    def test_write_primary_run_leaves_a_gitignore_symlink_alone(self):
        import output_io
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "not-yet.txt")
            ad = os.path.join(tmp, "analysis")
            os.makedirs(ad)
            os.symlink(target, os.path.join(ad, ".gitignore"))
            src = os.path.join(tmp, "a.kicad_sch")
            with open(src, "w", encoding="utf-8") as f:
                f.write("x")
            with redirect_stderr(io.StringIO()):
                output_io.write_primary_run(ad, "{}", analyzer="schematic", source_path=src,
                                            script_name="analyze_schematic.py")
            self.assertFalse(os.path.exists(target))

    def test_overwrite_current_refused_copy_keeps_the_old_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = os.path.join(tmp, "analysis")
            rid = analysis_cache.create_run(ad, _outputs(tmp), source_hashes={"a.kicad_sch": "old"},
                                            scripts={}, run_id="r1")
            leaf = os.path.join(ad, rid, "schematic.json")
            os.remove(leaf)
            os.symlink(self._secret(tmp), leaf)
            out2 = os.path.join(tmp, "out2")
            os.makedirs(out2)
            _write(os.path.join(out2, "schematic.json"), {"analyzer_type": "schematic"})
            with redirect_stderr(io.StringIO()):
                analysis_cache.overwrite_current(ad, out2, source_hashes={"a.kicad_sch": "new"})
            hashes = analysis_cache.load_manifest(ad)["runs"]["r1"]["source_hashes"]
            self.assertEqual(hashes, {"a.kicad_sch": "old"})


class ReadBytesTest(unittest.TestCase):
    def test_non_utf8_manifest_is_corrupt_not_a_crash(self):
        with tempfile.TemporaryDirectory() as ad:
            Path(ad, "manifest.json").write_bytes(b"\xff\xfe{")
            with redirect_stderr(io.StringIO()):
                self.assertEqual(analysis_cache.load_manifest(ad)["runs"], {})

    def test_summarize_skips_a_non_utf8_output(self):
        import summarize_findings
        with tempfile.TemporaryDirectory() as ad:
            os.makedirs(os.path.join(ad, "r1"))
            _write(os.path.join(ad, "manifest.json"),
                   {"version": 1, "current": "r1", "runs": {"r1": {"timestamp": "t"}}})
            Path(ad, "r1", "pcb.json").write_bytes(b"\xff\xfe")
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                self.assertEqual(summarize_findings.main([ad, "--json"]), 0)
            self.assertIn("Warning: skipping", err.getvalue())

    def _run_dir(self, ad):
        os.makedirs(os.path.join(ad, "r1"))
        _write(os.path.join(ad, "manifest.json"),
               {"version": 1, "current": "r1", "runs": {"r1": {"timestamp": "t"}}})

    def _summarize(self, ad):
        import summarize_findings
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = summarize_findings.main([ad, "--json"])
        return rc, out.getvalue(), err.getvalue()

    def test_summarize_skips_a_non_object_output(self):
        with tempfile.TemporaryDirectory() as ad:
            self._run_dir(ad)
            _write(os.path.join(ad, "r1", "pcb.json"), [])
            _write(os.path.join(ad, "r1", "schematic.json"),
                   {"findings": [{"rule_id": "XX-001", "severity": "high"}]})
            rc, out, err = self._summarize(ad)
            self.assertEqual(rc, 0)
            self.assertIn("Warning: skipping", err)
            self.assertIn("XX-001", out)

    def test_summarize_skips_non_list_findings(self):
        with tempfile.TemporaryDirectory() as ad:
            self._run_dir(ad)
            _write(os.path.join(ad, "r1", "pcb.json"), {"findings": 5, "assessments": 5})
            self.assertEqual(self._summarize(ad)[0], 0)

    def test_summarize_non_object_manifest_is_a_clean_error(self):
        import summarize_findings
        for manifest, text in (([], "not a JSON object"),
                               ({"version": "two", "current": "r1",
                                 "runs": {"r1": {"timestamp": "t"}}}, "version is not an integer")):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as ad:
                os.makedirs(os.path.join(ad, "r1"))
                _write(os.path.join(ad, "manifest.json"), manifest)
                with self.assertRaises(SystemExit) as cm:
                    summarize_findings.main([ad, "--json"])
                self.assertIn(text, str(cm.exception))

    def test_summarize_skips_a_deeply_nested_output(self):
        with tempfile.TemporaryDirectory() as ad:
            self._run_dir(ad)
            Path(ad, "r1", "pcb.json").write_bytes(b"[" * 100000 + b"]" * 100000)
            rc, _out, err = self._summarize(ad)
            self.assertEqual(rc, 0)
            self.assertIn("Warning: skipping", err)

    def test_summarize_skips_a_deeply_nested_deep_review(self):
        with tempfile.TemporaryDirectory() as ad:
            self._run_dir(ad)
            Path(ad, "deep_review.json").write_bytes(b"[" * 100000 + b"]" * 100000)
            rc, _out, err = self._summarize(ad)
            self.assertEqual(rc, 0)
            self.assertIn("Warning:", err)

    def test_summarize_skips_non_list_deep_review_findings(self):
        with tempfile.TemporaryDirectory() as ad:
            self._run_dir(ad)
            _write(os.path.join(ad, "deep_review.json"), {"findings": 5})
            self.assertEqual(self._summarize(ad)[0], 0)

    def test_summarize_skips_a_non_object_deep_review(self):
        with tempfile.TemporaryDirectory() as ad:
            self._run_dir(ad)
            _write(os.path.join(ad, "deep_review.json"), [1])
            rc, _out, err = self._summarize(ad)
            self.assertEqual(rc, 0)
            self.assertIn("Warning: skipping", err)

    def test_summarize_unreadable_manifest_is_a_clean_error(self):
        import summarize_findings
        with tempfile.TemporaryDirectory() as ad:
            Path(ad, "manifest.json").write_bytes(b"\xff\xfe{")
            with self.assertRaises(SystemExit) as cm:
                summarize_findings.main([ad, "--json"])
            self.assertIn("cannot read", str(cm.exception))

    def test_summarize_skips_a_non_utf8_deep_review(self):
        import summarize_findings
        with tempfile.TemporaryDirectory() as ad:
            os.makedirs(os.path.join(ad, "r1"))
            _write(os.path.join(ad, "manifest.json"),
                   {"version": 1, "current": "r1", "runs": {"r1": {"timestamp": "t"}}})
            Path(ad, "deep_review.json").write_bytes(b"\xff\xfe")
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                self.assertEqual(summarize_findings.main([ad, "--json"]), 0)
            self.assertIn("Warning: skipping unreadable", err.getvalue())

    def test_non_utf8_capability_mode_file_is_unreadable_not_a_crash(self):
        import capability_mode
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "capability_mode.json")
            p.write_bytes(b"\xff\xfe{")
            self.assertIsNone(capability_mode._read_capability_mode(p))

    def test_should_create_new_run_treats_non_utf8_output_as_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = _outputs(tmp)
            ad = os.path.join(tmp, "analysis")
            os.makedirs(os.path.join(ad, "r1"))
            Path(ad, "r1", "schematic.json").write_bytes(b"\xff\xfe")
            _write(os.path.join(ad, "manifest.json"),
                   {"version": 1, "current": "r1", "runs": {"r1": {"timestamp": "t"}}})
            self.assertTrue(analysis_cache.should_create_new_run(ad, out))


@unittest.skipIf(os.name == "nt", "symlinks")
class RefusedCopyHonestyTest(unittest.TestCase):
    def _outside(self, tmp):
        path = os.path.join(tmp, "outside.json")
        Path(path).write_text("outside-secret", encoding="utf-8")
        return path

    def _out2(self, tmp):
        out2 = os.path.join(tmp, "out2")
        os.makedirs(out2)
        _write(os.path.join(out2, "thermal.json"), {"analyzer_type": "thermal"})
        return out2

    def test_refused_output_is_not_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = os.path.join(tmp, "analysis")
            analysis_cache.create_run(ad, _outputs(tmp), source_hashes={}, scripts={}, run_id="r1")
            os.symlink(self._outside(tmp), os.path.join(ad, "r1", "thermal.json"))
            with redirect_stderr(io.StringIO()):
                self.assertIs(analysis_cache.overwrite_current(ad, self._out2(tmp)), False)
            self.assertEqual(analysis_cache.load_manifest(ad)["runs"]["r1"]["outputs"],
                             {"schematic": "schematic.json"})

    def test_refused_output_already_listed_is_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = os.path.join(tmp, "analysis")
            out1 = _outputs(tmp)
            _write(os.path.join(out1, "thermal.json"), {"analyzer_type": "thermal"})
            analysis_cache.create_run(ad, out1, source_hashes={}, scripts={}, run_id="r1")
            leaf = os.path.join(ad, "r1", "thermal.json")
            os.remove(leaf)
            os.symlink(self._outside(tmp), leaf)
            with redirect_stderr(io.StringIO()):
                self.assertIs(analysis_cache.overwrite_current(ad, self._out2(tmp)), False)
            outputs = analysis_cache.load_manifest(ad)["runs"]["r1"]["outputs"]
            self.assertNotIn("thermal", outputs)
            self.assertIn("schematic", outputs)

    def test_refused_new_run_copy_is_not_reported_cached(self):
        import output_io
        with tempfile.TemporaryDirectory() as tmp:
            outside = self._outside(tmp)

            def plant(ad):
                os.makedirs(os.path.join(ad, "r1"))
                os.symlink(outside, os.path.join(ad, "r1", "schematic.json"))

            with mock.patch.object(analysis_cache, "generate_run_folder_name", return_value="r1"):
                ad = os.path.join(tmp, "analysis")
                plant(ad)
                with redirect_stderr(io.StringIO()):
                    self.assertIs(analysis_cache.overwrite_current(ad, _outputs(tmp)), False)
                ad2 = os.path.join(tmp, "analysis2")
                plant(ad2)
                src = os.path.join(tmp, "x.kicad_sch")
                Path(src).write_text("", encoding="utf-8")
                err = io.StringIO()
                with redirect_stderr(err):
                    output_io.write_primary_run(ad2, "{}", analyzer="schematic", source_path=src,
                                                script_name="analyze_schematic.py")
            self.assertNotIn("Analysis cached", err.getvalue())
            self.assertIn("symlink", err.getvalue())
            self.assertEqual(Path(outside).read_text(encoding="utf-8"), "outside-secret")

    def test_refused_manifest_backup_says_no_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            ad = os.path.join(tmp, "analysis")
            os.makedirs(ad)
            Path(ad, "manifest.json").write_text("{not json", encoding="utf-8")
            victim = self._outside(tmp)
            os.symlink(victim, os.path.join(ad, "manifest.json.bak"))
            err = io.StringIO()
            with redirect_stderr(err):
                analysis_cache.load_manifest(ad)
            self.assertIn("no backup", err.getvalue())
            self.assertNotIn("backed up to", err.getvalue())
            self.assertEqual(Path(victim).read_text(encoding="utf-8"), "outside-secret")


class CorruptManifestBackupTest(unittest.TestCase):
    def test_corrupt_manifest_backup_keeps_the_bytes(self):
        with tempfile.TemporaryDirectory() as ad:
            Path(ad, "manifest.json").write_text("{not json", encoding="utf-8")
            err = io.StringIO()
            with redirect_stderr(err):
                analysis_cache.load_manifest(ad)
            self.assertIn("backed up to", err.getvalue())
            self.assertEqual(Path(ad, "manifest.json.bak").read_text(encoding="utf-8"), "{not json")


if __name__ == "__main__":
    unittest.main()
