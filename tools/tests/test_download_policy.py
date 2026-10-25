"""Datasheet downloads go only to http(s) URLs on public addresses, every redirect is
checked, and a download stops at a size and wall-clock limit. No network: the resolver
and every transport are local fakes."""
import argparse, http.client, io, json, os, sys, tempfile, unittest, urllib.request, urllib.response
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "datasheets"))

from distributor_core import download  # noqa: E402

PUBLIC = ["93.184.216.34"]
PDF = b"%PDF-1.4 datasheet\n"


def _fail(*a, **k):
    raise AssertionError("transport must not be called")


class _FakeRequestsResponse:
    def __init__(self, status, headers=None, chunks=()):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = chunks

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OSError(f"HTTP {self.status_code}")

    def iter_content(self, size):
        return iter(self._chunks)

    def close(self):
        pass


class _FakeRequests:
    """A ``requests`` stand-in answering each URL from a table; records every call."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.answers[url]()


def _urllib_handler(answers, seen):
    """An HTTP(S) handler for the urllib opener answering each URL from a table."""
    class Fake(urllib.request.BaseHandler):
        def http_open(self, req):
            url = req.full_url
            seen.append(url)
            status, location, body = answers[url]
            headers = http.client.HTTPMessage()
            if location:
                headers["Location"] = location
            resp = urllib.response.addinfourl(io.BytesIO(body), headers, url, status)
            resp.msg = "Found" if location else "OK"
            return resp
        https_open = http_open
    return Fake


def _with_fake_urllib_handler(fake):
    return [fake if issubclass(h, urllib.request.AbstractHTTPHandler) else h
            for h in download._URLLIB_HANDLERS]


class UrlProblemTest(unittest.TestCase):
    def test_url_problem_table(self):
        with mock.patch.object(download, "_resolve", return_value=PUBLIC):
            for url in ("https://example.com/a.pdf", "http://example.com/a.pdf"):
                self.assertIsNone(download.url_problem(url, allow_private=False), url)
            for url in ("file:///etc/passwd", "ftp://example.com/a.pdf",
                        "data:application/pdf;base64,JVBE", "https:///a.pdf",
                        "http://127.0.0.1/a.pdf", "http://10.0.0.5/a.pdf",
                        "http://192.168.1.1/a.pdf", "http://169.254.169.254/latest",
                        "http://100.64.0.1/a.pdf", "http://224.0.0.1/a.pdf",
                        "http://[::1]/a.pdf", "http://[::ffff:127.0.0.1]/a.pdf",
                        "http://[fe80::1]/a.pdf"):
                self.assertIsInstance(download.url_problem(url, allow_private=False), str, url)
        with mock.patch.object(download, "_resolve", return_value=["10.1.2.3"]):
            self.assertIsInstance(
                download.url_problem("https://intranet.example/a.pdf", allow_private=False), str)
        with mock.patch.object(download, "_resolve", return_value=["93.184.216.34", "127.0.0.1"]):
            self.assertIsInstance(
                download.url_problem("https://mixed.example/a.pdf", allow_private=False), str)
        with mock.patch.object(download, "_resolve", side_effect=OSError("no such host")):
            self.assertIsInstance(
                download.url_problem("https://nowhere.example/a.pdf", allow_private=False), str)
        self.assertIsNone(download.url_problem("http://10.0.0.5/a.pdf", allow_private=True))
        self.assertIsInstance(download.url_problem("file:///x", allow_private=True), str)


class DownloadPolicyTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(download, "_resolve", side_effect=self._resolve)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(download, "_allow_private_hosts", return_value=False)
        p.start()
        self.addCleanup(p.stop)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.out = os.path.join(self.dir.name, "x.pdf")
        self.stderr = io.StringIO()

    @staticmethod
    def _resolve(host):
        return {"intranet.example": ["10.1.2.3"]}.get(host, PUBLIC)

    def _download(self, url, *, requests=None, urllib_fn=None, playwright=None, handlers=None):
        patches = [mock.patch.object(download, "_requests", requests),
                   mock.patch.object(download, "_sync_playwright", playwright)]
        if urllib_fn is not None:
            patches.append(mock.patch.object(download, "_download_urllib", urllib_fn))
        if handlers is not None:
            patches.append(mock.patch.object(download, "_URLLIB_HANDLERS", handlers))
        for p in patches:
            p.start()
        try:
            with redirect_stderr(self.stderr), redirect_stdout(io.StringIO()):
                return download.download_pdf(url, self.out)
        finally:
            for p in reversed(patches):
                p.stop()

    def test_download_pdf_refuses_before_any_transport(self):
        self.assertFalse(self._download("file:///etc/passwd", requests=_FakeRequests({}),
                                        urllib_fn=_fail, playwright=_fail))
        self.assertEqual(os.listdir(self.dir.name), [])
        self.assertIn("download refused", self.stderr.getvalue())

    def test_urllib_redirect_to_private_refused(self):
        seen = []
        answers = {"https://example.com/x.pdf": (302, "http://127.0.0.1/x.pdf", b""),
                   "http://127.0.0.1/x.pdf": (200, None, PDF)}
        handlers = _with_fake_urllib_handler(_urllib_handler(answers, seen))
        self.assertFalse(self._download("https://example.com/x.pdf", handlers=handlers,
                                         playwright=_fail))
        self.assertEqual(seen, ["https://example.com/x.pdf"])
        self.assertEqual(os.listdir(self.dir.name), [])

    def test_requests_redirect_to_private_refused(self):
        fake = _FakeRequests({
            "https://example.com/x.pdf":
                lambda: _FakeRequestsResponse(302, {"Location": "http://127.0.0.1/x.pdf"}),
            "http://127.0.0.1/x.pdf": lambda: _FakeRequestsResponse(200, chunks=[PDF]),
        })
        self.assertFalse(self._download("https://example.com/x.pdf", requests=fake,
                                        urllib_fn=_fail, playwright=_fail))
        self.assertEqual([u for u, _ in fake.calls], ["https://example.com/x.pdf"])
        self.assertIs(fake.calls[0][1]["allow_redirects"], False)
        self.assertIs(fake.calls[0][1]["stream"], True)

    def test_relative_redirect_to_intranet_refused(self):
        fake = _FakeRequests({
            "https://example.com/x.pdf":
                lambda: _FakeRequestsResponse(301, {"Location": "//intranet.example/x.pdf"}),
        })
        self.assertFalse(self._download("https://example.com/x.pdf", requests=fake,
                                        urllib_fn=_fail, playwright=_fail))
        self.assertEqual(len(fake.calls), 1)

    def test_public_redirect_followed(self):
        seen = []
        answers = {"https://example.com/x.pdf": (302, "https://cdn.example.org/x.pdf", b""),
                   "https://cdn.example.org/x.pdf": (200, None, PDF)}
        handlers = _with_fake_urllib_handler(_urllib_handler(answers, seen))
        self.assertTrue(self._download("https://example.com/x.pdf", handlers=handlers))
        self.assertEqual(seen, ["https://example.com/x.pdf", "https://cdn.example.org/x.pdf"])
        with open(self.out, "rb") as f:
            self.assertEqual(f.read(), PDF)

        os.remove(self.out)
        fake = _FakeRequests({
            "https://example.com/x.pdf":
                lambda: _FakeRequestsResponse(302, {"Location": "https://cdn.example.org/x.pdf"}),
            "https://cdn.example.org/x.pdf": lambda: _FakeRequestsResponse(200, chunks=[PDF]),
        })
        self.assertTrue(self._download("https://example.com/x.pdf", requests=fake, urllib_fn=_fail))
        self.assertEqual([u for u, _ in fake.calls],
                         ["https://example.com/x.pdf", "https://cdn.example.org/x.pdf"])

    def test_size_limit(self):
        body = b"%PDF" + b"0" * (2 * 1024 * 1024)
        chunks = [body[i:i + 65536] for i in range(0, len(body), 65536)]
        fake = _FakeRequests({"https://example.com/x.pdf":
                              lambda: _FakeRequestsResponse(200, chunks=chunks)})
        seen = []
        handlers = _with_fake_urllib_handler(
            _urllib_handler({"https://example.com/x.pdf": (200, None, body)}, seen))
        with mock.patch.object(download, "MAX_DOWNLOAD_BYTES", 1024 * 1024):
            self.assertFalse(self._download("https://example.com/x.pdf", requests=fake,
                                            handlers=handlers, playwright=_fail))
            self.assertEqual(os.listdir(self.dir.name), [])
            self.assertFalse(self._download("https://example.com/x.pdf", handlers=handlers,
                                            playwright=_fail))
            self.assertEqual(os.listdir(self.dir.name), [])

    def test_wall_clock_limit(self):
        clock = [1000.0]

        def chunks():
            for _ in range(5):
                clock[0] += 30.0
                yield PDF

        fake = _FakeRequests({"https://example.com/x.pdf":
                              lambda: _FakeRequestsResponse(200, chunks=chunks())})
        with mock.patch.object(download, "DOWNLOAD_TIMEOUT_S", 60.0), \
             mock.patch.object(download.time, "monotonic", lambda: clock[0]):
            self.assertFalse(self._download("https://example.com/x.pdf", requests=fake,
                                            urllib_fn=_fail, playwright=_fail))
        self.assertEqual(os.listdir(self.dir.name), [])
        self.assertEqual(fake.calls[0][1]["timeout"], 20)

    def test_playwright_gated(self):
        broken = _FakeRequests({})
        self.assertFalse(self._download("http://127.0.0.1/x.pdf", requests=broken,
                                        urllib_fn=lambda u, p: False, playwright=_fail))
        self.assertEqual(broken.calls, [])


class AllowPrivateTest(unittest.TestCase):
    def _allow(self, home, cwd=None):
        old = os.getcwd()
        try:
            if cwd:
                os.chdir(cwd)
            with mock.patch.dict(os.environ, {"HOME": home}):
                return download._allow_private_hosts()
        finally:
            os.chdir(old)

    def test_allow_private_reads_user_config_only(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as proj:
            cfg = os.path.join(home, ".kicad-happy.json")
            with open(cfg, "w", encoding="utf-8") as f:
                json.dump({"datasheets": {"allow_private_hosts": True}}, f)
            self.assertIs(self._allow(home), True)
            with open(cfg, "w", encoding="utf-8") as f:
                json.dump({"datasheets": {"allow_private_hosts": "true"}}, f)
            self.assertIs(self._allow(home), False)
            os.remove(cfg)
            with open(os.path.join(proj, ".kicad-happy.json"), "w", encoding="utf-8") as f:
                json.dump({"datasheets": {"allow_private_hosts": True}}, f)
            self.assertIs(self._allow(home, cwd=proj), False)

    def test_load_user_config_never_raises(self):
        sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
        from kicad_core.project import load_user_config
        with tempfile.TemporaryDirectory() as home:
            cfg = os.path.join(home, ".kicad-happy.json")
            with mock.patch.dict(os.environ, {"HOME": home}):
                self.assertEqual(load_user_config(), {})
                for text in ("{not json", "[1, 2]", "\xff"):
                    with open(cfg, "w", encoding="latin-1") as f:
                        f.write(text)
                    self.assertEqual(load_user_config(), {}, text)
                with open(cfg, "w", encoding="utf-8") as f:
                    f.write('{\n  // user settings\n  "datasheets": {"allow_private_hosts": true},\n}')
                self.assertEqual(load_user_config(), {"datasheets": {"allow_private_hosts": True}})


class CliFlagsTest(unittest.TestCase):
    def test_cli_flags(self):
        parser = argparse.ArgumentParser()
        download.add_download_args(parser)
        args = parser.parse_args(["--max-download-mb", "5", "--download-timeout", "30"])
        with mock.patch.object(download, "MAX_DOWNLOAD_BYTES", 0), \
             mock.patch.object(download, "DOWNLOAD_TIMEOUT_S", 0.0):
            download.apply_download_args(args)
            self.assertEqual(download.MAX_DOWNLOAD_BYTES, 5242880)
            self.assertEqual(download.DOWNLOAD_TIMEOUT_S, 30.0)
            download.apply_download_args(parser.parse_args([]))
            self.assertEqual(download.MAX_DOWNLOAD_BYTES, 52428800)
            self.assertEqual(download.DOWNLOAD_TIMEOUT_S, 120.0)
        for bad in (["--max-download-mb", "0"], ["--max-download-mb", "-1"],
                    ["--download-timeout", "0"], ["--download-timeout", "nan"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                parser.parse_args(bad)
            self.assertEqual(cm.exception.code, 2, bad)


if __name__ == "__main__":
    unittest.main()
