import json, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "datasheets" / "scripts" / "datasheet_verify.py"
sys.path.insert(0, str(ROOT / "skills" / "datasheets" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
import datasheet_verify as dv  # noqa: E402


def _ext(pins, **extra):
    d = {"base": {"pinout": pins, "recommended_operating": {"VDD33": []}}}
    d.update(extra)
    return d


def _pin(n, pd=None):
    p = {"name": f"P{n}", "numbers": [str(n)]}
    if pd is not None:
        p["power_domain"] = pd
    return p


def _run(extraction, *, flag):
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "X.json"
        f.write_text(json.dumps(extraction))
        args = ["--mpn", "X", "--extract-dir", td, "--self-consistency", "--json"] if flag else [str(f)]
        return subprocess.run([sys.executable, str(SCRIPT), *args],
                              capture_output=True, text=True)


class VerifyCli(unittest.TestCase):
    def test_warnings_only_exit_0(self):
        for flag in (False, True):
            r = _run(_ext([_pin(1, "3V3")]), flag=flag)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["count"], 1)
            rows = out["violations"] if flag else out["issues"]
            self.assertEqual(rows[0]["severity"], "warning")

    def test_error_still_exit_1(self):
        e = _ext([_pin(1)], regulator={"feedback_pin": "99"})
        for flag in (False, True):
            self.assertEqual(_run(e, flag=flag).returncode, 1)

    def test_power_domain_warning_grouped(self):
        issues = dv.verify_v14_extraction(_ext([_pin(i, "3V3") for i in (1, 2, 3)]))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["path"], "base.pinout[0].power_domain")
        for needle in ("3 pins", "base.pinout[1]", "base.pinout[2]"):
            self.assertIn(needle, issues[0]["description"])
        two = dv.verify_v14_extraction(_ext([_pin(1, "A"), _pin(2, "B"), _pin(3, "A")]))
        self.assertEqual(len(two), 2)

    def test_single_unresolved_pin_keeps_description(self):
        issues = dv.verify_v14_extraction(_ext([_pin(1, "3V3")]))
        self.assertEqual(issues, [{
            "path": "base.pinout[0].power_domain",
            "severity": "warning",
            "description": "power_domain '3V3' does not resolve to a key in "
                           "base.recommended_operating (['VDD33'])",
        }])

    def test_non_object_pin_elements_reported(self):
        issues = dv.verify_v14_extraction(_ext([None, _pin(1)]))
        self.assertEqual([(i["path"], i["severity"]) for i in issues],
                         [("base.pinout[0]", "error")])
        self.assertEqual(_run(_ext([None, _pin(1)]), flag=True).returncode, 1)

    def test_sentinel_pinout_reported(self):
        e = _ext({"_extraction_failed": True, "reason": "x"})
        issues = dv.verify_v14_extraction(e)
        self.assertEqual([(i["path"], i["severity"]) for i in issues],
                         [("base.pinout", "error")])

    def test_unhashable_power_domain_does_not_crash(self):
        issues = dv.verify_v14_extraction(_ext([_pin(1, ["a"])]))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "warning")


if __name__ == "__main__":
    unittest.main()
