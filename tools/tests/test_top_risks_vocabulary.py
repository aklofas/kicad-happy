"""Top Risks, summarize_findings and the schematic severity histogram speak the canonical vocabulary
(severity error/warning/info; confidence deterministic/heuristic/datasheet-backed)."""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from tools.tests._fixtures import fixture, fixture_path, have

ROOT = Path(os.environ.get("KH_PRODUCT_ROOT", Path(__file__).resolve().parents[2]))
KS = ROOT / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(KS))

from project_config import compute_top_risks  # noqa: E402
import summarize_findings as sf  # noqa: E402

FX = fixture_path()


def _f(sev, cat, rule, conf="deterministic"):
    return {"severity": sev, "confidence": conf, "category": cat, "rule_id": rule}


class TopRisksTest(unittest.TestCase):
    def test_top_risks_canonical_severity(self):
        r = compute_top_risks([_f("error", "thermal_safety", "TS-001"),
                               _f("warning", "ground_plane", "GP-001"),
                               _f("info", "ground_plane", "GP-002")])
        self.assertEqual([f["rule_id"] for f in r["bringup"]], ["TS-001"])
        self.assertEqual([f["rule_id"] for f in r["respin"]], ["GP-001"])

    def test_legacy_severity_still_scores(self):
        r = compute_top_risks([_f("HIGH", "thermal_safety", "TS-009")])
        self.assertEqual([f["rule_id"] for f in r["bringup"]], ["TS-009"])

    def test_top_risks_missing_keys(self):
        r = compute_top_risks([{"category": "ground_plane", "rule_id": "A"},
                               {"severity": "bogus", "category": "ground_plane", "rule_id": "B"},
                               {"severity": None, "confidence": ["x"], "category": "ground_plane"},
                               _f("error", "ground_plane", "C", conf="unheard-of")])
        self.assertEqual([f["rule_id"] for f in r["respin"]], ["C"])


@unittest.skipUnless(have(FX / "action-format-report" / "emc_v14_aslanpad_macropad.json"), "fixtures absent")
class ActionReportTest(unittest.TestCase):
    def test_action_report_has_top_risks(self):
        # The fixture holds an error ground_plane finding (respin bucket).
        emc = fixture("action-format-report/emc_v14_aslanpad_macropad.json")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "r.md")
            r = subprocess.run([sys.executable, str(ROOT / "action" / "format-report.py"),
                                "--emc", str(emc), "--output", out,
                                "--output-full", os.path.join(tmp, "f.md")],
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out, encoding="utf-8") as f:
                text = f.read()
        self.assertIn("### Top Risks", text)
        self.assertIn("PCB Respin Risks", text)


class SummarizeVocabularyTest(unittest.TestCase):
    def test_summarize_confidence_vocabulary(self):
        rows = sf._aggregate([
            {"rule_id": "X", "severity": "error", "confidence": "datasheet-backed"},
            {"rule_id": "X", "severity": "error", "confidence": "heuristic"}])
        self.assertEqual(rows[0]["by_confidence"],
                         {"deterministic": 0, "heuristic": 1, "datasheet_backed": 1})

    def test_filters_accept_canonical_names(self):
        fs = [{"confidence": "datasheet-backed", "evidence_source": "api_lookup"},
              {"confidence": "heuristic", "evidence_source": "bom"}]
        self.assertEqual(sf._filter_confidence(fs, "datasheet-backed"), fs[:1])
        self.assertEqual(sf._filter_confidence(fs, "datasheet_backed"), fs[:1])
        self.assertEqual(sf._filter_evidence_source(fs, "api_lookup"), fs[:1])
        self.assertEqual(sf._filter_evidence_source(fs, "symbol_footprint"), [])


@unittest.skipUnless(have(FX / "simple-project" / "simple.kicad_sch"), "fixtures absent")
class PresentationHistogramTest(unittest.TestCase):
    def test_presentation_histogram_counts_error(self):
        from schematic.pipeline import analyze_schematic
        r = analyze_schematic(str(FX / "simple-project" / "simple.kicad_sch"))
        sevs = [f.get("severity") for f in r["findings"]]
        errors, warnings = sevs.count("error"), sevs.count("warning")
        self.assertGreater(errors, 0)
        bs = r["summary"]["by_severity"]
        self.assertEqual((bs["error"], bs["warning"], bs["info"]),
                         (errors, warnings, len(sevs) - errors - warnings))


if __name__ == "__main__":
    unittest.main()
