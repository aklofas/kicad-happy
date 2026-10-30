"""Lifecycle numbers: temperature strings keep signs and decimals, shortfalls
are positive on both sides, lead times in days round up to whole weeks, and a
blank status label states nothing."""
import sys, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import lifecycle_audit  # noqa: E402

NAMES = ("lcsc", "digikey", "element14", "mouser")


def bom_audit(temp_range=None, **replies):
    fns = {n: (lambda mpn, r=replies.get(n): dict(r) if r is not None else None)
           for n in NAMES}
    analysis = {"bom": [{"mpn": "ABC12345", "references": ["U1"]}]}
    with mock.patch.object(lifecycle_audit, "query_lifecycle_lcsc", fns["lcsc"]), \
            mock.patch.object(lifecycle_audit, "query_lifecycle_digikey", fns["digikey"]), \
            mock.patch.object(lifecycle_audit, "query_lifecycle_element14", fns["element14"]), \
            mock.patch.object(lifecycle_audit, "query_lifecycle_mouser", fns["mouser"]):
        return lifecycle_audit.audit_bom(analysis, delay=0, temp_range=temp_range)


class TempStringTest(unittest.TestCase):
    def test_strings(self):
        cases = {
            "-40°C ~ 85°C": (-40, 85),
            "-40°C~+85°C": (-40, 85),
            "-40C to +125C": (-40, 125),
            "0 ~ 70": (0, 70),
            "-55 ~ -10": (-55, -10),
            "-40°C~-10°C": (-40, -10),
            "-0.5 ~ 70": (-0.5, 70),
            "-40.5°C ~ +85.5°C": (-40.5, 85.5),
            "−40°C ~ 85°C": (-40, 85),
            "−40°C ~ −10°C": (-40, -10),
            "-55°C ~ 150°C (TJ)": (-55, 150),
        }
        for text, want in cases.items():
            self.assertEqual(lifecycle_audit._parse_temp_range(text), want, text)

    def test_no_range(self):
        self.assertIsNone(lifecycle_audit._parse_temp_range("RoHS"))


class ShortfallTest(unittest.TestCase):
    def test_both_shortfalls_positive(self):
        out = bom_audit(temp_range=(-40, 85),
                        digikey={"status": "Active",
                                 "temp_min_c": 0, "temp_max_c": 70})
        v = [f for f in out["findings"] if f.get("rule_id") == "LT-001"][0]["violations"]
        self.assertEqual((v["min_shortfall_c"], v["max_shortfall_c"]), (40, 15))

    def test_part_rated_minus_20_on_minus_40_requirement(self):
        out = bom_audit(temp_range=(-40, 85),
                        digikey={"status": "Active",
                                 "temp_min_c": -20, "temp_max_c": 85})
        self.assertEqual([f for f in out["findings"] if f.get("rule_id") == "LT-001"][0]["violations"]["min_shortfall_c"], 20)


class LeadWeeksTest(unittest.TestCase):
    def weeks(self, text):
        out = bom_audit(mouser={"status": "Active", "lead_time": text})
        f = [x for x in out["findings"] if x.get("rule_id") == "LC-006"]
        return (f[0]["lead_weeks"], f[0]["severity"]) if f else None

    def test_days_round_up(self):
        self.assertIsNone(self.weeks("84 Days"))
        self.assertEqual(self.weeks("90 Days"), (13, "info"))
        self.assertEqual(self.weeks("182 Days"), (26, "info"))
        self.assertEqual(self.weeks("183 Days"), (27, "warning"))

    def test_weeks_unchanged(self):
        self.assertEqual(self.weeks("14 Weeks"), (14, "info"))


class BlankStatusTest(unittest.TestCase):
    def test_blank_label_states_nothing(self):
        self.assertIsNone(lifecycle_audit._source_status({"status": "  "}))
        out = bom_audit(digikey={"status": "Active"}, mouser={"status": "  "})
        self.assertEqual([f for f in out["findings"] if f.get("rule_id") == "LC-005"], [])


if __name__ == "__main__":
    unittest.main()
