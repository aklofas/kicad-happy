"""Fixture-root helper: no machine-local defaults, skip when unset."""
import importlib
import os
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent


class FixtureRootTest(unittest.TestCase):
    def test_no_hardcoded_fixture_roots(self):
        bad = []
        for p in sorted(HERE.glob("*.py")):
            if p.name == Path(__file__).name:
                continue
            text = p.read_text(encoding="utf-8")
            if "/tmp/harness-pin" in text or 'os.environ.get("FX"' in text:
                bad.append(p.name)
        self.assertEqual(bad, [])

    def test_fixture_skips_when_unset(self):
        import tools.tests._fixtures as fx
        env = {k: v for k, v in os.environ.items() if k != "KH_FIXTURES"}
        try:
            with mock.patch.dict(os.environ, env, clear=True):
                importlib.reload(fx)
                self.assertIsNone(fx.FIXTURES)
                with self.assertRaises(unittest.SkipTest):
                    fx.fixture("simple-project")
                self.assertFalse(fx.fixture_path("simple-project").exists())
        finally:
            importlib.reload(fx)

    def test_set_but_missing_root_fails_not_skips(self):
        import tools.tests._fixtures as fx
        try:
            with mock.patch.dict(os.environ, {"KH_FIXTURES": "/nonexistent-kh-root"}):
                with self.assertRaises(AssertionError):
                    importlib.reload(fx)
        finally:
            importlib.reload(fx)

    def test_set_root_missing_fixture_fails_not_skips(self):
        import tempfile
        import tools.tests._fixtures as fx
        with tempfile.TemporaryDirectory() as d:
            try:
                with mock.patch.dict(os.environ, {"KH_FIXTURES": d}):
                    importlib.reload(fx)
                    self.assertTrue(fx.have(Path(d)))
                    with self.assertRaises(AssertionError):
                        fx.fixture("no-such-fixture")
                    with self.assertRaises(AssertionError):
                        fx.have(Path(d, "no-such-fixture"))
            finally:
                importlib.reload(fx)
