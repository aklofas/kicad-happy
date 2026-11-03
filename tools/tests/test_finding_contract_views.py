# tools/tests/test_finding_contract_views.py
"""Pins that the Finding dataclass (which drives --schema) and make_finding (the runtime serializer) agree on the keys."""
import dataclasses, inspect, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from analyzer_envelope import Finding
from finding_schema import make_finding

# Finding fields a default make_finding() call does not emit, and why.
NOT_EMITTED_BY_DEFAULT = {
    "stages": "added later by output_filters.assign_stages",
    "detection_id": "supplied by the detector through make_finding's **extra",
    "provenance": "supplied by the detector through make_finding's **extra",
    "fix_params": "supplied by the detector, and only on findings that carry a machine-readable fix",
    "extra": "schema-only container; make_finding merges extra kwargs flat into the finding",
}


def _json_name(f):
    return f.metadata.get("json_name", f.name)


def _required():
    return [n for n, p in inspect.signature(make_finding).parameters.items()
            if p.default is p.empty and p.kind is p.POSITIONAL_OR_KEYWORD]


class FindingContractViews(unittest.TestCase):
    def setUp(self):
        self.emitted = set(make_finding(**{n: "x" for n in _required()}))

    def test_every_finding_field_is_emitted_unless_named(self):
        missing = {_json_name(f) for f in dataclasses.fields(Finding)} - self.emitted
        self.assertEqual(missing, set(NOT_EMITTED_BY_DEFAULT))

    def test_named_exceptions_are_fields(self):
        names = {_json_name(f) for f in dataclasses.fields(Finding)}
        self.assertLessEqual(set(NOT_EMITTED_BY_DEFAULT), names)

    def test_required_make_finding_args_are_finding_fields(self):
        required = _required()
        names = {f.name for f in dataclasses.fields(Finding)}
        self.assertTrue(required)
        self.assertLessEqual(set(required), names)


if __name__ == "__main__":
    unittest.main()
