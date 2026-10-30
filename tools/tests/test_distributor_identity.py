"""A distributor search hit is stored only when it is the requested part.

Expected values come from the makers' ordering information: TI ``G4`` and ``/NOPB`` are
lead-free finishes, ADI/LTC ``#PBF``/``#TRPBF`` tube and reel, ``-TR`` tape and reel; family
members (``2N7002`` vs the dual ``2N7002V``) are different parts with different datasheets.
"""
import contextlib
import copy
import importlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILLS = Path(__file__).resolve().parents[2] / "skills"
sys.path.insert(0, str(SKILLS / "datasheets"))
PROVIDERS = ("digikey", "mouser", "lcsc", "element14")

# (requested, hit, same part as an MPN property, same part as a Value-field MPN)
PAIRS = (
    ("LM358DR", "LM358DRG4", True, True),
    ("LM2596S-5.0/NOPB", "LM2596S-5.0", True, True),
    ("LT1763CS8-3.3#PBF", "LT1763CS8-3.3#TRPBF", True, True),
    ("LT1763CS8-3.3", "LT1763CS8-3.3#PBF", True, True),
    ("BAT54S", "BAT54S-TR", True, True),
    ("TPS61023DRLR", "TPS61023DRLT", False, False),
    ("BSS138", "BSS138LT1G", False, True),
    ("1N4148W", "1N4148W-7-F", False, True),
    ("AP2112K-3.3TRG1", "AP2112K-1.8TRG1", False, False),
    ("2N7002", "2N7002V", False, True),
    ("BSS138", "BSS138DWQ-7", False, True),
    ("SI1012CR", "1012C", False, False),
    ("RC0603FR-0710KL", "RC0603FR-07100KL", False, False),
    ("STM32F103C8T6", "STM32F103C8T6TR", True, True),
    ("STM32F103C8T6", "STM32F103CBT6", False, False),
    ("ESP32-C3FH4", "ESP32-C3FH4X", False, True),
    ("NE555P", "NE555", False, False),
    ("LM358", "LM358DR", False, True),
)


class SamePart(unittest.TestCase):
    def test_ordering_suffix_list_is_the_curated_one(self):
        from distributor_core.verify import ORDERING_SUFFIXES
        self.assertEqual(ORDERING_SUFFIXES, ("#TRPBF", "#PBF", "#TR", "/NOPB", "T&R", "TR", "REEL", "REEL7",
                                             "PBF", "G4", "E3", "GE3", "LF"))

    def test_labelled_pairs(self):
        from distributor_core.verify import same_part
        for requested, hit, strict, family in PAIRS:
            with self.subTest(requested=requested, hit=hit):
                self.assertIs(same_part(requested, hit), strict)
                self.assertIs(same_part(requested, hit, allow_family=True), family)

    def test_suffix_variants_and_normalisation(self):
        from distributor_core.verify import same_part
        for a, b in (("LM2596S-ADJ/NOPB", "LM2596S-ADJ"), ("lm358dr", "LM358DR"), ("LM 358-DR", "LM358DR"),
                     ("SI2302CDS-T1-GE3", "SI2302CDS-T1"), ("MBR0530-E3", "MBR0530"), ("BAT54S-T&R", "BAT54S"),
                     ("LT1763CS8-3.3#TRPBF", "LT1763CS8-3.3"), ("SN74LVC1G14DBVR-REEL7", "SN74LVC1G14DBVR"),
                     ("LM2596S-5.0/NOPB-TR", "LM2596S-5.0")):
            with self.subTest(a=a, b=b):
                self.assertTrue(same_part(a, b))
                self.assertTrue(same_part(b, a))

    def test_family_members_stay_distinct(self):
        from distributor_core.verify import same_part
        for a, b in (("2N7002", "2N7002V"), ("BSS138", "BSS138DWQ-7")):
            with self.subTest(a=a, b=b):
                self.assertFalse(same_part(a, b))
                self.assertFalse(same_part(a, b, allow_family=False))

    def test_passive_value_codes_stay_distinct(self):
        from distributor_core.verify import same_part
        for fam in (False, True):
            self.assertFalse(same_part("RC0402FR-0710RL", "RC0402FR-07100KL", allow_family=fam))
            self.assertFalse(same_part("RC0402FR-07100KL", "RC0402FR-0710RL", allow_family=fam))

    def test_family_name_keeps_its_tail(self):
        # G4 ends the family name STM32G4; it is not the TI finish code there.
        from distributor_core.verify import same_part
        self.assertFalse(same_part("STM32G4", "STM32G071RB", allow_family=True))
        self.assertTrue(same_part("STM32G4", "STM32G431CBU6", allow_family=True))
        self.assertTrue(same_part("LM358", "LM358DR", allow_family=True))

    def test_other_part_checks_the_mpn_of_a_pn_hit_without_a_pn(self):
        from distributor_core.verify import other_part
        self.assertEqual(other_part("296-1-ND", "TPS61023DRLR", [], by_pn=True, part_mpn="LM358DR"), "TPS61023DRLR")
        self.assertEqual(other_part("296-1-ND", "LM358DRG4", [], by_pn=True, part_mpn="LM358DR"), "")
        self.assertEqual(other_part("296-1-ND", "REALMPN123", [], by_pn=True, part_mpn=""), "")
        self.assertEqual(other_part("296-1-ND", "TPS61023DRLR", ["296-1-ND"], by_pn=True, part_mpn="LM358DR"), "")

    def test_family_needs_the_request_as_prefix(self):
        from distributor_core.verify import same_part
        self.assertTrue(same_part("LM358", "LM358DR", allow_family=True))
        self.assertFalse(same_part("LM358DR", "LM358", allow_family=True))

    def test_empty_strings_are_never_the_same_part(self):
        from distributor_core.verify import same_part
        for a, b in (("", ""), ("LM358DR", ""), ("", "LM358DR"), ("TR", "LF")):
            self.assertFalse(same_part(a, b, allow_family=True), (a, b))


class VerifyAgainstRequest(unittest.TestCase):
    def test_pdf_naming_the_part_without_its_ordering_suffix_verifies(self):
        from distributor_core import verify
        with mock.patch.object(verify, "_extract_pdf_text", lambda *a, **k: PDF_TEXT):
            self.assertEqual(verify.verify_datasheet("x.pdf", "LM358DRG4")["confidence"], "verified")
            self.assertEqual(verify.verify_datasheet("x.pdf", "LM358DR#TRPBF")["confidence"], "verified")
            self.assertFalse(verify.verify_datasheet("x.pdf", "LM358DRX")["mpn_found"])


class MpnFromValue(unittest.TestCase):
    def test_value_fallback_is_recorded_on_the_part(self):
        from distributor_core.inputs import extract_parts, mpn_from_value
        bom = {"bom": [{"mpn": "", "value": "LM358", "lib_id": "Amplifier_Operational:LM358", "references": ["U1"], "type": "ic"},
                       {"mpn": "LM358DR", "value": "LM358", "lib_id": "Amplifier_Operational:LM358", "references": ["U2"], "type": "ic"},
                       {"mpn": "", "value": "AMS", "digikey": "296-1-ND", "lib_id": "Acme:AMS", "references": ["U3"], "type": "ic"}]}
        parts = extract_parts(bom)
        self.assertEqual([(p["mpn"], mpn_from_value(p)) for p in parts],
                         [("LM358", True), ("LM358DR", False), ("", False)])

    def test_mpn_list_parts_are_not_value_fallbacks(self):
        from distributor_core.inputs import load_mpn_list, mpn_from_value
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "mpns.txt"
            p.write_text("LM358\n", encoding="utf-8")
            self.assertFalse(mpn_from_value(load_mpn_list(p)[0]))


def _load_provider(p):
    sys.path.insert(0, str(SKILLS / p / "scripts"))
    try:
        return importlib.import_module(f"provider_{p}")
    finally:
        sys.path.pop(0)


def _hit(p, mpn, code, url):
    if p == "digikey":
        hit = {"ManufacturerProductNumber": mpn, "DatasheetUrl": url, "Manufacturer": {"Name": "Texas Instruments"},
               "Description": {"ProductDescription": "Op amp"}}
        if code:
            hit["ProductVariations"] = [{"DigiKeyProductNumber": code}]
        return hit
    if p == "mouser":
        hit = {"ManufacturerPartNumber": mpn, "DataSheetUrl": url, "Manufacturer": "Texas Instruments", "Description": "Op amp"}
        if code:
            hit["MouserPartNumber"] = code
        return hit
    if p == "lcsc":
        return {"mfr": mpn, "lcsc": code[1:], "datasheet": url,
                "extra": {"number": code, "mpn": mpn, "description": "Op amp", "manufacturer": {"name": "Texas Instruments"},
                          "datasheet": {"pdf": url}}}
    return {"translatedManufacturerPartNumber": mpn, "sku": code, "datasheets": [{"url": url}],
            "brandName": "Texas Instruments", "displayName": "Op amp"}


CTX = {"digikey": ("TOKEN", "CID"), "mouser": "KEY", "lcsc": None, "element14": ("KEY", "www.newark.com")}
SEARCH = {"digikey": "search_digikey_with_token", "mouser": "search_mouser", "lcsc": "search_lcsc",
          "element14": "search_element14"}
CODES = {"digikey": ("296-1-ND", "296-9-ND"), "mouser": ("595-LM358A", "595-LM358B"),
         "lcsc": ("C9999999", "C14663"), "element14": ("94AK6874", "11AB1001")}
URL = "https://example.com/hit.pdf"
OTHER_URL = "https://example.com/other.pdf"
PDF_TEXT = "LM358DR Dual Operational Amplifier, low power, wide supply range."


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _body(p, results):
    """One API response listing *results*, in the provider's own envelope."""
    import json
    if p == "digikey":
        data = {"Products": results}
    elif p == "mouser":
        data = {"Errors": [], "SearchResults": {"Parts": results}}
    elif p == "lcsc":
        data = {"components": results}
    else:
        data = {"manufacturerPartNumberSearchReturn": {"products": results}}
    return json.dumps(data).encode()


def _sync_one(p, part, hits, body=None):
    """Run the provider's sync_one_part with the recorded hits (or, with *body*, the real search
    over that API response); return (result, files written)."""
    prov = _load_provider(p)
    from distributor_core import verify

    def search(query, *a, **k):
        return copy.deepcopy(hits.get(query))

    def download(url, output_path, *a, **k):
        if url not in (URL, OTHER_URL):
            return False
        Path(output_path).write_bytes(b"%PDF fixture")
        return True

    base = {"mpn": "", "manufacturer": "", "value": "", "description": "", "datasheet": "", "references": ["U1"],
            "type": "ic", **{k: "" for k in prov.ID_KEYS}}
    with tempfile.TemporaryDirectory() as d, \
            (mock.patch("urllib.request.urlopen", lambda *a, **k: _Resp(body)) if body is not None
             else mock.patch.object(prov, SEARCH[p], search)), \
            mock.patch.object(prov, "download_pdf", download), \
            mock.patch.object(prov, "try_alternative_sources", lambda *a, **k: False), \
            mock.patch.object(verify, "_extract_pdf_text", lambda *a, **k: PDF_TEXT), \
            mock.patch("time.sleep", lambda *a, **k: None):
        if p == "lcsc":
            stack = mock.patch.object(prov, "search_lcsc_direct", lambda *a, **k: None)
        elif p == "mouser":
            stack = mock.patch.object(prov, "scrape_product_page", lambda *a, **k: "")
        else:
            stack = contextlib.nullcontext()
        with stack, contextlib.redirect_stderr(io.StringIO()):
            result = prov.sync_one_part({**base, **part}, Path(d), {}, 0.0, CTX[p])
        files = sorted(f.name for f in Path(d).iterdir())
    return result, files


class ProviderGuard(unittest.TestCase):
    def test_fuzzy_mpn_hit_is_not_found_and_nothing_is_written(self):
        for p in PROVIDERS:
            with self.subTest(provider=p):
                r, files = _sync_one(p, {"mpn": "2N7002"}, {"2N7002": _hit(p, "2N7002V", CODES[p][1], URL)})
                self.assertEqual(r["status"], "not_found")
                self.assertIn("No matching", r["error"])
                self.assertIn("(closest: '2N7002V', a different part)", r["error"])
                self.assertEqual(files, [])

    def test_fuzzy_code_hit_is_not_found_and_nothing_is_written(self):
        for p in PROVIDERS:
            req, other = CODES[p]
            with self.subTest(provider=p):
                r, files = _sync_one(p, {p: req}, {req: _hit(p, "LM358DR", other, URL)})
                self.assertEqual(r["status"], "not_found")
                self.assertIn(f"(closest: '{other}', a different part)", r["error"])
                self.assertEqual(files, [])

    def test_exact_code_hit_is_stored(self):
        for p in PROVIDERS:
            req, _ = CODES[p]
            with self.subTest(provider=p):
                r, files = _sync_one(p, {p: req}, {req: _hit(p, "LM358DR", req, URL)})
                self.assertEqual(r["status"], "ok")
                self.assertEqual(len(files), 1)

    def test_suffix_variant_hit_is_stored_and_verified_against_the_requested_mpn(self):
        # The PDF names the requested LM358DR, not the hit's LM358DRG4: the check is against the request.
        for p in PROVIDERS:
            with self.subTest(provider=p):
                r, files = _sync_one(p, {"mpn": "LM358DR"}, {"LM358DR": _hit(p, "LM358DRG4", CODES[p][1], URL)})
                self.assertEqual(r["status"], "ok")
                self.assertEqual(r["verification"], "verified")
                self.assertEqual(len(files), 1)

    def test_family_hit_is_stored_only_for_a_value_field_mpn(self):
        for p in PROVIDERS:
            with self.subTest(provider=p):
                hits = {"LM358": _hit(p, "LM358DR", CODES[p][1], URL)}
                r, files = _sync_one(p, {"mpn": "LM358", "mpn_source": "value"}, hits)
                self.assertEqual(r["status"], "ok")
                self.assertEqual(r["verification"], "verified")
                r, files = _sync_one(p, {"mpn": "LM358"}, hits)
                self.assertEqual(r["status"], "not_found")
                self.assertEqual(files, [])

    def test_wrong_code_hit_falls_back_to_the_mpn(self):
        for p in ("digikey", "lcsc"):
            req, other = CODES[p]
            with self.subTest(provider=p):
                hits = {req: _hit(p, "TPS61023DRLR", other, "https://example.com/other.pdf"),
                        "LM358DR": _hit(p, "LM358DR", "", URL)}
                r, files = _sync_one(p, {"mpn": "LM358DR", p: req}, hits)
                self.assertEqual(r["status"], "ok")
                self.assertEqual(r["verification"], "verified")


class Pickers(unittest.TestCase):
    def test_listing_with_the_wrong_part_first_stores_the_requested_one(self):
        # Neither is a case-exact match: LM358DRG4 is LM358DR with a finish code.
        for p in PROVIDERS:
            with self.subTest(provider=p):
                body = _body(p, [_hit(p, "LM358DRX", CODES[p][1], OTHER_URL), _hit(p, "LM358DRG4", CODES[p][0], URL)])
                r, files = _sync_one(p, {"mpn": "LM358DR"}, {}, body=body)
                self.assertEqual(r["status"], "ok")
                self.assertEqual(r["datasheet_url"], URL)

    def test_value_part_prefers_a_family_member_over_another_part(self):
        for p in PROVIDERS:
            with self.subTest(provider=p):
                body = _body(p, [_hit(p, "TPS62130RGTR", CODES[p][1], OTHER_URL),
                                 _hit(p, "TPS61023DRLR", CODES[p][0], URL)])
                r, files = _sync_one(p, {"mpn": "TPS61023", "mpn_source": "value"}, {}, body=body)
                self.assertEqual(r["status"], "ok")
                self.assertEqual(r["datasheet_url"], URL)

    def test_pn_hit_without_a_pn_field_must_carry_the_parts_mpn(self):
        for p in ("digikey", "lcsc"):
            req, _ = CODES[p]
            with self.subTest(provider=p):
                wrong = _hit(p, "TPS61023DRLR", "", OTHER_URL)
                hits = {req: wrong, "LM358DR": _hit(p, "LM358DR", "", URL)}
                r, files = _sync_one(p, {"mpn": "LM358DR", p: req}, hits)
                self.assertEqual(r["status"], "ok")
                self.assertEqual(r["datasheet_url"], URL)

    def test_digikey_pn_query_prefers_the_product_with_that_number(self):
        prov = _load_provider("digikey")
        body = _body("digikey", [_hit("digikey", "LM358DR", "296-9-ND", OTHER_URL),
                                 _hit("digikey", "LM358DR", "296-1-ND", URL)])
        with mock.patch("urllib.request.urlopen", lambda *a, **k: _Resp(body)):
            hit = prov.search_digikey_with_token("296-1-ND", "TOKEN", "CID")
        self.assertEqual(hit["ProductVariations"][0]["DigiKeyProductNumber"], "296-1-ND")


class DigiKeyPicker(unittest.TestCase):
    def test_keyword_search_prefers_the_requested_part_over_a_family_member(self):
        import json
        prov = _load_provider("digikey")
        body = json.dumps({"Products": [{"ManufacturerProductNumber": "2N7002V"},
                                        {"ManufacturerProductNumber": "2N7002"}]}).encode()

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch("urllib.request.urlopen", lambda *a, **k: Resp(body)):
            hit = prov.search_digikey_with_token("2N7002", "TOKEN", "CID")
        self.assertEqual(hit["ManufacturerProductNumber"], "2N7002")


if __name__ == "__main__":
    unittest.main()
