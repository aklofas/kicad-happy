# tools/tests/test_extraction_schema.py
"""extraction_schema.validate_against_schema: the one validator behind merge_results and
validate_extraction_result; jsonschema/referencing load on use and their absence is loud."""
import importlib.util, sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "datasheets" / "scripts"))

SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
          "properties": {"vin_max": {"type": "number"}}, "required": ["vin_max"]}
HAVE = bool(importlib.util.find_spec("jsonschema") and importlib.util.find_spec("referencing"))


class ExtractionSchema(unittest.TestCase):
    @unittest.skipUnless(HAVE, "jsonschema/referencing not installed")
    def test_passing_document(self):
        from extraction_schema import validate_against_schema
        self.assertIsNone(validate_against_schema({"vin_max": 5.5}, SCHEMA))

    @unittest.skipUnless(HAVE, "jsonschema/referencing not installed")
    def test_failing_document_names_path_and_message(self):
        from extraction_schema import validate_against_schema
        self.assertEqual(validate_against_schema({"vin_max": "5.5"}, SCHEMA), "vin_max: '5.5' is not of type 'number'")
        self.assertEqual(validate_against_schema({}, SCHEMA), "<root>: 'vin_max' is a required property")

    def test_missing_packages_raise_runtime_error(self):
        import extraction_schema
        with mock.patch.dict(sys.modules, {"jsonschema": None, "referencing": None}):
            with self.assertRaises(RuntimeError) as cm:
                extraction_schema.validate_against_schema({"vin_max": 5.5}, SCHEMA)
        self.assertEqual(str(cm.exception), "full schema validation needs the optional packages jsonschema "
                                            "and referencing (pip install jsonschema referencing)")

    def test_scripts_import_without_the_packages(self):
        with mock.patch.dict(sys.modules, {"jsonschema": None, "referencing": None}):
            for name in ("merge_results", "validate_extraction_result"):
                sys.modules.pop(name, None)
                mod = importlib.import_module(name)
                self.assertFalse(hasattr(mod, "_build_registry"), name)
                self.assertFalse(hasattr(mod, "_validate"), name)
                sys.modules.pop(name, None)


if __name__ == "__main__":
    unittest.main()
