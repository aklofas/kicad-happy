import contextlib, hashlib, io, json, os, shutil, sys, tempfile, unittest
from unittest import mock
from pathlib import Path
from tools.tests._fixtures import fixture_path, have
SKILLS = Path(__file__).resolve().parents[2] / "skills"
for _d in ("kicad", "emc"):
    if str(SKILLS / _d / "scripts") not in sys.path:
        sys.path.insert(0, str(SKILLS / _d / "scripts"))
import project_config as pc

SIMPLE = fixture_path("simple-project")


def _canonical_hash(effective):
    text = json.dumps(effective, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@contextlib.contextmanager
def _home(path):
    with mock.patch.dict(os.environ, {"HOME": str(path), "USERPROFILE": str(path)}):
        yield


class ResolveConfig(unittest.TestCase):
    def test_discovered_mode_matches_load_config_and_hash_rule(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as home, _home(home):
            cfg = Path(d) / ".kicad-happy.json"
            cfg.write_text(json.dumps({"version": 1, "project": {"name": "x"}}), encoding="utf-8")
            r = pc.resolve_config(None, d)
            self.assertEqual(r.effective, pc.load_config(d))
            self.assertEqual(r.config_hash, _canonical_hash(r.effective))
            self.assertIn(str(cfg), r.paths)

    def test_discovered_mode_without_file(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as home, _home(home):
            r = pc.resolve_config(None, d)
            self.assertIsNone(r.config_hash)
            self.assertEqual(r.paths, ())
            self.assertEqual(r.effective, pc.load_config(d))

    def test_explicit_mode_does_not_cascade(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "c.json"; f.write_text('{"version": 1, "project": {"name": "y"}}', encoding="utf-8")
            r = pc.resolve_config(str(f), d)
            self.assertEqual((r.paths, r.config_hash), ((str(f),), _canonical_hash(r.effective)))
            self.assertEqual(r.effective, pc.load_config_from_path(str(f)))
            missing = pc.resolve_config(str(Path(d) / "nope.json"), d)
            self.assertEqual((missing.paths, missing.config_hash), ((), None))
            self.assertEqual(missing.effective, pc.load_config_from_path(str(Path(d) / "nope.json")))

    def test_parent_layer_is_hashed(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as home, _home(home):
            child = Path(d) / "child"
            child.mkdir()
            (Path(d) / ".kicad-happy.json").write_text('{"version":1,"project":{"name":"a"}}',
                                                       encoding="utf-8")
            r = pc.resolve_config(None, str(child))
            self.assertEqual(r.effective["project"], {"name": "a"})
            self.assertEqual(r.config_hash, _canonical_hash(r.effective))

    def test_home_layer_change_changes_hash(self):
        hashes = []
        with tempfile.TemporaryDirectory() as d:
            for name in ("a", "b"):
                with tempfile.TemporaryDirectory() as home, _home(home):
                    Path(home, ".kicad-happy.json").write_text(
                        json.dumps({"version": 1, "project": {"name": name}}), encoding="utf-8")
                    hashes.append(pc.resolve_config(None, d).config_hash)
        self.assertIsNotNone(hashes[0])
        self.assertNotEqual(hashes[0], hashes[1])

    def test_canonical_hash_ignores_layout(self):
        layouts = ('{"version": 1, "project": {"name": "n", "emc_standard": "cispr-32"}}',
                   '// project settings\n{\n  "project": {"emc_standard": "cispr-32",\n'
                   '    "name": "n"},  /* same */\n  "version": 1\n}\n')
        hashes = []
        with tempfile.TemporaryDirectory() as home, _home(home):
            for text in layouts:
                with tempfile.TemporaryDirectory() as d:
                    Path(d, ".kicad-happy.json").write_text(text, encoding="utf-8")
                    hashes.append(pc.resolve_config(None, d).config_hash)
        self.assertIsNotNone(hashes[0])
        self.assertEqual(hashes[0], hashes[1])

    def test_home_only_config_hash_is_stable(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as home, _home(home):
            Path(home, ".kicad-happy.json").write_text(
                '{"version": 1, "analysis": {"retention": 3}, "project": {"name": "h"}}', encoding="utf-8")
            first = pc.resolve_config(None, d).config_hash
            second = pc.resolve_config(None, d).config_hash
            Path(home, ".kicad-happy.json").write_text(
                '{"project": {"name": "h"}, "analysis": {"retention": 3}, "version": 1}', encoding="utf-8")
            reordered = pc.resolve_config(None, d).config_hash
        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        self.assertEqual(first, reordered)

    def test_missing_explicit_config_warns(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            cfg = pc.load_config_from_path("/nonexistent/typo.json")
        self.assertEqual(cfg, pc.DEFAULT_CONFIG)
        self.assertEqual(err.getvalue().strip(),
                         "Warning: config file not found: /nonexistent/typo.json; using built-in defaults")

    def test_empty_explicit_path_is_silent(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            pc.load_config_from_path("")
            pc.load_config_from_path(None)
        self.assertEqual(err.getvalue(), "")

    def test_discovery_without_config_is_silent(self):
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as home, \
                _home(home), contextlib.redirect_stderr(err):
            pc.resolve_config(None, d)
        self.assertEqual(err.getvalue(), "")


@unittest.skipUnless(have(SIMPLE), "harness fixtures not present")
class CliConfigHashTest(unittest.TestCase):
    """inputs.config_hash on the four config-reading analyzers."""

    def _runs(self, project, home):
        """inputs.config_hash of schematic, pcb, emc and thermal run on a copy of the simple
        project in *project*, with HOME at *home*."""
        import analyze_schematic, analyze_pcb, analyze_emc, analyze_thermal
        for name in ("simple.kicad_sch", "simple.kicad_pcb", "simple.kicad_pro"):
            shutil.copy(SIMPLE / name, project / name)
        sch, pcb = str(project / "sch.json"), str(project / "pcb.json")
        out = {}
        cwd = os.getcwd()
        os.chdir(project)
        try:
            with _home(home), contextlib.redirect_stderr(io.StringIO()), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(analyze_schematic.main([str(project / "simple.kicad_sch"), "-o", sch]), 0)
                self.assertEqual(analyze_pcb.main([str(project / "simple.kicad_pcb"), "-o", pcb]), 0)
                for name, main in (("emc", analyze_emc.main), ("thermal", analyze_thermal.main)):
                    target = str(project / f"{name}.json")
                    self.assertEqual(main(["--schematic", sch, "--pcb", pcb, "-o", target]), 0)
        finally:
            os.chdir(cwd)
        for name in ("sch", "pcb", "emc", "thermal"):
            with open(project / f"{name}.json", encoding="utf-8") as f:
                out[name] = json.load(f)["inputs"]["config_hash"]
        return out

    def test_no_config_gives_null_hash(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as home:
            got = self._runs(Path(d), home)
        self.assertEqual(got, {"sch": None, "pcb": None, "emc": None, "thermal": None})

    def test_discovered_config_hash_on_every_analyzer(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as home:
            project = Path(d) / "board"
            project.mkdir()
            Path(d, ".kicad-happy.json").write_text('{"version": 1, "project": {"name": "p"}}',
                                                    encoding="utf-8")
            with _home(home):
                want = _canonical_hash(pc.load_config(str(project)))
            got = self._runs(project, home)
        self.assertIsNotNone(want)
        self.assertEqual(got, {"sch": want, "pcb": want, "emc": want, "thermal": want})


if __name__ == "__main__":
    unittest.main()
