"""The SPICE model cache sits beside the project the analysis names, never in one
machine-wide temp directory, and it writes its manifest atomically."""
import contextlib, io, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPICE = ROOT / "skills" / "spice" / "scripts"
if str(SPICE) not in sys.path:
    sys.path.insert(0, str(SPICE))

import spice_model_cache  # noqa: E402
from spice_model_cache import ModelOptions  # noqa: E402

OPAMP = {"detector": "detect_opamp_circuits", "configuration": "inverting", "reference": "U1",
         "value": "LM358", "output_net": "OUT", "inverting_input_net": "INN",
         "non_inverting_input_net": "GND", "gain": -10.0,
         "feedback_resistor": {"ref": "R2", "ohms": 100000.0},
         "input_resistor": {"ref": "R1", "ohms": 10000.0}}


class FallbackDirTest(unittest.TestCase):
    def test_fallback_dir_is_per_process_not_machine_wide(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(spice_model_cache, "_PROCESS_CACHE_DIR", None, create=True), \
                mock.patch("tempfile.tempdir", root):
            first = spice_model_cache.resolve_cache_dir({})
            second = spice_model_cache.resolve_cache_dir({})
            self.assertEqual(first, second)
            self.assertTrue(Path(first).resolve().is_relative_to(Path(root).resolve()), first)
            self.assertTrue(Path(first).parent.parent.name.startswith("kicad-happy-spice-"), first)
            self.assertFalse((Path(root) / "kicad-happy-spice" / "models").exists())

    def test_override_and_file_unchanged(self):
        self.assertEqual(spice_model_cache.resolve_cache_dir({}, override_dir="/x"),
                         Path("/x") / "spice" / "models")
        self.assertEqual(spice_model_cache.resolve_cache_dir({"file": "/p/a.kicad_sch"}),
                         Path("/p") / "spice" / "models")

    def test_source_files_names_the_project(self):
        a = {"inputs": {"source_files": ["/x/proj/board.kicad_sch"]}}
        self.assertEqual(spice_model_cache.resolve_cache_dir(a),
                         Path("/x/proj") / "spice" / "models")
        self.assertEqual(spice_model_cache.project_dir_from_analysis(a), Path("/x/proj"))

    def test_file_wins_over_source_files(self):
        a = {"file": "/p/a.kicad_sch", "inputs": {"source_files": ["/x/proj/board.kicad_sch"]}}
        self.assertEqual(spice_model_cache.resolve_cache_dir(a), Path("/p") / "spice" / "models")

    def test_no_source_file_uses_the_process_fallback(self):
        for a in ({}, {"file": None, "inputs": {"source_files": []}}, {"inputs": None}):
            self.assertIsNone(spice_model_cache.project_dir_from_analysis(a))
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(spice_model_cache, "_PROCESS_CACHE_DIR", None, create=True), \
                mock.patch("tempfile.tempdir", root):
            got = spice_model_cache.resolve_cache_dir({"file": None, "inputs": {"source_files": []}})
            self.assertTrue(Path(got).resolve().is_relative_to(Path(root).resolve()), got)


class ManifestTest(unittest.TestCase):
    def test_manifest_write_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "models"
            with mock.patch("spice_model_cache.os.replace", wraps=os.replace) as rep:
                spice_model_cache.cache_model(d, "LM358", ".subckt X\n.ends\n", {"gbw_hz": 1e6},
                                              "lookup", "opamp")
            # the model file is swapped in first, then the manifest
            self.assertEqual([Path(c.args[1]) for c in rep.call_args_list],
                             [d / "LM358.sub", d / "manifest.json"])
            src = Path(rep.call_args.args[0])
            self.assertEqual(src.parent, d)
            self.assertNotEqual(src.name, "manifest.json.tmp")
            self.assertTrue(src.name.startswith("manifest.") and src.name.endswith(".tmp"), src.name)
            self.assertEqual(list(d.glob("*.tmp")), [])
            with open(d / "manifest.json", encoding="utf-8") as f:
                self.assertEqual(json.load(f)["LM358"]["mpn"], "LM358")


    def test_manifest_write_failure_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "models"
            spice_model_cache.cache_model(d, "LM358", ".subckt X\n.ends\n", {}, "lookup", "opamp")
            before = (d / "manifest.json").read_bytes()
            with mock.patch("spice_model_cache.json.dump", side_effect=ValueError("boom")):
                with self.assertRaises(ValueError):
                    spice_model_cache.cache_model(d, "TL072", ".subckt Y\n.ends\n", {}, "lookup", "opamp")
            self.assertEqual(list(d.glob("manifest.*.tmp")), [])
            self.assertEqual((d / "manifest.json").read_bytes(), before)


class UnwritableCacheTest(unittest.TestCase):
    def test_lookup_model_is_used_when_the_cache_cannot_be_written(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root can write a read-only directory")
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "proj"
            d.mkdir()
            os.chmod(d, 0o555)
            try:
                if os.access(d, os.W_OK):
                    self.skipTest("directory is still writable")
                sink = []
                subckt, source, specs = spice_model_cache.get_model_for_part(
                    "LM358", "opamp", {"inputs": {"source_files": [str(d / "x.kicad_sch")]}},
                    ModelOptions(offline=True), diagnostics=sink)
            finally:
                os.chmod(d, 0o755)
        self.assertEqual(source, "lookup:LM358")
        self.assertIn("LM358", subckt)
        self.assertTrue(specs)
        self.assertEqual(len(sink), 1, sink)
        self.assertEqual(sink[0]["source"], "spice_model_cache.cache_model")
        self.assertEqual(sink[0]["effect"], "model not cached")


class SimulateCacheDirTest(unittest.TestCase):
    def _run(self, wd, model_options=None, analysis=None):
        import simulate_subcircuits as ss
        import spice_spec_fetcher

        def fake(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, "", "")
        with mock.patch("spice_simulator.subprocess.run", side_effect=fake), \
                mock.patch.object(spice_spec_fetcher, "fetch_specs", return_value=(None, None)), \
                mock.patch("spice_model_cache.resolve_cache_dir",
                           wraps=spice_model_cache.resolve_cache_dir) as rcd:
            ss.simulate_subcircuits(dict(analysis or {}, findings=[dict(OPAMP)]), workdir=wd,
                                    model_options=model_options)
        return rcd

    def test_simulate_defaults_cache_to_workdir_when_analysis_has_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            wd = os.path.join(tmp, "ws")
            rcd = self._run(wd)
            self.assertTrue(rcd.call_args_list)
            for c in rcd.call_args_list:
                self.assertEqual(c.kwargs["override_dir"], wd)
            self.assertTrue((Path(wd) / "spice" / "models" / "manifest.json").is_file())

            other = os.path.join(tmp, "other")
            rcd = self._run(os.path.join(tmp, "ws2"), ModelOptions(cache_dir=other))
            self.assertTrue(rcd.call_args_list)
            for c in rcd.call_args_list:
                self.assertEqual(c.kwargs["override_dir"], other)
            self.assertTrue((Path(other) / "spice" / "models" / "manifest.json").is_file())
            self.assertFalse((Path(tmp) / "ws2" / "spice").exists())

    def test_simulate_caches_beside_the_named_source_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = os.path.join(tmp, "proj")
            wd = os.path.join(tmp, "ws")
            rcd = self._run(wd, analysis={"inputs": {"source_files": [
                os.path.join(proj, "board.kicad_sch")]}})
            self.assertTrue(rcd.call_args_list)
            for c in rcd.call_args_list:
                self.assertIsNone(c.kwargs["override_dir"])
            self.assertTrue((Path(proj) / "spice" / "models" / "manifest.json").is_file())
            self.assertFalse((Path(wd) / "spice").exists())


class CacheFileModeTest(unittest.TestCase):
    def test_model_and_manifest_use_the_import_time_mode(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(spice_model_cache, "DEFAULT_FILE_MODE", 0o640, create=True):
            spice_model_cache.cache_model(tmp, "LM358", ".subckt LM358 1 2\n.ends\n", {},
                                          "lookup", "opamp")
            self.assertEqual((Path(tmp) / "LM358.sub").stat().st_mode & 0o777, 0o640)
            self.assertEqual((Path(tmp) / "manifest.json").stat().st_mode & 0o777, 0o640)


class SimulateSymlinkedProjectCacheTest(unittest.TestCase):
    """A project whose spice/ or spice/models/ is a symlink caches under the run's
    workdir instead; an explicit cache dir is the user's choice and is used as given."""

    def _run(self, wd, analysis, model_options=None):
        import simulate_subcircuits as ss
        import spice_spec_fetcher

        def fake(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, "", "")
        with mock.patch("spice_simulator.subprocess.run", side_effect=fake), \
                mock.patch.object(spice_spec_fetcher, "fetch_specs", return_value=(None, None)), \
                contextlib.redirect_stderr(io.StringIO()):
            return ss.simulate_subcircuits(dict(analysis, findings=[dict(OPAMP)]), workdir=wd,
                                           model_options=model_options)

    def test_symlinked_project_folders_not_used(self):
        for link in ("spice", "spice/models"):
            with self.subTest(link=link), tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                outside = tmp / "outside"
                outside.mkdir()
                proj = tmp / "proj"
                (proj / link).parent.mkdir(parents=True, exist_ok=True)
                (proj / link).symlink_to(outside, target_is_directory=True)
                wd = tmp / "ws"
                report = self._run(str(wd), {"file": str(proj / "board.kicad_sch")})
                self.assertEqual(os.listdir(outside), [])
                self.assertTrue((wd / "spice" / "models" / "manifest.json").is_file())
                cache_records = [d for d in report["diagnostics"]
                                 if d["source"] == "simulate_subcircuits.simulate_subcircuits"]
                self.assertEqual(len(cache_records), 1, report["diagnostics"])
                self.assertIn(str(proj / link), cache_records[0]["message"])

    def test_explicit_cache_dir_symlink_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            outside = tmp / "outside"
            outside.mkdir()
            chosen = tmp / "chosen"
            chosen.mkdir()
            (chosen / "spice").symlink_to(outside, target_is_directory=True)
            report = self._run(str(tmp / "ws"), {"file": str(tmp / "proj" / "board.kicad_sch")},
                               ModelOptions(cache_dir=str(chosen)))
            self.assertTrue((outside / "models" / "manifest.json").is_file())
            self.assertEqual(report["diagnostics"], [])


if __name__ == "__main__":
    unittest.main()
