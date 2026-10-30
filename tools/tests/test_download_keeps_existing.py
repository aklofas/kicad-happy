"""A failed datasheet download never removes the file already on disk, and a distributor
search that failed in transport (timeout, refused connection, 5xx) is not recorded as
not_found: the next run retries it. No network: every transport is a local fake."""
import io, json, os, sys, tempfile, unittest, urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "datasheets"))
sys.path.insert(0, str(ROOT / "skills" / "lcsc" / "scripts"))

GOOD = b"%PDF-1.4 good datasheet\n"


def _writer(body):
    def fn(url, path):
        with open(path, "wb") as f:
            f.write(body)
        return True
    return fn


def _raiser(exc):
    def fn(url, path):
        with open(path, "wb") as f:
            f.write(b"partial")
        raise exc
    return fn


class DownloadKeepsExistingTest(unittest.TestCase):
    def setUp(self):
        from distributor_core import download
        p = mock.patch.object(download, "_resolve", return_value=["93.184.216.34"])
        p.start()
        self.addCleanup(p.stop)

    def _download(self, method):
        from distributor_core import download
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "LM358.pdf")
            with open(target, "wb") as f:
                f.write(GOOD)
            with mock.patch.object(download, "_requests", None), \
                    mock.patch.object(download, "_sync_playwright", None), \
                    mock.patch.object(download, "_download_urllib", method), \
                    redirect_stdout(io.StringIO()):
                ok = download.download_pdf("https://example.invalid/x.pdf", target)
            with open(target, "rb") as f:
                body = f.read()
            return ok, body, sorted(os.listdir(d))

    def test_transport_failure_keeps_the_existing_file(self):
        ok, body, files = self._download(_raiser(urllib.error.URLError("refused")))
        self.assertFalse(ok)
        self.assertEqual(body, GOOD)
        self.assertEqual(files, ["LM358.pdf"])

    def test_non_pdf_body_keeps_the_existing_file(self):
        ok, body, files = self._download(_writer(b"<html>error</html>"))
        self.assertFalse(ok)
        self.assertEqual(body, GOOD)
        self.assertEqual(files, ["LM358.pdf"])

    def test_good_download_replaces_the_file(self):
        ok, body, files = self._download(_writer(b"%PDF-1.7 newer"))
        self.assertTrue(ok)
        self.assertEqual(body, b"%PDF-1.7 newer")
        self.assertEqual(files, ["LM358.pdf"])


class TransportClassificationTest(unittest.TestCase):
    def test_classification(self):
        from distributor_core.download import is_transport_error
        http = lambda code: urllib.error.HTTPError("u", code, "m", {}, None)
        self.assertTrue(is_transport_error(urllib.error.URLError("refused")))
        self.assertTrue(is_transport_error(TimeoutError("timed out")))
        self.assertTrue(is_transport_error(ConnectionRefusedError()))
        self.assertTrue(is_transport_error(http(500)))
        self.assertTrue(is_transport_error(http(503)))
        self.assertTrue(is_transport_error(http(429)))
        self.assertFalse(is_transport_error(http(401)))
        self.assertFalse(is_transport_error(http(403)))
        self.assertFalse(is_transport_error(http(404)))
        self.assertFalse(is_transport_error(http(400)))
        self.assertFalse(is_transport_error(ValueError("bad json")))


LABELS = {"found": "Found {n} ({k})", "skipped_key": "skipped_no_identifier", "total_key": "total",
          "dry_skipped": "Skipped: {k}", "summary_skipped": "  Skipped: {k}"}


def _provider(sync_one_part):
    return SimpleNamespace(
        NAME="fake", DEFAULT_DELAY=0.0, ID_KEYS=("lcsc",), KEY_PRIORITY=("lcsc",), SEARCH_KEY="lcsc",
        RENAME_PRESENT=False, FAILED_DETAIL_WITH_URL=False,
        NORMALIZE_REDIRECTS=False, LABELS=LABELS, preflight=lambda **kw: {},
        authenticate=lambda: {"ctx": None}, report_tail=lambda *a: None, sync_one_part=sync_one_part)


def _not_found(part, outage=None):
    from distributor_core.download import note_transport_failure
    if outage is not None:
        note_transport_failure(outage)
    return {"manufacturer": "", "description": "", "value": part["value"],
            "references": part["references"], "status": "not_found",
            "error": "No results", "last_attempt": "t"}


class SyncOutageTest(unittest.TestCase):
    def _bom(self, d):
        p = Path(d) / "bom.json"
        p.write_text(json.dumps({"bom": [{"mpn": "LM358DR", "references": ["U1"],
                                          "value": "LM358DR", "type": "ic"}]}), encoding="utf-8")
        return str(p)

    def _sync(self, d, provider, **kw):
        from distributor_core.sync import sync_datasheets
        self.stderr = io.StringIO()
        with redirect_stderr(self.stderr), redirect_stdout(io.StringIO()):
            r = sync_datasheets(provider, input_path=self._bom(d), output_dir=str(Path(d) / "out"), **kw)
        m = json.loads((Path(d) / "out" / "manifest.json").read_text(encoding="utf-8"))
        return r, m

    def test_rate_limit_is_retried_next_run(self):
        err = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        with tempfile.TemporaryDirectory() as d:
            _, m = self._sync(d, _provider(lambda p, *a: _not_found(p, err)))
            self.assertEqual(m["parts"]["LM358DR"]["status"], "error")
            self.assertIn("429", m["parts"]["LM358DR"]["error"])
            dry, _ = self._sync(d, _provider(lambda p, *a: _not_found(p)), dry_run=True, as_json=True)
            self.assertEqual(dry["would_download"], ["LM358DR"])

    def test_auth_failure_is_an_error_naming_the_status(self):
        for code in (401, 403):
            err = urllib.error.HTTPError("u", code, "Forbidden", {}, None)
            with tempfile.TemporaryDirectory() as d:
                _, m = self._sync(d, _provider(lambda p, *a: _not_found(p, err)))
            entry = m["parts"]["LM358DR"]
            self.assertEqual(entry["status"], "error", code)
            self.assertIn(f"HTTP {code}", entry["error"])
            self.assertIn("credentials", entry["error"])

    def test_outage_is_retried_next_run(self):
        outage = urllib.error.URLError(ConnectionRefusedError("refused"))
        with tempfile.TemporaryDirectory() as d:
            _, m = self._sync(d, _provider(lambda p, *a: _not_found(p, outage)))
            self.assertEqual(m["parts"]["LM358DR"]["status"], "error")
            self.assertIn("network failure", m["parts"]["LM358DR"]["error"])
            dry, _ = self._sync(d, _provider(lambda p, *a: _not_found(p)), dry_run=True, as_json=True)
            self.assertEqual(dry["would_download"], ["LM358DR"])
            self.assertEqual(dry["skipped_previous_failures"], [])

    def test_real_not_found_stays_not_found(self):
        with tempfile.TemporaryDirectory() as d:
            _, m = self._sync(d, _provider(lambda p, *a: _not_found(p)))
            self.assertEqual(m["parts"]["LM358DR"]["status"], "not_found")
            dry, _ = self._sync(d, _provider(lambda p, *a: _not_found(p)), dry_run=True, as_json=True)
            self.assertEqual(dry["skipped_previous_failures"], ["LM358DR"])

    def test_http_4xx_is_an_answer(self):
        err = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        with tempfile.TemporaryDirectory() as d:
            _, m = self._sync(d, _provider(lambda p, *a: _not_found(p, err)))
            self.assertEqual(m["parts"]["LM358DR"]["status"], "not_found")

    def test_force_all_outage_keeps_a_present_ok_entry(self):
        outage = TimeoutError("timed out")
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out"
            out.mkdir()
            (out / "LM358DR.pdf").write_bytes(GOOD)
            ok = {"file": "LM358DR.pdf", "status": "ok", "references": ["U1"], "size_bytes": len(GOOD)}
            (out / "manifest.json").write_text(json.dumps({"parts": {"LM358DR": ok}}), encoding="utf-8")
            r, m = self._sync(d, _provider(lambda p, *a: _not_found(p, outage)), force_all=True)
            self.assertEqual(m["parts"]["LM358DR"]["status"], "ok")
            self.assertEqual((out / "LM358DR.pdf").read_bytes(), GOOD)
            self.assertEqual(r["failed"], 1)
            self.assertIn("LM358DR — network failure, retried next run: TimeoutError: timed out",
                          self.stderr.getvalue())


class LcscProviderOutageTest(unittest.TestCase):
    def test_refused_search_is_not_not_found(self):
        import provider_lcsc
        from distributor_core.sync import sync_datasheets

        def refuse(*a, **k):
            raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        with tempfile.TemporaryDirectory() as d:
            bom = Path(d) / "bom.json"
            bom.write_text(json.dumps({"bom": [{"mpn": "", "lcsc": "C85364", "references": ["U1"],
                                                "value": "x", "type": "ic"}]}), encoding="utf-8")
            with mock.patch.object(provider_lcsc.urllib.request, "urlopen", refuse), \
                    redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                sync_datasheets(provider_lcsc, input_path=str(bom), output_dir=str(Path(d) / "out"), delay=0)
            m = json.loads((Path(d) / "out" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m["parts"]["C85364"]["status"], "error")


if __name__ == "__main__":
    unittest.main()
