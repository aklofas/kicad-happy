"""LC-005 (single source) counts a distributor only when it states a lifecycle
status; a null-status answer is no more a response than an outage."""
import sys, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import lifecycle_audit  # noqa: E402

NAMES = ("lcsc", "digikey", "element14", "mouser")


def bom_audit(**replies):
    fns = {n: (lambda mpn, r=replies.get(n): dict(r) if r is not None else None)
           for n in NAMES}
    analysis = {"bom": [{"mpn": "ABC12345", "references": ["U1"]}]}
    with mock.patch.object(lifecycle_audit, "query_lifecycle_lcsc", fns["lcsc"]), \
            mock.patch.object(lifecycle_audit, "query_lifecycle_digikey", fns["digikey"]), \
            mock.patch.object(lifecycle_audit, "query_lifecycle_element14", fns["element14"]), \
            mock.patch.object(lifecycle_audit, "query_lifecycle_mouser", fns["mouser"]):
        return lifecycle_audit.audit_bom(analysis, delay=0)


def lc005(out):
    return [f for f in out["findings"] if f.get("rule_id") == "LC-005"]


class SingleSourceTest(unittest.TestCase):
    def test_null_status_second_source_is_not_a_response(self):
        out = bom_audit(digikey={"status": "Active"}, mouser={"status": None})
        self.assertEqual(lc005(out), [])

    def test_stated_but_unmapped_label_is_a_response(self):
        for label in ("Restricted Availability", "Preliminary"):
            out = bom_audit(digikey={"status": "Active"}, mouser={"status": label})
            f = lc005(out)
            self.assertEqual(len(f), 1, label)
            self.assertEqual(f[0]["source_name"], "digikey")
            self.assertEqual(f[0]["responded"], 2)

    def test_flag_only_source_states_a_status(self):
        out = bom_audit(digikey={"status": "Active"},
                        mouser={"status": None, "discontinued": True})
        self.assertEqual(lc005(out), [])
        lc001 = [f for f in out["findings"] if f.get("rule_id") == "LC-001"]
        self.assertEqual(len(lc001), 1)
        self.assertEqual(lc001[0]["per_source_status"],
                         {"digikey": "active", "mouser": "discontinued"})

    def test_end_of_life_elsewhere_is_not_single_source(self):
        out = bom_audit(digikey={"status": "Active"}, mouser={"status": "End of Life"})
        self.assertEqual(lc005(out), [])

    def test_two_active_sources_unchanged(self):
        out = bom_audit(digikey={"status": "Active"}, mouser={"status": "New Product"})
        self.assertEqual(lc005(out), [])

    def test_outage_never_counts(self):
        out = bom_audit(digikey={"status": "Active"})
        self.assertEqual(lc005(out), [])


if __name__ == "__main__":
    unittest.main()
