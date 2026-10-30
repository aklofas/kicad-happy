"""what_if runs SPICE and the EMC preview on the patched design, and its export replaces the
patched findings without touching others that share their detection_id.

Expected values are hand arithmetic (RC cutoff 1/(2*pi*R*C), divider Vin*Rb/(Rt+Rb) at the
testbench's 3.3 V) or counted by hand from recorded analyzer output (dangrie158/AmpStation
AmplifierBoard; celeritous STM32F745VE_Module REV1.0 -> REV1.1 EMC)."""
import copy, json, math, os, shutil, subprocess, sys, tempfile, types, unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
WHAT_IF = SCRIPTS / "what_if.py"
sys.path.insert(0, str(SCRIPTS))
import what_if  # noqa: E402

_NO_CREDS = ("DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET", "MOUSER_SEARCH_API_KEY", "ELEMENT14_API_KEY")


def _finding(detector, rule_id, did, fid, summary, components, **fields):
    f = dict(fields)
    f.update({"detector": detector, "rule_id": rule_id, "category": "x", "severity": "info",
              "confidence": "deterministic", "evidence_source": "topology", "summary": summary,
              "components": components, "nets": [], "pins": [], "detection_id": did,
              "finding_id": fid})
    return f


# AmplifierBoard: RC filter R49/C101 and the two dividers sharing R13 (fields as analyze_schematic emits)
RC_R49 = _finding("detect_rc_filters", "RC-DET", "rc_filters:a320da0de752",
                  "schematic:rc_filters-a320da0de752", "RC filter R49/C101 at 15.92Hz", ["C101", "R49"],
                  type="RC-network", resistor={"ref": "R49", "value": "1k", "ohms": 1000.0},
                  capacitor={"ref": "C101", "value": "10µF", "farads": 1e-05},
                  cutoff_hz=15.92, time_constant_s=0.01, input_net="__unnamed_4",
                  output_net="__unnamed_5", ground_net="__unnamed_7")
VD_R10 = _finding("detect_voltage_dividers", "VD-DET", "voltage_dividers:c97412abd138",
                  "schematic:voltage_dividers-c97412abd138", "Voltage divider R10/R13", ["R10", "R13"],
                  r_top={"ref": "R10", "value": "1.8k", "ohms": 1800.0},
                  r_bottom={"ref": "R13", "value": "3k3", "ohms": 3300.0},
                  top_net="__unnamed_85", mid_net="__unnamed_68", bottom_net="GNDA", ratio=0.647059)
VD_R12 = _finding("detect_voltage_dividers", "VD-DET", "voltage_dividers:f897aba22efb",
                  "schematic:voltage_dividers-f897aba22efb", "Voltage divider R12/R13", ["R12", "R13"],
                  r_top={"ref": "R12", "value": "680", "ohms": 680.0},
                  r_bottom={"ref": "R13", "value": "3k3", "ohms": 3300.0},
                  top_net="__unnamed_67", mid_net="__unnamed_68", bottom_net="GNDA", ratio=0.829146)

# AmplifierBoard decoupling: seven findings, one constant detection_id, positional finding_ids
_DC_RAILS = [("VDC", ["C77", "C39"]), ("+12V", ["C37", "C35", "C11", "C14"]), ("+5V", ["C38", "C62"]),
             ("-12V", ["C60", "C40", "C98"]), ("+3V3", ["C63", "C55", "C52"]), ("-5V", ["C61"]),
             ("+9V", ["C78"])]


def _decoupling():
    out = []
    for i, (rail, caps) in enumerate(_DC_RAILS):
        farads = {"C11": 0.00047}
        capl = [{"ref": c, "value": "100nF", "farads": farads.get(c, 1e-07)} for c in caps]
        out.append(_finding("detect_decoupling", "DC-DET", "decoupling_analysis:9a1adf60f6b2",
                            "schematic:decoupling_analysis-9a1adf60f6b2" + (f"#{i}" if i else ""),
                            f"Decoupling on {rail}", sorted(caps), rail=rail, capacitors=capl,
                            total_capacitance_uF=round(sum(c["farads"] for c in capl) * 1e6, 1),
                            cap_count=len(capl)))
    return out


def _components(refs_values):
    return [{"reference": r, "type": {"R": "resistor", "C": "capacitor"}[r[0]], "value": v,
             "parsed_value": pv} for r, v, pv in refs_values]


AMP_COMPONENTS = _components([("R49", "1k", 1000.0), ("C101", "10µF", 1e-05),
                              ("R10", "1.8k", 1800.0), ("R12", "680", 680.0), ("R13", "3k3", 3300.0),
                              ("C14", "100nF 16V", 1e-07), ("R99", "4.7k", 4700.0)])


def _run(analysis, *args):
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "sch.json")
        out = os.path.join(tmp, "patched.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(analysis, f)
        args = [out if a == "{OUT}" else a for a in args]
        env = {k: v for k, v in os.environ.items() if k not in _NO_CREDS}
        r = subprocess.run([sys.executable, str(WHAT_IF), p, *args], capture_output=True,
                           text=True, encoding="utf-8", cwd=tmp, env=env, timeout=240)
        exported = None
        if os.path.exists(out):
            with open(out, encoding="utf-8") as f:
                exported = json.load(f)
    return r, exported


def _amp():
    return {"analyzer_type": "schematic", "findings": [RC_R49, VD_R10, VD_R12] + _decoupling(),
            "components": AMP_COMPONENTS}


class SpiceSeesThePatchedDetection(unittest.TestCase):
    """The simulator is handed findings[] holding exactly the detection under test."""

    def _stub(self, seen):
        fake = types.ModuleType("simulate_subcircuits")

        def sim(mini, **kw):
            seen.append((copy.deepcopy(mini), kw))
            det = mini["findings"][0]
            return {"simulation_results": [{"status": "pass",
                                            "simulated": {"r_ohms": det["resistor"]["ohms"]}}]}
        fake.simulate_subcircuits = sim
        stub_sim = types.ModuleType("spice_simulator")
        stub_sim.detect_simulator = lambda name: "stub"
        return {"simulate_subcircuits": fake, "spice_simulator": stub_sim}

    def test_each_run_gets_one_finding_and_the_offline_option(self):
        seen = []
        affected = [("rc_filters", 0, RC_R49, {})]
        patched = copy.deepcopy(RC_R49)
        patched["resistor"]["ohms"] = 2000.0
        with mock.patch.dict(sys.modules, self._stub(seen)):
            res = what_if._run_spice_comparison(affected, [patched], {"findings": [], "components": []},
                                                offline=True)
        self.assertEqual([len(m["findings"]) for m, _ in seen], [1, 1])
        self.assertEqual([m["findings"][0]["resistor"]["ohms"] for m, _ in seen], [1000.0, 2000.0])
        self.assertTrue(all(kw["model_options"].offline for _, kw in seen))
        self.assertEqual(res[("rc_filters", 0)]["r_ohms"], {"before": 1000.0, "after": 2000.0,
                                                           "delta_pct": 100.0})


@unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
class SpiceOnThePatchedValues(unittest.TestCase):
    def _spice(self, change):
        r, _ = _run(_amp(), change, "--spice", "--offline")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(out["summary"]["spice_verified"], out)
        return {s["label"]: s.get("spice_delta", {}) for s in out["affected_subcircuits"]}

    def test_rc_cutoff_follows_the_new_resistor(self):
        d = self._spice("R49=2k")["rc filter R49/C101"]["cutoff_hz"]
        self.assertAlmostEqual(d["before"], 1 / (2 * math.pi * 1000 * 10e-6), delta=0.16)  # 15.92
        self.assertAlmostEqual(d["after"], 1 / (2 * math.pi * 2000 * 10e-6), delta=0.08)   # 7.96

    def test_both_dividers_on_the_changed_resistor(self):
        got = self._spice("R13=4.7k")
        for label, rt in (("voltage divider R10/R13", 1800), ("voltage divider R12/R13", 680)):
            d = got[label]["vout_V"]
            self.assertAlmostEqual(d["before"], 3.3 * 3300 / (rt + 3300), delta=0.005, msg=label)
            self.assertAlmostEqual(d["after"], 3.3 * 4700 / (rt + 4700), delta=0.005, msg=label)


class SpiceFlagScope(unittest.TestCase):
    def test_spice_with_a_sweep_is_a_usage_error(self):
        r, _ = _run(_amp(), "R49=1k..10k:3", "--spice")
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("--spice", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


def _emc(score, findings):
    fs = [{"finding_id": fid, "rule_id": rule, "severity": sev, "summary": summ,
           "components": comps, "nets": nets, "category": "x", "detector": "emc"}
          for fid, rule, sev, summ, comps, nets in findings]
    return {"analyzer_type": "emc", "summary": {"emc_risk_score": score}, "findings": fs}


_CLOCKS = ["/ETH_REF_CLK", "/JTAG_SWCLK", "/MCLKOUT", "/OSC32IN", "/OSC32OUT", "/OSCHSIN",
           "/OSCHSOUT", "/SPI2_SCK", "/SPI4_SCK"]


def _stm32(rev):
    common = ([("emc:GP-001:c6f889950823", "GP-001", "info", "Return path analysis data not available", [], [])]
              + [(f"emc:IO-002:{r.lower()}", "IO-002", s, f"Insufficient ground pins on {r}", [r], [])
                 for r, s in (("J1", "warning"), ("P2", "info"), ("P3", "info"))]
              + [(f"emc:CK-001:{n.lower()}", "CK-001", "warning", f"Clock {n} on outer layer", [], [n])
                 for n in _CLOCKS]
              + [("emc:EE-001:14ba23cdf0dc", "EE-001", "info", "Board cavity resonance frequencies", [], [])])
    if rev == "1.0":
        dc = [("emc:DC-001:u3", "DC-001", "error", "Decoupling cap too far from U3", ["U3", "C19", "C14"], []),
              ("emc:DC-001:u4", "DC-001", "warning", "Decoupling cap moderately far from U4",
               ["U4", "C16", "C21"], [])]
        return _emc(74.5, dc + common)
    dc = [("emc:DC-001:u3", "DC-001", "warning", "Decoupling cap moderately far from U3",
           ["U3", "C13", "C18"], [])]
    return _emc(86.5, dc + common)


def _preview(before, after):
    outputs = [before, after]

    def fake_run(cmd, **kw):
        with open(cmd[cmd.index("--output") + 1], "w", encoding="utf-8") as f:
            json.dump(outputs.pop(0), f)
        return subprocess.CompletedProcess(cmd, 0)
    with mock.patch("subprocess.run", fake_run):
        return what_if._run_emc_preview({}, {})


class EmcPreview(unittest.TestCase):
    def test_recorded_revision_pair(self):
        got = _preview(_stm32("1.0"), _stm32("1.1"))
        self.assertEqual((got["before_risk"], got["after_risk"]), (74.5, 86.5))
        self.assertEqual([(r["rule"], r["detail"]) for r in got["resolved"]],
                         [("DC-001", "Decoupling cap moderately far from U4")])
        self.assertEqual(got["improved"], [{"rule": "DC-001", "before": "error", "after": "warning",
                                            "detail": "Decoupling cap moderately far from U3"}])
        self.assertEqual((got["worsened"], got["new_findings"], got["unchanged"]), ([], [], 14))

    def test_hand_case(self):
        before = _emc(50, [("emc:A:1", "A", "error", "a", ["U1"], []), ("emc:B:1", "B", "warning", "b", [], [])])
        after = _emc(60, [("emc:A:1", "A", "warning", "a", ["U1"], []), ("emc:C:1", "C", "info", "c", [], [])])
        got = _preview(before, after)
        self.assertEqual([r["rule"] for r in got["resolved"]], ["B"])
        self.assertEqual([r["rule"] for r in got["improved"]], ["A"])
        self.assertEqual([r["rule"] for r in got["new_findings"]], ["C"])
        self.assertEqual((got["worsened"], got["unchanged"]), ([], 0))

    def test_worsened(self):
        before = _emc(80, [("emc:A:1", "A", "warning", "a", ["U1"], [])])
        after = _emc(70, [("emc:A:1", "A", "error", "a", ["U1"], [])])
        got = _preview(before, after)
        self.assertEqual(got["worsened"], [{"rule": "A", "before": "warning", "after": "error",
                                            "detail": "a"}])
        self.assertEqual((got["improved"], got["unchanged"]), ([], 0))

    def test_positional_twin_resolved_is_the_one_that_left(self):
        # Two same-stem findings; the bare id moves to the survivor in the after run
        before = _emc(70, [("emc:DC-001:x", "DC-001", "warning", "cap far from U1", ["U1", "C1"], []),
                           ("emc:DC-001:x#1", "DC-001", "warning", "cap far from U2", ["U2", "C2"], [])])
        after = _emc(75, [("emc:DC-001:x", "DC-001", "warning", "cap far from U2", ["U2", "C2"], [])])
        got = _preview(before, after)
        self.assertEqual([r["detail"] for r in got["resolved"]], ["cap far from U1"])
        self.assertEqual((got["new_findings"], got["unchanged"]), ([], 1))

    def test_text_names_score_and_worsened(self):
        result = {"changes": {}, "affected_subcircuits": [{"label": "x", "delta": []}],
                  "emc_delta": {"before_risk": 80, "after_risk": 70, "resolved": [], "improved": [],
                                "worsened": [{"rule": "A", "before": "warning", "after": "error"}],
                                "new_findings": [], "unchanged": 0}}
        text = what_if.format_text(result)
        self.assertIn("Overall risk score (100 = lowest risk): 80 → 70", text)
        self.assertIn("A: WORSENED — warning → error", text)


class Export(unittest.TestCase):
    def test_c14_keeps_the_other_decoupling_findings(self):
        analysis = _amp()
        r, exported = _run(analysis, "C14=10u", "-o", "{OUT}")
        self.assertEqual(r.returncode, 0, r.stderr)
        dc = [f for f in exported["findings"] if f["detector"] == "detect_decoupling"]
        self.assertEqual([f["rail"] for f in dc], [rail for rail, _ in _DC_RAILS])
        # false-output pin: the +9V finding is exported exactly as analysed
        self.assertEqual(dc[-1], analysis["findings"][-1])
        twelve = {c["ref"]: c["farads"] for c in dc[1]["capacitors"]}
        self.assertAlmostEqual(twelve["C14"], 10e-6, delta=1e-12)
        self.assertEqual(dc[1]["finding_id"], "schematic:decoupling_analysis-9a1adf60f6b2#1")
        unaffected = [f for i, f in enumerate(exported["findings"]) if i != 4]
        self.assertEqual(unaffected, [f for i, f in enumerate(analysis["findings"]) if i != 4])

    def test_scalar_parsed_value_follows_the_change(self):
        r, exported = _run(_amp(), "R49=2k", "-o", "{OUT}")
        self.assertEqual(r.returncode, 0, r.stderr)
        r49 = next(c for c in exported["components"] if c["reference"] == "R49")
        self.assertEqual((r49["value"], r49["parsed_value"]), ("2k", 2000.0))

    def test_before_is_the_analysed_value(self):
        r, _ = _run(_amp(), "R49=2k")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["changes"]["R49"]["before"], 1000.0)

    def test_before_is_set_when_nothing_is_affected(self):
        r, _ = _run(_amp(), "R99=10k")
        self.assertEqual(r.returncode, 0, r.stderr)
        info = json.loads(r.stdout)["changes"]["R99"]
        self.assertEqual((info["before"], info["before_str"]), (4700.0, "4.7k"))


if __name__ == "__main__":
    unittest.main()
