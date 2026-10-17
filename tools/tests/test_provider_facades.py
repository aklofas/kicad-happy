import json, sys, unittest
from pathlib import Path
TESTS = Path(__file__).resolve().parent
SKILLS = TESTS.parents[1] / "skills"
PROVIDERS = ("digikey", "mouser", "lcsc", "element14")


def _load(p, kind):
    import importlib
    sys.path.insert(0, str(SKILLS / p / "scripts"))
    try:
        return importlib.import_module(f"{kind}_{p}")
    finally:
        sys.path.pop(0)


class Facades(unittest.TestCase):
    def test_fetch_and_sync_scripts_bind_every_round5_name(self):
        for p in PROVIDERS:
            for kind in ("fetch_datasheet", "sync_datasheets"):
                mod = _load(p, kind)
                names = json.loads((TESTS / f"{kind}_{p}_names_round5.json").read_text(encoding="utf-8"))
                missing = [n for n in names if n != "main" and not hasattr(mod, n)]
                self.assertEqual(missing, [], f"{kind}_{p}")

    def test_provider_adapters_expose_the_contract(self):
        import importlib
        for p in PROVIDERS:
            sys.path.insert(0, str(SKILLS / p / "scripts"))
            try:
                prov = importlib.import_module(f"provider_{p}")
            finally:
                sys.path.pop(0)
            for attr in ("NAME", "DEFAULT_DELAY", "ID_KEYS", "KEY_PRIORITY", "SKIPPED_COUNTS_IDS", "RENAME_PRESENT",
                         "FAILED_DETAIL_WITH_URL", "NORMALIZE_REDIRECTS", "LABELS", "preflight", "authenticate",
                         "sync_one_part", "report_tail"):
                self.assertTrue(hasattr(prov, attr), f"{p}.{attr}")
            self.assertEqual(prov.NAME, p)
            self.assertEqual(set(prov.LABELS), {"found", "skipped_key", "total_key", "dry_skipped", "summary_skipped"})

    def test_lcsc_enrich_looks_up_search_direct_in_provider_module(self):
        import importlib, inspect
        sys.path.insert(0, str(SKILLS / "lcsc" / "scripts"))
        try:
            prov = importlib.import_module("provider_lcsc")
        finally:
            sys.path.pop(0)
        self.assertIn("search_lcsc_direct(", inspect.getsource(prov.enrich_with_wmsc))
        self.assertIs(prov.enrich_with_wmsc.__globals__["search_lcsc_direct"], prov.search_lcsc_direct)


if __name__ == "__main__":
    unittest.main()
