"""Datasheet downloads go only to http(s) URLs on public addresses, every redirect is
checked, and a download stops at a size and wall-clock limit. No network: the resolver
and every transport are local fakes."""
import argparse, contextlib, http.client, http.server, io, json, os, socket, subprocess, sys, tempfile, threading, time, unittest
import urllib.request, urllib.response
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "datasheets"))

from distributor_core import download  # noqa: E402
from tools.tests._download_fakes import fake_requests  # noqa: E402

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

    def Session(self):
        return fake_requests(self.get).Session()


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
            for url in ("https://example.com/a.pdf", "http://example.com/a.pdf",
                        "http://xn--fa-hia.example.com/x.pdf", "https://example.com/\u00df.pdf"):
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

    def test_embedded_ipv4_prefixes(self):
        url = "https://h.example/a.pdf"
        for address in ("64:ff9b::7f00:1", "64:ff9b::a00:1", "::127.0.0.1", "::10.0.0.1",
                        "2002:a00:1::1", "2002:7f00:1::"):
            with mock.patch.object(download, "_resolve", return_value=[address]):
                self.assertIsInstance(download.url_problem(url, allow_private=False), str,
                                      address)
        self.assertIsInstance(download.url_problem("http://[64:ff9b::a9fe:a9fe]/latest",
                                                   allow_private=False), str)
        # A public IPv4 address behind a translator stays allowed: DNS64 resolvers
        # synthesize the NAT64 form for every IPv4-only host.
        for address in ("64:ff9b::5db8:d822", "::93.184.216.34"):
            with mock.patch.object(download, "_resolve", return_value=[address]):
                self.assertIsNone(download.url_problem(url, allow_private=False), address)

    def test_each_address_is_checked_once(self):
        calls = []

        def getaddrinfo(host, port, *a, **k):
            calls.append(k)
            return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800::1", 0, 0, 0)),
                    (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800::1", 0, 0, 0)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        with mock.patch.object(socket, "getaddrinfo", getaddrinfo):
            self.assertEqual(download._resolve("example.com"), ["2606:2800::1", "93.184.216.34"])
        self.assertEqual(calls, [{"type": socket.SOCK_STREAM}])
        with mock.patch.object(download, "_resolve",
                               return_value=["93.184.216.34", "93.184.216.34", "93.184.216.35"]):
            self.assertEqual(download._checked("https://example.com/a.pdf", False),
                             (None, ["93.184.216.34", "93.184.216.35"]))

    def test_credentials_backslashes_and_blanks_refused(self):
        # Parsers disagree on where the host ends in these URLs (urlsplit reads
        # ``evil.com`` in the first one, requests and browsers read ``127.0.0.1``), so
        # they are refused whatever the host resolves to.
        with mock.patch.object(download, "_resolve", return_value=PUBLIC):
            for url in ("http://127.0.0.1\\@evil.com/x.pdf", "http://evil.com@127.0.0.1/",
                        "http://user:pw@example.com/a.pdf", "http://@example.com/a.pdf",
                        "http://exa mple.com/", "http://example.com/a\tb.pdf",
                        "http://example.com/a.pdf\n", "http://example.com/a\x00.pdf",
                        "http://example.com/a\x7f.pdf", "http://example.com\\a.pdf",
                        "http://fa\u00df.example.com/x.pdf", "https://\uff25\uff38\uff21\uff2d\uff30\uff2c\uff25.com/x.pdf",
                        "http://example.com:\uff18\uff10/x.pdf"):
                for allow_private in (False, True):
                    self.assertIsInstance(
                        download.url_problem(url, allow_private=allow_private), str, url)


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

    def test_requests_redirect_to_non_ascii_host_refused(self):
        fake = _FakeRequests({
            "https://example.com/x.pdf":
                lambda: _FakeRequestsResponse(302, {"Location": "http://fa\u00df.example.com/x.pdf"}),
            "http://fa\u00df.example.com/x.pdf": lambda: _FakeRequestsResponse(200, chunks=[PDF]),
        })
        self.assertFalse(self._download("https://example.com/x.pdf", requests=fake,
                                        urllib_fn=_fail, playwright=_fail))
        self.assertEqual([u for u, _ in fake.calls], ["https://example.com/x.pdf"])
        self.assertIn("download refused", self.stderr.getvalue())
        self.assertIn("non-ASCII", self.stderr.getvalue())

    def test_spaces_after_the_host_are_encoded(self):
        fake = _FakeRequests({
            "https://example.com/Data%20Sheet.pdf?a=b%20c#p%202":
                lambda: _FakeRequestsResponse(200, chunks=[PDF]),
        })
        self.assertTrue(self._download("https://example.com/Data Sheet.pdf?a=b c#p 2",
                                       requests=fake, urllib_fn=_fail, playwright=_fail))
        self.assertEqual([u for u, _ in fake.calls],
                         ["https://example.com/Data%20Sheet.pdf?a=b%20c#p%202"])
        for url in ("http://exa mple.com/a.pdf", "http://example.com/a\tb.pdf",
                    "http://example.com/a b\\c.pdf", "http://u ser@example.com/a.pdf"):
            self.assertFalse(self._download(url, requests=_FakeRequests({}),
                                            urllib_fn=_fail, playwright=_fail), url)

    def test_percent_encoded_host_refused(self):
        self.assertIsInstance(download.url_problem("http://%31%32%37.0.0.1/x.pdf",
                                                   allow_private=False), str)
        self.assertIsInstance(download.url_problem("http://example.com:%38%30/x.pdf",
                                                   allow_private=True), str)
        self.assertIsNone(download.url_problem("https://example.com/a%20b.pdf",
                                               allow_private=False))
        fake = _FakeRequests({
            "https://example.com/x.pdf":
                lambda: _FakeRequestsResponse(302, {"Location": "http://%31%36%39.254.169.254/"}),
        })
        self.assertFalse(self._download("https://example.com/x.pdf", requests=fake,
                                        urllib_fn=_fail, playwright=_fail))
        self.assertEqual([u for u, _ in fake.calls], ["https://example.com/x.pdf"])

    def test_redirect_with_backslash_userinfo_refused(self):
        fake = _FakeRequests({
            "https://example.com/x.pdf":
                lambda: _FakeRequestsResponse(
                    302, {"Location": "http://169.254.169.254\\@public.example/x.pdf"}),
        })
        self.assertFalse(self._download("https://example.com/x.pdf", requests=fake,
                                        urllib_fn=_fail, playwright=_fail))
        self.assertEqual([u for u, _ in fake.calls], ["https://example.com/x.pdf"])
        self.assertEqual(os.listdir(self.dir.name), [])

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


class _Trickle:
    """A real socket answering 200 with a large Content-Length, then one byte every 50 ms
    for at most 4 s: a single 64 KiB read never completes and no recv is ever idle long
    enough for the socket timeout."""

    def __init__(self):
        self.server, self.client = socket.socketpair()
        self.client.settimeout(2)
        self.stop = threading.Event()
        self.server.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n%PDF")
        self.thread = threading.Thread(target=self._drip, daemon=True)
        self.thread.start()

    def _drip(self):
        end = time.monotonic() + 4
        try:
            while not self.stop.is_set() and time.monotonic() < end:
                self.server.sendall(b"0")
                time.sleep(0.05)
        except OSError:
            pass
        self.server.close()

    def response(self, url):
        resp = http.client.HTTPResponse(self.client, method="GET", url=url)
        resp.begin()
        resp.msg = resp.reason
        return resp

    def close(self):
        self.stop.set()
        self.thread.join()
        self.client.close()


class _HeaderTrickle(_Trickle):
    """A real socket whose status line and headers never finish: one header byte every 50 ms for at most 4 s."""

    def __init__(self):
        self.server, self.client = socket.socketpair()
        self.client.settimeout(2)
        self.stop = threading.Event()
        self.server.sendall(b"HTTP/1.1 200 OK\r\nX-Slow: ")
        self.thread = threading.Thread(target=self._drip, daemon=True)
        self.thread.start()


class MouserScrapePolicyTest(unittest.TestCase):
    PAGE = "https://www.mouser.com/ProductDetail/x"
    LINK = b'<a href="/datasheet/2/x.pdf">Data Sheet</a>'

    def setUp(self):
        sys.path.insert(0, str(ROOT / "skills" / "mouser" / "scripts"))
        try:
            import provider_mouser
        finally:
            sys.path.pop(0)
        self.prov = provider_mouser
        self.requests = _FakeRequests({})
        for patch in (mock.patch.object(download, "_resolve", return_value=PUBLIC),
                      mock.patch.object(download, "_allow_private_hosts", return_value=False),
                      mock.patch.object(download, "_requests", self.requests),
                      mock.patch.object(provider_mouser, "_requests", self.requests, create=True)):
            patch.start()
            self.addCleanup(patch.stop)

    def _scrape(self, answers, resolve=None):
        seen = []
        handlers = _with_fake_urllib_handler(_urllib_handler(answers, seen))
        err = io.StringIO()
        with mock.patch.object(download, "_URLLIB_HANDLERS", handlers), redirect_stderr(err):
            if resolve:
                with mock.patch.object(download, "_resolve", return_value=resolve):
                    got = self.prov.scrape_product_page(self.PAGE)
            else:
                got = self.prov.scrape_product_page(self.PAGE)
        return got, seen, err.getvalue()

    def test_private_product_url_is_not_fetched(self):
        got, seen, err = self._scrape({self.PAGE: (200, None, self.LINK)}, resolve=["10.0.0.5"])
        self.assertEqual(got, "")
        self.assertEqual(seen, [])
        self.assertEqual(self.requests.calls, [])
        self.assertIn("refused", err)

    def test_redirect_to_a_private_host_is_refused(self):
        got, seen, _ = self._scrape({self.PAGE: (302, "http://10.0.0.5/p", b""),
                                     "http://10.0.0.5/p": (200, None, self.LINK)})
        self.assertEqual(got, "")
        self.assertEqual(seen, [self.PAGE])

    def test_oversized_page_is_dropped(self):
        body = b"x" * (4 * 2**20) + self.LINK
        got, _, _ = self._scrape({self.PAGE: (200, None, body)})
        self.assertEqual(got, "")

    def test_page_only_requests_can_fetch_is_read(self):
        page = self.PAGE

        class Resp(_FakeRequestsResponse):
            def iter_content(self, size):
                return iter([MouserScrapePolicyTest.LINK])
        self.requests.answers[page] = lambda: Resp(200)
        got, seen, _ = self._scrape({})
        self.assertEqual(got, "https://www.mouser.com/datasheet/2/x.pdf")
        self.assertEqual(seen, [])

    def test_public_page_link_is_found(self):
        got, _, _ = self._scrape({self.PAGE: (200, None, self.LINK)})
        self.assertEqual(got, "https://www.mouser.com/datasheet/2/x.pdf")


class TrickleDeadlineTest(unittest.TestCase):
    URL = "https://example.com/x.pdf"

    def setUp(self):
        for target, kw in (("_resolve", {"return_value": PUBLIC}),
                           ("_allow_private_hosts", {"return_value": False}),
                           ("DOWNLOAD_TIMEOUT_S", None)):
            p = (mock.patch.object(download, target, 0.5) if kw is None
                 else mock.patch.object(download, target, **kw))
            p.start()
            self.addCleanup(p.stop)
        self.trickle = _Trickle()
        self.addCleanup(self.trickle.close)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def _run(self, **patches):
        stderr = io.StringIO()
        start = time.monotonic()
        with mock.patch.multiple(download, _sync_playwright=None, **patches), \
             redirect_stderr(stderr), redirect_stdout(io.StringIO()):
            ok = download.download_pdf(self.URL, os.path.join(self.dir.name, "x.pdf"))
        elapsed = time.monotonic() - start
        self.assertFalse(ok)
        self.assertLess(elapsed, 3.0)
        self.assertIn("download stopped", stderr.getvalue())
        self.assertEqual(os.listdir(self.dir.name), [])

    def test_urllib_trickle_stops_at_the_deadline(self):
        trickle = self.trickle

        class Fake(urllib.request.BaseHandler):
            def https_open(self, req):
                return trickle.response(req.full_url)
        handlers = _with_fake_urllib_handler(Fake)
        self._run(_requests=None, _URLLIB_HANDLERS=handlers)

    def test_requests_trickle_stops_at_the_deadline(self):
        trickle = self.trickle

        class Resp(_FakeRequestsResponse):
            def __init__(self):
                super().__init__(200)
                self.raw = trickle.response(TrickleDeadlineTest.URL)

            def iter_content(self, size):
                return iter(lambda: self.raw.read(size), b"")
        self._run(_requests=_FakeRequests({self.URL: Resp}), _download_urllib=_fail)

    def test_requests_header_trickle_stops_at_the_deadline(self):
        slow = _HeaderTrickle()
        self.addCleanup(slow.close)

        # blocks in HTTPResponse.begin() while headers trickle
        self._run(_requests=fake_requests(lambda url, **kw: slow.response(url)),
                  _download_urllib=_fail)

    @unittest.skipIf(download._requests is None, "requests is not installed")
    def test_redirect_body_is_not_read(self):
        body = 64 * 2**20
        sent = [0]
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(4)

        def serve():
            while True:
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                with conn:
                    if b"/final.pdf" in conn.recv(65536):
                        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n"
                                     b"Connection: close\r\n\r\n%PDF-1.4")
                        continue
                    conn.sendall(b"HTTP/1.1 302 Found\r\nLocation: /final.pdf\r\n"
                                 b"Content-Length: %d\r\n\r\n" % body)
                    chunk = b"\0" * 65536
                    try:
                        while sent[0] < body:
                            conn.sendall(chunk)
                            sent[0] += len(chunk)
                    except OSError:
                        pass
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        self.addCleanup(lambda: (srv.close(), t.join(5)))
        url = f"http://127.0.0.1:{srv.getsockname()[1]}/x.pdf"
        with mock.patch.object(download, "_allow_private_hosts", return_value=True), \
             mock.patch.dict(os.environ, {"NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}), \
             mock.patch.multiple(download, _sync_playwright=None, _download_urllib=_fail), \
             redirect_stderr(io.StringIO()):
            ok = download.download_pdf(url, os.path.join(self.dir.name, "x.pdf"))
        self.assertTrue(ok)
        self.assertLess(sent[0], 8 * 2**20)

    @unittest.skipIf(download._requests is None, "requests is not installed")
    def test_real_requests_header_trickle_stops_at_the_deadline(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        stop = threading.Event()

        def serve():
            conn, _ = srv.accept()
            with conn:
                conn.sendall(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                end = time.monotonic() + 4
                while not stop.is_set() and time.monotonic() < end:
                    try:
                        conn.sendall(b"0")
                    except OSError:
                        return
                    time.sleep(0.05)
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        self.addCleanup(lambda: (stop.set(), t.join(), srv.close()))
        url = f"http://127.0.0.1:{srv.getsockname()[1]}/x.pdf"
        stderr, start = io.StringIO(), time.monotonic()
        with mock.patch.object(download, "_allow_private_hosts", return_value=True), \
             mock.patch.dict(os.environ, {"NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}), \
             mock.patch.multiple(download, _sync_playwright=None, _download_urllib=_fail), \
             redirect_stderr(stderr):
            ok = download.download_pdf(url, os.path.join(self.dir.name, "x.pdf"))
        self.assertFalse(ok)
        self.assertLess(time.monotonic() - start, 3.0)
        self.assertIn("download stopped", stderr.getvalue())


class _FakeRoute:
    """A Playwright route for ``url``; ``chain`` answers each fetched URL with
    ``(status, location)``, or an exception to raise."""

    def __init__(self, url, log, chain):
        self.request = mock.Mock(url=url)
        self._log, self._chain = log, chain

    def abort(self, reason=None):
        self._log.append(("abort", self.request.url))

    def continue_(self):
        self._log.append(("continue", self.request.url))

    def fetch(self, url=None, max_redirects=None, timeout=None):
        url = url or self.request.url
        self._log.append(("fetch", url, max_redirects))
        answer = self._chain.get(url, (200, None))
        if isinstance(answer, Exception):
            raise answer
        status, location = answer
        headers = {"location": location} if location else {}
        return mock.Mock(status=status, headers=headers)

    def fulfill(self, response=None):
        self._log.append(("fulfill", self.request.url))


def _fake_playwright(urls, chain, log, response=None, on_download=None, context_error=None):
    """A ``sync_playwright`` stand-in: its page records ``route`` registrations and, on
    ``goto``, drives the registered handler with a fake route for each of ``urls`` and
    answers ``response``. ``log`` also records the context options, the WebSocket route and
    each ``goto``."""
    registered = []

    class Page:
        def route(self, pattern, handler):
            registered.append(pattern)
            self.handler = handler

        def route_web_socket(self, pattern, handler):
            log.append(("route_web_socket", pattern))

        def expect_download(self, timeout=None):
            if on_download is not None:
                on_download()
            raise RuntimeError("no download event")

        def goto(self, url, **kw):
            assert registered, "route must be installed before navigation"
            log.append(("goto", url))
            for u in urls:
                self.handler(_FakeRoute(u, log, chain))
            return response

    class Context:
        def new_page(self):
            return Page()

        def close(self):
            log.append(("context.close",))

    class Browser:
        def new_context(self, **kw):
            log.append(("new_context", kw))
            if context_error is not None:
                raise context_error
            return Context()

        def new_page(self):
            return Page()

        def close(self):
            log.append(("browser.close",))

    class P:
        chromium = mock.Mock(launch=lambda headless: Browser())

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return (lambda: P()), registered


def _route_log(log):
    return [e for e in log if e[0] in ("fetch", "fulfill", "abort", "continue")]


class PlaywrightRouteTest(unittest.TestCase):
    def test_browser_requests_follow_the_policy(self):
        chain = {
            "https://a.example/x": (302, "https://b.example/y"),
            "https://b.example/y": (302, "http://169.254.169.254/latest"),
            "https://cdn.example.org/app.js": (302, "http://10.0.0.1/x"),
            "https://example.com/moved": (301, "https://cdn.example.org/x.pdf"),
            "https://loop.example/a": (302, "/b"),
            "https://loop.example/b": (302, "/a"),
            "https://broken.example/x": OSError("connection reset"),
        }
        urls = ["https://example.com/x.pdf", "http://127.0.0.1/admin", "https://a.example/x",
                "https://cdn.example.org/app.js", "https://example.com/moved",
                "file:///etc/passwd", "https://loop.example/a", "https://broken.example/x"]
        log = []
        fake, registered = _fake_playwright(urls, chain, log)
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(download, "_resolve", return_value=PUBLIC), \
             mock.patch.object(download, "_allow_private_hosts", return_value=False), \
             mock.patch.object(download, "_requests", None), \
             mock.patch.object(download, "_download_urllib", lambda u, p: False), \
             mock.patch.object(download, "_sync_playwright", fake), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertFalse(download.download_pdf("https://example.com/x.pdf",
                                                   os.path.join(d, "x.pdf")))
        self.assertEqual(registered, ["**/*"])
        log = _route_log(log)
        loop = [("fetch", "https://loop.example/a", 0), ("fetch", "https://loop.example/b", 0)] * 3
        self.assertEqual(log, [
            ("fetch", "https://example.com/x.pdf", 0),
            ("fulfill", "https://example.com/x.pdf"),
            ("abort", "http://127.0.0.1/admin"),
            ("fetch", "https://a.example/x", 0),
            ("fetch", "https://b.example/y", 0),
            ("abort", "https://a.example/x"),
            ("fetch", "https://cdn.example.org/app.js", 0),
            ("abort", "https://cdn.example.org/app.js"),
            ("fetch", "https://example.com/moved", 0),
            ("fetch", "https://cdn.example.org/x.pdf", 0),
            ("fulfill", "https://example.com/moved"),
            ("abort", "file:///etc/passwd"),
            *loop,
            ("abort", "https://loop.example/a"),
            ("fetch", "https://broken.example/x", 0),
            ("abort", "https://broken.example/x"),
        ])


    def _run(self, fake, *, timeout=None):
        stderr = io.StringIO()
        patches = [mock.patch.object(download, "_resolve", return_value=PUBLIC),
                   mock.patch.object(download, "_allow_private_hosts", return_value=False),
                   mock.patch.object(download, "_requests", None),
                   mock.patch.object(download, "_download_urllib", lambda u, p: False),
                   mock.patch.object(download, "_sync_playwright", fake)]
        if timeout is not None:
            patches.append(mock.patch.object(download, "DOWNLOAD_TIMEOUT_S", timeout))
        with tempfile.TemporaryDirectory() as d, contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                ok = download.download_pdf("https://example.com/x.pdf", os.path.join(d, "x.pdf"))
            self.assertEqual(os.listdir(d), [])
        return ok, stderr.getvalue()

    def test_browser_context_blocks_service_workers_and_websockets(self):
        log = []
        fake, _ = _fake_playwright([], {}, log)
        self.assertFalse(self._run(fake)[0])
        self.assertEqual(log[0], ("new_context", {"service_workers": "block"}))
        self.assertLess(log.index(("route_web_socket", "**/*")),
                        log.index(("goto", "https://example.com/x.pdf")))
        self.assertEqual(log[-2:], [("context.close",), ("browser.close",)])

    def test_browser_closed_when_the_context_fails(self):
        log = []
        fake, _ = _fake_playwright([], {}, log, context_error=RuntimeError("no context"))
        self.assertFalse(self._run(fake)[0])
        self.assertEqual(log[-1], ("browser.close",))

    def test_oversized_body_not_buffered(self):
        log = []
        response = mock.Mock(headers={"content-length": str(download.MAX_DOWNLOAD_BYTES + 1)},
                             body=lambda: log.append(("body",)) or PDF)
        fake, _ = _fake_playwright([], {}, log, response=response)
        self.assertFalse(self._run(fake)[0])
        self.assertIn(("goto", "https://example.com/x.pdf"), log)
        self.assertNotIn(("body",), log)

    def test_deadline_stops_the_browser_between_steps(self):
        clock = [1000.0]
        log = []

        def slow_download_attempt():
            clock[0] += 61.0
        fake, _ = _fake_playwright([], {}, log, response=mock.Mock(headers={}, body=lambda: PDF),
                                   on_download=slow_download_attempt)
        with mock.patch.object(download.time, "monotonic", lambda: clock[0]):
            ok, stderr = self._run(fake, timeout=60.0)
        self.assertFalse(ok)
        self.assertIn("download stopped", stderr)
        self.assertNotIn(("goto", "https://example.com/x.pdf"), log)
        self.assertEqual(log[-2:], [("context.close",), ("browser.close",)])


@unittest.skipIf(download._sync_playwright is None, "playwright is not installed")
class RealPlaywrightTest(unittest.TestCase):
    def test_browser_fallback_downloads_a_pdf(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(len(PDF)))
                self.end_headers()
                self.wfile.write(PDF)

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close(), t.join(5)))
        try:
            with download._sync_playwright() as p:
                p.chromium.launch(headless=True).close()
        except Exception as exc:
            self.skipTest(f"no headless Chromium: {exc}")
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(download, "_allow_private_hosts", return_value=True), \
             mock.patch.multiple(download, _requests=None, _download_urllib=lambda u, p: False), \
             mock.patch.dict(os.environ, {"no_proxy": "*", "NO_PROXY": "*"}), \
             redirect_stderr(io.StringIO()):
            out = os.path.join(d, "x.pdf")
            self.assertTrue(download.download_pdf(
                f"http://127.0.0.1:{srv.server_address[1]}/x.pdf", out))
            with open(out, "rb") as f:
                self.assertEqual(f.read(), PDF)


class UrllibOpenerTest(unittest.TestCase):
    def test_opener_keeps_proxies_and_has_no_local_schemes(self):
        # A ProxyHandler without any proxy configured registers no methods and is dropped.
        proxies = {"http_proxy": "http://proxy.example:3128",
                   "https_proxy": "http://proxy.example:3128"}
        with mock.patch.dict(os.environ, proxies):
            handlers = download._urllib_opener().handlers
        kinds = [type(h) for h in handlers]
        self.assertTrue(any(issubclass(k, urllib.request.ProxyHandler) for k in kinds))
        for banned in (urllib.request.FileHandler, urllib.request.FTPHandler,
                       urllib.request.DataHandler, urllib.request.UnknownHandler):
            self.assertFalse(any(issubclass(k, banned) for k in kinds), banned)


class _FakeSSLContext:
    """Records the name each socket is wrapped for (the SNI and certificate host)."""
    post_handshake_auth = None

    def __init__(self):
        self.server_hostnames = []

    def set_alpn_protocols(self, protocols):
        pass

    def wrap_socket(self, sock, server_hostname=None):
        self.server_hostnames.append(server_hostname)
        return sock


class PinnedConnectTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, download._call, "pins", {})

    def _connect(self, pins):
        download._call.pins = pins
        addresses, context = [], _FakeSSLContext()

        def create_connection(address, *a, **k):
            addresses.append(address)
            return mock.Mock()
        with mock.patch.object(socket, "create_connection", create_connection):
            download._WatchedHTTPSConnection("example.com", 443, context=context).connect()
        return addresses, context.server_hostnames

    def test_connect_uses_the_checked_address_and_keeps_sni(self):
        self.assertEqual(self._connect({"example.com": ["93.184.216.34"]}),
                         ([("93.184.216.34", 443)], ["example.com"]))

    def test_urllib_tries_each_checked_address_once(self):
        attempts = []

        def create_connection(address, *a, **k):
            attempts.append(address)
            raise ConnectionRefusedError(111, "Connection refused")
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(download, "_resolve",
                               return_value=["93.184.216.34", "93.184.216.34", "93.184.216.35"]), \
             mock.patch.object(download, "_allow_private_hosts", return_value=False), \
             mock.patch.multiple(download, _requests=None, _sync_playwright=None), \
             mock.patch.object(socket, "create_connection", create_connection), \
             mock.patch.dict(os.environ, {"no_proxy": "*", "NO_PROXY": "*"}), \
             redirect_stderr(io.StringIO()):
            self.assertFalse(download.download_pdf("https://example.com/x.pdf",
                                                   os.path.join(d, "x.pdf")))
        self.assertEqual(attempts, [("93.184.216.34", 443), ("93.184.216.35", 443)])

    def test_unpinned_host_connects_by_name(self):
        self.assertEqual(self._connect({}), ([("example.com", 443)], ["example.com"]))

    def test_rebinding_answer_is_not_used(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/x.pdf":
                    self.send_response(302)
                    self.send_header("Location", f"http://other.example:{port}/y.pdf")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(PDF)))
                self.end_headers()
                self.wfile.write(PDF)

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close(), t.join(5)))
        real_getaddrinfo = socket.getaddrinfo

        # The check saw 127.0.0.1 (allowed here); a lookup at connect time would fail.
        def getaddrinfo(host, *a, **k):
            if host in ("rebind.example", "other.example"):
                raise socket.gaierror(socket.EAI_NONAME, "rebound")
            return real_getaddrinfo(host, *a, **k)
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(download, "_resolve", return_value=["127.0.0.1"]), \
             mock.patch.object(download, "_address_problem", return_value=None), \
             mock.patch.object(download, "_allow_private_hosts", return_value=False), \
             mock.patch.multiple(download, _requests=None, _sync_playwright=None), \
             mock.patch.object(socket, "getaddrinfo", getaddrinfo), \
             mock.patch.dict(os.environ, {"no_proxy": "*", "NO_PROXY": "*"}), \
             redirect_stderr(io.StringIO()):
            out = os.path.join(d, "x.pdf")
            self.assertTrue(download.download_pdf(f"http://rebind.example:{port}/x.pdf", out))
            with open(out, "rb") as f:
                self.assertEqual(f.read(), PDF)
        self.assertEqual(download._call.pins, {})


@unittest.skipIf(download._requests is None or not hasattr(
    download._requests.adapters.HTTPAdapter, "build_connection_pool_key_attributes"),
    "requests 2.32.2 or later is not installed")
class PinnedRequestsTest(unittest.TestCase):
    """Real requests and urllib3 over a socket pair: the resolver, the TCP connect and the
    TLS handshake are faked; urllib3's own certificate name check runs."""

    def _download(self, cert_names, addresses=PUBLIC, refused=(), redirect=None):
        """Download https://example.com/x.pdf from servers whose certificate names
        ``cert_names``; ``refused`` addresses refuse the connect and ``redirect`` is a
        Location the first answer sends."""
        import urllib3.connection
        import urllib3.util.connection
        connected, server_names, sent = [], [], []
        answers = [b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s"
                   % (len(PDF), PDF)]
        if redirect:
            answers.insert(0, b"HTTP/1.1 302 Found\r\nLocation: %s\r\nContent-Length: 0\r\n"
                              b"Connection: close\r\n\r\n" % redirect.encode())

        def serve(server, answer):
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = server.recv(65536)
                if not chunk:
                    return
                data += chunk
            sent.append(data)
            server.sendall(answer)

        def create_connection(address, *a, **k):
            connected.append(address)
            if address[0] in refused:
                raise ConnectionRefusedError(111, "Connection refused")
            client, server = socket.socketpair()
            t = threading.Thread(target=serve, args=(server, answers.pop(0)), daemon=True)
            t.start()
            self.addCleanup(t.join, 5)
            self.addCleanup(server.close)
            self.addCleanup(client.close)
            return client

        class TLSSocket:
            def __init__(self, sock):
                self._sock = sock

            def getpeercert(self, binary_form=False):
                return {"subjectAltName": tuple(("DNS", n) for n in cert_names)}

            def __getattr__(self, name):
                return getattr(self._sock, name)

        def ssl_wrap_socket(sock, *a, server_hostname=None, **k):
            server_names.append(server_hostname)
            return TLSSocket(sock)

        resolved = {"example.com": addresses, "cdn.example.org": ["93.184.216.40"]}
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(download, "_resolve", side_effect=resolved.__getitem__), \
             mock.patch.object(download, "_allow_private_hosts", return_value=False), \
             mock.patch.multiple(download, _sync_playwright=None, _download_urllib=_fail), \
             mock.patch.object(urllib3.util.connection, "create_connection", create_connection), \
             mock.patch.object(urllib3.connection, "ssl_wrap_socket", ssl_wrap_socket), \
             mock.patch.dict(os.environ, {"no_proxy": "*", "NO_PROXY": "*"}), \
             redirect_stderr(io.StringIO()):
            ok = download.download_pdf("https://example.com/x.pdf", os.path.join(d, "x.pdf"))
        return ok, connected, server_names, sent

    def test_requests_without_the_connect_error_name_stays_unpinned(self):
        code = ("import sys, requests.adapters\n"
                "del requests.adapters.ConnectTimeoutError\n"
                f"sys.path.insert(0, {str(ROOT / 'skills' / 'datasheets')!r})\n"
                "from distributor_core import download\n"
                "print(download._PinnedAdapter, download._requests is not None)\n")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             timeout=60)
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "None True"), out.stderr)

    def test_requests_connects_to_the_checked_address_and_checks_the_host_name(self):
        ok, connected, server_names, sent = self._download(["example.com"])
        self.assertTrue(ok)
        self.assertEqual(connected, [(PUBLIC[0], 443)])
        self.assertEqual(server_names, ["example.com"])
        self.assertIn(b"\r\nHost: example.com\r\n", sent[0])

    def test_certificate_for_another_name_is_refused(self):
        ok, connected, server_names, sent = self._download(["other.example"])
        self.assertFalse(ok)
        self.assertEqual(connected, [(PUBLIC[0], 443)])
        self.assertEqual(server_names, ["example.com"])
        self.assertEqual(sent, [])

    def test_next_checked_address_after_a_refused_connect(self):
        ok, connected, _, _ = self._download(
            ["example.com"], addresses=["93.184.216.34", "93.184.216.34", "93.184.216.35"],
            refused={"93.184.216.34"})
        self.assertTrue(ok)
        self.assertEqual(connected, [("93.184.216.34", 443), ("93.184.216.35", 443)])

    def test_redirect_hop_is_checked_and_pinned(self):
        ok, connected, server_names, sent = self._download(
            ["example.com", "cdn.example.org"], redirect="https://cdn.example.org/y.pdf")
        self.assertTrue(ok)
        self.assertEqual(connected, [(PUBLIC[0], 443), ("93.184.216.40", 443)])
        self.assertEqual(server_names, ["example.com", "cdn.example.org"])
        self.assertIn(b"\r\nHost: example.com\r\n", sent[0])
        self.assertIn(b"\r\nHost: cdn.example.org\r\n", sent[1])


class AllowPrivateTest(unittest.TestCase):
    def _allow(self, home, cwd=None):
        old = os.getcwd()
        try:
            if cwd:
                os.chdir(cwd)
            with mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home}):
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
            with mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home}):
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
