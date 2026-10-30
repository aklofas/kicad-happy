# tools/tests/test_datasheet_prompt_shapes.py
"""The extraction prompts' example shapes validate against the schemas they name, the
schemas carry versions, and a generic ceramic capacitor class is accepted."""
import importlib.util, json, re, sys, unittest
from pathlib import Path
DS = Path(__file__).resolve().parents[2] / "skills" / "datasheets"
sys.path.insert(0, str(DS / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))
HAVE = bool(importlib.util.find_spec("jsonschema") and importlib.util.find_spec("referencing"))
FENCE = re.compile(r"```json\n(.*?)```", re.S)


def _schema(name):
    return json.loads((DS / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))


def _examples(prompt):
    text = (DS / "prompts" / f"{prompt}.md").read_text(encoding="utf-8")
    return [json.loads(m) for m in FENCE.findall(text)]


class SchemaVersions(unittest.TestCase):
    def test_capability_mode_lists_every_versioned_schema(self):
        from capability_mode import _read_schema_versions
        v = _read_schema_versions()
        for name in ("base", "pinout", "extraction"):
            self.assertEqual(v.get(name), "1.0", name)
        self.assertEqual(v.get("regulator"), "0.4")


@unittest.skipUnless(HAVE, "jsonschema/referencing not installed")
class PromptShapes(unittest.TestCase):
    def _check(self, prompt, schema):
        from extraction_schema import validate_against_schema
        examples = _examples(prompt)
        self.assertTrue(examples, prompt)
        for ex in examples:
            self.assertIsNone(validate_against_schema(ex, _schema(schema)), prompt)

    def test_base_example_validates(self):
        self._check("base", "base")

    def test_pinout_example_validates(self):
        self._check("pinout", "pinout")

    def test_regulator_example_validates(self):
        self._check("regulator", "regulator")

    def test_prompts_name_only_vocabulary_the_schemas_accept(self):
        pin_types = set(_schema("pinout")["$defs"]["Pin"]["properties"]["type"]["enum"])
        text = (DS / "prompts" / "pinout.md").read_text(encoding="utf-8")
        listed = set(re.findall(r"`([a-z_]+)`", re.search(r"- `type`: exactly one of (.*?)\(", text).group(1)))
        self.assertTrue(listed <= pin_types, sorted(listed - pin_types))
        rules = text.split("Choose the closest match", 1)[1].split("\n", 1)[0]
        for t in ("open_collector", "open_emitter", "tri_state", "not_connected", "power_in", "power_out", "passive"):
            self.assertIn("`%s`" % t, rules, t)
        reg = (DS / "prompts" / "regulator.md").read_text(encoding="utf-8")
        allowed = set(_schema("regulator")["properties"]["stability_conditions"]["properties"]
                      ["cap_types_allowed"]["items"]["enum"])
        listed = set(re.findall(r"`([a-z0-9_]+)`", re.search(r"cap_types_allowed` \(array of strings from (.*?`film`)", reg).group(1)))
        self.assertTrue(listed <= allowed, sorted(listed - allowed))

    def test_ceramic_is_a_stability_capacitor_class(self):
        from extraction_schema import validate_against_schema
        sub = _schema("regulator")["properties"]["stability_conditions"]["properties"]["cap_types_allowed"]
        self.assertIsNone(validate_against_schema(["ceramic", "tantalum"], {**sub, "$schema": "https://json-schema.org/draft/2020-12/schema"}))
        self.assertIsNotNone(validate_against_schema(["mlcc"], {**sub, "$schema": "https://json-schema.org/draft/2020-12/schema"}))


if __name__ == "__main__":
    unittest.main()
