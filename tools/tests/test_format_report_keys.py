"""The Action report reads the keys the analyzers emit: PCB dimensions/DFM from dfm_summary,
divider refs from r_top/r_bottom, filter refs and frequencies from resistor/inductor/capacitor
and cutoff_hz/resonant_hz, single-pin nets as '<net> (<ref> pin <n>)'."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FR = ROOT / "action" / "format-report.py"
KS = ROOT / "skills" / "kicad" / "scripts"
FX = Path(os.environ.get("KH_FIXTURES", "/tmp/harness-pin/tests/fixtures"))
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


@unittest.skipUnless((FX / "simple-project" / "simple.kicad_pcb").is_file(), "fixtures absent")
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
        sch_src = FX / "determinism" / "usb_dual_esd.kicad_sch"
        if not sch_src.is_file():
            self.skipTest("fixture absent")
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


if __name__ == "__main__":
    unittest.main()
