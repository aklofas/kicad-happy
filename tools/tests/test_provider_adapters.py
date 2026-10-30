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


class NullPayload(unittest.TestCase):
    """A listing whose fields are JSON null (or unparseable) is a failed part, not a crash."""

    def _sync(self, p, hit, search, extra_patches=(), **kw):
        import io, json, tempfile
        from contextlib import ExitStack, redirect_stderr, redirect_stdout
        from unittest import mock
        prov = _load(p, "provider")
        from distributor_core.sync import sync_datasheets
        results = {}
        for par in (1, 2):
            with tempfile.TemporaryDirectory() as d, ExitStack() as stack:
                d = Path(d)
                stack.enter_context(mock.patch.object(prov, search, lambda *a, **k: hit))
                stack.enter_context(mock.patch.object(prov, "try_alternative_sources", lambda *a, **k: False))
                for name, value in extra_patches:
                    stack.enter_context(mock.patch.object(prov, name, value))
                stack.enter_context(redirect_stderr(io.StringIO()))
                stack.enter_context(redirect_stdout(io.StringIO()))
                (d / "m.txt").write_text("LM358DR\nNE555P\n", encoding="utf-8")
                sync_datasheets(prov, mpn_list=str(d / "m.txt"), output_dir=str(d / "o"),
                                delay=0, parallel=par, **kw)
                parts = json.loads((d / "o" / "manifest.json").read_text(encoding="utf-8"))["parts"]
                results[par] = {k: (v["status"], v["error"], v["manufacturer"]) for k, v in parts.items()}
        self.assertEqual(results[1], results[2])
        return results[1]

    def test_element14_null_datasheets(self):
        hit = {"translatedManufacturerPartNumber": "LM358DR", "sku": "1", "datasheets": None}
        got = self._sync("element14", hit, "search_element14", api_key="KEY")
        self.assertEqual(got["LM358DR"], ("failed", "No datasheet URL or all download methods failed", ""))

    def test_digikey_null_manufacturer_and_description(self):
        hit = {"ManufacturerProductNumber": "LM358DR", "Manufacturer": None, "Description": None,
               "DatasheetUrl": ""}
        got = self._sync("digikey", hit, "search_digikey_with_token",
                         extra_patches=(("get_oauth_token", lambda: ("T", "C")),))
        self.assertEqual(got["LM358DR"], ("no_datasheet", "DigiKey listing has no datasheet URL", ""))

    def test_lcsc_unparseable_extra(self):
        hit = {"mfr": "LM358DR", "lcsc": "7950", "datasheet": "", "extra": "{not json"}
        got = self._sync("lcsc", hit, "search_lcsc",
                         extra_patches=(("search_lcsc_direct", lambda *a, **k: None),))
        self.assertEqual(got["LM358DR"], ("failed", "No datasheet URL or all download methods failed", ""))


if __name__ == "__main__":
    unittest.main()
