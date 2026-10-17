# tools/tests/test_distributor_sync_driver.py
import io, json, sys, tempfile, unittest
from contextlib import redirect_stderr
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
            with redirect_stderr(err):
                r = sync_datasheets(fake_provider(SKIPPED_COUNTS_IDS=()), input_path=self._bom(d), output_dir=str(Path(d) / "out"), dry_run=True, as_json=False)
            self.assertEqual(r["skipped_no_identifier"], 2)   # both id-only parts count under the Mouser rule
            self.assertIn("Found 2 unique parts with part numbers (2 skipped without any identifier)", err.getvalue())


if __name__ == "__main__":
    unittest.main()
