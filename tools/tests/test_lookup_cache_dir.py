"""Typed datasheet lookups read only the schematic folder's own datasheets/extracted, and
no project-derived cache directory is read through a symlinked datasheets/ or extracted/."""
import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "datasheets" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "spice" / "scripts"))

from schematic.pipeline import _resolve_lookup_paths  # noqa: E402


class LookupCacheDirTest(unittest.TestCase):
    def test_parent_folder_cache_is_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "parent"
            (parent / "datasheets" / "extracted").mkdir(parents=True)
            (parent / "board").mkdir()
            sch = parent / "board" / "x.kicad_sch"
            sch.write_text("", encoding="utf-8")
            self.assertIsNone(_resolve_lookup_paths(sch))

    def test_own_folder_cache_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp) / "board"
            (board / "datasheets" / "extracted").mkdir(parents=True)
            sch = board / "x.kicad_sch"
            sch.write_text("", encoding="utf-8")
            self.assertEqual(_resolve_lookup_paths(sch),
                             board.resolve() / "datasheets" / "extracted")


def _write_cache(ex):
    """An extraction cache for part XA100 that every project-dir reader accepts."""
    ex.mkdir(parents=True, exist_ok=True)
    (ex / "XA100.json").write_text(json.dumps({
        "meta": {"extraction_score": 8},
        "spice_specs": {"gbw_hz": 1000000},
        "recommended_operating_conditions": {"temp_min_c": -40, "temp_max_c": 85},
        "absolute_maximum_ratings": {"vin_max_v": 5},
    }), encoding="utf-8")
    (ex / "manifest.json").write_text(json.dumps(
        {"extractions": {"XA100": {"file": "XA100.json"}}}), encoding="utf-8")


def _derating_vin_max(project_dir):
    """abs_max_vin of the VD-002 finding analyze_voltage_derating gives an XA100 on a 12 V rail."""
    from schematic.system_analyses import analyze_voltage_derating
    ctx = SimpleNamespace(
        components=[{"type": "ic", "reference": "U1", "value": "XA100", "mpn": "XA100",
                     "pins": [{"number": "1"}]}],
        nets={}, pin_net={("U1", "1"): ("+12V", None)},
        is_power_net=lambda n: n == "+12V", is_ground=lambda n: False,
        rail_by_net={}, rail_voltage_or=lambda n, f: 12.0,
        rail_source_fields=lambda *a: {})
    out = analyze_voltage_derating(ctx, {}, project_dir=str(project_dir))
    return [f.get("abs_max_vin") for f in out if f.get("rule_id") == "VD-002"]


@unittest.skipIf(os.name == "nt", "symlinks")
class SymlinkedProjectCacheTest(unittest.TestCase):
    """Every reader that derives the cache from a project folder reads a regular tree and
    ignores one whose datasheets/ or datasheets/extracted/ is a symlink."""

    def _projects(self, tmp):
        real = Path(tmp) / "real"
        _write_cache(real / "datasheets" / "extracted")
        linked_ds = Path(tmp) / "linked_ds"
        linked_ds.mkdir()
        os.symlink(real / "datasheets", linked_ds / "datasheets")
        linked_ex = Path(tmp) / "linked_ex"
        (linked_ex / "datasheets").mkdir(parents=True)
        os.symlink(real / "datasheets" / "extracted", linked_ex / "datasheets" / "extracted")
        return real, (linked_ds, linked_ex)

    def _check(self, read, ok, refused):
        with tempfile.TemporaryDirectory() as tmp:
            real, linked = self._projects(tmp)
            self.assertEqual(read(real), ok)
            for proj in linked:
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(read(proj), refused, proj.name)

    def test_schematic_lookup_dir(self):
        def read(proj):
            sch = proj / "x.kicad_sch"
            sch.write_text("", encoding="utf-8")
            return _resolve_lookup_paths(sch) is not None
        self._check(read, True, False)

    def test_resolve_extract_dir_from_project_dir_and_analysis_json(self):
        import datasheet_extract_cache as dec
        self._check(lambda p: dec.resolve_extract_dir(project_dir=str(p)) is not None, True, False)

        def from_json(p):
            sch = p / "x.kicad_sch"
            sch.write_text("", encoding="utf-8")
            return dec.resolve_extract_dir(analysis_json={"file": str(sch)}) is not None
        self._check(from_json, True, False)

    def test_datasheet_verify_dir(self):
        import datasheet_verify
        self._check(lambda p: bool(datasheet_verify._resolve_extract_dir(str(p))), True, False)

    def test_lifecycle_temperature(self):
        from lifecycle_engine import read_extraction_temperature
        self._check(lambda p: read_extraction_temperature("XA100", str(p)) is not None, True, False)

    def test_spice_spec_fetcher(self):
        from spice_spec_fetcher import fetch_specs_from_extraction
        self._check(lambda p: (fetch_specs_from_extraction("XA100", str(p)) or {}).get("gbw_hz"),
                    1000000, None)

    def test_voltage_derating_abs_max(self):
        self._check(_derating_vin_max, [5], [])


class ManifestFileEscapeTest(unittest.TestCase):
    """A manifest ``file`` value that leaves the extraction cache is a miss for the SPICE spec
    fetcher and the voltage-derating abs-max reader; a plain leaf name is read."""

    def _read_both(self, file_value, linked_sub=False):
        from spice_spec_fetcher import fetch_specs_from_extraction
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside"
            _write_cache(outside)
            proj = Path(tmp) / "proj"
            ex = proj / "datasheets" / "extracted"
            ex.mkdir(parents=True)
            if linked_sub:
                os.symlink(outside, ex / "sub")
            if file_value == "LEAF.json":
                (ex / "LEAF.json").write_bytes((outside / "XA100.json").read_bytes())
            value = str(outside / "XA100.json") if file_value == "ABS" else file_value
            (ex / "manifest.json").write_text(json.dumps(
                {"extractions": {"XA100": {"file": value}}}), encoding="utf-8")
            spice = (fetch_specs_from_extraction("XA100", str(proj)) or {}).get("gbw_hz")
            return spice, _derating_vin_max(proj)

    def test_leaf_name_is_read(self):
        self.assertEqual(self._read_both("LEAF.json"), (1000000, [5]))

    @unittest.skipIf(os.name == "nt", "symlinks")
    def test_dotdot_absolute_and_linked_subdir_are_a_miss(self):
        for value, linked in (("../../../outside/XA100.json", False),
                              ("ABS", False), ("sub/XA100.json", True)):
            with self.subTest(value=value):
                self.assertEqual(self._read_both(value, linked), (None, []))


class MalformedNestedCacheTest(unittest.TestCase):
    """A legacy extraction whose blocks have the wrong JSON type is a miss for every project-dir reader."""
    def test_readers(self):
        from spice_spec_fetcher import fetch_specs_from_extraction
        import analyze_thermal
        cases = ({"meta": "x"}, {"meta": {"extraction_score": "9"}},
                 {"meta": {"extraction_score": 8}, "absolute_maximum_ratings": [1]},
                 {"meta": {"extraction_score": 8}, "absolute_maximum_ratings": {"vin_max_v": "5"}})
        for data in cases:
            for manifest in ({"extractions": {"XA100": {"file": "XA100.json"}}}, {"extractions": []}):
                with self.subTest(data=data, manifest=manifest), tempfile.TemporaryDirectory() as tmp:
                    proj = Path(tmp); ex = proj / "datasheets" / "extracted"; ex.mkdir(parents=True)
                    (ex / "XA100.json").write_text(json.dumps(data), encoding="utf-8")
                    (ex / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.assertIsNone(fetch_specs_from_extraction("XA100", str(proj)))
                        self.assertEqual(_derating_vin_max(proj), [])
                        self.assertEqual(analyze_thermal._get_datasheet_thermal("XA100", str(ex)), {})


if __name__ == "__main__":
    unittest.main()
