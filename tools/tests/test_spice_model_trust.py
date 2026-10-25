"""A project's cached SPICE models are pasted into netlists only when they hold no
simulator control commands and include nothing outside the models folder, unless the
user opts in from ~/.kicad-happy.json. Manifest `file` names stay inside the cache
and model files are never written through a symlink."""
import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPICE = ROOT / "skills" / "spice" / "scripts"
if str(SPICE) not in sys.path:
    sys.path.insert(0, str(SPICE))

import spice_model_cache as smc  # noqa: E402
from spice_model_cache import ModelOptions  # noqa: E402

CLEAN = ".subckt OPAMP_LM358 inp inn out vcc vee\nR1 inp inn 1e12\nE1 out 0 inp inn 1e5\n.ends\n"
CONTROL = ".subckt LM358 1 2 3 4 5\n.ends\n.control\nshell touch /tmp/x\n.endc\n"


class _CacheCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.models = self.root / "spice" / "models"
        self.models.mkdir(parents=True)
        patcher = mock.patch.object(smc, "_index_cache", {})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def plant(self, text, file="LM358.sub", specs=None):
        if text is not None:
            (self.models / file).write_text(text, encoding="utf-8")
        entry = {"file": file, "mpn": "LM358", "type": "opamp", "source": "lookup",
                 "specs": {"gbw_hz": 1000000.0} if specs is None else specs}
        (self.models / "manifest.json").write_text(json.dumps({"LM358": entry}),
                                                   encoding="utf-8")

    def resolve(self, trust=False):
        sink = []
        got = smc.get_model_for_part(
            "LM358", "opamp", None,
            options=ModelOptions(cache_dir=str(self.root), offline=True,
                                 trust_project_models=trust),
            diagnostics=sink)
        return got, sink


class ModelTrustTest(_CacheCase):
    def test_control_block_model_skipped(self):
        self.plant(CONTROL)
        (subckt, source, _), sink = self.resolve()
        self.assertEqual(source, "lookup:LM358")
        self.assertNotIn(".control", subckt)
        self.assertEqual(len(sink), 1, sink)
        self.assertEqual(sink[0]["source"], "spice_model_cache.get_cached_model")
        self.assertEqual(sink[0]["effect"], "project model skipped")
        self.assertEqual(sink[0]["exception"], "ValueError")

    def test_clean_model_used(self):
        self.plant(CLEAN)
        (subckt, source, specs), sink = self.resolve()
        self.assertEqual(source, "cache:LM358")
        self.assertEqual(subckt, CLEAN)
        self.assertEqual(specs, {"gbw_hz": 1000000.0})
        self.assertEqual(sink, [])

    def test_include_or_control_line_skipped(self):
        for line in (".include ../../etc/x.lib", ".LIB /abs/x.lib", '.inc "../x.lib"',
                     ".inc\n+ ../../etc/x.lib", ".include helper.lib", ".lib sub/x.lib tt",
                     ".LIBRARY x", ".incx /abs/evil.lib", ".controlx",
                     "shell rm -rf x", "source evil.cir"):
            with self.subTest(line=line):
                smc._index_cache.clear()
                self.plant(".subckt LM358 1 2 3 4 5\n" + line + "\n.ends\n")
                (_, source, _), sink = self.resolve()
                self.assertEqual(source, "lookup:LM358")
                self.assertEqual(len(sink), 1, sink)

    def test_element_names_like_control_words_used(self):
        text = ".subckt LM358 1 2 3 4 5\nSOURCE1 1 2 3 4 SW1\nshellcap 1 2 1p\n.ends\n"
        self.plant(text)
        (subckt, source, _), sink = self.resolve()
        self.assertEqual(source, "cache:LM358")
        self.assertEqual(subckt, text)
        self.assertEqual(sink, [])

    def test_trusted_used_verbatim(self):
        self.plant(CONTROL)
        (subckt, source, _), sink = self.resolve(trust=True)
        self.assertEqual(source, "cache:LM358")
        self.assertEqual(subckt, CONTROL)
        self.assertEqual(sink, [])

    def test_poisoned_cached_specs_are_dropped(self):
        self.plant(CLEAN, specs={"gbw_hz": 1000000.0, "swing_v": "1\n.control",
                                 "rro": "yes", "vos_mv": 2})
        (_, source, specs), _ = self.resolve(trust=True)
        self.assertEqual(source, "cache:LM358")
        self.assertEqual(specs, {"gbw_hz": 1000000.0, "vos_mv": 2})


    def test_skipped_model_is_never_overwritten(self):
        self.plant(CONTROL)
        sub_before = (self.models / "LM358.sub").read_bytes()
        manifest_before = (self.models / "manifest.json").read_bytes()
        (subckt, source, _), _ = self.resolve()
        self.assertEqual(source, "lookup:LM358")
        self.assertIn(".subckt", subckt)
        self.assertEqual((self.models / "LM358.sub").read_bytes(), sub_before)
        self.assertEqual((self.models / "manifest.json").read_bytes(), manifest_before)
        self.assertEqual(sorted(p.name for p in self.models.iterdir()),
                         ["LM358.sub", "manifest.json"])


class ModelTextProblemTest(unittest.TestCase):
    def test_problems(self):
        self.assertIsNone(smc.model_text_problem(CLEAN))
        self.assertIsNone(smc.model_text_problem("* .control in a comment\n"))
        for ok in ("SOURCE1 1 2 3 4 SW1\n", "shellcap 1 2 1p\n", "Sourcefoo 1 0\n",
                   "R1 inc lib 1k\n", ".ends\n"):
            self.assertIsNone(smc.model_text_problem(ok), ok)
        for bad in ("SOURCE x.cir\n", "Shell\trm x\n", "shell\n", ".Control\n",
                    "  .endc  \n", ".controlx\n", ".LIBRARY x\n", ".inc ~/x.lib\n",
                    ".include helper.lib\n", ".incx a\n", ".lib\n", "  .Inc\n+ x.lib\n"):
            self.assertIsNotNone(smc.model_text_problem(bad), bad)


class ManifestFileTest(_CacheCase):
    def test_manifest_file_outside_is_miss(self):
        secret = self.root / "spice" / "secret.sub"
        secret.write_text(".subckt SECRET\n.ends\n", encoding="utf-8")
        for name in ("../secret.sub", str(secret), "", "LM358.txt"):
            with self.subTest(name=name):
                smc._index_cache.clear()
                self.plant(None, file=name)
                read = []
                real = Path.read_text

                def spy(p, *a, **k):
                    read.append(Path(p).name)
                    return real(p, *a, **k)

                with mock.patch.object(Path, "read_text", spy):
                    self.assertEqual(smc.get_cached_model(self.models, "LM358"), (None, None))
                self.assertNotIn("secret.sub", read)

    def test_symlink_leaf_is_miss(self):
        outside = self.root / "outside.sub"
        outside.write_text(CLEAN, encoding="utf-8")
        self.plant(None)
        os.symlink(outside, self.models / "LM358.sub")
        self.assertEqual(smc.get_cached_model(self.models, "LM358"), (None, None))

    def test_symlink_leaf_not_written_through(self):
        outside = self.root / "outside.txt"
        outside.write_text("keep", encoding="utf-8")
        os.symlink(outside, self.models / "LM358.sub")
        smc.cache_model(self.models, "LM358", "X", {}, "lookup", "opamp")
        self.assertEqual(outside.read_text(encoding="utf-8"), "keep")
        leaf = self.models / "LM358.sub"
        self.assertFalse(leaf.is_symlink())
        self.assertEqual(leaf.read_text(encoding="utf-8"), "X")
        self.assertEqual(sorted(p.name for p in self.models.iterdir()),
                         ["LM358.sub", "manifest.json"])


class TrustFlagSourceTest(unittest.TestCase):
    def _main_options(self, home, project):
        import simulate_subcircuits as ss
        import spice_simulator
        analysis = Path(project) / "analysis.json"
        analysis.write_text(json.dumps({"file": str(Path(project) / "b.kicad_sch")}),
                            encoding="utf-8")
        captured = {}

        def fake(analysis_json, **kw):
            captured["opts"] = kw.get("model_options")
            return {"summary": {}}

        with mock.patch.dict(os.environ, {"HOME": home}), \
                mock.patch.object(spice_simulator, "detect_simulator", return_value=object()), \
                mock.patch.object(ss, "simulate_subcircuits", fake), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ss.main([str(analysis)]), 0)
        return captured["opts"]

    def test_trust_flag_from_user_config_only(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as proj:
            cfg = json.dumps({"spice": {"trust_project_models": True}})
            Path(proj, ".kicad-happy.json").write_text(cfg, encoding="utf-8")
            opts = self._main_options(home, proj)
            self.assertFalse(opts is not None and opts.trust_project_models)
            Path(home, ".kicad-happy.json").write_text(
                json.dumps({"spice": {"trust_project_models": "true"}}), encoding="utf-8")
            opts = self._main_options(home, proj)
            self.assertFalse(opts is not None and opts.trust_project_models)
            Path(home, ".kicad-happy.json").write_text(cfg, encoding="utf-8")
            opts = self._main_options(home, proj)
            self.assertEqual(opts, ModelOptions(trust_project_models=True))


class SimulateKeepsTrustTest(unittest.TestCase):
    def test_workdir_fallback_keeps_the_flag(self):
        import simulate_subcircuits as ss
        seen = []

        def gen(det, out_file, context=None, parasitics=None, model_options=None):
            seen.append(model_options)
            raise ValueError("stop")

        with tempfile.TemporaryDirectory() as wd, \
                mock.patch.dict(ss.TEMPLATE_REGISTRY, {"opamp_circuits": gen}):
            ss.simulate_subcircuits(
                {"findings": [{"detector": "detect_opamp_circuits", "reference": "U1"}]},
                workdir=wd, types=["opamp_circuits"], simulator_backend=object(),
                model_options=ModelOptions(trust_project_models=True))
        self.assertEqual(seen, [ModelOptions(cache_dir=wd, trust_project_models=True)])


if __name__ == "__main__":
    unittest.main()
