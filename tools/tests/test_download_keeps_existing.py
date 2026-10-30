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


def _named(name, sync_one_part):
    p = _provider(sync_one_part)
    p.NAME = name
    return p


class PerProviderFailureTest(unittest.TestCase):
    """A failure is skipped only by the distributor that recorded it; the others still try."""
    _bom, _sync = SyncOutageTest._bom, SyncOutageTest._sync

    def _seed(self, d, entry):
        out = Path(d) / "out"
        out.mkdir()
        (out / "manifest.json").write_text(json.dumps({"parts": {"LM358DR": entry}}), encoding="utf-8")

    def _counting(self, name, outcome):
        calls = []

        def one(p, *a):
            calls.append(p["_key"])
            return outcome(p)
        return _named(name, one), calls

    def test_other_providers_not_found_is_tried(self):
        with tempfile.TemporaryDirectory() as d:
            _, m = self._sync(d, _named("digikey", lambda p, *a: _not_found(p)))
            self.assertEqual(m["parts"]["LM358DR"]["failed_providers"], ["digikey"])
            dry, _ = self._sync(d, _named("lcsc", lambda p, *a: _not_found(p)), dry_run=True, as_json=True)
            self.assertEqual(dry["would_download"], ["LM358DR"])
            self.assertEqual(dry["skipped_previous_failures"], [])
            lcsc, calls = self._counting("lcsc", _not_found)
            _, m = self._sync(d, lcsc)
            self.assertEqual(calls, ["LM358DR"])
            self.assertEqual(m["parts"]["LM358DR"]["failed_providers"], ["digikey", "lcsc"])

    def test_own_failure_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d, {"status": "not_found", "error": "No results", "references": ["U1"],
                           "failed_providers": ["digikey"]})
            prov, calls = self._counting("digikey", _not_found)
            r, _ = self._sync(d, prov)
            self.assertEqual(calls, [])
            self.assertEqual(r["failed"], 1)

    def test_legacy_failure_is_tried_once_by_each_provider(self):
        legacy = {"status": "failed", "error": "All download methods failed", "references": ["U1"]}
        with tempfile.TemporaryDirectory() as d:
            self._seed(d, legacy)
            for name, expect in (("digikey", ["digikey"]), ("lcsc", ["digikey", "lcsc"])):
                prov, calls = self._counting(name, _failed)
                _, m = self._sync(d, prov)
                self.assertEqual(calls, ["LM358DR"], name)
                self.assertEqual(m["parts"]["LM358DR"]["failed_providers"], expect, name)
            for name in ("digikey", "lcsc"):
                dry, _ = self._sync(d, _named(name, _failed), dry_run=True, as_json=True)
                self.assertEqual(dry["skipped_previous_failures"], ["LM358DR"], name)

    def test_success_by_another_provider_drops_the_list(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d, {"status": "not_found", "error": "No results", "references": ["U1"],
                           "failed_providers": ["digikey"]})

            def ok(p, *a):
                (Path(d) / "out" / "LM358DR.pdf").write_bytes(GOOD)
                return {"file": "LM358DR.pdf", "status": "ok", "references": p["references"],
                        "size_bytes": len(GOOD)}
            _, m = self._sync(d, _named("lcsc", ok))
            self.assertEqual(m["parts"]["LM358DR"]["status"], "ok")
            self.assertNotIn("failed_providers", m["parts"]["LM358DR"])

    def test_ok_entry_is_never_retried(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out"
            out.mkdir()
            (out / "LM358DR.pdf").write_bytes(GOOD)
            ok = {"file": "LM358DR.pdf", "status": "ok", "references": ["U1"], "size_bytes": len(GOOD)}
            (out / "manifest.json").write_text(json.dumps({"parts": {"LM358DR": ok}}), encoding="utf-8")
            for name in ("digikey", "lcsc"):
                prov, calls = self._counting(name, _not_found)
                _, m = self._sync(d, prov)
                self.assertEqual(calls, [], name)
                self.assertEqual(m["parts"]["LM358DR"]["status"], "ok", name)
                self.assertNotIn("failed_providers", m["parts"]["LM358DR"], name)

    def test_outage_records_no_provider(self):
        outage = TimeoutError("timed out")
        with tempfile.TemporaryDirectory() as d:
            _, m = self._sync(d, _named("digikey", lambda p, *a: _not_found(p, outage)))
            self.assertEqual(m["parts"]["LM358DR"]["status"], "error")
            self.assertNotIn("failed_providers", m["parts"]["LM358DR"])

    def test_malformed_list_is_read_as_legacy(self):
        for bad in ("digikey", [{"x": 1}, 3], None):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as d:
                self._seed(d, {"status": "not_found", "error": "No results", "references": ["U1"],
                               "failed_providers": bad})
                prov, calls = self._counting("digikey", _not_found)
                _, m = self._sync(d, prov)
                self.assertEqual(calls, ["LM358DR"])
                self.assertEqual(m["parts"]["LM358DR"]["failed_providers"], ["digikey"])


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



def _load_provider(name):
    import importlib
    sys.path.insert(0, str(ROOT / "skills" / name / "scripts"))
    try:
        return importlib.import_module(f"provider_{name}")
    finally:
        sys.path.pop(0)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# Stands in for the requests module when its download method is replaced
_FAKE_REQUESTS = SimpleNamespace(exceptions=SimpleNamespace(RequestException=type("RequestException", (OSError,), {})))


class DownloadTransportNoteTest(unittest.TestCase):
    """download_pdf records a failure of the network (retried next run), never one of this machine."""

    def setUp(self):
        from distributor_core import download
        p = mock.patch.object(download, "_resolve", return_value=["93.184.216.34"])
        p.start()
        self.addCleanup(p.stop)

    def _noted(self, method):
        from distributor_core import download
        download.take_transport_failure()
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(download, "_requests", None), \
                mock.patch.object(download, "_sync_playwright", None), \
                mock.patch.object(download, "_download_urllib", method), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            ok = download.download_pdf("https://example.invalid/x.pdf", os.path.join(d, "x.pdf"))
        self.assertFalse(ok)
        return download.take_transport_failure()

    def test_dropped_connection_is_a_transport_failure(self):
        noted = self._noted(_raiser(ConnectionResetError(104, "Connection reset by peer")))
        self.assertEqual(noted, "network failure, retried next run: "
                                "ConnectionResetError: [Errno 104] Connection reset by peer")

    def test_unwritable_file_is_not_a_transport_failure(self):
        self.assertIsNone(self._noted(_raiser(PermissionError(13, "Permission denied"))))

    def test_http_404_is_not_a_transport_failure(self):
        self.assertIsNone(self._noted(_raiser(urllib.error.HTTPError("u", 404, "Not Found", {}, None))))

    def test_bare_oserror_with_a_network_errno_is_a_transport_failure(self):
        import errno
        noted = self._noted(_raiser(OSError(errno.EHOSTUNREACH, "No route to host")))
        self.assertTrue(noted.startswith("network failure, retried next run: OSError"), noted)

    def _two_methods(self, second, before=None):
        """requests drops the connection, then urllib ends with ``second``."""
        from distributor_core import download
        download.take_transport_failure()
        if before is not None:
            download.note_transport_failure(before)
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(download, "_requests", _FAKE_REQUESTS), \
                mock.patch.object(download, "_sync_playwright", None), \
                mock.patch.object(download, "_download_requests",
                                  _raiser(ConnectionResetError(104, "Connection reset by peer"))), \
                mock.patch.object(download, "_download_urllib", _raiser(second)), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            ok = download.download_pdf("https://example.invalid/x.pdf", os.path.join(d, "x.pdf"))
        self.assertFalse(ok)
        return download.take_transport_failure()

    def test_refusal_after_a_dropped_connection_is_permanent(self):
        from distributor_core import download
        self.assertIsNone(self._two_methods(download.DownloadRefused("redirect to a private address")))

    def test_limit_after_a_dropped_connection_is_permanent(self):
        from distributor_core import download
        self.assertIsNone(self._two_methods(download.DownloadLimitExceeded("larger than 50 MB")))

    def test_refusal_keeps_a_failure_recorded_before_the_download(self):
        from distributor_core import download
        noted = self._two_methods(download.DownloadRefused("private"), before=TimeoutError("search timed out"))
        self.assertEqual(noted, "network failure, retried next run: TimeoutError: search timed out")

    def test_redirect_limit_lets_the_next_method_try(self):
        from distributor_core import download
        resp = SimpleNamespace(status_code=302, headers={"Location": "/again"}, close=lambda: None)
        fake = SimpleNamespace(get=lambda *a, **k: resp, exceptions=_FAKE_REQUESTS.exceptions)
        download.take_transport_failure()
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(download, "_requests", fake), \
                mock.patch.object(download, "_sync_playwright", None), \
                mock.patch.object(download, "_download_urllib", _writer(GOOD)), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            ok = download.download_pdf("https://example.invalid/x.pdf", os.path.join(d, "x.pdf"))
        self.assertTrue(ok)  # the next method finishes what the redirect limit stopped
        self.assertIsNone(download.take_transport_failure())

    def test_redirect_limit_alone_is_not_a_transport_failure(self):
        from distributor_core import download
        resp = SimpleNamespace(status_code=302, headers={"Location": "/again"}, close=lambda: None)
        fake = SimpleNamespace(get=lambda *a, **k: resp, exceptions=_FAKE_REQUESTS.exceptions)
        download.take_transport_failure()
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(download, "_requests", fake), \
                mock.patch.object(download, "_sync_playwright", None), \
                mock.patch.object(download, "_download_urllib", lambda *a: False), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            ok = download.download_pdf("https://example.invalid/x.pdf", os.path.join(d, "x.pdf"))
        self.assertFalse(ok)
        self.assertIsNone(download.take_transport_failure())

    def test_closed_stdout_does_not_fail_a_download(self):
        from distributor_core import download
        out = io.StringIO()
        out.close()
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(download, "_requests", None), \
                mock.patch.object(download, "_sync_playwright", None), \
                mock.patch.object(download, "_download_urllib", _writer(GOOD)), \
                redirect_stdout(out):
            self.assertTrue(download.download_pdf("https://example.invalid/x.pdf", os.path.join(d, "x.pdf")))

    def test_unprintable_path_does_not_fail_a_download(self):
        from distributor_core import download

        class Ascii(io.StringIO):
            def write(self, text):
                text.encode("ascii")
                return super().write(text)
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(download, "_requests", None), \
                mock.patch.object(download, "_sync_playwright", None), \
                mock.patch.object(download, "_download_urllib", _writer(GOOD)), \
                redirect_stdout(Ascii()):
            self.assertTrue(download.download_pdf("https://example.invalid/x.pdf", os.path.join(d, "µ.pdf")))


def _failed(part, outage=None):
    from distributor_core.download import note_transport_failure
    if outage is not None:
        note_transport_failure(outage)
    return {"manufacturer": "", "description": "", "value": part["value"],
            "references": part["references"], "status": "failed",
            "error": "All download methods failed", "last_attempt": "t"}


class SyncDownloadFailureTest(unittest.TestCase):
    _bom, _sync = SyncOutageTest._bom, SyncOutageTest._sync

    def test_download_outage_is_retried_next_run(self):
        outage = ConnectionResetError(104, "Connection reset by peer")
        with tempfile.TemporaryDirectory() as d:
            _, m = self._sync(d, _provider(lambda p, *a: _failed(p, outage)))
            self.assertEqual(m["parts"]["LM358DR"]["status"], "error")
            self.assertIn("network failure", m["parts"]["LM358DR"]["error"])
            dry, _ = self._sync(d, _provider(lambda p, *a: _failed(p)), dry_run=True, as_json=True)
            self.assertEqual(dry["would_download"], ["LM358DR"])

    def test_failed_download_without_outage_stays_failed(self):
        with tempfile.TemporaryDirectory() as d:
            _, m = self._sync(d, _provider(lambda p, *a: _failed(p)))
            self.assertEqual(m["parts"]["LM358DR"]["status"], "failed")

    OK = {"file": "LM358DR.pdf", "status": "ok", "datasheet_url": "https://x/old.pdf",
          "references": ["U1"], "size_bytes": len(GOOD)}

    def _force_all(self, d, outcome):
        out = Path(d) / "out"
        out.mkdir()
        (out / "LM358DR.pdf").write_bytes(GOOD)
        (out / "manifest.json").write_text(json.dumps({"parts": {"LM358DR": self.OK}}), encoding="utf-8")
        r, m = self._sync(d, _provider(outcome), force_all=True)
        self.assertEqual((out / "LM358DR.pdf").read_bytes(), GOOD)
        self.assertEqual(r["failed"], 1)
        return m["parts"]["LM358DR"]

    def test_force_all_failed_refresh_keeps_a_present_ok_entry(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._force_all(d, lambda p, *a: _failed(p)), self.OK)
            self.assertIn("LM358DR — All download methods failed", self.stderr.getvalue())

    def test_force_all_real_answer_replaces_the_ok_entry(self):
        def no_datasheet(p, *a):
            return {**_not_found(p), "status": "no_datasheet", "error": "listing has no datasheet URL"}
        for outcome, status in ((lambda p, *a: _not_found(p), "not_found"), (no_datasheet, "no_datasheet")):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as d:
                self.assertEqual(self._force_all(d, outcome)["status"], status)

    def test_outage_keeps_the_distributors_own_message(self):
        outage = ConnectionResetError(104, "Connection reset by peer")
        with tempfile.TemporaryDirectory() as d:
            _, m = self._sync(d, _provider(lambda p, *a: _failed(p, outage)))
        self.assertEqual(m["parts"]["LM358DR"]["error"],
                         "network failure, retried next run: ConnectionResetError: [Errno 104] "
                         "Connection reset by peer; distributor said: All download methods failed")

    def test_missing_file_is_not_kept(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out"
            out.mkdir()
            ok = {"file": "LM358DR.pdf", "status": "ok", "references": ["U1"]}
            (out / "manifest.json").write_text(json.dumps({"parts": {"LM358DR": ok}}), encoding="utf-8")
            _, m = self._sync(d, _provider(lambda p, *a: _failed(p)), force_all=True)
            self.assertEqual(m["parts"]["LM358DR"]["status"], "failed")


WMSC_DETAIL = {"result": {"productCode": "C15525", "productModel": "CL05A106MQ5NUNC", "productDescEn": "10uF 6.3V X5R 0402",
                          "brandNameEn": "Samsung", "pdfUrl": "https://example.com/C15525.pdf"}}


class LcscDirectLookupTest(unittest.TestCase):
    """A code jlcsearch does not list is looked up on LCSC's own product page."""

    def _sync(self, wmsc, mpn=""):
        prov = _load_provider("lcsc")
        from distributor_core.sync import sync_datasheets
        calls = []

        def urlopen(req, *a, **k):
            url = req.full_url
            calls.append(url.split("?")[0])
            if url.startswith("https://jlcsearch.tscircuit.com/"):
                return _Resp(json.dumps({"components": []}).encode())
            if url.startswith("https://wmsc.lcsc.com/") and "productCode=C15525" in url:
                return wmsc()
            raise AssertionError(url)

        def download(url, output_path, *a, **k):
            if url != "https://example.com/C15525.pdf":
                return False
            Path(output_path).write_bytes(GOOD)
            return True

        with tempfile.TemporaryDirectory() as d:
            bom = Path(d) / "bom.json"
            bom.write_text(json.dumps({"bom": [{"mpn": mpn, "lcsc": "C15525", "references": ["C11", "C12"],
                                                "value": "10uF", "type": "capacitor"}]}), encoding="utf-8")
            with mock.patch.object(prov.urllib.request, "urlopen", urlopen), \
                    mock.patch.object(prov, "download_pdf", download), \
                    mock.patch.object(prov, "try_alternative_sources", lambda *a, **k: False), \
                    mock.patch.object(prov, "verify_datasheet", lambda *a, **k: {"confidence": "verified"}), \
                    redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                sync_datasheets(prov, input_path=str(bom), output_dir=str(Path(d) / "out"), delay=0)
            m = json.loads((Path(d) / "out" / "manifest.json").read_text(encoding="utf-8"))
        return m["parts"][mpn or "C15525"], calls

    def test_code_jlcsearch_lacks_is_found_by_direct_lookup(self):
        entry, calls = self._sync(lambda: _Resp(json.dumps(WMSC_DETAIL).encode()))
        self.assertEqual(entry["status"], "ok")
        self.assertEqual(entry["source"], "lcsc")
        self.assertEqual(entry["lcsc"], "C15525")
        self.assertEqual(entry["datasheet_url"], "https://example.com/C15525.pdf")
        self.assertEqual(calls, ["https://jlcsearch.tscircuit.com/api/search",
                                 "https://wmsc.lcsc.com/ftps/wm/product/detail"])

    def test_direct_lookup_outage_is_retried_next_run(self):
        def refuse():
            raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        entry, _ = self._sync(refuse)
        self.assertEqual(entry["status"], "error")
        self.assertIn("network failure", entry["error"])

    def test_direct_lookup_answering_another_code_is_not_found(self):
        other = {"result": {**WMSC_DETAIL["result"], "productCode": "C15849"}}
        entry, _ = self._sync(lambda: _Resp(json.dumps(other).encode()))
        self.assertEqual(entry["status"], "not_found")
        self.assertIn("(closest: 'C15849', a different part)", entry["error"])

    def test_direct_lookup_without_a_code_is_checked_by_mpn(self):
        no_code = {"result": {k: v for k, v in WMSC_DETAIL["result"].items() if k != "productCode"}}
        entry, _ = self._sync(lambda: _Resp(json.dumps(no_code).encode()), mpn="GRM155R60J106ME15D")
        self.assertEqual(entry["status"], "not_found")
        self.assertIn("(closest: 'CL05A106MQ5NUNC', a different part)", entry["error"])
        entry, _ = self._sync(lambda: _Resp(json.dumps(no_code).encode()), mpn="CL05A106MQ5NUNC")
        self.assertEqual(entry["status"], "ok")

    def test_direct_lookup_with_no_product_stays_not_found(self):
        entry, _ = self._sync(lambda: _Resp(json.dumps({"result": None}).encode()))
        self.assertEqual(entry["status"], "not_found")


class DigikeyRateLimitTest(unittest.TestCase):
    def _search(self, responses):
        prov = _load_provider("digikey")
        from distributor_core import download
        seen = {"open": 0, "sleep": []}

        def urlopen(*a, **k):
            seen["open"] += 1
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return _Resp(json.dumps(r).encode())

        download.take_transport_failure()
        with mock.patch.object(prov.urllib.request, "urlopen", urlopen), \
                mock.patch.object(prov.time, "sleep", seen["sleep"].append), \
                redirect_stderr(io.StringIO()):
            hit = prov.search_digikey_with_token("LM358DR", "TOKEN", "CID")
        return hit, seen, download.take_transport_failure()

    @staticmethod
    def _429():
        return urllib.error.HTTPError("https://api.digikey.com", 429, "Too Many Requests", {}, None)

    def test_rate_limit_stops_after_three_retries(self):
        hit, seen, noted = self._search([self._429() for _ in range(5)])
        self.assertIsNone(hit)
        self.assertEqual(seen["open"], 4)
        self.assertEqual(seen["sleep"], [10, 10, 10])
        self.assertTrue(noted.startswith("network failure, retried next run: HTTPError"), noted)
        self.assertIn("429", noted)

    def test_rate_limit_then_answer_returns_the_hit(self):
        product = {"ManufacturerProductNumber": "LM358DR", "DigiKeyProductNumber": "296-1395-1-ND"}
        hit, seen, noted = self._search([self._429(), self._429(), {"Products": [product]}])
        self.assertEqual(hit, product)
        self.assertEqual(seen["open"], 3)
        self.assertIsNone(noted)


class Element14SearchLadderTest(unittest.TestCase):
    """A hit the identity guard rejects does not end element14's search ladder."""

    def test_sku_rejected_by_mpn_search_is_found_by_id_search(self):
        prov = _load_provider("element14")
        wrong = {"translatedManufacturerPartNumber": "BMP280", "sku": "11AB1001",
                 "datasheets": [{"url": "https://example.com/bmp280.pdf"}]}
        right = {"translatedManufacturerPartNumber": "BME280", "sku": "94AK6874",
                 "datasheets": [{"url": "https://example.com/bme280.pdf"}],
                 "brandName": "Bosch", "displayName": "Sensor"}
        terms = []

        def raw(term, *a, **k):
            terms.append(term)
            return {"manuPartNum:94AK6874": wrong, "id:94AK6874": right}.get(term)

        def download(url, output_path, *a, **k):
            if url != "https://example.com/bme280.pdf":
                return False
            Path(output_path).write_bytes(GOOD)
            return True

        part = {"mpn": "", "element14": "94AK6874", "manufacturer": "", "value": "SENSOR",
                "description": "", "datasheet": "", "references": ["U11"], "type": "ic"}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(prov, "_search_element14_raw", raw), \
                mock.patch.object(prov, "download_pdf", download), \
                mock.patch.object(prov, "try_alternative_sources", lambda *a, **k: False), \
                mock.patch.object(prov, "verify_datasheet", lambda *a, **k: {"confidence": "verified"}), \
                mock.patch.object(prov.time, "sleep", lambda *a: None), \
                redirect_stderr(io.StringIO()):
            r = prov.sync_one_part(part, Path(d), {}, 0.0, ("KEY", "www.newark.com"))
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["datasheet_url"], "https://example.com/bme280.pdf")
        self.assertEqual(terms, ["manuPartNum:94AK6874", "id:94AK6874"])


if __name__ == "__main__":
    unittest.main()
