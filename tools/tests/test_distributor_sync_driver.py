# tools/tests/test_distributor_sync_driver.py
import io, json, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "datasheets"))

LABELS = {"found": "Found {n} unique parts with part numbers ({k} skipped without any identifier)", "skipped_key": "skipped_no_identifier",
          "total_key": "total_identified_parts", "dry_skipped": "Skipped (no identifier): {k}", "summary_skipped": "  Skipped (no identifier): {k}"}


def fake_provider(**over):
    base = dict(NAME="fake", DEFAULT_DELAY=0.0, ID_KEYS=("digikey",), KEY_PRIORITY=("digikey",), SKIPPED_COUNTS_IDS=("digikey",),
                RENAME_PRESENT=False, FAILED_DETAIL_WITH_URL=False, NORMALIZE_REDIRECTS=False, LABELS=LABELS,
                preflight=lambda **kw: {}, authenticate=lambda: {"ctx": "C"}, report_tail=lambda *a: None,
                sync_one_part=lambda part, out_dir, index, delay, ctx: {"status": "not_found", "error": f"ctx={ctx}", "manufacturer": "", "description": "", "value": part["value"], "references": part["references"], "last_attempt": "t"})
    base.update(over)
    return SimpleNamespace(**base)


class Driver(unittest.TestCase):
    def _bom(self, d):
        p = Path(d) / "bom.json"
        p.write_text(json.dumps({"bom": [{"mpn": "LM358DR", "references": ["U1"], "value": "LM358DR", "type": "ic"},
                                         {"mpn": "", "digikey": "296-1-ND", "references": ["U2"], "value": "", "type": "ic"},
                                         {"mpn": "", "element14": "94AK", "references": ["U3"], "value": "", "type": "ic"}]}), encoding="utf-8")
        return str(p)

    def test_two_workers_store_the_same_manifest_as_the_serial_run(self):
        from distributor_core.sync import sync_datasheets

        def one(part, out_dir, index, delay, ctx):
            if part["mpn"] == "NE555P":
                return {"status": "ok", "file": "NE555P.pdf", "size_bytes": 3, "verification": "unverified"}
            return {"status": "not_found", "error": "none", "manufacturer": "", "description": "",
                    "value": part["value"], "references": part["references"], "last_attempt": "t"}
        manifests = {}
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            mpns = d / "mpns.txt"
            mpns.write_text("LM358DR\nNE555P\nTL072\nLM317\n", encoding="utf-8")
            for par in (1, 2):
                with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                    r = sync_datasheets(fake_provider(sync_one_part=one), mpn_list=str(mpns),
                                        output_dir=str(d / f"out{par}"), parallel=par)
                m = json.loads((d / f"out{par}" / "manifest.json").read_text(encoding="utf-8"))
                m.pop("last_sync")
                manifests[par] = (m, r["downloaded"], r["failed"])
            self.assertEqual(manifests[1], manifests[2])
            self.assertEqual(manifests[1][1:], (1, 3))

    def test_two_workers_keep_a_transport_outage_like_the_serial_run(self):
        from distributor_core.sync import sync_datasheets
        from distributor_core import download

        def one(part, out_dir, index, delay, ctx):
            if part["mpn"] == "NE555P":
                download.note_transport_failure(TimeoutError("search timed out"))
            return {"status": "not_found", "error": "none", "manufacturer": "", "description": "",
                    "value": part["value"], "references": part["references"], "last_attempt": "t"}
        runs = {}
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            mpns = d / "mpns.txt"
            mpns.write_text("LM358DR\nNE555P\nTL072\nLM317\n", encoding="utf-8")
            for par in (1, 2):
                with redirect_stderr(io.StringIO()) as err, redirect_stdout(io.StringIO()):
                    sync_datasheets(fake_provider(sync_one_part=one), mpn_list=str(mpns),
                                    output_dir=str(d / f"out{par}"), parallel=par)
                m = json.loads((d / f"out{par}" / "manifest.json").read_text(encoding="utf-8"))
                runs[par] = (m["parts"]["NE555P"]["status"], m["parts"]["NE555P"]["error"],
                             m["parts"]["TL072"]["error"])
            self.assertEqual(runs[1], runs[2])
            self.assertEqual(runs[1][:2], ("error", "network failure, retried next run: TimeoutError: search timed out"))
            self.assertEqual(runs[1][2], "none")

    def test_preflight_error_wins_before_output_dir_is_created(self):
        from distributor_core.sync import sync_datasheets
        with tempfile.TemporaryDirectory() as d:
            r = sync_datasheets(fake_provider(preflight=lambda **kw: {"error": "NOKEY"}), input_path=self._bom(d), output_dir=str(Path(d) / "out"))
            self.assertEqual(r, {"error": "NOKEY"})
            self.assertFalse((Path(d) / "out").exists())

    def test_ctx_from_authenticate_reaches_sync_one_part_and_key_priority_applies(self):
        from distributor_core.sync import sync_datasheets
        with tempfile.TemporaryDirectory() as d, redirect_stderr(io.StringIO()):
            sync_datasheets(fake_provider(), input_path=self._bom(d), output_dir=str(Path(d) / "out"))
            m = json.loads((Path(d) / "out" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(set(m["parts"]), {"LM358DR", "296-1-ND"})   # element14-only part excluded by ID_KEYS
            self.assertEqual(m["parts"]["LM358DR"]["error"], "ctx=C")

    def test_skipped_count_rule_and_labels(self):
        from distributor_core.sync import sync_datasheets
        with tempfile.TemporaryDirectory() as d:
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                r = sync_datasheets(fake_provider(SKIPPED_COUNTS_IDS=()), input_path=self._bom(d), output_dir=str(Path(d) / "out"), dry_run=True, as_json=False)
            self.assertEqual(r["skipped_no_identifier"], 2)   # both id-only parts count under the Mouser rule
            self.assertIn("Found 2 unique parts with part numbers (2 skipped without any identifier)", err.getvalue())


if __name__ == "__main__":
    unittest.main()
