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


class TestScreenHarmonics(unittest.TestCase):
    """Check deterministic per-band comparison and screening semantics."""

    def _screen(
        self,
        spectrum=VALID_SPECTRUM,
        profile=VALID_PROFILE,
        detector="peak",
        margin=0.0,
    ):
        screen = getattr(harmonic, "screen_harmonics", None)
        self.assertIsNotNone(screen, "screen_harmonics is required")
        return screen(
            harmonic.validate_spectrum(copy.deepcopy(spectrum)),
            harmonic.validate_limit_profile(copy.deepcopy(profile)),
            detector,
            margin,
        )

    def test_boundaries_are_inclusive_and_highest_level_wins(self):
        spectrum = copy.deepcopy(VALID_SPECTRUM)
        spectrum["points"] = [
            {"frequency_hz": 100, "level_dbuv": 20},
            {"frequency_hz": 150, "level_dbuv": 35},
            {"frequency_hz": 200, "level_dbuv": 30},
        ]
        profile = copy.deepcopy(VALID_PROFILE)
        profile["bands"] = [
            {
                "name": "inclusive",
                "start_hz": 100,
                "stop_hz": 200,
                "limits_dbuv": {"peak": 40},
            }
        ]

        band = self._screen(spectrum, profile)["bands"][0]
        self.assertEqual(band["worst_frequency_hz"], 150.0)
        self.assertEqual(band["level_dbuv"], 35.0)
        self.assertEqual(band["margin_db"], 5.0)

    def test_equal_levels_choose_lowest_frequency_deterministically(self):
        spectrum = copy.deepcopy(VALID_SPECTRUM)
        spectrum["points"] = [
            {"frequency_hz": 200, "level_dbuv": 35},
            {"frequency_hz": 100, "level_dbuv": 35},
        ]
        profile = copy.deepcopy(VALID_PROFILE)
        profile["bands"][0].update(start_hz=100, stop_hz=200)

        band = self._screen(spectrum, profile)["bands"][0]
        self.assertEqual(band["worst_frequency_hz"], 100.0)

    def test_overlapping_bands_evaluate_same_point_independently(self):
        spectrum = copy.deepcopy(VALID_SPECTRUM)
        spectrum["points"] = [
            {"frequency_hz": 150, "level_dbuv": 35}
        ]
        profile = copy.deepcopy(VALID_PROFILE)
        profile["bands"] = [
            {
                "name": "first",
                "start_hz": 100,
                "stop_hz": 200,
                "limits_dbuv": {"peak": 40},
            },
            {
                "name": "second",
                "start_hz": 150,
                "stop_hz": 250,
                "limits_dbuv": {"peak": 30},
            },
        ]

        bands = self._screen(spectrum, profile)["bands"]
        self.assertEqual(
            [band["worst_frequency_hz"] for band in bands],
            [150.0, 150.0],
        )
        self.assertEqual(
            [band["status"] for band in bands],
            ["below_limit_screen", "above_limit_screen"],
        )

    def test_positive_zero_and_negative_margins_are_classified(self):
        spectrum = copy.deepcopy(VALID_SPECTRUM)
        spectrum["points"] = [
            {"frequency_hz": 100, "level_dbuv": 40}
        ]
        profile = copy.deepcopy(VALID_PROFILE)
        profile["bands"] = [
            {
                "name": "positive",
                "start_hz": 100,
                "stop_hz": 100,
                "limits_dbuv": {"peak": 41},
            },
            {
                "name": "zero",
                "start_hz": 100,
                "stop_hz": 100,
                "limits_dbuv": {"peak": 40},
            },
            {
                "name": "negative",
                "start_hz": 100,
                "stop_hz": 100,
                "limits_dbuv": {"peak": 39},
            },
        ]

        bands = self._screen(spectrum, profile)["bands"]
        self.assertEqual(
            [band["margin_db"] for band in bands], [1.0, 0.0, -1.0]
        )
        self.assertEqual(
            [band["status"] for band in bands],
            [
                "below_limit_screen",
                "below_limit_screen",
                "above_limit_screen",
            ],
        )

    def test_design_margin_creates_near_limit_only_for_nonnegative_margin(self):
        spectrum = copy.deepcopy(VALID_SPECTRUM)
        spectrum["points"] = [
            {"frequency_hz": 100, "level_dbuv": 40}
        ]
        profile = copy.deepcopy(VALID_PROFILE)
        profile["bands"] = [
            {
                "name": "near",
                "start_hz": 100,
                "stop_hz": 100,
                "limits_dbuv": {"peak": 42},
            },
            {
                "name": "above",
                "start_hz": 100,
                "stop_hz": 100,
                "limits_dbuv": {"peak": 39},
            },
        ]

        bands = self._screen(spectrum, profile, margin=3.0)["bands"]
        self.assertEqual(
            [band["status"] for band in bands],
            ["near_limit", "above_limit_screen"],
        )

    def test_each_supported_detector_uses_its_own_limit(self):
        results = {
            detector: self._screen(detector=detector)["bands"][0][
                "limit_dbuv"
            ]
            for detector in ("peak", "quasi_peak", "average")
        }
        self.assertEqual(
            results,
            {"peak": 54.0, "quasi_peak": 41.0, "average": 34.0},
        )

    def test_empty_spectrum_marks_every_band_not_assessed(self):
        spectrum = copy.deepcopy(VALID_SPECTRUM)
        spectrum["points"] = []
        result = self._screen(spectrum=spectrum)
        self.assertTrue(result["bands"])
        self.assertTrue(
            all(
                band["status"] == "not_assessed"
                for band in result["bands"]
            )
        )

    def test_missing_detector_and_empty_band_are_not_assessed(self):
        spectrum = copy.deepcopy(VALID_SPECTRUM)
        spectrum["points"] = [
            {"frequency_hz": 100, "level_dbuv": 40}
        ]
        profile = copy.deepcopy(VALID_PROFILE)
        profile["bands"] = [
            {
                "name": "missing-detector",
                "start_hz": 100,
                "stop_hz": 100,
                "limits_dbuv": {"average": 30},
            },
            {
                "name": "empty",
                "start_hz": 200,
                "stop_hz": 300,
                "limits_dbuv": {"peak": 50},
            },
        ]

        missing, empty = self._screen(spectrum, profile)["bands"]
        self.assertEqual(
            missing,
            {
                "name": "missing-detector",
                "worst_frequency_hz": 100.0,
                "level_dbuv": 40.0,
                "limit_dbuv": None,
                "margin_db": None,
                "status": "not_assessed",
            },
        )
        self.assertEqual(
            empty,
            {
                "name": "empty",
                "worst_frequency_hz": None,
                "level_dbuv": None,
                "limit_dbuv": 50.0,
                "margin_db": None,
                "status": "not_assessed",
            },
        )

    def test_output_carries_screening_boundary_and_never_uses_pass_fail(self):
        result = self._screen()
        self.assertEqual(
            result["schema_version"], "harmonic-limit-screen/1"
        )
        self.assertEqual(result["result_class"], "screening_only")
        self.assertEqual(
            result["claim_boundary"],
            "This comparison is not a compliance determination.",
        )
        statuses = {band["status"] for band in result["bands"]}
        self.assertFalse(statuses & {"pass", "fail"})

    def test_invalid_detector_and_design_margin_are_rejected(self):
        spectrum = harmonic.validate_spectrum(
            copy.deepcopy(VALID_SPECTRUM)
        )
        profile = harmonic.validate_limit_profile(
            copy.deepcopy(VALID_PROFILE)
        )
        screen = getattr(harmonic, "screen_harmonics", None)
        self.assertIsNotNone(screen, "screen_harmonics is required")
        with self.assertRaisesRegex(harmonic.ValidationError, "detector"):
            screen(spectrum, profile, "rms")
        for value in (-1, math.nan, math.inf):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    harmonic.ValidationError, "design_margin_db"
                ):
                    screen(spectrum, profile, "peak", value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
