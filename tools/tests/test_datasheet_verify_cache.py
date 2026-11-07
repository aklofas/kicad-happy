# tools/tests/test_datasheet_verify_cache.py
import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DS_SCRIPTS = ROOT / "skills" / "datasheets" / "scripts"
sys.path.insert(0, str(DS_SCRIPTS))
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
import datasheet_extract_cache as cache  # noqa: E402
import datasheet_verify as dv  # noqa: E402

CORPUS = Path(os.environ.get("KH_CORPUS", "/home/aklofas/Projects/kicad-happy-testharness/repos"))
BUCK = CORPUS / "ikajdan" / "stm32-buck-converter" / "hardware"

LM358 = {
    "mpn": "LM358", "category": "opamp",
    "pins": [
        {"number": "8", "name": "V+", "type": "power", "direction": "input", "voltage_abs_max": 32.0},
        {"number": "4", "name": "GND", "type": "ground", "direction": "passive"},
        {"number": "3", "name": "IN1+", "type": "analog", "direction": "input", "voltage_abs_max": 32.0},
    ],
    "application_circuit": {"decoupling_cap": "100nF x3"},
}


def lm358(score, decoupling="100nF x3"):
    d = json.loads(json.dumps(LM358))
    d["application_circuit"]["decoupling_cap"] = decoupling
    d["extraction_metadata"] = {"extraction_score": score, "extraction_version": 2}
    return d


def run_buck(score, decoupling="100nF x3"):
    with tempfile.TemporaryDirectory() as t:
        proj = Path(t) / "hw"
        shutil.copytree(BUCK, proj)
        cache.cache_extraction(str(proj / "datasheets" / "extracted"), "LM358", lm358(score, decoupling))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DIGIKEY_", "MOUSER_", "ELEMENT14_"))}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        out = Path(t) / "out.json"
        subprocess.run([sys.executable, str(ROOT / "skills/kicad/scripts/analyze_schematic.py"),
                        str(proj / "buck_converter.kicad_sch"), "--output", str(out)],
                       env=env, capture_output=True, timeout=300, check=True)
        return json.loads(out.read_text(encoding="utf-8"))["datasheet_verification"]


class LoadExtraction(unittest.TestCase):
    def test_finds_cache_manager_entries_by_mpn_any_case(self):
        with tempfile.TemporaryDirectory() as d:
            cache.cache_extraction(d, "LM2596-ADJ", {"mpn": "LM2596-ADJ", "pins": []})
            for q in ("LM2596-ADJ", "lm2596-adj"):
                self.assertEqual(dv._load_extraction(d, q).get("mpn"), "LM2596-ADJ")

    def test_manifest_file_with_separator_or_dotdot_is_not_read(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "extracted"; d.mkdir()
            (Path(t) / "x.json").write_text('{"mpn": "EVIL", "pins": []}', encoding="utf-8")
            for fname in ("../x.json", "sub/x.json", "..", ""):
                (d / "manifest.json").write_text(json.dumps(
                    {"extractions": {"EVIL_aaaaaa": {"mpn": "EVIL", "file": fname}}}), encoding="utf-8")
                self.assertEqual(dv._load_extraction(str(d), "EVIL"), {}, fname)

    def test_non_dict_and_undecodable_files_give_empty(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "A1.json").write_text("null", encoding="utf-8")
            Path(d, "B1.json").write_bytes(b'{"mpn": "caf\xe9"}')
            Path(d, "C1.json").write_text("[1]", encoding="utf-8")
            for m in ("A1", "B1", "C1"):
                self.assertEqual(dv._load_extraction(d, m), {}, m)

    def test_manifest_entry_that_is_not_a_dict_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "manifest.json").write_text(json.dumps({"extractions": {"Z": 5}}), encoding="utf-8")
            self.assertEqual(dv._load_extraction(d, "Z"), {})


def ic_analysis(mpn="LM358"):
    return {"components": [{"reference": "U1", "type": "ic", "value": mpn, "mpn": mpn, "pin_nets": {}}],
            "nets": {}, "rail_voltages": {}}


class FileNameCollision(unittest.TestCase):
    def test_file_named_after_another_mpn_is_not_returned(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "BAV99_215.json").write_text(json.dumps(
                {"schema_version": "1.4", "source": {"mpn": "BAV99/215"}, "base": {}}))
            Path(d, "X1_A.json").write_text(json.dumps({"mpn": "X1.A"}))
            for mpn in ("BAV99-215", "BAV99.215", "BAV99 215", "X1-A", "X1/A"):
                self.assertEqual(cache.find_extraction(d, mpn), (None, None), mpn)
            self.assertEqual(cache.find_extraction(d, "BAV99/215")[1], Path(d, "BAV99_215.json"))
            self.assertEqual(cache.find_extraction(d, "X1.A")[1], Path(d, "X1_A.json"))

    def test_file_that_records_no_mpn_is_taken_by_its_name(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "LM1117.json").write_text(json.dumps({"category": "regulator"}))
            self.assertEqual(cache.find_extraction(d, "LM1117")[1], Path(d, "LM1117.json"))

    def test_cached_extraction_is_still_found_for_its_own_mpn(self):
        with tempfile.TemporaryDirectory() as d:
            cache.cache_extraction(d, "LM1117-3.3", {"mpn": "LM1117-3.3", "pins": []})
            ext, path = cache.find_extraction(d, "LM1117-3.3")
            self.assertEqual(ext["mpn"], "LM1117-3.3")
            self.assertEqual(cache.find_extraction(d, "LM1117_3.3"), (None, None))


class ExtractDirResolution(unittest.TestCase):
    def test_shared_sticky_parent_cache_is_not_read(self):
        with tempfile.TemporaryDirectory() as t:
            os.chmod(t, 0o1777)
            proj = Path(t) / "proj"; proj.mkdir()
            cache.cache_extraction(str(Path(t) / "datasheets" / "extracted"), "LM358", lm358(9.0))
            out = dv.run_datasheet_verification(ic_analysis(), project_dir=str(proj))
            self.assertEqual(out["summary"].get("ics_with_extractions", 0), 0)
            self.assertEqual(out["findings"], [])
            self.assertEqual(dv._resolve_extract_dir(str(proj)), "")

    def test_project_own_cache_is_found(self):
        with tempfile.TemporaryDirectory() as t:
            proj = Path(t) / "proj"
            cache.cache_extraction(str(proj / "datasheets" / "extracted"), "LM358", lm358(9.0))
            out = dv.run_datasheet_verification(ic_analysis(), project_dir=str(proj))
            self.assertEqual(out["summary"]["ics_with_extractions"], 1)

    @unittest.skipIf(os.name == "nt", "symlinks")
    def test_symlinked_manifest_is_not_read(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "extracted"; d.mkdir()
            (d / "M1_abc123.json").write_text('{"mpn": "M1", "pins": []}', encoding="utf-8")
            real = Path(t) / "real_manifest.json"
            real.write_text(json.dumps({"extractions": {"M1_abc123": {"mpn": "M1", "file": "M1_abc123.json"}}}),
                            encoding="utf-8")
            try:
                os.symlink(real, d / "manifest.json")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            self.assertEqual(dv._load_extraction(str(d), "M1"), {})

    def test_oversized_manifest_is_not_read(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "M1_abc123.json").write_text('{"mpn": "M1", "pins": []}', encoding="utf-8")
            Path(d, "manifest.json").write_text(json.dumps(
                {"extractions": {"M1_abc123": {"mpn": "M1", "file": "M1_abc123.json"}},
                 "pad": "x" * (dv.MAX_EXTRACTION_BYTES + 1)}), encoding="utf-8")
            self.assertEqual(dv._load_extraction(d, "M1"), {})


@unittest.skipUnless(BUCK.is_dir(), "local-only: needs the corpus (set KH_CORPUS)")
class SharedParentBoard(unittest.TestCase):
    def test_schematic_in_shared_dir_gets_no_verification(self):
        with tempfile.TemporaryDirectory() as t:
            os.chmod(t, 0o1777)
            proj = Path(t) / "hw"
            shutil.copytree(BUCK, proj)
            shutil.rmtree(proj / "datasheets", ignore_errors=True)
            cache.cache_extraction(str(Path(t) / "datasheets" / "extracted"), "LM358", lm358(9.0))
            env = {k: v for k, v in os.environ.items() if not k.startswith(("DIGIKEY_", "MOUSER_", "ELEMENT14_"))}
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            out = Path(t) / "out.json"
            subprocess.run([sys.executable, str(ROOT / "skills/kicad/scripts/analyze_schematic.py"),
                            str(proj / "buck_converter.kicad_sch"), "--output", str(out)],
                           env=env, capture_output=True, timeout=300, check=True, cwd=t)
            self.assertNotIn("datasheet_verification", json.loads(out.read_text(encoding="utf-8")))


class Quality(unittest.TestCase):
    def test_extraction_metadata_score_is_read(self):
        f = dv._quality_finding("LM358", lm358(4.0))
        self.assertEqual(f["type"], "extraction_quality_low")
        self.assertEqual(f["quality_score"], 4.0)
        self.assertIsNone(dv._quality_finding("LM358", lm358(9.0)))

    def test_meta_shape_still_honoured(self):
        f = dv._quality_finding("X", {"meta": {"extraction_score": 3.0}})
        self.assertEqual(f["quality_score"], 3.0)


def three_unit_analysis(d, ref="U9"):
    """U9 is a 3-unit IC: units 1-2 carry signal pins, unit 3 the power pins."""
    def unit(n, pn):
        return {"reference": ref, "type": "ic", "value": "LM358", "lib_id": "Amplifier:LM358",
                "unit": n, "mpn": "LM358", "parsed_value": None, "pin_nets": pn}
    comps = [unit(1, {"1": "SIG1"}), unit(2, {"2": "SIG2"}), unit(3, {"8": "+3.3V", "4": "GND"})]
    for cref in ("C1", "C2", "C3"):
        comps.append({"reference": cref, "type": "capacitor", "value": "100nF",
                      "parsed_value": 1e-7, "pin_nets": {"1": "+3.3V", "2": "GND"}})
    nets = {"+3.3V": {"pins": [{"component": ref, "pin_number": "8"}] +
                      [{"component": r, "pin_number": "1"} for r in ("C1", "C2", "C3")]},
            "GND": {"pins": [{"component": ref, "pin_number": "4"}] +
                    [{"component": r, "pin_number": "2"} for r in ("C1", "C2", "C3")]},
            "SIG1": {"pins": [{"component": ref, "pin_number": "1"}]},
            "SIG2": {"pins": [{"component": ref, "pin_number": "2"}]}}
    return {"components": comps, "nets": nets, "rail_voltages": {"+3.3V": 3.3}, "file": ""}


class MultiUnit(unittest.TestCase):
    def test_non_power_units_raise_no_decoupling_error(self):
        with tempfile.TemporaryDirectory() as t:
            ex = Path(t) / "datasheets" / "extracted"
            cache.cache_extraction(str(ex), "LM358", lm358(9.0))
            res = dv.run_datasheet_verification(three_unit_analysis(t), project_dir=t)
        self.assertEqual([f for f in res["findings"] if f["type"] == "decoupling_insufficient"], [])
        self.assertEqual(res["summary"]["ics_checked"], 1)
        self.assertEqual(res["summary"]["ics_with_extractions"], 1)

    def test_real_shortfall_is_still_reported_once(self):
        with tempfile.TemporaryDirectory() as t:
            ex = Path(t) / "datasheets" / "extracted"
            e = lm358(9.0); e["application_circuit"]["decoupling_cap"] = "100nF x5"
            cache.cache_extraction(str(ex), "LM358", e)
            res = dv.run_datasheet_verification(three_unit_analysis(t), project_dir=t)
        f = [x for x in res["findings"] if x["type"] == "decoupling_insufficient"]
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0]["ref"], f[0]["actual_count"], f[0]["required_count"]), ("U9", 3, 5))
        self.assertEqual(f[0]["severity"], "warning")


    def test_unannotated_reference_raises_no_error_from_logic_units(self):
        with tempfile.TemporaryDirectory() as t:
            cache.cache_extraction(str(Path(t) / "datasheets" / "extracted"), "LM358", lm358(9.0))
            res = dv.run_datasheet_verification(three_unit_analysis(t, ref="U?"), project_dir=t)
        self.assertEqual([f for f in res["findings"] if f["type"] == "decoupling_insufficient"], [])

    def test_two_physical_parts_sharing_a_reference_are_both_checked(self):
        # Probe A: two LM358 (each unit 1 + unit 3 style pair collapsed to one entry each),
        # same reference; the one on +12V has no caps.
        def part(net):
            return {"reference": "U1", "type": "ic", "value": "LM358", "lib_id": "Amplifier:LM358",
                    "unit": 1, "mpn": "LM358", "parsed_value": None, "pin_nets": {"8": net, "4": "GND"}}
        comps = [part("+3.3V"), part("+12V")]
        for r in ("C1", "C2", "C3"):
            comps.append({"reference": r, "type": "capacitor", "value": "100nF", "parsed_value": 1e-7,
                          "pin_nets": {"1": "+3.3V", "2": "GND"}})
        nets = {"+3.3V": {"pins": [{"component": r, "pin_number": "1"} for r in ("C1", "C2", "C3")]
                          + [{"component": "U1", "pin_number": "8"}]},
                "+12V": {"pins": [{"component": "U1", "pin_number": "8"}]},
                "GND": {"pins": []}}
        with tempfile.TemporaryDirectory() as t:
            cache.cache_extraction(str(Path(t) / "datasheets" / "extracted"), "LM358", lm358(9.0))
            res = dv.run_datasheet_verification(
                {"components": comps, "nets": nets, "rail_voltages": {}, "file": ""}, project_dir=t)
        f = [x for x in res["findings"] if x["type"] == "decoupling_insufficient"]
        self.assertEqual([(x["actual_count"], x["severity"]) for x in f], [(0, "error")])

    def test_different_parts_under_one_reference_are_not_merged(self):
        # Probe B: LM358 unit 1, a 74HC14 with the same reference, LM358 unit 3.
        def e(lib, val, unit, pn):
            return {"reference": "U1", "type": "ic", "value": val, "lib_id": lib, "unit": unit,
                    "mpn": val, "parsed_value": None, "pin_nets": pn}
        comps = [e("Amplifier:LM358", "LM358", 1, {"1": "SIG"}),
                 e("74xx:74HC14", "74HC14", 1, {"14": "+5V", "7": "GND"}),
                 e("Amplifier:LM358", "LM358", 3, {"8": "+3.3V", "4": "GND"})]
        for r in ("C1", "C2", "C3"):
            comps.append({"reference": r, "type": "capacitor", "value": "100nF", "parsed_value": 1e-7,
                          "pin_nets": {"1": "+3.3V", "2": "GND"}})
        nets = {"+3.3V": {"pins": [{"component": r, "pin_number": "1"} for r in ("C1", "C2", "C3")]
                          + [{"component": "U1", "pin_number": "8"}]}, "GND": {"pins": []}}
        with tempfile.TemporaryDirectory() as t:
            cache.cache_extraction(str(Path(t) / "datasheets" / "extracted"), "LM358", lm358(9.0))
            res = dv.run_datasheet_verification(
                {"components": comps, "nets": nets, "rail_voltages": {}, "file": ""}, project_dir=t)
        self.assertEqual([f for f in res["findings"] if f["type"] == "decoupling_insufficient"], [])
        self.assertEqual(res["summary"]["ics_checked"], 3 - 1)  # LM358 group + 74HC14

    def test_first_nonempty_mpn_of_a_group_is_used(self):
        comps = three_unit_analysis(".")["components"]
        comps[0]["mpn"] = ""
        comps[2]["mpn"] = "LM358"
        merged = [c for c in dv._merge_ic_units(comps) if c["reference"] == "U9"]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["mpn"], "LM358")


class CacheFileLimits(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "symlinks")
    def test_symlinked_cache_file_is_not_read(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "extracted"; d.mkdir()
            (Path(t) / "real.json").write_text('{"mpn": "S1", "pins": []}', encoding="utf-8")
            try:
                os.symlink(Path(t) / "real.json", d / "S1.json")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            self.assertEqual(dv._load_extraction(str(d), "S1"), {})

    def test_oversized_cache_file_is_not_read(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "BIG.json").write_text('{"pad": "' + "x" * (dv.MAX_EXTRACTION_BYTES + 1) + '"}', encoding="utf-8")
            self.assertEqual(dv._load_extraction(d, "BIG"), {})


@unittest.skipUnless(BUCK.is_dir(), "local-only: needs the corpus (set KH_CORPUS)")
class BuckBoard(unittest.TestCase):
    def test_hand_derived_result(self):
        # LM358 V+ (pin 8) sits on +3.3V; the 100 nF caps across +3.3V-GND are C5 and C8,
        # so "100nF x3" is two of three for each of U1 and U2.
        dvr = run_buck(9.0)
        f = [x for x in dvr["findings"] if x["type"] == "decoupling_insufficient"]
        self.assertEqual(sorted(x["ref"] for x in f), ["U1", "U2"])
        for x in f:
            self.assertEqual(x["severity"], "warning")
            self.assertEqual((x["required_count"], x["actual_count"]), (3, 2))
            self.assertEqual(sorted(c["ref"] for c in x["actual_caps"]), ["C5", "C8"])
        self.assertEqual(len(dvr["findings"]), 2)

    def test_low_score_gives_one_quality_finding(self):
        dvr = run_buck(4.0, "100nF")
        q = [x for x in dvr["findings"] if x["type"] == "extraction_quality_low"]
        self.assertEqual(len(q), 1)
        self.assertEqual(q[0]["quality_score"], 4.0)
        self.assertEqual(len(dvr["findings"]), 1)


class SharedLookupOrder(unittest.TestCase):
    """The verifier, the feature helpers and the lifecycle audit read the same extraction."""

    def _ext(self, root, files, manifest=None):
        ext = Path(root) / "datasheets" / "extracted"
        ext.mkdir(parents=True)
        for name, (lo, hi) in files.items():
            (ext / name).write_text(json.dumps({
                "category": "opamp", "mpn": "P1",
                "recommended_operating_conditions": {"temp_min_c": lo, "temp_max_c": hi}}),
                encoding="utf-8")
        if manifest is not None:
            (ext / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return ext

    def _read_all(self, root, ext):
        import datasheet_features as df
        import lifecycle_engine
        out = {}
        out["verify"] = dv._load_extraction(str(ext), "P1")["recommended_operating_conditions"]["temp_min_c"]
        out["features"] = df._load("P1", extract_dir=str(ext))["recommended_operating_conditions"]["temp_min_c"]
        out["lifecycle"] = lifecycle_engine.read_extraction_temperature("P1", str(root))["temp_min_c"]
        return out

    def test_manifest_entry_wins_over_direct_file(self):
        with tempfile.TemporaryDirectory() as d:
            ext = self._ext(d, {"P1.json": (0, 70), "P1_v2.json": (-40, 85)},
                            {"extractions": {"P1": {"file": "P1_v2.json", "mpn": "P1"}}})
            self.assertEqual(self._read_all(d, ext), {"verify": -40, "features": -40, "lifecycle": -40})

    def test_direct_file_without_manifest_is_still_read(self):
        with tempfile.TemporaryDirectory() as d:
            ext = self._ext(d, {"P1.json": (0, 70)})
            self.assertEqual(self._read_all(d, ext), {"verify": 0, "features": 0, "lifecycle": 0})

    def test_manifest_found_by_recorded_mpn_when_key_differs(self):
        with tempfile.TemporaryDirectory() as d:
            ext = self._ext(d, {"abc.json": (-40, 85)},
                            {"extractions": {"abc": {"file": "abc.json", "mpn": "p1"}}})
            self.assertEqual(self._read_all(d, ext), {"verify": -40, "features": -40, "lifecycle": -40})

    def _hashed_entry_to(self, d, body):
        ext = self._ext(d, {"P1.json": (-40, 85)}, {"extractions": {
            cache._sanitize_mpn("P1"): {"file": "bad.json", "mpn": "P1"}}})
        (ext / "bad.json").write_text(body, encoding="utf-8")
        return ext

    def test_unreadable_manifest_file_does_not_hide_the_direct_file(self):
        for body in ("{bad", "{}"):
            with tempfile.TemporaryDirectory() as d:
                ext = self._hashed_entry_to(d, body)
                self.assertEqual(self._read_all(d, ext),
                                 {"verify": -40, "features": -40, "lifecycle": -40}, body)


class MixedV13V14Cache(unittest.TestCase):
    """A cache holding a v1.4 extraction of a part and an older v1.3 manifest entry for it:
    every reader takes the v1.4 file."""
    MPN = "LM2596-ADJ"

    def _cache(self, root, v13):
        ext = Path(root) / "datasheets" / "extracted"
        ext.mkdir(parents=True)
        shutil.copy(ROOT / "skills" / "datasheets" / "examples" / "lm2596-adj.json",
                    ext / f"{self.MPN}.json")
        (ext / "old_v13.json").write_text(json.dumps(v13), encoding="utf-8")
        (ext / "manifest.json").write_text(json.dumps({"extractions": {
            cache._sanitize_mpn(self.MPN): {"file": "old_v13.json", "mpn": self.MPN}}}),
            encoding="utf-8")
        return ext

    def test_all_readers_take_the_v14_file(self):
        import datasheet_features as df
        import lifecycle_engine
        v13 = {"mpn": self.MPN, "topology": "ldo", "pins": [],
               "extraction_metadata": {"extraction_score": 9.0, "extraction_version": 2},
               "recommended_operating_conditions": {"temp_min_c": 0, "temp_max_c": 70}}
        with tempfile.TemporaryDirectory() as d:
            ext = self._cache(d, v13)
            self.assertIsInstance(dv._load_extraction(str(ext), self.MPN).get("base"), dict)
            self.assertEqual(df.get_regulator_features(self.MPN, extract_dir=str(ext))["topology"],
                             "buck")
            got = lifecycle_engine.read_extraction_temperature(self.MPN, d)
            self.assertEqual((got["temp_min_c"], got["temp_max_c"]), (-40, 125))

    def test_feature_helpers_still_fall_back_to_v13_for_facts_v14_lacks(self):
        import datasheet_features as df
        v13 = {"mpn": self.MPN, "topology": "mcu", "pins": [],
               "extraction_metadata": {"extraction_score": 9.0, "extraction_version": 2},
               "peripherals": {"usb": {"speed": "FS", "native_phy": True}}}
        with tempfile.TemporaryDirectory() as d:
            ext = self._cache(d, v13)
            self.assertEqual(df.get_mcu_features(self.MPN, extract_dir=str(ext))["usb_speed"], "FS")


if __name__ == "__main__":
    unittest.main()
