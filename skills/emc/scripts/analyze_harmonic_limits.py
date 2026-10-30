#!/usr/bin/env python3
"""Compare RMS dBµV spectral lines with a user-supplied limit profile."""

import argparse
import json
import math
from pathlib import Path
import sys


SPECTRUM_SCHEMA = "harmonic-lines/1"
PROFILE_SCHEMA = "emc-limit-profile/1"
RESULT_SCHEMA = "harmonic-limit-screen/1"
DETECTORS = ("peak", "quasi_peak", "average")
MARGIN_DECIMALS = 6
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
    try:
        number = float(value)
    except OverflowError:
        raise ValidationError(f"{path} must be a finite number") from None
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
        normalized["source"] = _mapping(root["source"], "spectrum.source")
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
    _text(raw_source.get("kind"), "profile.source.kind")
    _text(raw_source.get("citation"), "profile.source.citation")

    raw_bands = _list(root.get("bands"), "profile.bands")
    if not raw_bands:
        raise ValidationError("profile.bands must contain at least one band")

    normalized_bands = []
    band_names = set()
    for index, raw_band in enumerate(raw_bands):
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
        "source": dict(raw_source),
        "bands": normalized_bands,
    }


def screen_harmonics(
    spectrum: dict,
    profile: dict,
    detector: str,
    design_margin_db: float = 0.0,
) -> dict:
    """Return a harmonic-limit-screen/1 result from validated inputs."""
    if detector not in DETECTORS:
        raise ValidationError(
            f"detector must be one of {', '.join(DETECTORS)}"
        )
    design_margin = _number(design_margin_db, "design_margin_db")
    if design_margin < 0:
        raise ValidationError(
            "design_margin_db must be greater than or equal to zero"
        )

    results = []
    for index, band in enumerate(profile["bands"]):
        in_band = [
            point
            for point in spectrum["points"]
            if band["start_hz"]
            <= point["frequency_hz"]
            <= band["stop_hz"]
        ]
        worst = max(
            in_band,
            key=lambda point: (
                point["level_dbuv"],
                -point["frequency_hz"],
            ),
            default=None,
        )
        limit = band["limits_dbuv"].get(detector)

        if worst is None or limit is None:
            margin = None
            status = "not_assessed"
        else:
            # Adding 0.0 turns a rounded -0.0 into 0.0 for clean output.
            margin = round(limit - worst["level_dbuv"], MARGIN_DECIMALS) + 0.0
            if not math.isfinite(margin):
                raise ValidationError(
                    f"bands[{index}].margin_db is not a finite number"
                )
            if margin < 0:
                status = "above_limit_screen"
            elif margin < design_margin:
                status = "near_limit"
            else:
                status = "below_limit_screen"

        results.append(
            {
                "name": band["name"],
                "worst_frequency_hz": (
                    worst["frequency_hz"] if worst else None
                ),
                "level_dbuv": worst["level_dbuv"] if worst else None,
                "limit_dbuv": limit,
                "margin_db": margin,
                "status": status,
            }
        )

    return {
        "schema_version": RESULT_SCHEMA,
        "result_class": "screening_only",
        "detector": detector,
        "design_margin_db": design_margin,
        "spectrum_source": spectrum.get("source"),
        "profile": {
            "profile_id": profile["profile_id"],
            "source": profile["source"],
        },
        "bands": results,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def _reject_duplicate_keys(pairs):
    parsed = {}
    for key, value in pairs:
        if key in parsed:
            raise ValidationError(f"duplicate key {key!r}")
        parsed[key] = value
    return parsed


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            return json.load(stream, object_pairs_hook=_reject_duplicate_keys)
    except ValidationError as exc:
        raise ValidationError(f"{path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ValidationError(
            f"{path} is not valid UTF-8 text: {exc}"
        ) from exc
    except ValueError as exc:
        raise ValidationError(f"{path} is not valid JSON: {exc}") from exc
    except RecursionError as exc:
        raise ValidationError(f"{path} is nested too deeply") from exc
    except OSError as exc:
        raise ValidationError(f"could not read {path}: {exc}") from exc


def _nonnegative_finite(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "must be a finite number greater than or equal to zero"
        ) from exc
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError(
            "must be a finite number greater than or equal to zero"
        )
    return number


def _write_json(payload: dict, output: Path | None):
    try:
        text = json.dumps(payload, indent=2, allow_nan=False) + "\n"
    except (ValueError, RecursionError) as exc:
        raise ValidationError(f"result is not valid JSON: {exc}") from exc
    if output is None:
        sys.stdout.write(text)
        return
    try:
        with output.open("w", encoding="utf-8") as stream:
            stream.write(text)
    except OSError as exc:
        raise ValidationError(f"could not write {output}: {exc}") from exc


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
        type=_nonnegative_finite,
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
    """Run the command-line tool and return a process exit code."""
    args = _build_parser().parse_args(argv)
    try:
        spectrum = validate_spectrum(_load_json(args.spectrum))
        profile = validate_limit_profile(_load_json(args.limits))
        result = screen_harmonics(
            spectrum,
            profile,
            detector=args.detector,
            design_margin_db=args.design_margin_db,
        )
        _write_json(result, args.output)
    except (ValidationError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
