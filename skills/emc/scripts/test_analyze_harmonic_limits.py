#!/usr/bin/env python3
"""Unit tests for the standalone harmonic-limit screening CLI."""

import copy
import math
from pathlib import Path
import subprocess
import sys
import unittest


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import analyze_harmonic_limits as harmonic


VALID_SPECTRUM = {
    "schema_version": "harmonic-lines/1",
    "level_unit": "dbuv_rms",
    "source": {
        "kind": "simulation",
        "description": "synthetic spectral lines",
    },
    "points": [
        {"frequency_hz": 2_000_000, "level_dbuv": 31.5},
        {"frequency_hz": 1_000_000, "level_dbuv": 42.0},
    ],
}

VALID_PROFILE = {
    "schema_version": "emc-limit-profile/1",
    "profile_id": "fictional-user-profile",
    "source": {
        "kind": "user_supplied",
        "citation": "Fictional example — not a regulatory source",
    },
    "bands": [
        {
            "name": "fictional-band",
            "start_hz": 500_000,
            "stop_hz": 1_800_000,
            "limits_dbuv": {
                "peak": 54.0,
                "quasi_peak": 41.0,
                "average": 34.0,
            },
        }
    ],
}


class TestHarmonicLimitCliSurface(unittest.TestCase):
    """Exercise the standalone tool through its user-facing entry point."""

    def test_help_identifies_both_input_schemas_and_detector_choices(self):
        script = SCRIPT_DIR / "analyze_harmonic_limits.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("harmonic-lines/1", result.stdout)
        self.assertIn("emc-limit-profile/1", result.stdout)
        self.assertIn("{peak,quasi_peak,average}", result.stdout)
        self.assertIn("--design-margin-db", result.stdout)
        self.assertIn("--output", result.stdout)


class TestSpectrumValidation(unittest.TestCase):
    """Reject ambiguous spectrum data and normalize point order."""

    def _validate(self, data):
        validator = getattr(harmonic, "validate_spectrum", None)
        self.assertIsNotNone(validator, "validate_spectrum is required")
        return validator(data)

    def test_points_are_sorted_by_frequency(self):
        normalized = self._validate(copy.deepcopy(VALID_SPECTRUM))
        self.assertEqual(
            [point["frequency_hz"] for point in normalized["points"]],
            [1_000_000.0, 2_000_000.0],
        )

    def test_empty_point_list_is_valid(self):
        data = copy.deepcopy(VALID_SPECTRUM)
        data["points"] = []
        self.assertEqual(self._validate(data)["points"], [])

    def test_duplicate_numeric_frequencies_are_rejected(self):
        data = copy.deepcopy(VALID_SPECTRUM)
        data["points"] = [
            {"frequency_hz": 1, "level_dbuv": 2},
            {"frequency_hz": 1.0, "level_dbuv": 3},
        ]
        with self.assertRaisesRegex(
            harmonic.ValidationError,
            "duplicate frequency_hz 1.0",
        ):
            self._validate(data)

    def test_invalid_spectrum_metadata_is_rejected(self):
        cases = (
            ("schema_version", "harmonic-lines/2", "schema_version"),
            ("level_unit", "dbuv_peak", "level_unit"),
        )
        for field, value, expected in cases:
            with self.subTest(field=field):
                data = copy.deepcopy(VALID_SPECTRUM)
                data[field] = value
                with self.assertRaisesRegex(
                    harmonic.ValidationError,
                    expected,
                ):
                    self._validate(data)

    def test_nonpositive_and_nonfinite_frequencies_are_rejected(self):
        for value in (0, -1, math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                data = copy.deepcopy(VALID_SPECTRUM)
                data["points"][0]["frequency_hz"] = value
                with self.assertRaisesRegex(
                    harmonic.ValidationError,
                    "frequency_hz",
                ):
                    self._validate(data)

    def test_nonfinite_levels_and_boolean_numbers_are_rejected(self):
        for value in (math.nan, math.inf, -math.inf, True):
            with self.subTest(value=value):
                data = copy.deepcopy(VALID_SPECTRUM)
                data["points"][0]["level_dbuv"] = value
                with self.assertRaisesRegex(
                    harmonic.ValidationError,
                    "level_dbuv",
                ):
                    self._validate(data)


class TestLimitProfileValidation(unittest.TestCase):
    """Require provenance and unambiguous detector bands."""

    def _validate(self, data):
        validator = getattr(harmonic, "validate_limit_profile", None)
        self.assertIsNotNone(validator, "validate_limit_profile is required")
        return validator(data)

    def test_valid_profile_preserves_required_provenance(self):
        normalized = self._validate(copy.deepcopy(VALID_PROFILE))
        self.assertEqual(normalized["profile_id"], "fictional-user-profile")
        self.assertEqual(normalized["source"], VALID_PROFILE["source"])

    def test_required_profile_strings_are_enforced(self):
        mutations = (
            (("schema_version",), "emc-limit-profile/2", "schema_version"),
            (("profile_id",), "", "profile_id"),
            (("source", "kind"), "", "source.kind"),
            (("source", "citation"), "", "source.citation"),
        )
        for path, value, expected in mutations:
            with self.subTest(path=path):
                data = copy.deepcopy(VALID_PROFILE)
                target = data
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaisesRegex(
                    harmonic.ValidationError,
                    expected,
                ):
                    self._validate(data)

    def test_duplicate_band_names_are_rejected(self):
        data = copy.deepcopy(VALID_PROFILE)
        data["bands"].append(copy.deepcopy(data["bands"][0]))
        with self.assertRaisesRegex(
            harmonic.ValidationError,
            "duplicate band name",
        ):
            self._validate(data)

    def test_invalid_ranges_are_rejected(self):
        for start, stop in ((0, 1), (-1, 1), (2, 1)):
            with self.subTest(start=start, stop=stop):
                data = copy.deepcopy(VALID_PROFILE)
                data["bands"][0]["start_hz"] = start
                data["bands"][0]["stop_hz"] = stop
                with self.assertRaisesRegex(
                    harmonic.ValidationError,
                    "start_hz",
                ):
                    self._validate(data)

    def test_detector_names_are_closed_and_one_is_required(self):
        cases = (
            ({}, "at least one"),
            ({"rms": 10}, "unsupported detector"),
        )
        for limits, expected in cases:
            with self.subTest(limits=limits):
                data = copy.deepcopy(VALID_PROFILE)
                data["bands"][0]["limits_dbuv"] = limits
                with self.assertRaisesRegex(
                    harmonic.ValidationError,
                    expected,
                ):
                    self._validate(data)

    def test_nonfinite_limit_is_rejected(self):
        for value in (math.nan, math.inf, -math.inf, False):
            with self.subTest(value=value):
                data = copy.deepcopy(VALID_PROFILE)
                data["bands"][0]["limits_dbuv"]["peak"] = value
                with self.assertRaisesRegex(
                    harmonic.ValidationError,
                    "limits_dbuv.peak",
                ):
                    self._validate(data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
