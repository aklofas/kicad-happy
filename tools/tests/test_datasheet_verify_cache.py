# tools/tests/test_datasheet_verify_cache.py
import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DS_SCRIPTS = ROOT / "skills" / "datasheets" / "scripts"
sys.path.insert(0, str(DS_SCRIPTS))
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
import datasheet_extract_cache as cache  # noqa: E402
import datasheet_verify as dv  # noqa: E402

BUCK = Path("/home/aklofas/Projects/kicad-happy-testharness/repos/ikajdan/stm32-buck-converter/hardware")

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


class Quality(unittest.TestCase):
    def test_extraction_metadata_score_is_read(self):
        f = dv._quality_finding("LM358", lm358(4.0))
        self.assertEqual(f["type"], "extraction_quality_low")
        self.assertEqual(f["quality_score"], 4.0)
        self.assertIsNone(dv._quality_finding("LM358", lm358(9.0)))

    def test_meta_shape_still_honoured(self):
        f = dv._quality_finding("X", {"meta": {"extraction_score": 3.0}})
        self.assertEqual(f["quality_score"], 3.0)


def three_unit_analysis(d):
    """U9 is a 3-unit IC: units 1-2 carry signal pins, unit 3 the power pins."""
    def unit(pn):
        return {"reference": "U9", "type": "ic", "value": "LM358", "mpn": "LM358",
                "parsed_value": None, "pin_nets": pn}
    comps = [unit({"1": "SIG1"}), unit({"2": "SIG2"}), unit({"8": "+3.3V", "4": "GND"})]
    for ref in ("C1", "C2", "C3"):
        comps.append({"reference": ref, "type": "capacitor", "value": "100nF",
                      "parsed_value": 1e-7, "pin_nets": {"1": "+3.3V", "2": "GND"}})
    nets = {"+3.3V": {"pins": [{"component": "U9", "pin_number": "8"}] +
                      [{"component": r, "pin_number": "1"} for r in ("C1", "C2", "C3")]},
            "GND": {"pins": [{"component": "U9", "pin_number": "4"}] +
                    [{"component": r, "pin_number": "2"} for r in ("C1", "C2", "C3")]},
            "SIG1": {"pins": [{"component": "U9", "pin_number": "1"}]},
            "SIG2": {"pins": [{"component": "U9", "pin_number": "2"}]}}
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


@unittest.skipUnless(BUCK.is_dir(), "corpus project not available")
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


if __name__ == "__main__":
    unittest.main()
