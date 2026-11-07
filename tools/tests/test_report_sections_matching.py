"""check_report_sections gives each report header to one required section only."""
import os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    import check_report_sections as crs
finally:
    sys.path.pop(0)


def _check(headers, envs):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "report.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(f"## {h}" for h in headers) + "\n")
        return crs.check_report(path, crs.required_sections(envs))


BASE_H = [label for label, _ in crs.BASE_SECTIONS]
GERBER_ENVS = {"schematic": {}, "gerber": {}}


class OneHeaderPerSection(unittest.TestCase):
    def test_full_report_passes(self):
        self.assertEqual(_check(BASE_H + ["Gerber Verification"], GERBER_ENVS), [])

    def test_gerber_header_does_not_also_satisfy_analyzer_verification(self):
        headers = [h for h in BASE_H if h != "Analyzer Verification"] + ["Gerber Verification"]
        self.assertEqual(_check(headers, GERBER_ENVS), ["Analyzer Verification"])

    def test_gerber_verification_alone_satisfies_gerber(self):
        self.assertEqual(_check(BASE_H, GERBER_ENVS), ["Gerber Verification"])
        self.assertNotIn("Gerber Verification", _check(BASE_H + ["Gerber Verification"], GERBER_ENVS))

    def test_a_bare_verification_header_still_satisfies_analyzer_verification(self):
        headers = [h for h in BASE_H if h != "Analyzer Verification"] + ["Verification"]
        self.assertEqual(_check(headers, {"schematic": {}}), [])

    def test_one_header_counts_once(self):
        headers = [h for h in BASE_H if h != "Power Tree"] + ["Power Tree and Power Sequencing"]
        missing = _check(headers, {"schematic": {"power_sequencing": [1]}})
        self.assertEqual(len(missing), 1)
        self.assertIn(missing[0], ("Power Tree", "Power Sequencing"))

    def test_components_header_still_counts(self):
        headers = [h for h in BASE_H if h != "Component Summary"] + ["Components"]
        self.assertEqual(_check(headers, {"schematic": {}}), [])


if __name__ == "__main__":
    unittest.main()
