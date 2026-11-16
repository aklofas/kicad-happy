"""Datasheet extraction quality scores: the v1.4 rubric and the legacy pin scorer."""
import json
import sys
import unittest
from pathlib import Path

from tools.tests._fixtures import fixture

DS = Path(__file__).resolve().parents[2] / "skills" / "datasheets"
sys.path.insert(0, str(DS / "scripts"))

import datasheet_score  # noqa: E402
from datasheet_score import score_v14_extraction  # noqa: E402


def _pin(n, **fields):
    return {"numbers": [str(n)], **fields}


def _sparse(category, payload):
    """Pinout half populated (name + type of 4 fields), base 2 of 8 reference
    fields, one category field."""
    return {
        "categories": [category],
        "base": {
            "package": {"code": "X", "pin_count": 2},
            "pinout": [_pin(1, name="A", type="input"), _pin(2, name="B", type="output")],
        },
        category: payload,
    }


def _uncategorized(pinout, base):
    """No categories; pinout and base populated to the given fraction (0.75, 0.8
    or 1.0)."""
    full = dict(name="P", type="input", power_domain="VDD", evidence={"page": 1})
    pins = [_pin(i, **full) for i in range(1, 6)]
    if pinout == 0.8:
        pins[-1] = _pin(5)
    refs = {"package": {"code": "X", "pin_count": 5}, "thermal": {"theta_ja": _sv(typ=50)},
            "absolute_max": {"VIN_max": _sv(max=6), "TJ_max": _sv(max=150)},
            "recommended_operating": {"VIN": _sv(max=5), "TA": _sv(max=85)},
            "esd": {"HBM": _sv(typ=2000)}}
    if base == 0.75:
        del refs["esd"]
        del refs["recommended_operating"]["TA"]
    return {"categories": [], "base": {**refs, "pinout": pins}}


def _sv(**kw):
    return [{"min": kw.get("min"), "typ": kw.get("typ"), "max": kw.get("max"),
             "unit": kw.get("unit"), "condition": None, "notes": None,
             "evidence": {"page": 5, "section": "EC", "confidence": "high", "method": "table"}}]


class V14Rubric(unittest.TestCase):
    def test_sparse_mcu_scores_29(self):
        self.assertEqual(score_v14_extraction(_sparse("mcu", {"core_family": "Cortex-M3"}))["score"], 29)

    def test_topology_only_regulator_scores_29(self):
        self.assertEqual(score_v14_extraction(_sparse("regulator", {"topology": "buck"}))["score"], 29)

    def test_unknown_category_earns_nothing(self):
        s = score_v14_extraction({"categories": ["relay"], "relay": {"x": 1}, "base": {}})
        self.assertEqual(s["dimensions"]["category_extension_completeness"], 0.0)

    def test_no_reserved_dimension(self):
        s = score_v14_extraction({"categories": [], "base": {}})
        self.assertEqual(set(s["dimensions"]), {"pinout_completeness", "base_completeness",
                                                "category_extension_completeness"})
        self.assertEqual(set(s["weights"]), set(s["dimensions"]))
        self.assertEqual(s["score"], 0)

    def test_uncategorized_extraction_is_scored_on_pinout_and_base(self):
        # A part the scout puts in no category (interface IC, sensor, logic) cannot
        # earn the category dimension, so it is left out of the scale.
        cases = (
            (1.0, 1.0, 100, 75),   # (pinout, base, score, score before the rubric change)
            (0.8, 0.75, 77, 65),
        )
        for pinout, base, score, before in cases:
            s = score_v14_extraction(_uncategorized(pinout, base))
            self.assertEqual(s["score"], score, (pinout, base))
            self.assertGreaterEqual(s["score"], before, (pinout, base))

    def test_listed_category_stays_in_the_scale(self):
        # Complete pinout and base, but the listed category earned nothing.
        e = dict(_uncategorized(1.0, 1.0), categories=["mcu"], mcu={})
        self.assertEqual(score_v14_extraction(e)["score"], 64)
        e = dict(_uncategorized(1.0, 1.0), categories=["mcu"], mcu={"_extraction_failed": True})
        self.assertEqual(score_v14_extraction(e)["score"], 64)

    def test_full_marks_score_100(self):
        pins = [_pin(i, name=f"P{i}", type="input", power_domain="VDD",
                     evidence={"page": 1}) for i in (1, 2)]
        e = {"categories": ["regulator"],
             "base": {"package": {"code": "X", "pin_count": 2}, "thermal": {"theta_ja": _sv(typ=50)},
                      "absolute_max": {"VIN_max": _sv(max=6), "TJ_max": _sv(max=150)},
                      "recommended_operating": {"VIN": _sv(max=5), "TA": _sv(max=85)},
                      "esd": {"HBM": _sv(typ=2000)}, "pinout": pins},
             "regulator": {f: _sv(typ=1) for f in datasheet_score._CATEGORY_FIELD_REQS["regulator"]["required"]
                           + datasheet_score._CATEGORY_FIELD_REQS["regulator"]["nice"]}}
        self.assertEqual(score_v14_extraction(e)["score"], 100)

    def test_transistor_fields_follow_the_type(self):
        fet = {"transistor_type": "mosfet_n", "vds_max": _sv(max=30), "id_max": _sv(max=5), "rds_on": _sv(typ=0.02)}
        jfet = {**fet, "transistor_type": "jfet_n"}
        bjt = {"transistor_type": "bjt_npn", "vceo_max": _sv(max=40), "ic_max": _sv(max=0.2), "hfe": _sv(typ=100)}
        pnp = {**bjt, "transistor_type": "bjt_pnp"}
        igbt = {"transistor_type": "igbt", "vceo_max": _sv(max=600), "ic_max": _sv(max=20), "vce_sat": _sv(typ=1.8)}
        for payload in (fet, jfet, bjt, pnp, igbt):
            s = score_v14_extraction({"categories": ["transistor"], "transistor": payload, "base": {}})
            self.assertAlmostEqual(s["dimensions"]["category_extension_completeness"], 0.7,
                                   msg=payload["transistor_type"])
        # BJT fields on a FET earn only the type field.
        s = score_v14_extraction({"categories": ["transistor"], "base": {},
                                  "transistor": {**bjt, "transistor_type": "mosfet_n"}})
        self.assertAlmostEqual(s["dimensions"]["category_extension_completeness"], 0.7 * 0.25)

    def test_diode_fields_follow_the_type(self):
        cases = {"zener": ("vz", "power_dissipation"), "tvs": ("breakdown_voltage", "vr_max"),
                 "varicap": ("cd", "vr_max"), "schottky": ("vf", "if_max", "vr_max")}
        for kind, fields in cases.items():
            payload = {"diode_type": kind, **{f: _sv(typ=1) for f in fields}}
            s = score_v14_extraction({"categories": ["diode"], "diode": payload, "base": {}})
            c = s["dimensions"]["category_extension_completeness"]
            # "cd" is also an optional field for every diode.
            self.assertAlmostEqual(c, 0.7 + (0.3 / 5 if "cd" in fields else 0.0), msg=kind)

    def test_opamp_and_crystal_required_fields(self):
        opamp = {f: _sv(typ=1) for f in ("opamp_topology", "channels", "vsupply_range", "gbw")}
        xtal = {f: _sv(typ=1) for f in ("crystal_type", "frequency", "load_capacitance", "frequency_tolerance")}
        for cat, payload in (("opamp", opamp), ("crystal", xtal)):
            s = score_v14_extraction({"categories": [cat], cat: payload, "base": {}})
            self.assertAlmostEqual(s["dimensions"]["category_extension_completeness"], 0.7, msg=cat)

    def test_null_pin_does_not_raise(self):
        s = score_v14_extraction({"base": {"pinout": [None, _pin(1, name="A")]}, "categories": []})
        self.assertIsInstance(s["score"], int)

    def test_malformed_shapes_do_not_raise(self):
        for e in ({"base": ["x"], "categories": "mcu"}, {"base": None, "categories": [["mcu"], 3]},
                  {"base": {}, "categories": ["diode"], "diode": {"diode_type": ["tvs"]}},
                  {"base": {}, "categories": ["transistor"], "transistor": {"transistor_type": 5}}):
            self.assertIsInstance(score_v14_extraction(e)["score"], int, e)

    def test_complete_regulator_stays_trusted(self):
        # The shape the harness contract builds: a full LM2596-like regulator.
        pin = lambda n, name, pd: _pin(n, name=name, type="input", power_domain=pd,
                                       evidence={"page": 3, "confidence": "high"})
        e = {"categories": ["regulator"],
             "base": {"package": {"code": "TO-263-5", "pin_count": 5},
                      "thermal": {"theta_ja": _sv(typ=50)},
                      "absolute_max": {"VIN_max": _sv(max=45), "TJ_max": _sv(max=150)},
                      "recommended_operating": {"VIN": _sv(min=4.5, max=40), "TA": _sv(min=-40, max=125)},
                      "esd": {"HBM": _sv(typ=2000)},
                      "pinout": [pin(1, "VIN", "VIN"), pin(2, "OUT", None), pin(3, "GND", None),
                                 pin(4, "FB", None), pin(5, "EN", None)]},
             "regulator": {"topology": "buck", "vin_range": _sv(min=4.5, max=40),
                           "vout_range": _sv(min=1.23, max=37), "iout_max": _sv(max=3),
                           "reference_voltage": _sv(typ=1.23), "switching_freq": _sv(typ=150000),
                           "enable_pin": "5", "cin_min": _sv(min=4.7e-4), "cout_min": _sv(min=2.2e-4)}}
        self.assertGreaterEqual(score_v14_extraction(e)["score"], 60)

    def test_stm32_without_its_category_stays_trusted(self):
        data = json.loads(fixture("datasheets-extracted", "STM32F103C8T6.json").read_text(encoding="utf-8"))
        data["categories"] = []
        self.assertEqual(score_v14_extraction(data)["score"], 69)   # 61 before the rubric change

    def test_real_extractions_frozen(self):
        expected = {"ABM8G-106-12.000MHZ-T": 66, "IRLML6344": 71, "LM2596-ADJ": 97,
                    "LM358": 71, "MBRS540T3G": 71, "STM32F103C8T6": 80}
        got = {}
        for mpn in expected:
            path = fixture("datasheets-extracted", f"{mpn}.json")
            got[mpn] = score_v14_extraction(json.loads(path.read_text(encoding="utf-8")))["score"]
        self.assertEqual(got, expected)


class LegacyPinCoverage(unittest.TestCase):
    def test_legacy_unnamed_pins_deduct(self):
        score, issues = datasheet_score._score_pin_coverage(
            {"pins": [{"number": str(i)} for i in range(1, 5)]}, 4)
        self.assertEqual(score, 6.0)
        self.assertIn("Pin 1: missing name", issues)

    def test_named_pin_with_specs_keeps_full_marks(self):
        pins = [{"number": "1", "name": "VIN", "voltage_abs_max": 6.0},
                {"number": "2", "name": "EN", "description": "enable"}]
        self.assertEqual(datasheet_score._score_pin_coverage({"pins": pins}, 2)[0], 10.0)

    def test_score_extraction_keys_unchanged(self):
        r = datasheet_score.score_extraction({"pins": [{"number": "1", "name": "A"}]})
        self.assertEqual(set(r), {"total", "pin_coverage", "voltage_ratings", "application_info",
                                  "electrical_characteristics", "spice_specs", "issues", "sufficient"})


if __name__ == "__main__":
    unittest.main()
