# tools/tests/test_cache_reader.py
import contextlib, copy, hashlib, io, json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock
from pathlib import Path
from tools.tests._fixtures import fixture, fixture_path
DS = Path(__file__).resolve().parents[2] / "skills" / "datasheets"
sys.path.insert(0, str(DS))
FX = fixture_path()


PDF = b"%PDF-1.4 fixture\n"


def _plant(tmp, local_path):
    """A project whose LM2596-ADJ cache names local_path; the same PDF bytes sit in datasheets/IN.pdf and outside the project at OUT.pdf."""
    ds = tmp / "proj" / "datasheets"; ex = ds / "extracted"; ex.mkdir(parents=True)
    (ds / "IN.pdf").write_bytes(PDF); (tmp / "OUT.pdf").write_bytes(PDF)
    data = json.loads(fixture("datasheets-extracted", "LM2596-ADJ.json").read_text(encoding="utf-8"))
    data["source"]["local_path"] = local_path(tmp, ds) if callable(local_path) else local_path
    data["source"]["sha256"] = "sha256:" + hashlib.sha256(PDF).hexdigest()
    (ex / "LM2596-ADJ.json").write_text(json.dumps(data), encoding="utf-8")
    return ds, ex


class CachePdfContainment(unittest.TestCase):
    def _ctx(self, local_path):
        from datasheet_types.cache_reader import lookup
        with tempfile.TemporaryDirectory() as d:
            ds, ex = _plant(Path(d), local_path)
            f = lookup("LM2596-ADJ", cache_dir=ex)
            return f.stale, f._cache_context.pdf_path, ds

    def test_inside_paths_are_hashed(self):
        for lp in ("IN.pdf", "datasheets/IN.pdf", lambda t, ds: str(ds / "IN.pdf")):
            stale, pdf, ds = self._ctx(lp)
            self.assertEqual((stale, pdf), (False, ds / "IN.pdf"), lp)

    def test_outside_and_non_string_paths_are_missing(self):
        for lp in ("../../OUT.pdf", lambda t, ds: str(t / "OUT.pdf"), 5):
            stale, pdf, _ = self._ctx(lp)
            self.assertEqual((stale, pdf), (True, None), lp)

    @unittest.skipUnless(os.path.exists("/dev/zero") and hasattr(os, "mkfifo"), "POSIX devices and FIFOs")
    def test_device_and_fifo_end_promptly(self):
        for lp, fifo in (("/dev/zero", False), ("FIFO.pdf", True)):
            with tempfile.TemporaryDirectory() as d:
                ds, ex = _plant(Path(d), lp)
                if fifo:
                    os.mkfifo(ds / "FIFO.pdf")
                code = ("import sys; sys.path.insert(0, %r); from pathlib import Path; "
                        "from datasheet_types.cache_reader import lookup; "
                        "print(lookup('LM2596-ADJ', cache_dir=Path(%r)).stale)") % (str(DS), str(ex))
                out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True,
                                     text=True, timeout=20, check=True).stdout
                self.assertEqual(out.strip(), "True", lp)


DEEP = b"[" * 100000 + b"]" * 100000


class CacheReader(unittest.TestCase):
    def test_lookup_is_a_normal_package_export_without_scripts_on_path(self):
        code = ("import sys, json; from pathlib import PurePath; sys.path.insert(0, %r); import datasheet_types as dt; "
                "print(json.dumps({'lookup': dt.lookup.__module__, 'scripts_on_path': any(PurePath(p).parts[-2:] == ('datasheets', 'scripts') for p in sys.path)}))" % str(DS))
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True).stdout
        d = json.loads(out)
        self.assertEqual(d["lookup"], "datasheet_types.cache_reader")
        self.assertFalse(d["scripts_on_path"])

    def test_feature_fallback_maps_the_mpn_like_the_cache(self):
        sys.path.insert(0, str(DS / "scripts"))
        import datasheet_features as df
        ldo = {"topology": "ldo", "pins": [], "features": {"has_pg": True},
               "extraction_metadata": {"extraction_version": 2, "extraction_score": 9}}
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "outside").mkdir()
            (d / "outside" / "ACME123.json").write_text(json.dumps(ldo), encoding="utf-8")
            ex = d / "proj" / "datasheets" / "extracted"; ex.mkdir(parents=True)
            for mpn in ("../../../outside/ACME123", str(d / "outside" / "ACME123")):
                self.assertIsNone(df.get_regulator_features(mpn, extract_dir=str(ex)), mpn)
            (ex / "LDO.1-A.json").write_text(json.dumps(ldo), encoding="utf-8")
            self.assertIs(df.get_regulator_features("LDO.1-A", extract_dir=str(ex))["has_pg"], True)

    def test_legacy_staleness_hashes_only_inside_datasheets(self):
        sys.path.insert(0, str(DS / "scripts"))
        import datasheet_extract_cache as dec
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); ds = d / "proj" / "datasheets"; ex = ds / "extracted"; ex.mkdir(parents=True)
            (d / "OUT.pdf").write_bytes(b"%PDF other")
            dec.cache_extraction(ex, "P1", {"extraction_metadata": {
                "extraction_score": 9, "source_pdf": "../../OUT.pdf", "source_pdf_hash": "sha256:" + "0" * 64}})
            self.assertEqual(dec.is_extraction_stale(ex, "P1", ds), (False, ""))

    def test_lookup_miss_and_malformed_json_return_none(self):
        from datasheet_types.cache_reader import lookup
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "extracted"; cache.mkdir()
            self.assertIsNone(lookup("NOPE", cache_dir=cache))
            (cache / "X1.json").write_text("{not json", encoding="utf-8")
            self.assertIsNone(lookup("X1", cache_dir=cache))

    def test_real_fixture_without_pdf_is_stale_pdf_missing(self):
        src = fixture("datasheets-extracted", "LM2596-ADJ.json")
        from datasheet_types.cache_reader import lookup, STALE_PDF_MISSING
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "extracted"; cache.mkdir()
            shutil.copy(src, cache / src.name)
            facts = lookup("LM2596-ADJ", cache_dir=cache)
            self.assertIsNotNone(facts)
            self.assertTrue(facts.stale)
            self.assertEqual(facts._cache_context.stale_reason, STALE_PDF_MISSING)
            self.assertEqual(facts._cache_context.cache_path, cache / "LM2596-ADJ.json")

    def test_required_block_set_to_null_is_a_miss(self):
        data = json.loads(fixture("datasheets-extracted", "LM2596-ADJ.json").read_text(encoding="utf-8"))
        for path in (("source",), ("extraction",), ("base",), ("base", "pinout")):
            d = copy.deepcopy(data); tgt = d
            for k in path[:-1]:
                tgt = tgt[k]
            tgt[path[-1]] = None
            self.assertIsNone(self._lookup_bytes(json.dumps(d).encode()), path)

    @staticmethod
    def _lm2596():
        return json.loads(fixture("datasheets-extracted", "LM2596-ADJ.json").read_text(encoding="utf-8"))

    def test_null_list_elements_are_a_miss(self):
        def null_pin(d): d["base"]["pinout"].insert(0, None)
        def null_number(d): d["base"]["pinout"][0]["numbers"] = [None]
        def null_spec(d): d["base"]["absolute_max"]["VIN_max"] = [None]
        for mutate in (null_pin, null_number, null_spec):
            d = self._lm2596(); mutate(d)
            self.assertIsNone(self._lookup_bytes(json.dumps(d).encode()), mutate.__name__)

    def test_non_numeric_spec_value_is_a_miss(self):
        def spec(d): return d["base"]["absolute_max"]["VIN_max"][0]
        def quoted(d): spec(d)["max"] = "36"
        def boolean(d): spec(d)["max"] = True
        def page(d): spec(d)["evidence"]["page"] = "5"
        for mutate in (quoted, boolean, page):
            d = self._lm2596(); mutate(d)
            self.assertIsNone(self._lookup_bytes(json.dumps(d).encode()), mutate.__name__)
        d = self._lm2596(); d["base"]["absolute_max"]["VIN_max"][0]["max"] = 36
        facts = self._lookup_bytes(json.dumps(d).encode())
        self.assertEqual(facts.base.absolute_max["VIN_max"][0].max, 36)

    def test_feature_readers_survive_a_null_pin(self):
        sys.path.insert(0, str(DS / "scripts"))
        import datasheet_features as df
        d = self._lm2596(); d["base"]["pinout"].insert(0, None)
        with tempfile.TemporaryDirectory() as t:
            ex = Path(t) / "datasheets" / "extracted"; ex.mkdir(parents=True)
            (ex / "LM2596-ADJ.json").write_text(json.dumps(d), encoding="utf-8")
            df.get_regulator_features("LM2596-ADJ", extract_dir=ex)
            df.get_pin_function("LM2596-ADJ", "1", extract_dir=ex)

    def test_legacy_view_skips_a_null_pin(self):
        sys.path.insert(0, str(DS / "scripts"))
        import datasheet_verify as dv
        pin = {"numbers": ["1"], "name": "VIN", "type": "power_in"}
        view = dv._legacy_verifier_view({"base": {"pinout": [None, pin]}})
        self.assertEqual(len(view["pins"]), 1)

    def test_analyzer_survives_malformed_cache(self):
        root = Path(__file__).resolve().parents[2]
        sch = Path(__file__).parent / "fixtures" / "datasheet_cache" / "opamp.kicad_sch"
        good = json.loads(fixture("datasheets-extracted", "LM358.json").read_text(encoding="utf-8"))
        def quoted_max(d):
            for specs in d["base"]["absolute_max"].values():
                for sv in specs:
                    sv["max"] = "36"
        def null_pin(d): d["base"]["pinout"].insert(0, None)
        for mutate in (quoted_max, null_pin):
            with self.subTest(mutate=mutate.__name__), tempfile.TemporaryDirectory() as d:
                data = copy.deepcopy(good); mutate(data)
                ex = Path(d) / "datasheets" / "extracted"; ex.mkdir(parents=True)
                (ex / "LM358.json").write_text(json.dumps(data), encoding="utf-8")
                shutil.copy(sch, Path(d) / sch.name)
                r = subprocess.run([sys.executable, "-I", str(root / "skills/kicad/scripts/analyze_schematic.py"),
                                    str(Path(d) / sch.name), "--output", str(Path(d) / "o.json")],
                                   capture_output=True, text=True, cwd=d)
                self.assertEqual(r.returncode, 0, r.stderr[-400:])
                out = json.loads((Path(d) / "o.json").read_text(encoding="utf-8"))
                self.assertNotIn("error", (out.get("datasheet_verification") or {}).get("summary", {}))

    def test_malformed_nested_legacy_cache_is_a_miss(self):
        sys.path.insert(0, str(DS / "scripts"))
        import datasheet_features as df
        meta = {"extraction_version": 2, "extraction_score": 9}
        bad = ({"topology": "ldo", "extraction_metadata": {"extraction_version": "2", "extraction_score": 9}},
               {"topology": "ldo", "extraction_metadata": "x"},
               {"topology": "ldo", "features": [1], "extraction_metadata": meta},
               {"topology": "ldo", "pins": ["x"], "extraction_metadata": meta},
               {"topology": "ldo", "pins": [{"function": "EN", "number": 1, "threshold_high_v": "1.2"}],
                "extraction_metadata": meta},
               {"topology": "mcu", "peripherals": [1], "extraction_metadata": meta},
               {"topology": "mcu", "peripherals": {"usb": "x"}, "extraction_metadata": meta})
        with tempfile.TemporaryDirectory() as d:
            for payload in bad:
                (Path(d) / "P1.json").write_text(json.dumps(payload), encoding="utf-8")
                self.assertIsNone(df.get_regulator_features("P1", extract_dir=d), payload)
                self.assertIsNone(df.get_mcu_features("P1", extract_dir=d), payload)
                self.assertIsNone(df.get_pin_function("P1", "1", extract_dir=d), payload)
            (Path(d) / "P2.json").write_text(json.dumps(
                {"topology": "ldo", "extraction_metadata": {"extraction_version": 1, "extraction_score": 9}}),
                encoding="utf-8")
            q = df.get_regulator_features("P2", extract_dir=d)["quality"]
            self.assertEqual((q["trusted"], q["reasons"]), (False, ["stale_version (1 < 2)"]))

    def test_falsy_wrong_typed_legacy_blocks_keep_their_old_result(self):
        sys.path.insert(0, str(DS / "scripts"))
        import datasheet_features as df
        meta = {"extraction_version": 2, "extraction_score": 9}
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "P1.json").write_text(json.dumps(
                {"topology": "ldo", "extraction_metadata": {"extraction_version": None, "extraction_score": 9}}),
                encoding="utf-8")
            q = df.get_regulator_features("P1", extract_dir=d)["quality"]
            self.assertEqual((q["trusted"], q["reasons"]), (False, ["stale_version (0 < 2)"]))
            for blk in ({"features": []}, {"features": ""}, {"pins": {}}, {"peripherals": []}, {"peripherals": {"usb": ""}}):
                (Path(d) / "P2.json").write_text(json.dumps(
                    dict(blk, topology="ldo", extraction_metadata=meta)), encoding="utf-8")
                self.assertIsNotNone(df.get_regulator_features("P2", extract_dir=d), blk)

    def test_verify_trust_gate_tolerates_non_dict_quality_blocks(self):
        sys.path.insert(0, str(DS / "scripts"))
        import datasheet_verify as dv
        for ext in ({"extraction_metadata": [1]}, {"meta": "x"}, {"extraction": "x", "meta": {"extraction_score": 3}}):
            dv._passes_trust_gate(ext)
        self.assertTrue(dv._passes_trust_gate({"extraction_metadata": "x", "meta": {"extraction_score": 7}}))
        self.assertFalse(dv._passes_trust_gate({"extraction_metadata": [1], "meta": {"extraction_score": 3}}))
        for blk in ("x", [1]):
            self.assertEqual(dv._quality_finding(
                "P1", {"extraction": blk, "meta": {"extraction_score": 3}})["quality_score"], 3)

    def test_legacy_staleness_with_malformed_metadata_is_stale(self):
        sys.path.insert(0, str(DS / "scripts"))
        import datasheet_extract_cache as dec
        with tempfile.TemporaryDirectory() as d:
            for i, meta in enumerate(({"extraction_version": "2"}, {"extraction_score": "9"}, {"retry_count": None})):
                dec.cache_extraction(Path(d), f"P{i}", {"extraction_metadata": dict(meta)})
                self.assertEqual(dec.is_extraction_stale(Path(d), f"P{i}"), (True, "malformed extraction_metadata"), meta)

    def _lookup_bytes(self, payload):
        from datasheet_types.cache_reader import lookup
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "extracted"; cache.mkdir()
            (cache / "P1.json").write_bytes(payload)
            return lookup("P1", cache_dir=cache)

    def test_null_list_utf16_and_latin1_caches_are_a_miss(self):
        for payload in (b"null", b"[]", b"\xff\xfe{", b'{"a": "\xe9"}', DEEP):
            self.assertIsNone(self._lookup_bytes(payload), payload[:20])

    @unittest.skipIf(os.name == "nt", "symlinks")
    def test_symlinked_and_oversized_caches_are_a_miss(self):
        from datasheet_types import cache_reader
        src = fixture("datasheets-extracted", "LM2596-ADJ.json")
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "extracted"; cache.mkdir()
            shutil.copy(src, cache / "REAL.json")
            os.symlink(cache / "REAL.json", cache / "P1.json")
            self.assertIsNone(cache_reader.lookup("P1", cache_dir=cache))
            shutil.copy(src, cache / "P2.json")
            old = cache_reader.MAX_CACHE_BYTES
            cache_reader.MAX_CACHE_BYTES = 10
            try:
                self.assertIsNone(cache_reader.lookup("P2", cache_dir=cache))
            finally:
                cache_reader.MAX_CACHE_BYTES = old
            self.assertIsNotNone(cache_reader.lookup("P2", cache_dir=cache))

    def test_valid_cache_still_returns_facts(self):
        src = fixture("datasheets-extracted", "LM2596-ADJ.json")
        self.assertIsNotNone(self._lookup_bytes(src.read_bytes()))

    def test_partial_body_mm_round_trips_without_null_dims(self):
        from datasheet_types.codec import to_dict
        data = json.loads(fixture("datasheets-extracted", "LM2596-ADJ.json").read_text(encoding="utf-8"))
        data["base"]["package"]["body_mm"] = {"length": 5.0, "width": 4.0}
        facts = self._lookup_bytes(json.dumps(data).encode())
        self.assertIsNotNone(facts)
        self.assertEqual(to_dict(facts)["base"]["package"]["body_mm"], {"length": 5.0, "width": 4.0})

    def test_cache_manager_leaf_only_manifest_and_non_utf8_manifest(self):
        sys.path.insert(0, str(DS / "scripts"))
        import datasheet_extract_cache as dec
        with tempfile.TemporaryDirectory() as d:
            ex = Path(d) / "extracted"; ex.mkdir()
            (Path(d) / "secret.json").write_text('{"x": 1}', encoding="utf-8")
            (ex / "manifest.json").write_text(json.dumps(
                {"extractions": {dec._sanitize_mpn("P1"): {"file": "../secret.json"},
                                 dec._sanitize_mpn("P2"): {"file": "P2.json"}}}), encoding="utf-8")
            (ex / "P2.json").write_text('{"ok": 1}', encoding="utf-8")
            self.assertIsNone(dec.get_cached_extraction(ex, "P1"))
            self.assertEqual(dec.get_cached_extraction(ex, "P2"), {"ok": 1})
        with tempfile.TemporaryDirectory() as d:
            ex = Path(d) / "extracted"; ex.mkdir()
            (ex / "manifest.json").write_bytes(b'{"extractions": {"P1": "\xe9"}}')
            self.assertEqual(dec._load_index(ex)["extractions"], {})

    def test_manifest_writes_leave_no_temp_files_and_use_unique_names(self):
        sys.path.insert(0, str(DS / "scripts"))
        import datasheet_extract_cache as dec
        with tempfile.TemporaryDirectory() as d:
            ex = Path(d) / "extracted"
            dec.cache_extraction(ex, "P1", {"extraction_metadata": {}})
            self.assertEqual([p.name for p in ex.iterdir() if p.name.endswith(".tmp")], [])
            # a stale fixed-name temp file must not be reused or clobbered
            (ex / "manifest.tmp").write_text("keep", encoding="utf-8")
            dec.cache_extraction(ex, "P2", {"extraction_metadata": {}})
            self.assertEqual((ex / "manifest.tmp").read_text(encoding="utf-8"), "keep")

    def test_unreadable_cache_does_not_stop_the_schematic_analyzer(self):
        root = Path(__file__).resolve().parents[2]
        sch = Path(__file__).parent / "fixtures" / "datasheet_cache" / "opamp.kicad_sch"
        for payload in (b"null", b"[1]", b'"x"', b"7", b"\xff\xfe{", b'{"a": "\xe9"}'):
            with self.subTest(payload=payload[:30]), tempfile.TemporaryDirectory() as d:
                ex = Path(d) / "datasheets" / "extracted"; ex.mkdir(parents=True)
                (ex / "LM358.json").write_bytes(payload)
                shutil.copy(sch, Path(d) / sch.name)
                r = subprocess.run([sys.executable, "-I", str(root / "skills/kicad/scripts/analyze_schematic.py"),
                                    str(Path(d) / sch.name), "--output", str(Path(d) / "o.json")],
                                   capture_output=True, text=True, cwd=d)
                self.assertEqual(r.returncode, 0, r.stderr[-400:])

    def test_feature_helpers_treat_non_object_direct_file_as_a_miss(self):
        sys.path.insert(0, str(DS / "scripts"))
        import datasheet_features as df
        for payload in (b"[1]", b'"x"', b"7", b"null"):
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / "P1.json").write_bytes(payload)
                self.assertIsNone(df.get_regulator_features("P1", extract_dir=d), payload)
                self.assertIsNone(df.get_mcu_features("P1", extract_dir=d), payload)
                self.assertIsNone(df.get_pin_function("P1", "1", extract_dir=d), payload)

    @unittest.skipIf(os.name == "nt", "POSIX modes")
    def test_manifest_and_extraction_files_keep_or_get_umask_modes(self):
        sys.path.insert(0, str(DS / "scripts"))
        import datasheet_extract_cache as dec
        from distributor_core import manifest as dm
        old_default = dm.DEFAULT_FILE_MODE
        dm.DEFAULT_FILE_MODE = 0o644
        try:
            with tempfile.TemporaryDirectory() as d:
                ex = Path(d) / "extracted"
                dec.cache_extraction(ex, "P1", {"extraction_metadata": {}})
                self.assertEqual((ex / "manifest.json").stat().st_mode & 0o777, 0o644)
                os.chmod(ex / "manifest.json", 0o640)
                dec.cache_extraction(ex, "P2", {"extraction_metadata": {}})
                self.assertEqual((ex / "manifest.json").stat().st_mode & 0o777, 0o640)
                dm.save_index(Path(d) / "manifest.json", {"parts": {}})
                self.assertEqual((Path(d) / "manifest.json").stat().st_mode & 0o777, 0o644)
                os.chmod(Path(d) / "manifest.json", 0o600)
                dm.save_index(Path(d) / "manifest.json", {"parts": {}})
                self.assertEqual((Path(d) / "manifest.json").stat().st_mode & 0o777, 0o600)
        finally:
            dm.DEFAULT_FILE_MODE = old_default

    def test_unreadable_manifest_is_never_overwritten(self):
        sys.path.insert(0, str(DS / "scripts"))
        import datasheet_extract_cache as dec
        for payload in (b'{"extractions": {"A": "\xe9"}}', b"{broken", b"[1]",
                        b'{"extractions": ' + DEEP + b"}"):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as d:
                ex = Path(d) / "extracted"; ex.mkdir()
                (ex / "manifest.json").write_bytes(payload)
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    dec.cache_extraction(ex, "P1", {"extraction_metadata": {}})
                self.assertEqual((ex / "manifest.json").read_bytes(), payload)
                self.assertIn("manifest.json", err.getvalue())
                self.assertEqual(len([p for p in ex.iterdir() if p.suffix == ".json" and p.name != "manifest.json"]), 1)
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "manifest.json").write_bytes(b'{"parts": {"P1": {}}, "x": "\xe9"}')
            before = (Path(d) / "manifest.json").read_bytes()
            with contextlib.redirect_stderr(io.StringIO()) as err:
                dec.update_datasheets_index(d, "P1", {"extraction_metadata": {}})
            self.assertEqual((Path(d) / "manifest.json").read_bytes(), before)
            self.assertIn("manifest.json", err.getvalue())

    def test_manifest_file_with_backslash_is_a_miss(self):
        sys.path.insert(0, str(DS / "scripts"))
        import datasheet_extract_cache as dec
        with tempfile.TemporaryDirectory() as d:
            ex = Path(d) / "extracted"; ex.mkdir()
            (ex / "sub").mkdir()  # on Windows the backslash name resolves into sub/, so the file exists there
            (ex / "sub\\x.json").write_text('{"ok": 1}', encoding="utf-8")
            (ex / "manifest.json").write_text(json.dumps(
                {"extractions": {dec._sanitize_mpn("P1"): {"file": "sub\\x.json"}}}), encoding="utf-8")
            self.assertIsNone(dec.get_cached_extraction(ex, "P1"))


class _NoNofollowOs:
    """``os`` as on Windows, where ``O_NOFOLLOW`` does not exist."""
    def __getattr__(self, name):
        if name == "O_NOFOLLOW":
            raise AttributeError(name)
        return getattr(os, name)


class CacheReadLinksAndPipes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        (self.d / "ok.json").write_text('{"a": 1}', encoding="utf-8")
        (self.d / "secret.json").write_text('{"secret": 1}', encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    @unittest.skipIf(os.name == "nt", "FIFOs")
    def test_fifo_returns_none_promptly(self):
        fifo = self.d / "fifo.json"
        os.mkfifo(fifo)
        code = ("import sys; sys.path.insert(0, %r); from datasheet_types.cache_reader import read_json_object; "
                "print(read_json_object(%r))" % (str(DS), str(fifo)))
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                             timeout=20, check=True).stdout
        self.assertEqual(out.strip(), "None")

    def _swap_before_open(self, cache_reader, target):
        """Patch the reader so ``target`` becomes a link to secret.json after any check, just
        before the file is opened."""
        real_open, real_getsize = os.open, os.path.getsize

        def swap():
            if not target.is_symlink():
                target.unlink()
                os.symlink(self.d / "secret.json", target)

        def fake_open(path, *a, **k):
            if Path(path) == target:
                swap()
            return real_open(path, *a, **k)

        def fake_getsize(path):
            n = real_getsize(path)
            if Path(path) == target:
                swap()
            return n
        return (mock.patch.object(cache_reader.os, "open", fake_open),
                mock.patch.object(cache_reader.os.path, "getsize", fake_getsize))

    @unittest.skipIf(os.name == "nt", "symlinks")
    def test_link_swapped_in_after_the_check_is_refused(self):
        from datasheet_types import cache_reader
        target = self.d / "ok.json"
        p1, p2 = self._swap_before_open(cache_reader, target)
        with p1, p2:
            self.assertIsNone(cache_reader.read_json_object(target))
        self.assertTrue(target.is_symlink())

    def test_without_o_nofollow_a_regular_file_still_reads(self):
        from datasheet_types import cache_reader
        with mock.patch.object(cache_reader, "os", _NoNofollowOs()):
            self.assertEqual(cache_reader.read_json_object(self.d / "ok.json"), {"a": 1})

    @unittest.skipIf(os.name == "nt", "symlinks")
    def test_without_o_nofollow_a_link_and_a_swap_are_refused(self):
        from datasheet_types import cache_reader
        os.symlink(self.d / "secret.json", self.d / "link.json")
        with mock.patch.object(cache_reader, "os", _NoNofollowOs()):
            self.assertIsNone(cache_reader.read_json_object(self.d / "link.json"))
        target = self.d / "ok.json"
        p1, p2 = self._swap_before_open(cache_reader, target)
        with p1, p2, mock.patch.object(cache_reader, "os", _NoNofollowOs()):
            self.assertIsNone(cache_reader.read_json_object(target))

    @unittest.skipIf(os.name == "nt", "symlinks")
    def test_safe_extract_dir_refuses_a_symlinked_datasheets_or_extracted(self):
        from datasheet_types.cache_reader import safe_extract_dir
        real = self.d / "proj" / "datasheets" / "extracted"
        real.mkdir(parents=True)
        self.assertEqual(safe_extract_dir(real), real)
        (self.d / "a").mkdir()
        os.symlink(self.d / "proj" / "datasheets", self.d / "a" / "datasheets")
        (self.d / "b" / "datasheets").mkdir(parents=True)
        os.symlink(real, self.d / "b" / "datasheets" / "extracted")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertIsNone(safe_extract_dir(self.d / "a" / "datasheets" / "extracted"))
            self.assertIsNone(safe_extract_dir(self.d / "b" / "datasheets" / "extracted"))
        self.assertIn("symlink", err.getvalue())

    @unittest.skipIf(os.name == "nt", "symlinks")
    def test_explicit_extract_dir_that_is_a_symlink_is_followed(self):
        import datasheet_extract_cache as dec
        from datasheet_types.cache_reader import lookup
        real = self.d / "shared"
        real.mkdir()
        shutil.copy(fixture("datasheets-extracted", "LM2596-ADJ.json"), real / "LM2596-ADJ.json")
        link = self.d / "mine"
        os.symlink(real, link)
        self.assertEqual(dec.resolve_extract_dir(override_dir=str(link)), link)
        self.assertIsNotNone(lookup("LM2596-ADJ", cache_dir=link))


if __name__ == "__main__":
    unittest.main()
