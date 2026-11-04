import sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "spice" / "scripts"))
import spice_model_cache as smc


class ModelOptions(unittest.TestCase):
    def test_offline_never_calls_fetch_specs_and_still_uses_lookup_table(self):
        import spice_spec_fetcher
        with mock.patch.object(spice_spec_fetcher, "fetch_specs", side_effect=AssertionError("network")) as mock_fetch:
            subckt, source, specs = smc.get_model_for_part("LM358", "opamp", None,
                                                           options=smc.ModelOptions(offline=True))
        self.assertFalse(mock_fetch.called)
        self.assertTrue(subckt)
        self.assertEqual(source, "lookup:LM358")

    def test_cache_dir_override_is_used_for_cache_reads_and_writes(self):
        with tempfile.TemporaryDirectory() as d:
            opts = smc.ModelOptions(cache_dir=d, offline=True)
            smc.get_model_for_part("LM358", "opamp", {"file": "/nonexistent/x.kicad_sch"}, options=opts)
            self.assertTrue((Path(d) / "spice" / "models").is_dir())
            subckt, source, _ = smc.get_model_for_part("LM358", "opamp", {"file": "/nonexistent/x.kicad_sch"}, options=opts)
            self.assertEqual(source, "cache:LM358")

    def test_defaults_unchanged(self):
        self.assertEqual(smc.ModelOptions(), smc.ModelOptions(cache_dir=None, offline=False))

    def test_cli_flags_exist(self):
        import subprocess
        r = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] / "skills/spice/scripts/simulate_subcircuits.py"), "--help"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        out = r.stdout
        self.assertIn("--model-cache-dir", out); self.assertIn("--offline", out)


if __name__ == "__main__":
    unittest.main()
