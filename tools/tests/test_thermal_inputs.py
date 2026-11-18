"""Thermal reads the keys the analyzers write and does not invent shunt currents."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.tests._fixtures import fixture

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "skills" / "datasheets" / "scripts"))

import analyze_thermal as at  # noqa: E402
import cross_verify as cv  # noqa: E402
from datasheet_extract_cache import cache_extraction  # noqa: E402
from finding_schema import make_finding  # noqa: E402


def _load(name):
    return json.loads(fixture("action-format-report", name).read_text(encoding="utf-8"))


class Shunts(unittest.TestCase):
    def test_shunt_without_current_skipped(self):
        sch = {"findings": [{
            "detector": "detect_current_sense",
            "shunt": {"ref": "R1", "value": "0.01", "ohms": 0.01},
            "max_current_50mV_A": 5.0,
            "max_current_100mV_A": 10.0,
        }]}
        results, skipped = at._estimate_all_power_dissipation(sch)
        self.assertEqual([r for r in results if r["ref"] == "R1"], [])
        self.assertIn({"ref": "R1", "value": "0.01", "reason": "no_operating_current"}, skipped)


class Packages(unittest.TestCase):
    def test_classify_package_table(self):
        table = {
            "MSOP-8": 200, "TSSOP-8": 150, "TSSOP-20": 80, "SSOP-28": 100,
            "SOIC-14_3.9x8.7mm": 100, "SOIC-8": 120, "SOP-8": 120, "SOIC-16W": 80,
            "MSOP-10-1EP": 100, "HTSSOP-20-1EP": 100,
            "VSSOP-8_3x3mm_P0.65mm": 200, "VSSOP-10_3x3mm_P0.5mm": 200,
            "HVSSOP-8-1EP_3x3mm_P0.65mm_EP1.57x1.89mm": 100,
        }
        for name, theta in table.items():
            with self.subTest(name=name):
                self.assertEqual(at._classify_package("Package_SO:" + name)[1], theta)

    def test_sot_names_without_a_hyphen(self):
        for name, theta in (("SOT23-5", 250), ("SOT-23-5", 250), ("SOT223", 60),
                            ("SOT-223-3_TabPin2", 60),
                            ("SOT23_Transistor_RevA_03Aug2010", 250),
                            ("SOT23_Diode_Handsoldering_RevA_03Aug2010", 250)):
            with self.subTest(name=name):
                self.assertEqual(at._classify_package("Lib:" + name)[1], theta)

    def test_ipc_sot223_body_is_not_a_sot23(self):
        # SOT230P696X180-4N is the IPC-7351 name of a SOT-223 body, not a SOT-23.
        self.assertEqual(at._classify_package("Package_TO_SOT_SMD:SOT230P696X180-4N")[0], "unknown")


V13_THERMAL = {"absolute_maximum_ratings": {"junction_temp_max_c": 150},
               "recommended_operating_conditions": {"temp_max_c": 125}}
FOUND = {"tj_max_c": 150.0, "temp_max_c": 125.0}


class DatasheetThermalLookup(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ex = Path(self._tmp.name) / "datasheets" / "extracted"
        self.ex.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, data):
        (self.ex / name).write_text(json.dumps(data), encoding="utf-8")

    def test_extraction_saved_by_the_cache_manager_is_found(self):
        # The cache manager names the file after a hashed key (LM1117_3_3_<md5>.json).
        cache_extraction(self.ex, "LM1117-3.3",
                         dict(V13_THERMAL, extraction_metadata={"extraction_score": 8.0}))
        self.assertFalse((self.ex / "LM1117-3.3.json").exists())
        self.assertEqual(at._get_datasheet_thermal("LM1117-3.3", str(self.ex)), FOUND)

    def test_v14_quality_score_below_60_is_rejected(self):
        for quality, expected in ((55, {}), (80, FOUND)):
            with self.subTest(quality=quality):
                self._write("XA100.json", dict(V13_THERMAL, extraction={"quality_score": quality},
                                               meta={"extraction_score": 9.0}))
                self.assertEqual(at._get_datasheet_thermal("XA100", str(self.ex)), expected)

    def test_v13_score_gate_and_no_score(self):
        for meta, expected in (({"extraction_score": 6.0}, FOUND), ({"extraction_score": 5.9}, {}),
                               ({"extraction_score": float("nan")}, {}), ({}, {})):
            with self.subTest(meta=meta):
                self._write("XA100.json", dict(V13_THERMAL, extraction_metadata=meta))
                self.assertEqual(at._get_datasheet_thermal("XA100", str(self.ex)), expected)


class TextReport(unittest.TestCase):
    def test_text_report_reads_assessments(self):
        data = _load("thermal_v14_arig_controleurspompes_error.json")
        bs = data["summary"]["by_severity"]
        text = at.format_text_report(data)
        self.assertIn("Component Thermal Summary", text)
        self.assertIn(data["assessments"][0]["ref"], text)
        for label, key in (("ERROR", "error"), ("WARNING", "warning"), ("INFO", "info")):
            self.assertIn(f"{label}:", text)
            line = [ln for ln in text.splitlines() if ln.strip().startswith(label + ":")][0]
            self.assertEqual(int(line.split(":")[1]), bs.get(key, 0))
        data["findings"].append(make_finding(
            detector="detect_tj_exceeds_max", rule_id="TJ-001", category="thermal",
            summary="Tj exceeds datasheet maximum", description="x"))
        self.assertIn("Tj exceeds datasheet maximum", at.format_text_report(data))

    def test_text_report_legacy_keys(self):
        a = _load("thermal_v14_rpi_i2c_board.json")["assessments"][0]
        legacy = {"summary": {"critical": 3, "total_findings": 3}, "findings": [],
                  "thermal_assessments": [a]}
        text = at.format_text_report(legacy)
        self.assertIn("Component Thermal Summary", text)
        self.assertIn(a["ref"], text)
        self.assertRegex(text, r"CRITICAL:\s+3")


class CrossVerify(unittest.TestCase):
    def test_cross_verify_thermal_vias(self):
        out = cv.check_thermal_vias(
            {"assessments": [{"ref": "U1", "margin_c": 5, "pdiss_w": 0.5, "tj_estimated_c": 120}]},
            {"findings": [{"detector": "analyze_thermal_pad_vias", "component": "U1", "via_count": 1}]})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["status"], "fail")


def _ldo(ref, value, vin, vout, cout_farads, out_rail):
    iout = min(sum(cout_farads) * 1e4, 1.0) if cout_farads else 0.1
    return {"detector": "detect_power_regulators", "ref": ref, "value": value, "topology": "LDO",
            "input_rail": "+VIN", "output_rail": out_rail, "estimated_vout": vout,
            "output_capacitors": [{"ref": f"C{ref}{i}", "farads": f} for i, f in enumerate(cout_farads)],
            "power_dissipation": {"vin_estimated_V": vin, "vout_V": vout, "dropout_V": round(vin - vout, 3),
                                  "estimated_iout_A": round(iout, 3),
                                  "estimated_pdiss_W": round((vin - vout) * iout, 3)}}


def _buck(ref, vin, vout, iout, out_rail):
    pout = vout * iout
    return {"detector": "detect_power_regulators", "ref": ref, "value": "BUCK1", "topology": "switching",
            "input_rail": "+VIN", "output_rail": out_rail, "estimated_vout": vout,
            "power_dissipation": {"vin_estimated_V": vin, "vout_V": vout, "efficiency_assumed": 0.85,
                                  "estimated_iout_A": iout, "estimated_pdiss_W": round(pout / 0.85 - pout, 3),
                                  "topology": "switching", "sub_topology": "buck"}}


def _fp(ref, library, x=10.0, y=10.0, value=""):
    return {"reference": ref, "value": value, "library": library, "x": x, "y": y}


class RegulatorLoadFromPowerBudget(unittest.TestCase):
    """An output capacitor sizes stability, not the load: the regulator's load is its output rail's
    power-budget load, and a load guessed from output capacitance raises at most an info."""

    def run_thermal(self, regulators, rail_loads_mA, footprints):
        sch = {"analyzer_type": "schematic", "inputs": {"source_files": []}, "findings": regulators,
               "power_budget": {"rails": {r: (ma if isinstance(ma, dict) else {"estimated_load_mA": ma})
                                          for r, ma in rail_loads_mA.items()}}}
        pcb = {"analyzer_type": "pcb", "footprints": footprints}
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "schematic.json").write_text(json.dumps(sch), encoding="utf-8")
            (d / "pcb.json").write_text(json.dumps(pcb), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPTS / "analyze_thermal.py"), "-s", str(d / "schematic.json"),
                                "-p", str(d / "pcb.json"), "-o", str(d / "thermal.json")],
                               capture_output=True, text=True, cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr[-600:])
            return json.loads((d / "thermal.json").read_text(encoding="utf-8"))

    @staticmethod
    def of(out, ref):
        assessed = {a["ref"]: a for a in out["assessments"]}.get(ref)
        findings = sorted((f["rule_id"], f["severity"]) for f in out["findings"] if ref in f["components"])
        return assessed, findings

    def test_ldo_with_large_output_caps_and_a_light_load_runs_cool(self):
        # 12 V to 5 V with 4 x 47 uF on the output and 10 mA of budget load: 7 V x 10 mA = 0.07 W.
        out = self.run_thermal([_ldo("U10", "NCP1117-5.0", 12.0, 5.0, [47e-6] * 4, "AVDD")], {"AVDD": 10},
                               [_fp("U10", "Package_TO_SOT_SMD:SOT-223-3_TabPin2"),
                                _fp("C1", "Capacitor_SMD:C_0805", x=12.0, value="10u")])
        a, findings = self.of(out, "U10")
        self.assertAlmostEqual(a["pdiss_w"], 0.07)
        self.assertAlmostEqual(a["tj_estimated_c"], 29.2)
        self.assertIn("power budget", a["pdiss_source"])
        self.assertEqual(findings, [])

    def test_light_rail_ldo_is_cool_and_the_heavy_rail_ldo_keeps_its_error(self):
        # Two 1117s from 12 V in DPAK: U5's rail draws 10 mA, U4's 260 mA (8.7 V x 0.26 A = 2.262 W).
        out = self.run_thermal(
            [_ldo("U4", "AZ1117CD-3.3TRG1", 12.0, 3.3, [22e-6, 10e-6, 10e-6, 10e-6, 10e-6], "+3V3"),
             _ldo("U5", "AZ1117CD-3.3TRG1", 12.0, 3.3, [22e-6, 10e-6, 0.1e-6], "+3.3VA")],
            {"+3V3": 260, "+3.3VA": 10},
            [_fp("U4", "Package_TO_SOT_SMD:TO-252-2"), _fp("U5", "Package_TO_SOT_SMD:TO-252-2", x=40.0),
             _fp("C12", "Capacitor_SMD:C_0805", x=13.0, value="22u"),
             _fp("C13", "Capacitor_SMD:C_0805", x=43.0, value="22u")])
        u5, u5_findings = self.of(out, "U5")
        self.assertAlmostEqual(u5["pdiss_w"], 0.087)
        self.assertEqual(u5_findings, [])
        u4, u4_findings = self.of(out, "U4")
        self.assertAlmostEqual(u4["pdiss_w"], 2.262)
        self.assertIn(("TS-002", "error"), u4_findings)
        self.assertIn(("TS-004", "warning"), u4_findings)

    def test_budget_load_keeps_the_error_on_a_small_package(self):
        # 240 mA through a SOT-23 LDO from 5 V: 1.7 V x 0.24 A = 0.408 W x 250 C/W -> Tj 127 C.
        out = self.run_thermal([_ldo("U1", "AP2112K-3.3", 5.0, 3.3, [1e-6], "+3V3")], {"+3V3": 240},
                               [_fp("U1", "Package_TO_SOT_SMD:SOT-23-5")])
        a, findings = self.of(out, "U1")
        self.assertAlmostEqual(a["pdiss_w"], 0.408)
        self.assertIn(("TS-001", "error"), findings)

    def test_ldo_without_a_budget_load_raises_only_info(self):
        # No budget load: the 47 uF output proxy (0.47 A) is all there is, so nothing above info.
        out = self.run_thermal([_ldo("U2", "LDO1", 5.0, 3.3, [47e-6], "+3V3")], {"+3V3": 0},
                               [_fp("U2", "Package_TO_SOT_SMD:SOT-23-5"),
                                _fp("C7", "Capacitor_THT:CP_Radial_D5.0mm", x=14.0, value="100u elec")])
        a, findings = self.of(out, "U2")
        self.assertAlmostEqual(a["pdiss_w"], 0.799)
        rules = {r for r, _ in findings}
        self.assertTrue({"TS-001", "TS-004", "TP-002"} <= rules, findings)
        self.assertEqual({s for _, s in findings}, {"info"})
        self.assertEqual(out["summary"]["by_severity"]["error"], 0)

    def test_switcher_without_a_budget_load_is_assessed_from_its_proxy_at_info(self):
        # U3: no budget load, so the regulator's own estimate, 5 V x 2 A x (1/0.85 - 1) = 1.765 W, at info.
        # U6: 1 A of budget load, 5 V x 1 A x (1/0.85 - 1) = 0.882 W x 250 C/W -> Tj 245 C, an error as before.
        out = self.run_thermal([_buck("U3", 12.0, 5.0, 2.0, "+5V"), _buck("U6", 12.0, 5.0, 0.2, "+5VA")],
                               {"+5V": 0, "+5VA": 1000},
                               [_fp("U3", "Package_TO_SOT_SMD:SOT-23-6"),
                                _fp("U6", "Package_TO_SOT_SMD:SOT-23-6", x=60.0)])
        a, findings = self.of(out, "U3")
        self.assertIsNotNone(a)
        self.assertAlmostEqual(a["pdiss_w"], 1.7647)
        self.assertNotIn("U3", [s["ref"] for s in out.get("skipped_components", [])])
        self.assertTrue(findings)
        self.assertEqual({s for _, s in findings}, {"info"})
        a6, findings6 = self.of(out, "U6")
        self.assertAlmostEqual(a6["pdiss_w"], 0.8824)
        self.assertIn(("TS-001", "error"), findings6)


    def test_ldo_feeding_another_ldo_carries_its_load(self):
        # U3 12 V -> 5 V feeds U4 (5 V -> 3.3 V, 130 mA on +3V3). The budget lists U4 on +5V as a 10 mA
        # IC; U3 really passes 130 + 5 mA: 7 V x 0.135 A = 0.945 W in SOT-223, no thermal vias.
        u3 = _ldo("U3", "AMS1117-5.0", 12.0, 5.0, [10e-6], "+5V")
        u4 = _ldo("U4", "AMS1117-3.3", 5.0, 3.3, [10e-6], "+3V3")
        u4["input_rail"] = "+5V"
        out = self.run_thermal(
            [u3, u4],
            {"+5V": {"estimated_load_mA": 15, "ics": [{"ref": "U4", "value": "AMS1117-3.3", "estimated_mA": 10}],
                     "other_loads": [{"ref": "D1", "type": "led", "estimated_mA": 5}]},
             "+3V3": 130},
            [_fp("U3", "Package_TO_SOT_SMD:SOT-223-3_TabPin2"),
             _fp("U4", "Package_TO_SOT_SMD:SOT-223-3_TabPin2", x=40.0)])
        a, findings = self.of(out, "U3")
        self.assertAlmostEqual(a["pdiss_w"], 0.945)
        self.assertIn(("TS-004", "warning"), findings)
        u4a, _ = self.of(out, "U4")
        self.assertAlmostEqual(u4a["pdiss_w"], 0.221)

    def test_ldo_feeding_a_switcher_carries_its_input_current(self):
        # U7 buck 5 V -> 1.8 V at 1 A draws 1.8 x 1 / (0.85 x 5) = 0.4235 A from +5V, not its 10 mA IC entry:
        # U3 drops 7 V x 0.4235 A = 2.965 W.
        u3 = _ldo("U3", "AMS1117-5.0", 12.0, 5.0, [10e-6], "+5V")
        u7 = _buck("U7", 5.0, 1.8, 0.2, "+1V8")
        u7["input_rail"] = "+5V"
        out = self.run_thermal(
            [u3, u7],
            {"+5V": {"estimated_load_mA": 10, "ics": [{"ref": "U7", "value": "BUCK1", "estimated_mA": 10}]},
             "+1V8": 1000},
            [_fp("U3", "Package_TO_SOT_SMD:SOT-223-3_TabPin2"),
             _fp("U7", "Package_TO_SOT_SMD:SOT-23-6", x=40.0)])
        a, findings = self.of(out, "U3")
        self.assertAlmostEqual(a["pdiss_w"], 2.9647)
        self.assertIn(("TS-001", "error"), findings)

    def test_regulators_feeding_each_other_are_counted_once(self):
        # A mis-read loop: U1 feeds +B (U2's input) and U2 feeds +A (U1's input). U1 carries +A's 20 mA
        # with U2's entry replaced by +B's load (20 mA, where U1 itself stays at its flat 10 mA): 30 mA.
        u1 = _ldo("U1", "LDO1", 12.0, 5.0, [1e-6], "+A")
        u1["input_rail"] = "+B"
        u2 = _ldo("U2", "LDO2", 12.0, 5.0, [1e-6], "+B")
        u2["input_rail"] = "+A"
        out = self.run_thermal(
            [u1, u2],
            {"+A": {"estimated_load_mA": 20, "ics": [{"ref": "U2", "value": "LDO2", "estimated_mA": 10}]},
             "+B": {"estimated_load_mA": 20, "ics": [{"ref": "U1", "value": "LDO1", "estimated_mA": 10}]}},
            [_fp("U1", "Package_TO_SOT_SMD:SOT-223-3_TabPin2"),
             _fp("U2", "Package_TO_SOT_SMD:SOT-223-3_TabPin2", x=40.0)])
        self.assertAlmostEqual(self.of(out, "U1")[0]["pdiss_w"], 0.21)
        self.assertAlmostEqual(self.of(out, "U2")[0]["pdiss_w"], 0.21)

    def test_an_ic_on_two_rails_of_one_tree_is_charged_once(self):
        # U3 feeds U4 (+3V3) and U5 (+3V3A); the MCU U9 sits on both, listed at 100 mA on each.
        # U3 carries 100 + 20 (+3V3) + 30 (+3V3A without U9 again) = 150 mA: 7 V x 0.15 A = 1.05 W.
        u3 = _ldo("U3", "AMS1117-5.0", 12.0, 5.0, [10e-6], "+5V")
        u4 = _ldo("U4", "AMS1117-3.3", 5.0, 3.3, [10e-6], "+3V3")
        u5 = _ldo("U5", "AMS1117-3.3", 5.0, 3.3, [10e-6], "+3V3A")
        u4["input_rail"] = u5["input_rail"] = "+5V"
        mcu = {"ref": "U9", "value": "MCU", "estimated_mA": 100}
        out = self.run_thermal(
            [u3, u4, u5],
            {"+5V": {"estimated_load_mA": 20, "ics": [{"ref": "U4", "value": "AMS1117-3.3", "estimated_mA": 10},
                                                       {"ref": "U5", "value": "AMS1117-3.3", "estimated_mA": 10}]},
             "+3V3": {"estimated_load_mA": 120, "ics": [mcu, {"ref": "U10", "value": "FLASH", "estimated_mA": 20}]},
             "+3V3A": {"estimated_load_mA": 130, "ics": [mcu, {"ref": "U11", "value": "ADC", "estimated_mA": 30}]}},
            [_fp("U3", "Package_TO_SOT_SMD:SOT-223-3_TabPin2")])
        self.assertAlmostEqual(self.of(out, "U3")[0]["pdiss_w"], 1.05)

    def test_only_a_linear_or_switching_regulator_feeding_another_rail_takes_its_load(self):
        # U1 is read with its output on its own input rail, U2 is a surge stopper: both take +12V's
        # own 50 mA, not the 300 mA that U3 passes on to +3V3.
        u1 = _ldo("U1", "LDO1", 24.0, 12.0, [1e-6], "+12V")
        u1["input_rail"] = "+12V"
        u2 = _buck("U2", 24.0, 12.0, 0.2, "+12V")
        u2["topology"] = "ic_with_internal_regulator"
        u3 = _ldo("U3", "LDO3", 12.0, 3.3, [1e-6], "+3V3")
        u3["input_rail"] = "+12V"
        out = self.run_thermal(
            [u1, u2, u3],
            {"+12V": {"estimated_load_mA": 50, "ics": [{"ref": "U3", "value": "LDO3", "estimated_mA": 10}]},
             "+3V3": 300},
            [_fp("U1", "Package_TO_SOT_SMD:SOT-223-3_TabPin2"),
             _fp("U2", "Package_TO_SOT_SMD:SOT-223-3_TabPin2", x=40.0),
             _fp("U3", "Package_TO_SOT_SMD:SOT-223-3_TabPin2", x=70.0)])
        self.assertAlmostEqual(self.of(out, "U1")[0]["pdiss_w"], 0.6)
        self.assertAlmostEqual(self.of(out, "U2")[0]["pdiss_w"], 0.1059)

    def test_negative_ldo_feeding_a_regulator_ic_carries_its_load(self):
        # U11 -15 V -> -8 V feeds U1, an LT3094 read as an IC with an internal regulator, whose V- rail
        # draws 150 mA: 7 V x 0.15 A = 1.05 W in TO-220, no thermal vias.
        u11 = _ldo("U11", "LM7908", -15.0, -8.0, [1e-6], "-8V")
        u11["power_dissipation"]["dropout_V"] = 7.0
        u1 = {"detector": "detect_power_regulators", "ref": "U1", "value": "LT3094xMSE",
              "topology": "ic_with_internal_regulator", "input_rail": "-8V", "output_rail": "V-"}
        out = self.run_thermal(
            [u11, u1],
            {"-8V": {"estimated_load_mA": 10, "ics": [{"ref": "U1", "value": "LT3094xMSE", "estimated_mA": 10}]},
             "V-": 150},
            [_fp("U11", "Package_TO_SOT_THT:TO-220-3_Vertical")])
        a, findings = self.of(out, "U11")
        self.assertAlmostEqual(a["pdiss_w"], 1.05)
        self.assertIn(("TS-004", "warning"), findings)

if __name__ == "__main__":
    unittest.main()
