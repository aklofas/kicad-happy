"""EMC findings take make_finding's key set and order (no `title`)."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
EMC = ROOT / "skills" / "emc" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(EMC))

from emc_rules import _make_finding  # noqa: E402
from finding_schema import make_finding  # noqa: E402


class FactoryShape(unittest.TestCase):
    def test_emc_finding_key_order_matches_make_finding(self):
        f = _make_finding("ground_plane", "HIGH", "GP-001", "t", "d", recommendation="r", components=["U1"])
        kicad = make_finding(detector="x", rule_id="GP-001", category="ground_plane", summary="t",
                             description="d", severity="error", components=["U1"], recommendation="r")
        self.assertEqual([k for k in f], [k for k in kicad if k != "finding_id"])
        self.assertNotIn("title", f)
        self.assertEqual(f["summary"], "t")
        self.assertEqual(f["detector"], "emc_ground_plane")
        self.assertEqual(f["severity"], "error")

    def test_fix_params_and_extra_land_where_make_finding_puts_them(self):
        f = _make_finding("pdn", "MEDIUM", "PD-001", "t", "d", fix_params={"a": 1}, net_count=3)
        kicad = make_finding(detector="x", rule_id="PD-001", category="pdn", summary="t", description="d",
                             severity="warning", fix_params={"a": 1}, net_count=3)
        self.assertEqual([k for k in f], [k for k in kicad if k != "finding_id"])
        self.assertEqual(list(f)[-3:], ["fix_params", "report_context", "net_count"])


if __name__ == "__main__":
    unittest.main()
