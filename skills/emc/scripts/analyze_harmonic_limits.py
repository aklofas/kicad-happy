#!/usr/bin/env python3
"""Compare RMS dBµV spectral lines with a user-supplied limit profile."""

import argparse
import math
from pathlib import Path


SPECTRUM_SCHEMA = "harmonic-lines/1"
PROFILE_SCHEMA = "emc-limit-profile/1"
RESULT_SCHEMA = "harmonic-limit-screen/1"
DETECTORS = ("peak", "quasi_peak", "average")
CLAIM_BOUNDARY = "This comparison is not a compliance determination."


class ValidationError(ValueError):
    """Raised when an input does not match the screening format."""


def _mapping(value, path):
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must be an object")
    return value


def _list(value, path):
    if not isinstance(value, list):
        raise ValidationError(f"{path} must be an array")
    return value


def _text(value, path):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{path} must be a non-empty string")
    return value


def _number(value, path):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{path} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValidationError(f"{path} must be a finite number")
    return number


def validate_spectrum(data: object) -> dict:
    """Return a normalized spectrum with points sorted by frequency."""
    root = _mapping(data, "spectrum")
    if root.get("schema_version") != SPECTRUM_SCHEMA:
        raise ValidationError(
            f"spectrum.schema_version must equal {SPECTRUM_SCHEMA!r}"
        )
    if root.get("level_unit") != "dbuv_rms":
        raise ValidationError("spectrum.level_unit must equal 'dbuv_rms'")

    normalized_points = []
    seen_frequencies = set()
    for index, raw_point in enumerate(
        _list(root.get("points"), "spectrum.points")
    ):
        point = _mapping(raw_point, f"spectrum.points[{index}]")
        frequency = _number(
            point.get("frequency_hz"),
            f"spectrum.points[{index}].frequency_hz",
        )
        level = _number(
            point.get("level_dbuv"),
            f"spectrum.points[{index}].level_dbuv",
        )
        if frequency <= 0:
            raise ValidationError(
                f"spectrum.points[{index}].frequency_hz must be greater "
                "than zero"
            )
        if frequency in seen_frequencies:
            raise ValidationError(
                f"spectrum.points contains duplicate frequency_hz {frequency}"
            )
        seen_frequencies.add(frequency)
        normalized_points.append(
            {"frequency_hz": frequency, "level_dbuv": level}
        )

    normalized_points.sort(key=lambda point: point["frequency_hz"])
    normalized = {
        "schema_version": SPECTRUM_SCHEMA,
        "level_unit": "dbuv_rms",
        "points": normalized_points,
    }
    if "source" in root:
        normalized["source"] = root["source"]
    return normalized


def validate_limit_profile(data: object) -> dict:
    """Return a normalized, provenance-preserving limit profile."""
    root = _mapping(data, "profile")
    if root.get("schema_version") != PROFILE_SCHEMA:
        raise ValidationError(
            f"profile.schema_version must equal {PROFILE_SCHEMA!r}"
        )

    profile_id = _text(root.get("profile_id"), "profile.profile_id")
    raw_source = _mapping(root.get("source"), "profile.source")
    source = {
        "kind": _text(raw_source.get("kind"), "profile.source.kind"),
        "citation": _text(
            raw_source.get("citation"), "profile.source.citation"
        ),
    }

    normalized_bands = []
    band_names = set()
    for index, raw_band in enumerate(
        _list(root.get("bands"), "profile.bands")
    ):
        band = _mapping(raw_band, f"profile.bands[{index}]")
        name = _text(band.get("name"), f"profile.bands[{index}].name")
        if name in band_names:
            raise ValidationError(
                f"profile.bands contains duplicate band name {name!r}"
            )
        band_names.add(name)

        start = _number(
            band.get("start_hz"), f"profile.bands[{index}].start_hz"
        )
        stop = _number(
            band.get("stop_hz"), f"profile.bands[{index}].stop_hz"
        )
        if start <= 0 or start > stop:
            raise ValidationError(
                f"profile.bands[{index}].start_hz must be positive and "
                "less than or equal to stop_hz"
            )

        raw_limits = _mapping(
            band.get("limits_dbuv"),
            f"profile.bands[{index}].limits_dbuv",
        )
        if not raw_limits:
            raise ValidationError(
                f"profile.bands[{index}].limits_dbuv must contain at "
                "least one detector"
            )
        unsupported = sorted(set(raw_limits) - set(DETECTORS))
        if unsupported:
            raise ValidationError(
                f"profile.bands[{index}].limits_dbuv has unsupported "
                f"detector {unsupported[0]!r}"
            )
        limits = {
            detector: _number(
                value,
                f"profile.bands[{index}].limits_dbuv.{detector}",
            )
            for detector, value in raw_limits.items()
        }
        normalized_bands.append(
            {
                "name": name,
                "start_hz": start,
                "stop_hz": stop,
                "limits_dbuv": limits,
            }
        )

    return {
        "schema_version": PROFILE_SCHEMA,
        "profile_id": profile_id,
        "source": source,
        "bands": normalized_bands,
    }


def _build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Screen supplied RMS dBµV spectral lines against a "
            "user-supplied limit profile"
        )
    )
    parser.add_argument(
        "--spectrum",
        type=Path,
        required=True,
        help=f"{SPECTRUM_SCHEMA} JSON input",
    )
    parser.add_argument(
        "--limits",
        type=Path,
        required=True,
        help=f"{PROFILE_SCHEMA} JSON input",
    )
    parser.add_argument(
        "--detector",
        choices=DETECTORS,
        required=True,
    )
    parser.add_argument(
        "--design-margin-db",
        default=0.0,
        help="Nonnegative engineering margin in dB (default: 0)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON here instead of stdout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _build_parser().parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
