# tools/tests/test_cache_reader.py
import contextlib, io, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from tools.tests._fixtures import fixture, fixture_path
DS = Path(__file__).resolve().parents[2] / "skills" / "datasheets"
sys.path.insert(0, str(DS))
FX = fixture_path()


class CacheReader(unittest.TestCase):
    def test_lookup_is_a_normal_package_export_without_scripts_on_path(self):
        code = ("import sys, json; from pathlib import PurePath; sys.path.insert(0, %r); import datasheet_types as dt; "
                "print(json.dumps({'lookup': dt.lookup.__module__, 'scripts_on_path': any(PurePath(p).parts[-2:] == ('datasheets', 'scripts') for p in sys.path)}))" % str(DS))
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True).stdout
        d = json.loads(out)
        self.assertEqual(d["lookup"], "datasheet_types.cache_reader")
        self.assertFalse(d["scripts_on_path"])

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

    def _lookup_bytes(self, payload):
        from datasheet_types.cache_reader import lookup
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "extracted"; cache.mkdir()
            (cache / "P1.json").write_bytes(payload)
            return lookup("P1", cache_dir=cache)

    def test_null_list_utf16_and_latin1_caches_are_a_miss(self):
        for payload in (b"null", b"[]", b"\xff\xfe{", b'{"a": "\xe9"}'):
            self.assertIsNone(self._lookup_bytes(payload), payload)

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
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as d:
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
        for payload in (b'{"extractions": {"A": "\xe9"}}', b"{broken", b"[1]"):
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
            (ex / "sub\\x.json").write_text('{"ok": 1}', encoding="utf-8")
            (ex / "manifest.json").write_text(json.dumps(
                {"extractions": {dec._sanitize_mpn("P1"): {"file": "sub\\x.json"}}}), encoding="utf-8")
            self.assertIsNone(dec.get_cached_extraction(ex, "P1"))


if __name__ == "__main__":
    unittest.main()
