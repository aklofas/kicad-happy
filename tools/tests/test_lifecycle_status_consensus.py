"""Lifecycle status takes the worst status any distributor reports, whatever the
query order; discontinuation flags and DigiKey's own labels are read."""
import itertools, sys, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import lifecycle_engine  # noqa: E402

NAMES = ("lcsc", "digikey", "element14", "mouser")


def audit(**replies):
    """audit_component with each named source answering the given dict (others None)."""
    fns = {n: (lambda mpn, r=replies.get(n): dict(r) if r is not None else None) for n in NAMES}
    with mock.patch.object(lifecycle_engine, "query_lifecycle_lcsc", fns["lcsc"]), \
            mock.patch.object(lifecycle_engine, "query_lifecycle_digikey", fns["digikey"]), \
            mock.patch.object(lifecycle_engine, "query_lifecycle_element14", fns["element14"]), \
            mock.patch.object(lifecycle_engine, "query_lifecycle_mouser", fns["mouser"]):
        return lifecycle_engine.audit_component("X1", [], delay=0)


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
        with mock.patch.object(lifecycle_engine, "query_lifecycle_lcsc", fns["lcsc"]), \
                mock.patch.object(lifecycle_engine, "query_lifecycle_digikey", fns["digikey"]), \
                mock.patch.object(lifecycle_engine, "query_lifecycle_element14", fns["element14"]), \
                mock.patch.object(lifecycle_engine, "query_lifecycle_mouser", fns["mouser"]):
            out = lifecycle_engine.audit_bom(analysis, delay=0)
        finding = next(f for f in out["findings"] if f.get("rule_id") == "LC-001")
        self.assertEqual(finding["severity"], "warning")
        self.assertIn("while digikey flag EOL", finding["description"])
        self.assertNotIn("element14", finding["description"].split("while")[1])


class UnknownStatusWordingTest(unittest.TestCase):
    def bom_audit(self, replies, mpn="RC0603FR-07330RL"):
        fns = {n: (lambda m, r=replies.get(n): dict(r) if r is not None else None)
               for n in NAMES}
        with mock.patch.object(lifecycle_engine, "query_lifecycle_lcsc", fns["lcsc"]), \
                mock.patch.object(lifecycle_engine, "query_lifecycle_digikey", fns["digikey"]), \
                mock.patch.object(lifecycle_engine, "query_lifecycle_element14", fns["element14"]), \
                mock.patch.object(lifecycle_engine, "query_lifecycle_mouser", fns["mouser"]):
            out = lifecycle_engine.audit_bom(
                {"bom": [{"mpn": mpn, "references": ["R1"]}]}, delay=0)
        return next(f for f in out["findings"] if f.get("rule_id", "").startswith("LC-0"))

    def test_no_source_answer_is_not_a_replace_order(self):
        f = self.bom_audit({})
        self.assertEqual(f["rule_id"], "LC-004")
        self.assertFalse(f["recommendation"].startswith("Replace"))
        self.assertIn("No distributor returned RC0603FR-07330RL", f["recommendation"])
        self.assertIn("credentials", f["recommendation"])

    def test_unknown_with_an_unmapped_answer(self):
        f = self.bom_audit({"digikey": {"status": None}})
        self.assertEqual(f["rule_id"], "LC-004")
        self.assertIn("No distributor returned RC0603FR-07330RL", f["recommendation"])
        self.assertNotIn("credentials", f["recommendation"])

    def test_obsolete_is_still_a_replace_order(self):
        f = self.bom_audit({"digikey": {"status": "Obsolete"}})
        self.assertEqual(f["rule_id"], "LC-001")
        self.assertEqual(f["recommendation"], "Replace RC0603FR-07330RL — part is obsolete.")


class MpnFieldAlternativesTest(unittest.TestCase):
    def run_field(self, field, answers, sources=("digikey",)):
        calls = []

        def digikey(mpn):
            calls.append(mpn)
            return answers.get(mpn)
        none = lambda mpn: None
        with mock.patch.object(lifecycle_engine, "query_lifecycle_lcsc", none), \
                mock.patch.object(lifecycle_engine, "query_lifecycle_digikey", digikey), \
                mock.patch.object(lifecycle_engine, "query_lifecycle_element14", none), \
                mock.patch.object(lifecycle_engine, "query_lifecycle_mouser", none):
            out = lifecycle_engine.audit_bom(
                {"bom": [{"mpn": field, "references": ["U1"]}]}, delay=0)
        return calls, out["findings"]

    def test_comma_field_is_looked_up_per_part(self):
        calls, _ = self.run_field("1012, 1012C", {})
        self.assertEqual(calls, ["1012", "1012C"])

    def test_one_alternative_found_is_no_lc004(self):
        _, findings = self.run_field("1012, 1012C", {"1012": {"status": "Active"}})
        self.assertFalse([f for f in findings if f["rule_id"] == "LC-004"])
        act = next(f for f in findings if f["rule_id"] == "LC-ACT")
        self.assertEqual(act["summary"], "1012, 1012C: active (1 ref(s))")

    def test_all_alternatives_missing_is_one_lc004(self):
        _, findings = self.run_field("1012, 1012C", {})
        lc4 = [f for f in findings if f["rule_id"] == "LC-004"]
        self.assertEqual(len(lc4), 1)
        self.assertIn("(checked as 1012, 1012C)", lc4[0]["description"])

    def test_end_of_life_alternative_is_not_hidden_by_an_active_one(self):
        _, findings = self.run_field(
            "1012, 1012C", {"1012": {"status": "Active"}, "1012C": {"status": "Obsolete"}})
        f = next(f for f in findings if f["rule_id"] == "LC-001")
        self.assertEqual(f["mpn"], "1012, 1012C")
        self.assertIn("(checked as 1012, 1012C)", f["description"])

    def test_slash_inside_a_part_number_is_not_split(self):
        calls, _ = self.run_field("BAV99/215", {})
        self.assertEqual(calls, ["BAV99/215"])

    def test_spaced_slash_and_semicolon_split(self):
        calls, _ = self.run_field("LM358 / LM2904; TL072", {})
        self.assertEqual(calls, ["LM358", "LM2904", "TL072"])

    def test_single_mpn_gets_one_call(self):
        calls, _ = self.run_field("RC0603FR-07330RL", {})
        self.assertEqual(calls, ["RC0603FR-07330RL"])

    def test_generic_values_are_not_alternatives(self):
        self.assertEqual(lifecycle_engine._mpn_alternatives("10k, 1%"), ["10k, 1%"])
        self.assertEqual(lifecycle_engine._mpn_alternatives("LM358, 10k"), ["LM358, 10k"])
        for field in ("1206, 50V", "0603, X7R", "100, 16V", "1206, 50V, X7R"):
            self.assertEqual(lifecycle_engine._mpn_alternatives(field), [field], field)


if __name__ == "__main__":
    unittest.main()
