import json, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))
import project_config as pc


class ResolveConfig(unittest.TestCase):
    def test_discovered_mode_matches_load_config_and_hash_rule(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / ".kicad-happy.json"
            cfg.write_text(json.dumps({"version": 1, "project": {"name": "x"}}), encoding="utf-8")
            r = pc.resolve_config(None, d)
            self.assertEqual(r.mode, "discovered")
            self.assertEqual(r.effective, pc.load_config(d))
            self.assertEqual(r.hash_input, str(cfg))
            self.assertIn(str(cfg), r.paths)

    def test_discovered_mode_without_file(self):
        with tempfile.TemporaryDirectory() as d:
            r = pc.resolve_config(None, d)
            self.assertIsNone(r.hash_input)
            self.assertEqual(r.effective, pc.load_config(d))

    def test_explicit_mode_does_not_cascade(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "c.json"; f.write_text('{"version": 1, "project": {"name": "y"}}', encoding="utf-8")
            r = pc.resolve_config(str(f), d)
            self.assertEqual((r.mode, r.paths, r.hash_input), ("explicit", (str(f),), str(f)))
            self.assertEqual(r.effective, pc.load_config_from_path(str(f)))
            missing = pc.resolve_config(str(Path(d) / "nope.json"), d)
            self.assertEqual((missing.paths, missing.hash_input), ((), None))
            self.assertEqual(missing.effective, pc.load_config_from_path(str(Path(d) / "nope.json")))


if __name__ == "__main__":
    unittest.main()
