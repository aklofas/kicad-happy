import sys, unittest
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


class ProviderAdapters(unittest.TestCase):
    def test_provider_adapters_expose_the_contract(self):
        import importlib
        for p in PROVIDERS:
            sys.path.insert(0, str(SKILLS / p / "scripts"))
            try:
                prov = importlib.import_module(f"provider_{p}")
            finally:
                sys.path.pop(0)
            for attr in ("NAME", "DEFAULT_DELAY", "ID_KEYS", "KEY_PRIORITY", "SEARCH_KEY", "RENAME_PRESENT",
                         "FAILED_DETAIL_WITH_URL", "NORMALIZE_REDIRECTS", "LABELS", "preflight", "authenticate",
                         "sync_one_part", "report_tail"):
                self.assertTrue(hasattr(prov, attr), f"{p}.{attr}")
            self.assertEqual(prov.NAME, p)
            self.assertEqual(prov.SEARCH_KEY, p)
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

    def test_normalize_url_redirect_flag_per_provider(self):
        import importlib
        ti = "https://www.ti.com/general/docs/suppproductinfo.tsp?gotoUrl=https%3A%2F%2Fwww.ti.com%2Flit%2Fgpn%2Flm358"
        expect = {"digikey": "https://www.ti.com/lit/gpn/lm358", "mouser": "https://www.ti.com/lit/gpn/lm358",
                  "lcsc": ti, "element14": ti}
        sys.path.insert(0, str(SKILLS / "digikey" / "scripts"))
        try:
            import _core_path  # noqa: F401
            from distributor_core.download import normalize_url
        finally:
            sys.path.pop(0)
        for p in ("digikey", "mouser"):
            self.assertEqual(normalize_url(ti), expect[p], p)
        for p in ("lcsc", "element14"):
            sys.path.insert(0, str(SKILLS / p / "scripts"))
            try:
                prov = importlib.import_module(f"provider_{p}")
            finally:
                sys.path.pop(0)
            self.assertEqual(prov.normalize_url(ti), ti, f"provider_{p}")


if __name__ == "__main__":
    unittest.main()
