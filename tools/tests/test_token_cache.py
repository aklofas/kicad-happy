"""The DigiKey access token is cached in a private per-user folder, bound to the
client id, and the old shared temp file is never read."""
import io, json, os, stat, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for sub in ("kicad/scripts", "digikey/scripts", "spice/scripts"):
    p = str(ROOT / "skills" / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

from kicad_core import token_cache  # noqa: E402
import lifecycle_audit  # noqa: E402
import provider_digikey  # noqa: E402
import spice_spec_fetcher  # noqa: E402

POSIX = sys.platform != "win32"


class _Env(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        env = {"HOME": self.home, "XDG_CACHE_HOME": os.path.join(self.home, "xdg"),
               "LOCALAPPDATA": os.path.join(self.home, "local")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)
        base = env["LOCALAPPDATA"] if not POSIX else env["XDG_CACHE_HOME"]
        self.file = os.path.join(base, "kicad-happy", "digikey_token.json")


class TokenCacheTest(_Env):
    def test_round_trip_client_binding_and_expiry(self):
        with mock.patch("time.time", return_value=1000.0):
            token_cache.store_token("digikey_token", "cid", "T", 540)
            self.assertEqual(token_cache.load_token("digikey_token", "cid"), "T")
            self.assertIsNone(token_cache.load_token("digikey_token", "other"))
        with mock.patch("time.time", return_value=1540.5):
            self.assertIsNone(token_cache.load_token("digikey_token", "cid"))

    @unittest.skipUnless(POSIX, "POSIX modes")
    def test_modes(self):
        token_cache.store_token("digikey_token", "cid", "T", 540)
        self.assertEqual(stat.S_IMODE(os.stat(self.file).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(self.file)).st_mode), 0o700)

    @unittest.skipUnless(POSIX, "POSIX modes")
    def test_loose_mode_symlink_and_garbage_are_rejected(self):
        token_cache.store_token("digikey_token", "cid", "T", 540)
        os.chmod(self.file, 0o644)
        self.assertIsNone(token_cache.load_token("digikey_token", "cid"))
        os.chmod(self.file, 0o600)
        self.assertEqual(token_cache.load_token("digikey_token", "cid"), "T")
        real = self.file + ".real"
        os.replace(self.file, real)
        os.symlink(real, self.file)
        self.assertIsNone(token_cache.load_token("digikey_token", "cid"))
        os.unlink(self.file)
        for body in ("[1, 2]", "not json", '{"client_id": "cid", "token": 5, "expires_at": 9e99}'):
            with open(self.file, "w") as f:
                f.write(body)
            os.chmod(self.file, 0o600)
            self.assertIsNone(token_cache.load_token("digikey_token", "cid"), body)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class CallersTest(_Env):
    def setUp(self):
        super().setUp()
        p = mock.patch.dict(os.environ, {"DIGIKEY_CLIENT_ID": "cid",
                                         "DIGIKEY_CLIENT_SECRET": "sec"})
        p.start()
        self.addCleanup(p.stop)

    def _check(self, get, unwrap):
        old = os.path.join(tempfile.gettempdir(), "digikey_token_cache.json")
        if not os.path.exists(old):
            with open(old, "w") as f:
                json.dump({"access_token": "EVIL", "token": "EVIL", "client_id": "cid",
                           "expires_at": 9e99}, f)
            self.addCleanup(os.unlink, old)
        with mock.patch("urllib.request.urlopen",
                        side_effect=lambda *a, **k: _Resp(b'{"access_token": "T1"}')) as uo:
            self.assertEqual(unwrap(get()), "T1")
            self.assertEqual(unwrap(get()), "T1")
            self.assertEqual(uo.call_count, 1)

    def test_lifecycle_audit(self):
        self._check(lifecycle_audit._get_digikey_token, lambda r: r[0])

    def test_provider_digikey(self):
        self._check(provider_digikey._get_digikey_token, lambda r: r)

    def test_spice_spec_fetcher(self):
        self._check(spice_spec_fetcher._get_digikey_token, lambda r: r)


if __name__ == "__main__":
    unittest.main()
