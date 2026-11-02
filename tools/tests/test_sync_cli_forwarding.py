"""Each sync_datasheets_<provider>.py main() forwards its flags to sync_datasheets unchanged, sets the
download limits, and exits 1 only when the summary carries an error."""
import importlib, sys, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
PROVIDERS = ("digikey", "mouser", "lcsc", "element14")
BASE = {"input_path": None, "output_dir": None, "force": False, "force_all": False, "parallel": 1,
        "dry_run": False, "as_json": False, "mpn_list": None}
DELAY = {"digikey": 1.0, "mouser": 1.0, "lcsc": 0.5, "element14": 0.5}


def _load(p):
    for name in [n for n in sys.modules if n.split(".")[0] in ("distributor_core", "_core_path")
                 or n.startswith(("provider_", "sync_datasheets_", "fetch_datasheet_"))]:
        del sys.modules[name]
    sys.path[:0] = [str(ROOT / "skills" / p / "scripts")]
    try:
        return importlib.import_module(f"sync_datasheets_{p}")
    finally:
        del sys.path[0]


class SyncCliForwarding(unittest.TestCase):
    def _run(self, mod, argv, result):
        seen = {}

        def fake(**kw):
            seen.update(kw)
            return result
        with mock.patch.object(mod, "sync_datasheets", fake), mock.patch.object(sys, "argv", ["x", *argv]):
            with self.assertRaises(SystemExit) as ex:
                mod.main()
        return seen, ex.exception.code

    def test_defaults_and_exit_codes(self):
        for p in PROVIDERS:
            mod = _load(p)
            with self.subTest(provider=p):
                want = dict(BASE, input_path="a.kicad_sch", delay=DELAY[p])
                if p == "element14":
                    want["store"] = "www.newark.com"
                for result, code in (({}, 0), ({"failed": 2}, 0), ({"error": "x"}, 1)):
                    seen, rc = self._run(mod, ["a.kicad_sch"], result)
                    self.assertEqual(seen, want)
                    self.assertEqual(rc, code)

    def test_every_flag_is_forwarded(self):
        for p in PROVIDERS:
            mod = _load(p)
            with self.subTest(provider=p):
                argv = ["--mpn-list", "m.txt", "-o", "out", "--force", "--force-all", "--delay", "2.5",
                        "--parallel", "3", "--dry-run", "--json", "--max-download-mb", "7",
                        "--download-timeout", "9"]
                want = dict(BASE, mpn_list="m.txt", output_dir="out", force=True, force_all=True,
                            delay=2.5, parallel=3, dry_run=True, as_json=True)
                if p == "element14":
                    argv += ["--store", "uk.farnell.com"]
                    want["store"] = "uk.farnell.com"
                seen, rc = self._run(mod, argv, {})
                self.assertEqual((seen, rc), (want, 0))
                dl = sys.modules["distributor_core.download"]
                self.assertEqual((dl.MAX_DOWNLOAD_BYTES, dl.DOWNLOAD_TIMEOUT_S), (7 * 1024 * 1024, 9.0))

    def test_boolean_flags_are_independent(self):
        # the full-flag run sets all four to True, so a swap between them shows only here
        flags = {"--force": "force", "--force-all": "force_all", "--dry-run": "dry_run", "--json": "as_json"}
        for p in PROVIDERS:
            mod = _load(p)
            for flag, key in flags.items():
                with self.subTest(provider=p, flag=flag):
                    seen, _ = self._run(mod, ["a.kicad_sch", flag], {})
                    self.assertEqual({k for k in flags.values() if seen[k]}, {key})

    def test_input_and_mpn_list_are_exclusive(self):
        for p in PROVIDERS:
            mod = _load(p)
            with self.subTest(provider=p), mock.patch("sys.stderr"):
                for argv in ([], ["a.kicad_sch", "--mpn-list", "m.txt"]):
                    with mock.patch.object(sys, "argv", ["x", *argv]), self.assertRaises(SystemExit) as ex:
                        mod.main()
                    self.assertEqual(ex.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
