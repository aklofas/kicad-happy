# tools/tests/test_distributor_sync_driver.py
import io, json, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "datasheets"))

LABELS = {"found": "Found {n} unique parts with part numbers ({k} skipped without any identifier)", "skipped_key": "skipped_no_identifier",
          "total_key": "total_identified_parts", "dry_skipped": "Skipped (no identifier): {k}", "summary_skipped": "  Skipped (no identifier): {k}"}


def fake_provider(**over):
    base = dict(NAME="fake", DEFAULT_DELAY=0.0, ID_KEYS=("digikey",), KEY_PRIORITY=("digikey",), SEARCH_KEY="digikey",
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
            self.assertEqual(runs[1][:2], ("error", "network failure, retried next run: TimeoutError: search timed out;"
                                                    " distributor said: none"))
            self.assertEqual(runs[1][2], "none")

    def test_preflight_error_wins_before_output_dir_is_created(self):
        from distributor_core.sync import sync_datasheets
        with tempfile.TemporaryDirectory() as d, redirect_stderr(io.StringIO()):
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
                r = sync_datasheets(fake_provider(SEARCH_KEY="element14", ID_KEYS=("digikey", "element14")),
                                    input_path=self._bom(d), output_dir=str(Path(d) / "out"), dry_run=True, as_json=False)
            self.assertEqual(r["skipped_no_identifier"], 1)   # the DigiKey-only part cannot be searched here
            self.assertIn("Found 2 unique parts with part numbers (1 skipped without any identifier)", err.getvalue())

    def _searched(self, bom_entries, **over):
        from distributor_core.sync import sync_datasheets
        seen = []

        def one(part, out_dir, index, delay, ctx):
            seen.append(part["_key"])
            return {"status": "not_found", "error": "x", "manufacturer": "", "description": "",
                    "value": part["value"], "references": part["references"], "last_attempt": "t"}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bom.json"
            p.write_text(json.dumps({"bom": bom_entries}), encoding="utf-8")
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                sync_datasheets(fake_provider(sync_one_part=one, **over), input_path=str(p), output_dir=str(Path(d) / "out"))
            mf = Path(d) / "out" / "manifest.json"
            m = json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else {}
        return seen, err.getvalue(), m

    def test_part_known_only_by_another_distributor_is_not_searched(self):
        ids = ("digikey", "mouser", "lcsc", "element14")
        entries = [{"mpn": "", "lcsc": "C14663", "references": ["U1"], "value": "", "type": "ic"}]
        for key in ids:
            seen, out, m = self._searched(entries, ID_KEYS=ids, KEY_PRIORITY=(key,), SEARCH_KEY=key)
            if key == "lcsc":
                self.assertEqual(seen, ["C14663"])
            else:
                self.assertEqual(seen, [], key)
                self.assertIn("(1 skipped without any identifier)", out, key)
                self.assertNotIn("", m.get("parts", {}), key)

    def test_part_with_an_mpn_is_searched_by_every_provider(self):
        ids = ("digikey", "mouser", "lcsc", "element14")
        entries = [{"mpn": "LM358DR", "lcsc": "C14663", "references": ["U1"], "value": "", "type": "ic"}]
        for key in ids:
            seen, out, _ = self._searched(entries, ID_KEYS=ids, KEY_PRIORITY=(key,), SEARCH_KEY=key)
            self.assertEqual(seen, ["LM358DR"], key)
            self.assertIn("(0 skipped without any identifier)", out, key)

    def test_value_derived_mpn_is_searched_by_providers_without_the_parts_number(self):
        ids = ("digikey", "mouser", "lcsc", "element14")
        entries = [{"mpn": "", "value": "AMS1117-3.3", "lib_id": "Regulator_Linear:AMS1117-3.3", "lcsc": "C6186",
                    "references": ["U1"], "type": "ic"}]
        for key in ids:
            seen, out, _ = self._searched(entries, ID_KEYS=ids, KEY_PRIORITY=(key,), SEARCH_KEY=key)
            self.assertEqual(seen, ["C6186" if key == "lcsc" else "AMS1117-3.3"], key)
            self.assertIn("(0 skipped", out, key)


def _row(mpn, refs, **kw):
    return {"mpn": mpn, "references": refs, "value": kw.pop("value", mpn), "type": "ic",
            "manufacturer": "", "description": "", "datasheet": "", **kw}


class RepeatedRows(unittest.TestCase):
    """A part on several BOM rows is one manifest entry, fetched once."""

    def _run(self, rows, parallel=1, seed=None):
        from distributor_core.sync import sync_datasheets
        seen = []

        def one(part, out_dir, index, delay, ctx):
            seen.append(dict(part))
            return {"status": "not_found", "error": "x", "manufacturer": part["manufacturer"],
                    "description": part["description"], "value": part["value"],
                    "references": part["references"], "last_attempt": "t"}
        with tempfile.TemporaryDirectory() as d:
            bom = Path(d) / "bom.json"
            bom.write_text(json.dumps({"bom": rows}), encoding="utf-8")
            out = Path(d) / "out"
            if seed:
                out.mkdir()
                for name, data in seed.items():
                    (out / name).write_bytes(data)
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                r = sync_datasheets(fake_provider(sync_one_part=one), input_path=str(bom),
                                    output_dir=str(out), parallel=parallel)
            m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        return seen, r, m, err.getvalue()

    ROWS = [_row("LM358DR", ["U1"]),
            _row("TL072", ["U2"], description="JFET op amp"),
            _row("LM358DR", ["U3", "U4"], description="Dual op amp", manufacturer="TI",
                 datasheet="https://example.com/lm358.pdf"),
            _row("LM358DR", ["U5"], description="Other text", manufacturer="Other")]

    def test_one_search_references_unioned_first_non_empty_fields(self):
        for par in (1, 2):
            with self.subTest(parallel=par):
                seen, r, m, err = self._run(self.ROWS, parallel=par)
                lm = [p for p in seen if p["_key"] == "LM358DR"]
                self.assertEqual(len(lm), 1)
                self.assertEqual(sorted(p["_key"] for p in seen), ["LM358DR", "TL072"])
                self.assertEqual(lm[0]["references"], ["U1", "U3", "U4", "U5"])
                self.assertEqual((lm[0]["description"], lm[0]["manufacturer"], lm[0]["datasheet"]),
                                 ("Dual op amp", "TI", "https://example.com/lm358.pdf"))
                self.assertEqual(m["parts"]["LM358DR"]["references"], ["U1", "U3", "U4", "U5"])
                self.assertEqual(sorted(m["parts"]), ["LM358DR", "TL072"])
                self.assertEqual((r["failed"], r["total_identified_parts"], r["skipped_no_identifier"]), (2, 2, 0))
                self.assertIn("Found 2 unique parts with part numbers (0 skipped", err)

    def test_present_part_records_every_reference(self):
        ok = {"status": "ok", "file": "LM358DR.pdf", "references": ["U9"], "size_bytes": 4}
        seed = {"manifest.json": json.dumps({"parts": {"LM358DR": ok}}).encode(), "LM358DR.pdf": b"%PDF"}
        seen, r, m, _ = self._run(self.ROWS[:1] + self.ROWS[2:3], seed=seed)
        self.assertEqual(seen, [])
        self.assertEqual(r["already_present"], 1)
        self.assertEqual(m["parts"]["LM358DR"]["references"], ["U1", "U3", "U4"])

    def test_distinct_part_numbers_never_coalesce(self):
        rows = [_row("2N7002", ["Q1"]), _row("2N7002V", ["Q2"]), _row("LM358DR", ["U1"]),
                _row("LM358DRG4", ["U2"]), _row("lm358dr", ["U3"])]
        seen, r, m, _ = self._run(rows)
        self.assertEqual([p["_key"] for p in seen], ["2N7002", "2N7002V", "LM358DR", "LM358DRG4", "lm358dr"])
        self.assertEqual({k: v["references"] for k, v in m["parts"].items()},
                         {"2N7002": ["Q1"], "2N7002V": ["Q2"], "LM358DR": ["U1"], "LM358DRG4": ["U2"],
                          "lm358dr": ["U3"]})

    def test_mpn_from_a_property_row_is_strict(self):
        value_row = {"mpn": "", "value": "LM358", "lib_id": "Amplifier_Operational:LM358",
                     "references": ["U1"], "type": "ic"}
        prop_row = _row("LM358", ["U2"])
        for rows, source in (([value_row, prop_row], ""), ([prop_row, value_row], ""),
                             ([value_row, dict(value_row, references=["U3"])], "value")):
            with self.subTest(source=source, first=rows[0]["references"]):
                seen, _, _, _ = self._run(rows)
                self.assertEqual(len(seen), 1)
                self.assertEqual(seen[0].get("mpn_source", ""), source)


class MachineOutput(unittest.TestCase):
    """Progress goes to stderr; every --json return prints JSON; an error is always reported."""

    def test_nothing_to_do_prints_json(self):
        from distributor_core.sync import sync_datasheets
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            out = d / "out"
            out.mkdir()
            (out / "LM358DR.pdf").write_bytes(b"%PDF")
            (out / "manifest.json").write_text(json.dumps({"parts": {"LM358DR": {
                "status": "ok", "file": "LM358DR.pdf", "references": []}}}), encoding="utf-8")
            mpns = d / "mpns.txt"
            mpns.write_text("LM358DR\n", encoding="utf-8")
            so, se = io.StringIO(), io.StringIO()
            with redirect_stdout(so), redirect_stderr(se):
                r = sync_datasheets(fake_provider(), mpn_list=str(mpns), output_dir=str(out), as_json=True)
        self.assertEqual(json.loads(so.getvalue()), {"downloaded": 0, "already_present": 1, "failed": 0})
        self.assertEqual(r, {"downloaded": 0, "already_present": 1, "failed": 0})
        self.assertIn("All 1 datasheets up to date.", se.getvalue())

    def test_error_return_is_reported(self):
        from distributor_core.sync import sync_datasheets
        for as_json in (False, True):
            with self.subTest(as_json=as_json), tempfile.TemporaryDirectory() as d:
                so, se = io.StringIO(), io.StringIO()
                with redirect_stdout(so), redirect_stderr(se):
                    r = sync_datasheets(fake_provider(preflight=lambda **kw: {"error": "NOKEY"}),
                                        mpn_list=str(Path(d) / "m.txt"), output_dir=str(Path(d) / "o"),
                                        as_json=as_json)
                self.assertEqual(r, {"error": "NOKEY"})
                self.assertEqual(se.getvalue(), "Error: NOKEY\n")
                self.assertEqual(json.loads(so.getvalue()) if as_json else so.getvalue(),
                                 {"error": "NOKEY"} if as_json else "")

    def test_missing_analyzer_json_is_an_error_not_a_traceback(self):
        from distributor_core.sync import sync_datasheets
        with tempfile.TemporaryDirectory() as d:
            se = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(se):
                r = sync_datasheets(fake_provider(), input_path=str(Path(d) / "gone.json"),
                                    output_dir=str(Path(d) / "o"))
        self.assertEqual(r, {"error": "Failed to analyze schematic"})
        self.assertIn("gone.json", se.getvalue())
        self.assertTrue(se.getvalue().endswith("Error: Failed to analyze schematic\n"))

    def test_download_message_is_not_on_stdout(self):
        from distributor_core import download

        def write(url, path):
            with open(path, "wb") as f:
                f.write(b"%PDF-1.4 x")
            return True
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(download, "_resolve", return_value=["93.184.216.34"]), \
                mock.patch.object(download, "_requests", None), \
                mock.patch.object(download, "_sync_playwright", None), \
                mock.patch.object(download, "_download_urllib", write):
            so, se = io.StringIO(), io.StringIO()
            with redirect_stdout(so), redirect_stderr(se):
                self.assertTrue(download.download_pdf("https://example.com/x.pdf", str(Path(d) / "x.pdf")))
        self.assertEqual(so.getvalue(), "")
        self.assertIn("Downloaded 10 bytes via urllib", se.getvalue())

    def test_symlinked_datasheets_refusal_reaches_the_user(self):
        import os, subprocess
        skills = Path(__file__).resolve().parents[2] / "skills"
        env = {k: v for k, v in os.environ.items()
               if k not in ("DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET", "MOUSER_SEARCH_API_KEY")}
        env["ELEMENT14_API_KEY"] = "KEY"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        with tempfile.TemporaryDirectory() as d:
            d = Path(d).resolve()
            (d / "elsewhere").mkdir()
            (d / "datasheets").symlink_to(d / "elsewhere", target_is_directory=True)
            bom = d / "bom.json"
            bom.write_text(json.dumps({"bom": [_row("LM358DR", ["U1"])]}), encoding="utf-8")
            want = f"{d / 'datasheets'} is a symlink; pass --output to write datasheets there"
            for p in ("digikey", "mouser", "lcsc", "element14"):
                for as_json in (False, True):
                    with self.subTest(provider=p, as_json=as_json):
                        cmd = [sys.executable, str(skills / p / "scripts" / f"sync_datasheets_{p}.py"), str(bom)]
                        r = subprocess.run(cmd + (["--json"] if as_json else []), cwd=d, env=env,
                                           capture_output=True, text=True, timeout=60)
                        self.assertEqual(r.returncode, 1)
                        self.assertEqual(r.stderr.splitlines()[-1], f"Error: {want}")
                        self.assertEqual(json.loads(r.stdout) if as_json else r.stdout,
                                         {"error": want} if as_json else "")
                        self.assertEqual(os.listdir(d / "elsewhere"), [])


if __name__ == "__main__":
    unittest.main()
