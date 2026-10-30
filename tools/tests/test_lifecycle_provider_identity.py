"""A distributor's lifecycle answer counts only when the result is the requested
part (a sibling or family member is no answer), and LCSC rows are read in the
current jlcsearch shape (top-level ``mfr``, no ``extra`` block).

Canned bodies follow the distributor SKILL.md response shapes and go through
the real query parsers; urlopen is replaced and sockets are refused."""
import io, json, os, socket, sys, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import lifecycle_audit  # noqa: E402


def _no_net(*a, **k):
    raise AssertionError("network access in an offline test")


class _Body(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def dk(*mpns, status="Active"):
    return {"Products": [{"ManufacturerProductNumber": m, "ProductStatus": {"Status": status},
                          "Discontinued": False, "Parameters": []} for m in mpns]}


def mo(*mpns, status="End of Life"):
    return {"SearchResults": {"Parts": [{"ManufacturerPartNumber": m, "LifecycleStatus": status,
                                         "IsDiscontinued": "false", "ProductAttributes": []}
                                        for m in mpns]}}


def e14(*mpns, status="Obsolete"):
    return {"manufacturerPartNumberSearchReturn": {"products": [
        {"translatedManufacturerPartNumber": m,
         "attributes": [{"attributeLabel": "Lifecycle Status", "attributeValue": status}]}
        for m in mpns]}}


def lcsc(*mpns, stock=500):
    return {"components": [{"lcsc": 7950 + i, "mfr": m, "package": "SOIC-8", "is_basic": False,
                            "is_preferred": False, "description": "", "stock": stock,
                            "price": 0.1} for i, m in enumerate(mpns)]}


class ProviderIdentityBase(unittest.TestCase):
    def setUp(self):
        self.bodies = {}
        self.requests = []
        env = {k: v for k, v in os.environ.items()
               if k not in ("DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET",
                            "MOUSER_SEARCH_API_KEY", "MOUSER_PART_API_KEY", "ELEMENT14_API_KEY")}
        env.update(MOUSER_SEARCH_API_KEY="offline", ELEMENT14_API_KEY="offline")
        for p in (mock.patch.dict(os.environ, env, clear=True),
                  mock.patch.object(socket, "create_connection", _no_net),
                  mock.patch.object(socket.socket, "connect", _no_net),
                  mock.patch.object(lifecycle_audit, "_get_digikey_token",
                                    lambda: ("tok", "cid")),
                  mock.patch.object(lifecycle_audit.urllib.request, "urlopen", self._urlopen)):
            p.start()
            self.addCleanup(p.stop)

    def _urlopen(self, req, timeout=None):
        self.requests.append(req)
        for key in ("digikey", "mouser", "element14", "jlcsearch"):
            if key in req.full_url:
                if key not in self.bodies:
                    raise lifecycle_audit.urllib.error.URLError("no canned body")
                return _Body(json.dumps(self.bodies[key]).encode())
        raise AssertionError("unexpected url " + req.full_url)

    def audit(self, mpn, sources):
        out = lifecycle_audit.audit_bom(
            {"bom": [{"references": ["U1"], "mpn": mpn, "type": "ic"}]},
            sources=sources, delay=0)
        main = [f for f in out["findings"]
                if f["rule_id"] not in ("LC-005", "LC-006", "LT-001")]
        return out, main[0]


class SiblingIsNoAnswerTest(ProviderIdentityBase):
    def test_digikey_six_char_prefix_sibling(self):
        self.bodies["digikey"] = dk("TPS54332DR")
        self.assertIsNone(lifecycle_audit.query_lifecycle_digikey("TPS54331DR"))
        out, f = self.audit("TPS54331DR", ["digikey"])
        self.assertEqual((f["status"], f["rule_id"]), ("unknown", "LC-004"))
        self.assertEqual(out["sources_available"], [])

    def test_mouser_non_exact_first_result(self):
        self.bodies["mouser"] = mo("LM358DR2G")
        self.assertIsNone(lifecycle_audit.query_lifecycle_mouser("LM358DR"))
        out, f = self.audit("LM358DR", ["mouser"])
        self.assertEqual((f["status"], f["rule_id"]), ("unknown", "LC-004"))

    def test_element14_non_exact_first_result(self):
        self.bodies["element14"] = e14("LM358DT")
        self.assertIsNone(lifecycle_audit.query_lifecycle_element14("LM358DR"))

    def test_ordering_variant_is_another_part_number(self):
        # TI obsoletes a G4 green variant on its own; LM358DR can stay active.
        self.bodies["element14"] = e14("LM358DRG4")
        self.assertIsNone(lifecycle_audit.query_lifecycle_element14("LM358DR"))
        out, f = self.audit("LM358DR", ["element14"])
        self.assertEqual((f["status"], f["rule_id"]), ("unknown", "LC-004"))
        self.bodies["digikey"] = dk("LM2596S-ADJ/NOPB")
        self.assertIsNone(lifecycle_audit.query_lifecycle_digikey("LM2596S-ADJ"))

    def test_ordering_marks_stay_significant(self):
        # Maxim/ADI "+" and LT "#PBF" name the lead-free orderable number; the leaded
        # one is obsoleted separately. AP2112K-3.3 is the 3.3 V part, not AP2112K-33.
        for requested, variant in (("MAX3232ECUE", "MAX3232ECUE+"),
                                   ("MAX3232ECUE+", "MAX3232ECUE"),
                                   ("LT1763CS8", "LT1763CS8#PBF"),
                                   ("AP2112K-3.3", "AP2112K-33")):
            self.bodies["digikey"] = dk(variant)
            self.assertIsNone(lifecycle_audit.query_lifecycle_digikey(requested),
                              (requested, variant))

    def test_lcsc_sibling(self):
        self.bodies["jlcsearch"] = lcsc("LM358DT")
        self.assertIsNone(lifecycle_audit.query_lifecycle_lcsc("LM358DR"))

    def test_near_miss_pair_stays_distinct_on_every_provider(self):
        self.bodies.update(digikey=dk("2N7002V"), mouser=mo("2N7002V"),
                           element14=e14("2N7002V"), jlcsearch=lcsc("2N7002V"))
        for q in (lifecycle_audit.query_lifecycle_digikey, lifecycle_audit.query_lifecycle_mouser,
                  lifecycle_audit.query_lifecycle_element14, lifecycle_audit.query_lifecycle_lcsc):
            self.assertIsNone(q("2N7002"), q.__name__)

    def test_sibling_never_makes_a_single_source(self):
        # A sibling's unmapped label would otherwise count as the second answer.
        self.bodies.update(digikey=dk("LM358DR"),
                           mouser=mo("LM358DR2G", status="Restricted Availability"))
        out, f = self.audit("LM358DR", ["digikey", "mouser"])
        self.assertEqual([x for x in out["findings"] if x["rule_id"] == "LC-005"], [])
        self.assertEqual(out["sources_available"], ["digikey"])


class RequestedPartIsReadTest(ProviderIdentityBase):
    def test_exact_result_after_a_sibling_is_used(self):
        self.bodies.update(digikey=dk("TPS54332DR", "TPS54331DR", status="Obsolete"),
                           mouser=mo("LM358DR2G", "LM358DR"),
                           element14=e14("LM358DT", "LM358DR"))
        self.assertEqual(lifecycle_audit.query_lifecycle_digikey("TPS54331DR")["status"],
                         "Obsolete")
        self.assertEqual(lifecycle_audit.query_lifecycle_mouser("LM358DR")["status"],
                         "End of Life")
        self.assertEqual(lifecycle_audit.query_lifecycle_element14("LM358DR")["status"],
                         "Obsolete")

    def test_listing_with_both_variants_uses_the_requested_row(self):
        self.bodies["mouser"] = {"SearchResults": {"Parts": [
            mo("MAX3232ECUE", status="Obsolete")["SearchResults"]["Parts"][0],
            mo("MAX3232ECUE+", status="New Product")["SearchResults"]["Parts"][0]]}}
        self.assertEqual(lifecycle_audit.query_lifecycle_mouser("MAX3232ECUE+")["status"],
                         "New Product")

    def test_literal_match_beats_a_normalised_one(self):
        self.bodies["digikey"] = {"Products": dk("LM358-DR", status="Obsolete")["Products"]
                                  + dk("LM358DR", status="Active")["Products"]}
        self.assertEqual(lifecycle_audit.query_lifecycle_digikey("LM358DR")["status"], "Active")

    def test_case_and_whitespace_ignored(self):
        self.bodies["digikey"] = dk("LM358DR")
        for req in ("lm358dr ", "lm358dr", "LM358 DR"):
            self.assertEqual(lifecycle_audit.query_lifecycle_digikey(req)["status"], "Active", req)

    def test_mouser_searches_exact(self):
        self.bodies["mouser"] = mo("LM358DR")
        lifecycle_audit.query_lifecycle_mouser("LM358DR")
        body = json.loads(self.requests[-1].data)
        self.assertEqual(body["SearchByPartRequest"],
                         {"mouserPartNumber": "LM358DR", "partSearchOptions": "Exact"})


class LcscCurrentShapeTest(ProviderIdentityBase):
    def test_row_without_extra_is_read(self):
        self.bodies["jlcsearch"] = lcsc("LM358DR")
        self.assertEqual(lifecycle_audit.query_lifecycle_lcsc("LM358DR"),
                         {"in_stock": True, "stock_qty": 500})
        out, f = self.audit("LM358DR", ["lcsc"])
        self.assertEqual(out["sources_available"], ["lcsc"])

    def test_lcsc_listed_beside_digikey_without_counting_for_single_source(self):
        self.bodies.update(digikey=dk("LM358DR"), jlcsearch=lcsc("LM358DR"))
        out, f = self.audit("LM358DR", ["digikey", "lcsc"])
        self.assertEqual(out["sources_available"], ["digikey", "lcsc"])
        self.assertEqual([x for x in out["findings"] if x["rule_id"] == "LC-005"], [])

    def test_older_extra_shape_still_read(self):
        self.bodies["jlcsearch"] = {"components": [
            {"stock": 3, "extra": {"mpn": "LM358DR", "attributes": {
                "Operating Temperature": "-40°C~+85°C"}}}]}
        r = lifecycle_audit.query_lifecycle_lcsc("LM358DR")
        self.assertEqual((r["stock_qty"], r["temp_min_c"], r["temp_max_c"]), (3, -40.0, 85.0))


if __name__ == "__main__":
    unittest.main()
