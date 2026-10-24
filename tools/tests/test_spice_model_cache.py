"""The SPICE model cache never shares one machine-wide temp directory, and it
writes its manifest atomically."""
import json, os, subprocess, sys, tempfile, unittest
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


class ManifestTest(unittest.TestCase):
    def test_manifest_write_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "models"
            with mock.patch("spice_model_cache.os.replace", wraps=os.replace) as rep:
                spice_model_cache.cache_model(d, "LM358", ".subckt X\n.ends\n", {"gbw_hz": 1e6},
                                              "lookup", "opamp")
            self.assertEqual(rep.call_count, 1)
            self.assertEqual(Path(rep.call_args.args[1]), d / "manifest.json")
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


class SimulateCacheDirTest(unittest.TestCase):
    def _run(self, wd, model_options=None):
        import simulate_subcircuits as ss
        import spice_spec_fetcher

        def fake(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, "", "")
        with mock.patch("spice_simulator.subprocess.run", side_effect=fake), \
                mock.patch.object(spice_spec_fetcher, "fetch_specs", return_value=(None, None)), \
                mock.patch("spice_model_cache.resolve_cache_dir",
                           wraps=spice_model_cache.resolve_cache_dir) as rcd:
            ss.simulate_subcircuits({"findings": [dict(OPAMP)]}, workdir=wd,
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


if __name__ == "__main__":
    unittest.main()
