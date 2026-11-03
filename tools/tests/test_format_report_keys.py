"""The Action report reads the keys the analyzers emit: PCB dimensions/DFM from dfm_summary,
divider refs from r_top/r_bottom, filter refs and frequencies from resistor/inductor/capacitor
and cutoff_hz/resonant_hz, single-pin nets as '<net> (<ref> pin <n>)'."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from tools.tests._fixtures import fixture, fixture_path, have

ROOT = Path(__file__).resolve().parents[2]
FR = ROOT / "action" / "format-report.py"
KS = ROOT / "skills" / "kicad" / "scripts"
FX = fixture_path()
PLACEHOLDERS = ("? × ?", "Vout=None", "{'ref'", "Single-pin net: {", "DFM: ?", "| DFM tier | ? |")


def _run(*args):
    r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r


def _render(tmp, **inputs):
    out, full = os.path.join(tmp, "fr.md"), os.path.join(tmp, "frfull.md")
    args = [FR, "--output", out, "--output-full", full]
    for k, v in inputs.items():
        args += [f"--{k}", v]
    _run(*args)
    with open(out, encoding="utf-8") as f, open(full, encoding="utf-8") as g:
        return f.read(), g.read()


@unittest.skipUnless(have(FX / "simple-project" / "simple.kicad_pcb"), "fixtures absent")
class FixtureReportTest(unittest.TestCase):
    def assertNoPlaceholders(self, *texts):
        for t in texts:
            for p in PLACEHOLDERS:
                self.assertNotIn(p, t)

    def test_simple_project_pcb_dimensions_and_dfm(self):
        with tempfile.TemporaryDirectory() as tmp:
            sch, pcb = os.path.join(tmp, "sch.json"), os.path.join(tmp, "pcb.json")
            _run(KS / "analyze_schematic.py", FX / "simple-project" / "simple.kicad_sch", "--output", sch)
            _run(KS / "analyze_pcb.py", FX / "simple-project" / "simple.kicad_pcb", "--output", pcb)
            with open(pcb, encoding="utf-8") as f:
                m = json.load(f)["dfm_summary"]
            md, full = _render(tmp, schematic=sch, pcb=pcb)
        w, h = m["metrics"]["board_width_mm"], m["metrics"]["board_height_mm"]
        self.assertIn(f"{w} × {h}mm", md)
        self.assertIn(f"DFM: {m['dfm_tier']}", md)
        self.assertIn(f"| Dimensions | {w} × {h} mm |", full)
        self.assertIn(f"| Min track | {m['metrics']['min_track_width_mm']} mm |", full)
        self.assertNoPlaceholders(md, full)

    def test_usb_dual_esd_dividers_and_single_pin_nets(self):
        sch_src = fixture("determinism", "usb_dual_esd.kicad_sch")
        with tempfile.TemporaryDirectory() as tmp:
            sch = os.path.join(tmp, "sch.json")
            _run(KS / "analyze_schematic.py", sch_src, "--output", sch)
            with open(sch, encoding="utf-8") as f:
                d = json.load(f)
            md, full = _render(tmp, schematic=sch)
        vd = next(x for x in d["findings"] if x.get("detector") == "detect_voltage_dividers")
        self.assertIn(f"- {vd['r_top']['ref']} / {vd['r_bottom']['ref']}: ratio=", full)
        sp = d["connectivity_issues"]["single_pin_nets"][0]
        self.assertIn(f"Single-pin net: {sp['net']} ({sp['pin']['component']} pin {sp['pin']['pin_number']})", md)
        self.assertNoPlaceholders(md, full)


class FilterRowsTest(unittest.TestCase):
    def test_rc_and_lc_rows(self):
        # Shapes as signal_detectors emits them (detect_rc_filters / detect_lc_filters).
        rc = {"detector": "detect_rc_filters", "rule_id": "RC-DET", "type": "low-pass",
              "resistor": {"ref": "R19", "value": "100k", "ohms": 100000.0},
              "capacitor": {"ref": "C18", "value": "2 caps parallel", "farads": 1.01e-09,
                            "parallel_caps": ["C18", "C20"]},
              "cutoff_hz": 1575.8}
        lc = {"detector": "detect_lc_filters", "rule_id": "LC-DET",
              "inductor": {"ref": "L1", "value": "2.2u", "henries": 2.2e-06},
              "capacitor": {"ref": "C7", "value": "10u", "farads": 1e-05},
              "resonant_hz": 33932.5}
        with tempfile.TemporaryDirectory() as tmp:
            sch = os.path.join(tmp, "sch.json")
            with open(sch, "w", encoding="utf-8") as f:
                json.dump({"analyzer_type": "schematic", "findings": [rc, lc]}, f)
            _, full = _render(tmp, schematic=sch)
        self.assertIn("- R19 + C18, C20: fc = 1.6 kHz (low-pass)", full)
        self.assertIn("- L1 + C7: fc = 33.9 kHz\n", full)
        self.assertNotIn("{'ref'", full)


class SpiceCountsTest(unittest.TestCase):
    def test_spice_counts_add_up_to_total(self):
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "skills" / "spice" / "scripts"))
        from spice_results import build_report
        runs = [{"subcircuit_type": "rc_filter", "components": ["R1", "C1"], "status": s}
                for s in ("pass", "warn", "fail", "skip", "info", "info")]
        rc = {"detector": "detect_rc_filters", "rule_id": "RC-DET", "type": "low-pass",
              "resistor": {"ref": "R1", "value": "1k", "ohms": 1000.0},
              "capacitor": {"ref": "C1", "value": "10n", "farads": 1e-08}, "cutoff_hz": 15915.5}
        with tempfile.TemporaryDirectory() as tmp:
            sch, sp = os.path.join(tmp, "sch.json"), os.path.join(tmp, "spice.json")
            with open(sch, "w", encoding="utf-8") as f:
                json.dump({"analyzer_type": "schematic", "findings": [rc]}, f)
            with open(sp, "w", encoding="utf-8") as f:
                json.dump(build_report(runs), f)
            md, full = _render(tmp, schematic=sch, spice=sp)
        self.assertIn("6 subcircuits — **1 pass**, 1 warn, 1 fail, 1 skip, 2 info", md)
        self.assertIn("6 subcircuits verified: 1 pass, 1 warn, 1 fail, 1 skip, 2 info", full)


def _vd(rule, severity, summary):
    return {"detector": "analyze_voltage_derating", "rule_id": rule, "category": "component_derating",
            "summary": summary, "severity": severity, "confidence": "heuristic",
            "evidence_source": "topology", "components": ["R1"], "nets": ["VCC"]}


class DeratingFindingsTest(unittest.TestCase):
    """VD-* findings live in findings[]: errors set has_critical, warnings count, info adds no row."""

    def _render(self, findings):
        with tempfile.TemporaryDirectory() as tmp:
            sch, summ = os.path.join(tmp, "sch.json"), os.path.join(tmp, "summary.json")
            with open(sch, "w", encoding="utf-8") as f:
                json.dump({"analyzer_type": "schematic", "findings": findings}, f)
            md, full = _render(tmp, schematic=sch, **{"output-summary": summ})
            with open(summ, encoding="utf-8") as f:
                return json.load(f), md, full

    def test_vd_error_sets_has_critical(self):
        text = "R1 (10k) 0805 exceeds power rating at 1.2W"
        s, md, full = self._render([_vd("VD-003", "error", text)])
        self.assertTrue(s["has_critical"])
        self.assertEqual(s["findings_count"], 1)
        self.assertEqual(md.count(text), 1)
        crit = full.split("## Critical Findings")[1].split("\n## ")[0]
        self.assertEqual(crit.count(text), 1)
        self.assertIn(f"| CRITICAL | {text} | Voltage Derating |", crit)
        self.assertEqual(full.count(text), 2)  # critical table + derating detail table

    def test_vd_warning_counts_without_critical(self):
        s, _, _ = self._render([_vd("VD-001", "warning", "C1 has marginal derating")])
        self.assertEqual(s["findings_count"], 1)
        self.assertFalse(s["has_critical"])

    def test_vd_info_adds_no_row(self):
        s, _, full = self._render([_vd("VD-004", "info", "C2 is over-designed")])
        self.assertEqual(s["findings_count"], 0)
        self.assertNotIn("| CRITICAL | C2", full)
        self.assertNotIn("| WARNING | C2", full)

    def test_other_schematic_error_does_not_gate(self):
        other = dict(_vd("SS-001", "error", "U1 has no MPN"), detector="audit_sourcing_gate")
        s, _, _ = self._render([other])
        self.assertFalse(s["has_critical"])
        self.assertEqual(s["findings_count"], 0)


if __name__ == "__main__":
    unittest.main()
