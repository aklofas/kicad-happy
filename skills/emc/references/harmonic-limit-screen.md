# Harmonic-Limit Screening

`analyze_harmonic_limits.py` compares already-calculated RMS dBµV spectral lines with a user-supplied band-limit profile. The result is an engineering screen, not a compliance determination. The tool does not process waveforms, emulate detector timing or receiver bandwidth, invoke a simulator, or provide regulatory limit tables.

## Command

```bash
python3 skills/emc/scripts/analyze_harmonic_limits.py \
  --spectrum harmonic-lines.json \
  --limits limit-profile.json \
  --detector peak \
  --design-margin-db 3 \
  --output harmonic-limit-screen.json
```

## Spectrum format

The input must use schema `harmonic-lines/1` and `level_unit: dbuv_rms`. Frequencies are positive finite hertz values, levels are finite RMS-referenced dBµV values, and duplicate frequencies are rejected.

```json
{
  "schema_version": "harmonic-lines/1",
  "level_unit": "dbuv_rms",
  "source": {
    "kind": "simulation",
    "description": "synthetic spectral lines"
  },
  "points": [
    {"frequency_hz": 1000000, "level_dbuv": 42.0},
    {"frequency_hz": 2000000, "level_dbuv": 31.5}
  ]
}
```

## Limit-profile format

Profiles use schema `emc-limit-profile/1`. `profile_id`, `source.kind`, and `source.citation` are required. Each uniquely named band has an inclusive positive frequency range and at least one finite dBµV limit named `peak`, `quasi_peak`, or `average`.

The repository does not provide regulatory tables. The following values are fictional and must not be used for a product decision:

```json
{
  "schema_version": "emc-limit-profile/1",
  "profile_id": "fictional-user-profile",
  "source": {
    "kind": "user_supplied",
    "citation": "Fictional example — not a regulatory source"
  },
  "bands": [
    {
      "name": "fictional-band",
      "start_hz": 500000,
      "stop_hz": 1800000,
      "limits_dbuv": {
        "peak": 54.0,
        "quasi_peak": 41.0,
        "average": 34.0
      }
    }
  ]
}
```

## Comparison and output

For each band, the tool selects the in-band point with the greatest `level_dbuv`; equal levels choose the lower frequency deterministically. Band endpoints are inclusive, and overlapping bands are evaluated independently. `margin_db` is `limit_dbuv - level_dbuv`.

| Status | Meaning |
|---|---|
| `below_limit_screen` | Margin is at least the requested design margin. |
| `near_limit` | Margin is nonnegative but smaller than the requested design margin. |
| `above_limit_screen` | Margin is negative. |
| `not_assessed` | The band has no points or no limit for the selected detector. |

An empty band has null worst-point fields. A missing detector limit has a null limit and margin but retains the worst point when one exists. Every result uses `result_class: screening_only` and includes `This comparison is not a compliance determination.`

## Limitations

- Input levels must already be RMS-referenced dBµV.
- No peak-to-RMS conversion is performed.
- No waveform import, FFT, Goertzel analysis, resampling, window correction, receiver-bandwidth integration, detector emulation, uncertainty budget, spread-spectrum estimate, or simulator invocation is included.
- The result does not alter EMC rules, findings, severities, risk scores, test plans, cache artifacts, or `emc.json`.
- A screen below a supplied profile is not evidence of regulatory compliance. Use calibrated equipment and the applicable test method for a compliance determination.
