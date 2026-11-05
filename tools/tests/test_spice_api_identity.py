"""A distributor's answer gives a SPICE model only when its part number is the one requested."""
import io, json, os, sys, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for sub in ("kicad/scripts", "spice/scripts"):
    p = str(ROOT / "skills" / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import spice_spec_fetcher  # noqa: E402

_ENV_KEYS = ("DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET", "ELEMENT14_API_KEY",
             "MOUSER_SEARCH_API_KEY", "MOUSER_PART_API_KEY")
WANT = "OPA2335"
SIBLING = "OPA2333AIDR"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _lcsc(mpn):
    return {"components": [{"extra": {"mpn": mpn,
            "attributes": {"Gain Bandwidth Product": "350kHz"}}}]}


def _digikey(mpn):
    return {"Products": [{"ManufacturerProductNumber": mpn, "Parameters": [
        {"ParameterText": "Gain Bandwidth Product", "ValueText": "350kHz"}]}]}


def _element14(mpn):
    return {"manufacturerPartNumberSearchReturn": {"products": [
        {"translatedManufacturerPartNumber": mpn, "attributes": [
            {"attributeLabel": "Gain Bandwidth Product", "attributeValue": "350kHz"}]}]}}


def _mouser(mpn):
    return {"SearchResults": {"Parts": [{"ManufacturerPartNumber": mpn, "ProductAttributes": [
        {"AttributeName": "Gain Bandwidth Product", "AttributeValue": "350kHz"}]}]}}


class ApiIdentityTest(unittest.TestCase):
    def fetch(self, name, body, env):
        clean = {k: v for k, v in os.environ.items() if k not in _ENV_KEYS}
        clean.update(env)
        with mock.patch.dict(os.environ, clean, clear=True), \
                mock.patch.object(spice_spec_fetcher, "_get_digikey_token", return_value="T"), \
                mock.patch.object(spice_spec_fetcher.urllib.request, "urlopen",
                                  side_effect=lambda *a, **k: _Resp(json.dumps(body).encode())):
            return getattr(spice_spec_fetcher, "fetch_specs_" + name)(WANT)

    def check(self, name, build, env):
        self.assertIsNone(self.fetch(name, build(SIBLING), env))
        specs = self.fetch(name, build(WANT.lower()), env)
        self.assertTrue(specs and specs.get("gbw_hz"))
        self.assertEqual(specs["_source"], "api:" + name)

    def test_lcsc(self):
        self.check("lcsc", _lcsc, {})

    def test_digikey(self):
        self.check("digikey", _digikey, {"DIGIKEY_CLIENT_ID": "id"})

    def test_element14(self):
        self.check("element14", _element14, {"ELEMENT14_API_KEY": "k"})

    def test_mouser(self):
        self.check("mouser", _mouser, {"MOUSER_SEARCH_API_KEY": "k"})

    def test_family_member_rejected(self):
        with mock.patch.object(spice_spec_fetcher.urllib.request, "urlopen",
                               side_effect=lambda *a, **k: _Resp(
                                   json.dumps(_lcsc("LM358DR")).encode())):
            self.assertIsNone(spice_spec_fetcher.fetch_specs_lcsc("LM358"))

    def test_non_string_hit_ignored(self):
        body = {"components": [{"extra": {"mpn": 5, "attributes": {"GBW": "1MHz"}}}]}
        self.assertIsNone(self.fetch("lcsc", body, {}))


if __name__ == "__main__":
    unittest.main()
