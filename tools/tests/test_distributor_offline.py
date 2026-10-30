import json, sys, tempfile, unittest
from pathlib import Path
TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
FX = TOOLS / "tests" / "fixtures" / "distributor"


class Oracle(unittest.TestCase):
    def test_frozen_clock_isoformat(self):
        from datetime import timezone
        import distributor_offline as do
        self.assertEqual(do.FrozenDatetime.now(timezone.utc).isoformat(), "2026-10-16T00:00:00+00:00")

    def test_fake_transport_download_writes_markers_and_extract_reads_them(self):
        import distributor_offline as do
        t = do.FakeTransport({"downloads": {"https://x/a.pdf": "LM358DR text", "https://x/bad.pdf": False}})
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d) / "a.pdf")
            self.assertTrue(t.download("https://x/a.pdf", out))
            self.assertEqual(t.extract_text(out), "LM358DR text")
            self.assertFalse(t.download("https://x/bad.pdf", str(Path(d) / "b.pdf")))
            self.assertFalse((Path(d) / "b.pdf").exists())
            self.assertFalse(t.download("https://x/unknown.pdf", str(Path(d) / "c.pdf")))

    def test_fake_transport_download_failure_is_recorded(self):
        import distributor_offline as do
        sys.path.insert(0, str(TOOLS.parent / "skills" / "datasheets"))
        from distributor_core.download import take_transport_failure
        t = do.FakeTransport({"downloads": {"https://x/a.pdf": {"transport": "ConnectionResetError"}}})
        take_transport_failure()
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(t.download("https://x/a.pdf", str(Path(d) / "a.pdf")))
            self.assertFalse((Path(d) / "a.pdf").exists())
        self.assertEqual(take_transport_failure(),
                         "network failure, retried next run: ConnectionResetError: fixture transport failure")

    def test_provider_modules_are_loaded_from_the_selected_tree(self):
        import importlib
        import shutil
        import distributor_offline as do
        repo = TOOLS.parent
        with tempfile.TemporaryDirectory() as d:
            other = Path(d) / "other"
            for name in ("datasheets", "digikey", "mouser", "lcsc", "element14", "kicad"):
                shutil.copytree(repo / "skills" / name, other / "skills" / name,
                                ignore=shutil.ignore_patterns("__pycache__"))
            saved = list(sys.path)
            try:
                sys.path[:0] = [str(other / "skills" / "datasheets"), str(other / "skills" / "kicad" / "scripts"),
                                str(other / "skills" / "digikey" / "scripts")]
                names = ["_core_path", "provider_digikey", "kicad_core", "schematic"]
                for name in names:
                    importlib.import_module(name)
                    self.assertTrue(Path(sys.modules[name].__file__).resolve().is_relative_to(other.resolve()))
                with tempfile.TemporaryDirectory() as w, do._provider_env("digikey", repo, Path(w)):
                    for name in names + ["distributor_core.sync"]:
                        mod = sys.modules.get(name) or importlib.import_module(name)
                        loaded = Path(mod.__file__).resolve()
                        self.assertTrue(loaded.is_relative_to((repo / "skills").resolve()), f"{name}: {loaded}")
                leftovers = [m for m in sys.modules if m.split(".")[0] in ("provider_digikey", "distributor_core")]
                self.assertFalse(leftovers)
            finally:
                sys.path[:] = saved
                do._drop_provider_modules()

    def test_second_provider_gets_its_own_core_path(self):
        import distributor_offline as do
        repo = TOOLS.parent
        seen = []
        for provider in ("digikey", "lcsc"):
            with tempfile.TemporaryDirectory() as w, do._provider_env(provider, repo, Path(w)):
                seen.append(Path(sys.modules["_core_path"].__file__).resolve())
        self.assertEqual(seen, [repo / "skills" / p / "scripts" / "_core_path.py" for p in ("digikey", "lcsc")])

    def test_provider_only_runs(self):
        import distributor_offline as do
        self.assertIn("sync-sch-dry (digikey)", do.runs_for("digikey"))
        self.assertNotIn("sync-sch-dry (digikey)", do.runs_for("lcsc"))
        self.assertIn("sync-lcsc-direct (lcsc)", do.runs_for("lcsc"))
        self.assertNotIn("sync-lcsc-direct (lcsc)", do.runs_for("mouser"))
        self.assertEqual(do.run_dir_name("sync-lcsc-direct (lcsc)"), "sync-lcsc-direct")

    def test_seed_names_the_provider_under_test_and_another(self):
        import distributor_offline as do
        for provider, other in (("digikey", "mouser"), ("element14", "digikey")):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as d:
                do._prepare(do.RUNS["sync-second-provider"], Path(d), provider)
                parts = json.loads((Path(d) / "ds" / "manifest.json").read_text(encoding="utf-8"))["parts"]
                self.assertEqual(parts["LM358DR"]["failed_providers"], [other])
                self.assertEqual(parts["MISSING9999"]["failed_providers"], [provider])

    def test_every_provider_and_run_matches_expected(self):
        import distributor_offline as do
        for provider in ("digikey", "mouser", "lcsc", "element14"):
            for run in do.runs_for(provider):
                with self.subTest(provider=provider, run=run):
                    diffs = do.compare_run(provider, run, FX / "expected")
                    self.assertEqual(diffs, [], f"{provider}/{run}: {diffs[:3]}")

    def test_scenario_covers_every_identifier_only_part(self):
        bom = json.loads((FX / "scenario" / "bom.schematic.json").read_text(encoding="utf-8"))["bom"]
        only = {e["references"][0]: [k for k in ("digikey", "mouser", "lcsc", "element14") if e.get(k)] for e in bom if not e["mpn"] and any(e.get(k) for k in ("digikey", "mouser", "lcsc", "element14"))}
        self.assertEqual(only, {"U8": ["digikey"], "U9": ["mouser"], "U10": ["lcsc"], "U11": ["element14"]})


if __name__ == "__main__":
    unittest.main()
