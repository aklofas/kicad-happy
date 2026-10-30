"""Lifecycle audit finds the project from the analysis inputs and reads the
operating temperature range from the project's datasheet extractions (v2
SpecValue shape and the older flat shape); a malformed extraction is skipped
with one warning instead of a traceback."""
import contextlib, io, json, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
SPICE = ROOT / "skills" / "spice" / "scripts"
for p in (SCRIPTS, SPICE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import lifecycle_audit  # noqa: E402
from kicad_core import project as kproject  # noqa: E402
from tools.tests._fixtures import fixture  # noqa: E402

NAMES = ("lcsc", "digikey", "element14", "mouser")


def patched_queries(**replies):
    stack = contextlib.ExitStack()
    for n in NAMES:
        r = replies.get(n)
        stack.enter_context(mock.patch.object(
            lifecycle_audit, f"query_lifecycle_{n}",
            lambda mpn, r=r: dict(r) if r is not None else None))
    return stack


def spec(lo, hi, unit="°C", condition=None):
    return {"min": lo, "typ": None, "max": hi, "unit": unit, "condition": condition,
            "notes": None, "evidence": {"page": 1, "method": "table", "confidence": "high"}}


def v2(recommended=None, absolute=None):
    return {"base": {"recommended_operating": recommended or {},
                     "absolute_max": absolute or {}}}


class ProjectDirHelperTest(unittest.TestCase):
    def test_source_files_and_file(self):
        f = kproject.project_dir_from_analysis
        self.assertEqual(f({"inputs": {"source_files": ["/x/proj/board.kicad_sch"]}}), Path("/x/proj"))
        self.assertEqual(f({"file": "/p/a.kicad_sch",
                            "inputs": {"source_files": ["/x/proj/b.kicad_sch"]}}), Path("/p"))
        for a in ({}, None, [], {"inputs": None}, {"file": None, "inputs": {"source_files": []}}):
            self.assertIsNone(f(a))

    def test_spice_cache_uses_the_same_helper(self):
        import spice_model_cache
        self.assertIs(spice_model_cache.project_dir_from_analysis, kproject.project_dir_from_analysis)


class ExtractionTemperatureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.ext = self.tmp / "datasheets" / "extracted"
        self.ext.mkdir(parents=True)

    def read(self, mpn):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            got = lifecycle_audit.read_extraction_temperature(mpn, str(self.tmp))
        return got, err.getvalue()

    def test_v2_ta_in_recommended_operating(self):
        (self.ext / "LM2596-ADJ.json").write_text(json.dumps(v2(
            {"TA": [spec(-40, 125, condition="Operating ambient temperature")]},
            {"TJ_max": [spec(None, 150)], "Tstg": [spec(-65, 150)]})), encoding="utf-8")
        got, _ = self.read("LM2596-ADJ")
        self.assertEqual(got, {"temp_min_c": -40.0, "temp_max_c": 125.0, "source": "extraction_cache"})

    def test_v2_via_manifest(self):
        sys.path.insert(0, str(ROOT / "skills" / "datasheets" / "scripts"))
        import datasheet_extract_cache
        datasheet_extract_cache.cache_extraction(
            self.ext, "STM32F103C8T6",
            v2({"TA": [spec(-40.0, 85.0, condition="Ambient temperature, suffix-6")]}))
        self.assertFalse((self.ext / "STM32F103C8T6.json").exists())
        got, _ = self.read("STM32F103C8T6")
        self.assertEqual((got["temp_min_c"], got["temp_max_c"]), (-40.0, 85.0))

    def test_v2_topr_in_absolute_max(self):
        (self.ext / "LM358.json").write_text(json.dumps(v2(
            None, {"TJ_max": [spec(None, 150)], "TOPR": [spec(0, 70)],
                   "TSTG": [spec(-65, 150)]})), encoding="utf-8")
        got, _ = self.read("LM358")
        self.assertEqual((got["temp_min_c"], got["temp_max_c"]), (0.0, 70.0))

    def test_junction_only_gives_nothing(self):
        (self.ext / "MBRS540T3G.json").write_text(json.dumps(v2(
            None, {"TJ": [spec(-65, 150, condition="Operating Junction Temperature")],
                   "Tstg": [spec(-65, 150, condition="Storage Temperature Range")]})),
            encoding="utf-8")
        self.assertEqual(self.read("MBRS540T3G"), (None, ""))
        (self.ext / "IRLML6344.json").write_text(json.dumps(v2(
            {"T_junction": [spec(-55, 150, condition="Operating junction temperature")]})),
            encoding="utf-8")
        self.assertEqual(self.read("IRLML6344"), (None, ""))

    def test_condition_fallback(self):
        (self.ext / "P2.json").write_text(json.dumps(v2({
            "T_op_stg": [spec(-55, 150, condition="Operating and storage temperature")],
            "T_range": [spec(-20, 70, condition="Operating ambient temperature")]})),
            encoding="utf-8")
        got, _ = self.read("P2")
        self.assertEqual((got["temp_min_c"], got["temp_max_c"]), (-20.0, 70.0))

    def put(self, name, ext):
        (self.ext / f"{name}.json").write_text(json.dumps(ext), encoding="utf-8")
        got, err = self.read(name)
        return (got["temp_min_c"], got["temp_max_c"]) if got else None

    def test_operating_rating_beats_absolute_max_ta(self):
        # A: a stress "ambient under bias" range must not hide the -40..85 operating rating
        self.assertEqual(self.put("A", v2(
            {"T_range": [spec(-40, 85, condition="Operating ambient temperature")]},
            {"TA": [spec(-55, 125, condition="Ambient temperature under bias")]})), (-40.0, 85.0))

    def test_one_bound_rating_does_not_fall_through(self):
        # E: recommended T_A with only a max is unusable; the wider absolute-max range is not read
        self.assertIsNone(self.put("E", v2(
            {"T_A": [spec(None, 85)]}, {"TOPR": [spec(-40, 125)]})))

    def test_one_bound_entry_is_skipped_within_recommended(self):
        self.assertEqual(self.put("H1", v2(
            {"TA": [spec(None, 85)], "T_OPERATING": [spec(-40, 85)]})), (-40.0, 85.0))
        self.assertEqual(self.put("H2", v2(
            {"TA": [spec(None, 85, condition="commercial"),
                    spec(-40, 85, condition="industrial")]})), (-40.0, 85.0))

    def test_case_style_is_not_a_case_temperature(self):
        self.assertEqual(self.put("K", v2(
            {"T_range": [spec(-40, 85, condition="Operating ambient temperature, case style SOT-23")]})),
            (-40.0, 85.0))
        self.assertIsNone(self.put("K2", v2(
            {"T_range": [spec(-40, 125, condition="Operating case temperature")]})))

    def test_absolute_max_ta_alone_is_not_read(self):
        self.assertIsNone(self.put("B", v2(None, {"TA": [spec(-55, 125)]})))
        self.assertIsNone(self.put("B2", v2(None, {"T_A": [spec(-55, 125)], "T_AMB": [spec(-55, 125)]})))

    def test_junction_storage_case_conditions_rejected_under_any_key(self):
        cases = {
            "G": v2({"T_OPERATING": [spec(-40, 150, condition="Operating junction temperature")]}),
            "I": v2(None, {"T_operating": [spec(-55, 150, condition="Operating and storage temperature")]}),
            "F": v2({"TA": [spec(-40, 150, condition="Junction temperature")]}),
            "C": v2({"TC": [spec(-40, 125, condition="Operating case temperature")]}),
        }
        for name, ext in cases.items():
            self.assertIsNone(self.put(name, ext), name)

    def test_list_extractions_in_manifest(self):
        (self.ext / "manifest.json").write_text('{"extractions": []}', encoding="utf-8")
        (self.ext / "LM358DR.json").write_text(json.dumps(
            {"recommended_operating_conditions": {"temp_min_c": -40, "temp_max_c": 125}}),
            encoding="utf-8")
        got, err = self.read("LM358DR")
        self.assertEqual((got["temp_min_c"], got["temp_max_c"]), (-40, 125))
        self.assertNotIn("Traceback", err)

    def test_fahrenheit_is_not_celsius(self):
        (self.ext / "P1.json").write_text(json.dumps(v2({"TA": [spec(-40, 185, unit="°F")]})),
                                          encoding="utf-8")
        self.assertEqual(self.read("P1"), (None, ""))

    def test_v1_flat_shape_still_read(self):
        (self.ext / "LM358DR.json").write_text(json.dumps(
            {"recommended_operating_conditions": {"temp_min_c": -40, "temp_max_c": 125}}),
            encoding="utf-8")
        got, _ = self.read("LM358DR")
        self.assertEqual((got["temp_min_c"], got["temp_max_c"]), (-40, 125))

    def test_v1_name_with_slash(self):
        (self.ext / "AB_12.json").write_text(json.dumps(
            {"recommended_operating_conditions": {"temp_min_c": 0, "temp_max_c": 70}}),
            encoding="utf-8")
        got, _ = self.read("AB/12")
        self.assertEqual((got["temp_min_c"], got["temp_max_c"]), (0, 70))

    def test_malformed_extractions_warn_once(self):
        for body in ("null", "[]", '{"recommended_operating_conditions": []}', "{not json"):
            (self.ext / "LM358DR.json").write_text(body, encoding="utf-8")
            got, err = self.read("LM358DR")
            self.assertIsNone(got, body)
            self.assertEqual(err.count("Warning:"), 1, (body, err))
            self.assertNotIn("Traceback", err)

    def test_no_project_dir_reads_nothing(self):
        with mock.patch.object(Path, "exists", side_effect=AssertionError("cache read")), \
                mock.patch.object(Path, "is_file", side_effect=AssertionError("cache read")):
            self.assertIsNone(lifecycle_audit.read_extraction_temperature("LM358DR", None))
            self.assertIsNone(lifecycle_audit.read_extraction_temperature("LM358DR", ""))


class HarnessExtractionsTest(unittest.TestCase):
    """The harness's real v2 extractions: four of six carry an ambient range."""

    def test_fixture_extractions(self):
        src = fixture("datasheets-extracted")
        want = {"ABM8G-106-12.000MHZ-T": (-40.0, 85.0), "IRLML6344": None,
                "LM2596-ADJ": (-40.0, 125.0), "LM358": (0.0, 70.0),
                "MBRS540T3G": None, "STM32F103C8T6": (-40.0, 85.0)}
        with tempfile.TemporaryDirectory() as d:
            ext = Path(d) / "datasheets" / "extracted"
            ext.mkdir(parents=True)
            for m in want:
                shutil.copy(Path(src) / f"{m}.json", ext / f"{m}.json")
            for m, w in want.items():
                got = lifecycle_audit.read_extraction_temperature(m, d)
                self.assertEqual(got and (got["temp_min_c"], got["temp_max_c"]), w, m)


class CliProjectDirTest(unittest.TestCase):
    """analysis/<run>/schematic.json names its schematic only in inputs.source_files."""

    def run_cli(self, analysis, extraction):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        run = tmp / "analysis" / "run1"
        run.mkdir(parents=True)
        ext = tmp / "datasheets" / "extracted"
        ext.mkdir(parents=True)
        (ext / "LM358DR.json").write_text(json.dumps(extraction), encoding="utf-8")
        if analysis is None:
            analysis = {"inputs": {"source_files": [str(tmp / "board.kicad_sch")]}}
        analysis["bom"] = [{"references": ["U1"], "mpn": "LM358DR", "type": "ic"}]
        (run / "schematic.json").write_text(json.dumps(analysis), encoding="utf-8")
        out = tmp / "out.json"
        with patched_queries(digikey={"status": "Active", "temp_min_c": 0.0, "temp_max_c": 70.0}), \
                contextlib.redirect_stderr(io.StringIO()):
            rc = lifecycle_audit.main([str(run / "schematic.json"), "--temp-range", "automotive",
                                       "--only", "digikey", "--delay", "0", "--output", str(out)])
        r = json.loads(out.read_text(encoding="utf-8"))
        return rc, r

    def test_extraction_beside_the_schematic_is_read(self):
        # automotive = -40..125; the datasheet range -40..125 meets it, the API's 0..70 does not
        rc, r = self.run_cli(None, {"recommended_operating_conditions": {"temp_min_c": -40, "temp_max_c": 125}})
        self.assertIn(rc, (0, None))
        self.assertEqual([f for f in r["findings"] if f["rule_id"] == "LT-001"], [])
        self.assertEqual(r["temperature_summary"]["components_meeting_spec"], 1)

    def test_null_extraction_falls_back_to_the_api(self):
        rc, r = self.run_cli(None, None)
        lt = [f for f in r["findings"] if f["rule_id"] == "LT-001"]
        self.assertEqual([(f["component_range"], f["evidence_source"]) for f in lt],
                         [({"min_c": 0.0, "max_c": 70.0}, "api_lookup")])

    def test_analysis_naming_no_source_reads_no_extraction(self):
        rc, r = self.run_cli({}, {"recommended_operating_conditions": {"temp_min_c": -40, "temp_max_c": 125}})
        lt = [f for f in r["findings"] if f["rule_id"] == "LT-001"]
        self.assertEqual([f["evidence_source"] for f in lt], ["api_lookup"])

    def test_cache_beside_a_json_naming_no_source_is_not_read(self):
        # A JSON in a shared folder (e.g. /tmp) next to a planted datasheets/extracted.
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        ext = tmp / "datasheets" / "extracted"
        ext.mkdir(parents=True)
        (ext / "LM358DR.json").write_text(json.dumps(
            {"recommended_operating_conditions": {"temp_min_c": -40, "temp_max_c": 125}}), encoding="utf-8")
        (tmp / "schematic.json").write_text(json.dumps(
            {"bom": [{"references": ["U1"], "mpn": "LM358DR", "type": "ic"}]}), encoding="utf-8")
        out = tmp / "out.json"
        with patched_queries(digikey={"status": "Active", "temp_min_c": 0.0, "temp_max_c": 70.0}), \
                mock.patch.object(lifecycle_audit, "read_extraction_temperature",
                                  side_effect=AssertionError("extraction read")), \
                contextlib.redirect_stderr(io.StringIO()):
            lifecycle_audit.main([str(tmp / "schematic.json"), "--temp-range", "automotive",
                                  "--only", "digikey", "--delay", "0", "--output", str(out)])
        r = json.loads(out.read_text(encoding="utf-8"))
        lt = [f for f in r["findings"] if f["rule_id"] == "LT-001"]
        self.assertEqual([(f["component_range"], f["evidence_source"]) for f in lt],
                         [({"min_c": 0.0, "max_c": 70.0}, "api_lookup")])


class ListManifestCliTest(unittest.TestCase):
    def test_cli_with_list_extractions_manifest(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        ext = tmp / "datasheets" / "extracted"
        ext.mkdir(parents=True)
        (ext / "manifest.json").write_text('{"extractions": []}', encoding="utf-8")
        sch = tmp / "schematic.json"
        sch.write_text(json.dumps({"inputs": {"source_files": [str(tmp / "b.kicad_sch")]},
                                   "bom": [{"references": ["U1"], "mpn": "LM358DR"}]}),
                       encoding="utf-8")
        out, err = tmp / "o.json", io.StringIO()
        with patched_queries(digikey={"status": "Active"}), contextlib.redirect_stderr(err):
            lifecycle_audit.main([str(sch), "--only", "digikey", "--delay", "0", "--output", str(out)])
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["components_checked"], 1)
        self.assertNotIn("Traceback", err.getvalue())


class PipelineLifecycleTest(unittest.TestCase):
    def finalize(self, project_dir):
        from schematic.pipeline import finalize_for_cli
        result = {"bom": [{"references": ["U1"], "mpn": "LM358DR", "type": "ic"}], "findings": []}
        with patched_queries(digikey={"status": "Active"}), \
                mock.patch.object(lifecycle_audit.time, "sleep", lambda s: None), \
                contextlib.redirect_stderr(io.StringIO()):
            finalize_for_cli(result, {}, schematic_path=str(Path(project_dir) / "board.kicad_sch"),
                             lifecycle=True, stage=None, audience=None)
        return result

    def test_null_extraction_does_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            ext = Path(d) / "datasheets" / "extracted"
            ext.mkdir(parents=True)
            (ext / "LM358DR.json").write_text("null", encoding="utf-8")
            result = self.finalize(d)
        self.assertEqual(result["lifecycle_audit"]["components_checked"], 1)

    def test_attribute_error_degrades_to_lc007(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(lifecycle_audit, "audit_bom", side_effect=AttributeError("boom")):
            result = self.finalize(d)
        lc7 = [f for f in result["findings"] if f.get("rule_id") == "LC-007"]
        self.assertEqual(len(lc7), 1)
        self.assertIn("AttributeError", json.dumps(lc7[0]))


class TempStringCarryTest(unittest.TestCase):
    def test_swapped_range_is_sorted(self):
        self.assertEqual(lifecycle_audit._parse_temp_range("85 ~ -40"), (-40, 85))
        self.assertEqual(lifecycle_audit._parse_temp_range("125°C ~ -40°C"), (-40, 125))

    def test_fahrenheit_and_ellipsis_are_not_read(self):
        self.assertIsNone(lifecycle_audit._parse_temp_range("-40 ~ 185°F"))
        self.assertIsNone(lifecycle_audit._parse_temp_range("-40 ~ 185 °F"))
        self.assertIsNone(lifecycle_audit._parse_temp_range("−40…+85"))

    def test_swapped_range_invents_no_cold_shortfall(self):
        analysis = {"bom": [{"mpn": "ABC12345", "references": ["U1"]}]}
        rng = lifecycle_audit._parse_temp_range("85 ~ -40")
        with patched_queries(digikey={"status": "Active",
                                      "temp_min_c": rng[0], "temp_max_c": rng[1]}):
            out = lifecycle_audit.audit_bom(analysis, delay=0, temp_range=(-40, 85))
        self.assertEqual([f for f in out["findings"] if f.get("rule_id") == "LT-001"], [])

    def test_wider_rating_than_required_is_quiet(self):
        analysis = {"bom": [{"mpn": "ABC12345", "references": ["U1"]}]}
        with patched_queries(digikey={"status": "Active", "temp_min_c": -55.0, "temp_max_c": 150.0}):
            out = lifecycle_audit.audit_bom(analysis, delay=0, temp_range=(-40, 85))
        self.assertEqual([f for f in out["findings"] if f.get("rule_id") == "LT-001"], [])


class LeadWeeksCarryTest(unittest.TestCase):
    def weeks(self, text):
        analysis = {"bom": [{"mpn": "ABC12345", "references": ["U1"]}]}
        with patched_queries(mouser={"status": "Active", "lead_time": text}):
            out = lifecycle_audit.audit_bom(analysis, delay=0)
        f = [x for x in out["findings"] if x.get("rule_id") == "LC-006"]
        return f[0]["lead_weeks"] if f else None

    def test_fractional_weeks_round_up(self):
        self.assertEqual(self.weeks("12.5 Weeks"), 13)
        self.assertEqual(self.weeks(12.5), 13)

    def test_days_to_weeks(self):
        # 50 / 7 = 7.14 -> 8; 100 / 7 = 14.3 -> 15
        self.assertEqual(lifecycle_audit._lead_weeks("50 Days"), 8)
        self.assertEqual(lifecycle_audit._lead_weeks("12.5 weeks"), 13)
        self.assertEqual(self.weeks("100 Days"), 15)

    def test_thousands_separator_and_negative(self):
        self.assertEqual(lifecycle_audit._lead_weeks("1,000 Days"), 143)
        self.assertIsNone(lifecycle_audit._lead_weeks("-5 Weeks"))
        self.assertIsNone(lifecycle_audit._lead_weeks(-3))
        self.assertIsNone(self.weeks("-20 Weeks"))


if __name__ == "__main__":
    unittest.main()
