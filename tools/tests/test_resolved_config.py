import contextlib, io, json, os, sys, tempfile, unittest
from unittest import mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))
import project_config as pc


class ResolveConfig(unittest.TestCase):
    def test_discovered_mode_matches_load_config_and_hash_rule(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / ".kicad-happy.json"
            cfg.write_text(json.dumps({"version": 1, "project": {"name": "x"}}), encoding="utf-8")
            r = pc.resolve_config(None, d)
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
            self.assertEqual((r.paths, r.hash_input), ((str(f),), str(f)))
            self.assertEqual(r.effective, pc.load_config_from_path(str(f)))
            missing = pc.resolve_config(str(Path(d) / "nope.json"), d)
            self.assertEqual((missing.paths, missing.hash_input), ((), None))
            self.assertEqual(missing.effective, pc.load_config_from_path(str(Path(d) / "nope.json")))

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
                mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home}), \
                contextlib.redirect_stderr(err):
            pc.resolve_config(None, d)
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
