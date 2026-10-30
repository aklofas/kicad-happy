"""what_if tolerance corners, the crystal load-cap fix, log-sweep bounds, the values a
patched detection carries, and the -o export file.

Expected values are hand arithmetic: RC cutoff 1/(2*pi*R*C) at the +-tol corners, divider
ratio Rb/(Rt+Rb), crystal load C1*C2/(C1+C2) + Cs, time constant R*C, LDO dissipation
(Vin - Vout) * Iout, switching dissipation Vout * Iout * (1/eff - 1)."""
import copy, json, os, stat, subprocess, sys, tempfile, unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
WHAT_IF = SCRIPTS / "what_if.py"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import what_if  # noqa: E402
from detection_schema import recalc_derived  # noqa: E402
from test_what_if_patched_design import RC_R49, VD_R10, _amp, _emc, _preview, _run  # noqa: E402


def _subcircuit(out, label):
    return next(s for s in out["affected_subcircuits"] if s["label"] == label)


class Tolerance(unittest.TestCase):
    def test_unchanged_nominal_still_gets_corners(self):
        r, _ = _run(_amp(), "R49=1k±5%")
        self.assertEqual(r.returncode, 0, r.stderr)
        tol = _subcircuit(json.loads(r.stdout), "rc filter R49/C101")["tolerance"]
        # 1/(2*pi*1050*10u) = 15.158 Hz, 1/(2*pi*950*10u) = 16.753 Hz
        self.assertEqual(tol, [{"field": "cutoff_hz", "nominal": 15.92, "worst_low": 15.16,
                                "worst_high": 16.75, "spread_pct": 10.0}])

    def test_divider_ratio_corners(self):
        r, _ = _run(_amp(), "R13=3k3+-5%")
        self.assertEqual(r.returncode, 0, r.stderr)
        tol = _subcircuit(json.loads(r.stdout), "voltage divider R10/R13")["tolerance"]
        self.assertEqual([t["field"] for t in tol], ["ratio"])
        self.assertAlmostEqual(tol[0]["worst_low"], 3135 / (1800 + 3135), places=6)
        self.assertAlmostEqual(tol[0]["worst_high"], 3465 / (1800 + 3465), places=6)

    def test_field_the_part_does_not_move_is_not_listed(self):
        # false-output pin: an output cap's tolerance leaves the regulator's Vout where it is
        reg = copy.deepcopy(_REGULATOR)
        reg["output_capacitors"] = [{"ref": "C1", "value": "10u", "farads": 1e-05}]
        analysis = {"analyzer_type": "schematic", "findings": [reg],
                    "components": [{"reference": "C1", "type": "capacitor", "value": "10u"}]}
        r, _ = _run(analysis, "C1=10u+-10%")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["affected_subcircuits"][0]["tolerance"], [])


def _crystal(c_farads, value, target, source):
    caps = [{"ref": ref, "value": value, "farads": c_farads, "net": net, "package": "0603",
             "esr_ohm": 2.0, "dielectric": "X7R"}
            for ref, net in (("C54", "__unnamed_54"), ("C53", "__unnamed_60"))]
    eff = round(c_farads * 1e12 / 2 + 3.0, 2)
    err = (eff - target) / target * 100
    status = ("ok" if abs(err) <= 10 else "unverified" if source == "frequency_default"
              else "marginal" if abs(err) <= 25 else "out_of_spec")
    return {"reference": "Y1", "value": "12MHz", "frequency": 12000000.0, "load_caps": caps,
            "effective_load_pF": eff, "target_load_pF": target, "target_load_source": source,
            "load_cap_error_pct": round(err, 1), "load_cap_status": status,
            "detector": "detect_crystal_circuits", "rule_id": "XL-DET", "category": "timing",
            "severity": "info", "confidence": "deterministic", "evidence_source": "topology",
            "summary": "Crystal Y1 at 12000000.0Hz", "components": ["Y1"], "nets": [], "pins": [],
            "detection_id": "crystal_circuits:c0421a3faf7d",
            "finding_id": "schematic:crystal_circuits-c0421a3faf7d"}


def _suggest(xtal, *extra):
    analysis = {"analyzer_type": "schematic", "findings": [xtal],
                "components": [{"reference": "C54", "type": "capacitor", "value": xtal["load_caps"][0]["value"]},
                               {"reference": "C53", "type": "capacitor", "value": xtal["load_caps"][1]["value"]}]}
    r, _ = _run(analysis, "--suggest-fixes", *extra)
    return r


class CrystalFix(unittest.TestCase):
    def test_both_load_caps_change_together(self):
        # 10p/10p: 10*10/20 + 3 = 8.0 pF against 12 pF; ideal 2*(12-3) = 18 pF each,
        # 18*18/36 + 3 = 12.0 pF (one cap alone: 18*10/28 + 3 = 9.43 pF)
        r = _suggest(_crystal(1e-11, "10pF", 12.0, "parsed_from_value"))
        self.assertEqual(r.returncode, 0, r.stderr)
        fix = json.loads(r.stdout)["fix_suggestions"]
        self.assertEqual(len(fix), 1)
        self.assertEqual(fix[0]["delta_with_e24"], [{"field": "effective_load_pF", "before": 8.0,
                                                     "after": 12.0, "delta_pct": 50.0}])

    def test_no_fix_for_a_frequency_default_target(self):
        # false-output pin: a default-table target is a guess, so nothing is suggested
        r = _suggest(_crystal(1.8e-11, "18pF", 20.0, "frequency_default"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["fix_suggestions"], [])

    def test_no_fix_within_ten_percent(self):
        r = _suggest(_crystal(1.8e-11, "18pF", 12.5, "parsed_from_value"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["fix_suggestions"], [])


class LogSweepBounds(unittest.TestCase):
    def test_bound_at_or_below_zero_is_a_usage_error(self):
        for spec in ("R49=-1k..10k:3", "R49=0..10k:3"):
            r, _ = _run(_amp(), spec)
            self.assertEqual(r.returncode, 2, spec)
            self.assertIn("above zero", r.stderr)
            self.assertNotIn("Traceback", r.stderr)


_REGULATOR = {
    "ref": "U1301", "value": "LM27313XMFX/NOPB", "topology": "switching",
    "estimated_vout": 3.397, "assumed_vref": 0.6, "vref_source": "heuristic",
    "feedback_divider": {"r_top": {"ref": "R1303", "ohms": 62000.0, "value": "62k"},
                         "r_bottom": {"ref": "R1302", "ohms": 13300.0, "value": "13.3k"},
                         "ratio": 0.176627},
    "power_dissipation": {"vin_estimated_V": 12.0, "vout_V": 3.397, "efficiency_assumed": 0.85,
                          "estimated_iout_A": 1.0, "estimated_pdiss_W": 0.599,
                          "topology": "switching", "sub_topology": "buck"},
    "detector": "detect_power_regulators", "rule_id": "PR-DET", "category": "power_management",
    "severity": "info", "confidence": "deterministic", "evidence_source": "topology",
    "summary": "Regulator U1301 switching", "components": ["U1301"], "nets": [], "pins": [],
}


def _ldo(vin):
    det = copy.deepcopy(_REGULATOR)
    det.update(topology="LDO", estimated_vout=3.397)
    det["power_dissipation"] = {"vin_estimated_V": vin, "vout_V": 3.397, "dropout_V": round(vin - 3.397, 3),
                                "estimated_iout_A": 0.1,
                                "estimated_pdiss_W": round((vin - 3.397) * 0.1, 3)}
    return det


class DerivedTwins(unittest.TestCase):
    def test_patched_rc_time_constant(self):
        r, exported = _run(_amp(), "R49=2k", "-o", "{OUT}")
        self.assertEqual(r.returncode, 0, r.stderr)
        rc = next(f for f in exported["findings"] if f["detector"] == "detect_rc_filters")
        self.assertAlmostEqual(rc["time_constant_s"], 2000 * 10e-6, places=12)  # 0.02 s
        self.assertEqual(rc["cutoff_hz"], 7.96)

    def test_crystal_error_and_status_follow_the_load(self):
        det = _crystal(1e-11, "10pF", 12.0, "parsed_from_value")
        for cap in det["load_caps"]:
            cap["farads"] = 1.8e-11
        recalc_derived(det, "crystal_circuits")
        self.assertEqual((det["effective_load_pF"], det["load_cap_error_pct"], det["load_cap_status"]),
                         (12.0, 0.0, "ok"))

    def test_crystal_default_target_miss_stays_unverified(self):
        det = _crystal(1.8e-11, "18pF", 20.0, "frequency_default")
        for cap in det["load_caps"]:
            cap["farads"] = 1e-11
        recalc_derived(det, "crystal_circuits")
        # (8.0 - 20) / 20 = -60 %
        self.assertEqual((det["effective_load_pF"], det["load_cap_error_pct"], det["load_cap_status"]),
                         (8.0, -60.0, "unverified"))

    def test_switching_dissipation_at_the_new_vout(self):
        det = copy.deepcopy(_REGULATOR)
        det["feedback_divider"]["r_bottom"]["ohms"] = 10000.0
        recalc_derived(det, "power_regulators")
        pd = det["power_dissipation"]
        # Vout 0.6 / (10k/72k) = 4.32 V; 4.32 * 1.0 * (1/0.85 - 1) = 0.7624 W
        self.assertEqual((det["estimated_vout"], pd["vout_V"], pd["estimated_pdiss_W"]), (4.32, 4.32, 0.762))

    def test_ldo_dissipation_at_the_new_vout(self):
        det = _ldo(5.0)
        det["feedback_divider"]["r_bottom"]["ohms"] = 10000.0
        recalc_derived(det, "power_regulators")
        pd = det["power_dissipation"]
        # dropout 5.0 - 4.32 = 0.68 V; 0.68 * 0.1 = 0.068 W
        self.assertEqual((pd["vout_V"], pd["dropout_V"], pd["estimated_pdiss_W"]), (4.32, 0.68, 0.068))

    def test_ldo_out_of_headroom_has_no_dissipation_block(self):
        det = _ldo(4.0)
        det["feedback_divider"]["r_bottom"]["ohms"] = 10000.0  # 4.32 V > 4.0 V in
        recalc_derived(det, "power_regulators")
        self.assertNotIn("power_dissipation", det)

    def test_unchanged_vout_keeps_the_analysed_block(self):
        det = copy.deepcopy(_REGULATOR)
        det["power_dissipation"]["estimated_pdiss_W"] = 0.6  # as analysed, from the unrounded current
        recalc_derived(det, "power_regulators")
        self.assertEqual(det["power_dissipation"], dict(_REGULATOR["power_dissipation"],
                                                        estimated_pdiss_W=0.6))


class EmcRowsCarryDetail(unittest.TestCase):
    def test_two_same_rule_changes_are_told_apart(self):
        before = _emc(70, [("emc:DC-001:u1", "DC-001", "error", "cap far from U1", ["U1"], []),
                           ("emc:DC-001:u2", "DC-001", "warning", "cap far from U2", ["U2"], [])])
        after = _emc(75, [("emc:DC-001:u1", "DC-001", "warning", "cap far from U1", ["U1"], []),
                          ("emc:DC-001:u2", "DC-001", "error", "cap far from U2", ["U2"], [])])
        got = _preview(before, after)
        self.assertEqual(got["improved"], [{"rule": "DC-001", "before": "error", "after": "warning",
                                            "detail": "cap far from U1"}])
        self.assertEqual(got["worsened"], [{"rule": "DC-001", "before": "warning", "after": "error",
                                            "detail": "cap far from U2"}])
        text = what_if.format_text({"changes": {}, "affected_subcircuits": [{"label": "x", "delta": []}],
                                    "emc_delta": got})
        self.assertIn("DC-001: IMPROVED — error → warning (cap far from U1)", text)
        self.assertIn("DC-001: WORSENED — warning → error (cap far from U2)", text)


class Export(unittest.TestCase):
    def test_parsed_value_set_when_the_analysis_has_none(self):
        analysis = _amp()
        for comp in analysis["components"]:
            if comp["reference"] == "R49":
                comp["parsed_value"] = None
            if comp["reference"] == "C101":
                del comp["parsed_value"]
        r, exported = _run(analysis, "R49=2k", "C101=22u", "-o", "{OUT}")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = {c["reference"]: c.get("parsed_value") for c in exported["components"]}
        self.assertEqual(got["R49"], 2000.0)
        self.assertAlmostEqual(got["C101"], 22e-6, delta=1e-15)

    def _write(self, tmp, out, preexec=None):
        src = os.path.join(tmp, "sch.json")
        analysis = _amp()
        analysis["components"][0]["value"] = "1k Ω"  # raw UTF-8 in the input
        with open(src, "w", encoding="utf-8") as f:
            json.dump(analysis, f, ensure_ascii=False)
        env = {k: v for k, v in os.environ.items() if not k.startswith("LC_") and k != "LANG"}
        env.update(LC_ALL="POSIX", PYTHONCOERCECLOCALE="0", PYTHONUTF8="0")
        return subprocess.run([sys.executable, "-X", "utf8=0", str(WHAT_IF), src, "R49=2k", "-o", out],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              cwd=tmp, env=env, timeout=120, preexec_fn=preexec)

    def test_utf8_input_under_an_ascii_locale(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "patched.json")
            r = self._write(tmp, out)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out, encoding="utf-8") as f:
                comps = {c["reference"]: c for c in json.load(f)["components"]}
            self.assertEqual(comps["R49"]["value"], "2k")
            self.assertEqual(sorted(os.listdir(tmp)), ["patched.json", "sch.json"])

    @unittest.skipIf(os.name == "nt", "POSIX modes")
    def test_new_file_gets_the_umask_mode_and_an_existing_one_keeps_its_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "patched.json")
            r = self._write(tmp, out, preexec=lambda: os.umask(0o027))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(stat.S_IMODE(os.stat(out).st_mode), 0o640)
            os.chmod(out, 0o604)
            r = self._write(tmp, out, preexec=lambda: os.umask(0o077))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(stat.S_IMODE(os.stat(out).st_mode), 0o604)
            self.assertEqual(sorted(os.listdir(tmp)), ["patched.json", "sch.json"])


if __name__ == "__main__":
    unittest.main()
