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

    def test_every_provider_and_run_matches_expected(self):
        import distributor_offline as do
        for provider in ("digikey", "mouser", "lcsc", "element14"):
            for run in do.RUNS:
                if run.endswith("(digikey)") and provider != "digikey":
                    continue
                with self.subTest(provider=provider, run=run):
                    diffs = do.compare_run(provider, run, FX / "expected")
                    self.assertEqual(diffs, [], f"{provider}/{run}: {diffs[:3]}")

    def test_scenario_covers_every_identifier_only_part(self):
        bom = json.loads((FX / "scenario" / "bom.schematic.json").read_text(encoding="utf-8"))["bom"]
        only = {e["references"][0]: [k for k in ("digikey", "mouser", "lcsc", "element14") if e.get(k)] for e in bom if not e["mpn"] and any(e.get(k) for k in ("digikey", "mouser", "lcsc", "element14"))}
        self.assertEqual(only, {"U8": ["digikey"], "U9": ["mouser"], "U10": ["lcsc"], "U11": ["element14"]})


if __name__ == "__main__":
    unittest.main()
