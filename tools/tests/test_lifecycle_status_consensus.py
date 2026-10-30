"""Lifecycle status takes the worst status any distributor reports, whatever the
query order; discontinuation flags and DigiKey's own labels are read."""
import itertools, sys, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import lifecycle_audit  # noqa: E402

NAMES = ("lcsc", "digikey", "element14", "mouser")


def audit(**replies):
    """audit_component with each named source answering the given dict (others None)."""
    fns = {n: (lambda mpn, r=replies.get(n): dict(r) if r is not None else None) for n in NAMES}
    with mock.patch.object(lifecycle_audit, "query_lifecycle_lcsc", fns["lcsc"]), \
            mock.patch.object(lifecycle_audit, "query_lifecycle_digikey", fns["digikey"]), \
            mock.patch.object(lifecycle_audit, "query_lifecycle_element14", fns["element14"]), \
            mock.patch.object(lifecycle_audit, "query_lifecycle_mouser", fns["mouser"]):
        return lifecycle_audit.audit_component("X1", [], delay=0)


class WorstStatusTest(unittest.TestCase):
    def test_obsolete_and_active_is_a_split_obsolete(self):
        for first, second in itertools.permutations(
                [("digikey", {"status": "Obsolete"}), ("mouser", {"status": "New Product"})]):
            r = audit(**dict([first, second]))
            self.assertEqual(r["status"], "obsolete")
            self.assertTrue(r["consensus_split"])

    def test_worst_beats_nrnd_regardless_of_source_order(self):
        r = audit(digikey={"status": "Obsolete"}, element14={"status": "NRND"})
        self.assertEqual(r["status"], "obsolete")
        self.assertFalse(r["consensus_split"])
        r = audit(element14={"status": "Obsolete"}, mouser={"status": "NRND"})
        self.assertEqual(r["status"], "obsolete")

    def test_eol_label_with_active_elsewhere(self):
        r = audit(digikey={"status": "Active"}, mouser={"status": "End of Life"})
        self.assertEqual(r["status"], "obsolete")
        self.assertTrue(r["consensus_split"])


class FlagsAndLabelsTest(unittest.TestCase):
    def test_discontinued_flag_raises_an_active_label(self):
        r = audit(digikey={"status": "Active", "discontinued": True})
        self.assertEqual(r["status"], "discontinued")
        self.assertEqual(r["per_source_status"], {"digikey": "discontinued"})

    def test_flag_without_label_states_a_status(self):
        for src in ("digikey", "mouser"):
            r = audit(**{src: {"status": None, "discontinued": True}})
            self.assertEqual(r["status"], "discontinued", src)

    def test_flag_never_lowers_a_worse_label(self):
        r = audit(digikey={"status": "Obsolete", "discontinued": True})
        self.assertEqual(r["status"], "obsolete")

    def test_false_flag_changes_nothing(self):
        r = audit(digikey={"status": "Active", "discontinued": False})
        self.assertEqual(r["status"], "active")

    def test_discontinued_at_digikey_label(self):
        r = audit(digikey={"status": "Discontinued at DigiKey", "discontinued": False})
        self.assertEqual(r["status"], "discontinued")
        self.assertFalse(r["consensus_split"])

    def test_discontinued_at_digikey_demoted_when_another_source_is_active(self):
        r = audit(digikey={"status": "Discontinued at DigiKey", "discontinued": False},
                  mouser={"status": "New Product"})
        self.assertEqual(r["status"], "discontinued")
        self.assertTrue(r["consensus_split"])

    def test_end_of_life_flag_is_not_read(self):
        r = audit(digikey={"status": "Active", "discontinued": False, "end_of_life": True})
        self.assertEqual(r["status"], "active")


class UnknownSourceTest(unittest.TestCase):
    def test_unknown_source_is_not_named_as_eol(self):
        replies = {"digikey": {"status": "Obsolete"}, "mouser": {"status": "New Product"},
                   "element14": {"status": "Preliminary"}}
        fns = {n: (lambda mpn, r=replies.get(n): dict(r) if r is not None else None)
               for n in NAMES}
        analysis = {"bom": [{"mpn": "ABC12345", "references": ["U1"]}]}
        with mock.patch.object(lifecycle_audit, "query_lifecycle_lcsc", fns["lcsc"]), \
                mock.patch.object(lifecycle_audit, "query_lifecycle_digikey", fns["digikey"]), \
                mock.patch.object(lifecycle_audit, "query_lifecycle_element14", fns["element14"]), \
                mock.patch.object(lifecycle_audit, "query_lifecycle_mouser", fns["mouser"]):
            out = lifecycle_audit.audit_bom(analysis, delay=0)
        finding = next(f for f in out["findings"] if f.get("rule_id") == "LC-001")
        self.assertEqual(finding["severity"], "warning")
        self.assertIn("while digikey flag EOL", finding["description"])
        self.assertNotIn("element14", finding["description"].split("while")[1])


if __name__ == "__main__":
    unittest.main()
